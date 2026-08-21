"""Phase 6 acceptance: the transcript and diff endpoints end-to-end --
registration -> real ingestion -> serving, plus the 403/404 boundary
cases through the actual HTTP layer, not just the underlying functions.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard import indexer, poller
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig
from runtime.observe import read_events_page


def _observer_reader(executable, log_path, *, after, limit):
    return read_events_page(Path(log_path), after=after, limit=limit)


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _write_execution_finished(log_path: Path, event_id: int, execution_id: str,
                              issue_id: str, transcript_path, start_commit: str,
                              end_commit: str) -> None:
    line = json.dumps({
        "event_id": event_id, "schema_version": 1, "ts": "2026-08-21T00:00:00Z",
        "run_id": None, "type": "ExecutionFinished", "issue_id": issue_id,
        "execution_id": execution_id,
        "payload": {"start_commit": start_commit, "end_commit": end_commit,
                   "transcript_path": transcript_path, "outcome": "OK"},
    }, sort_keys=True, separators=(",", ":")) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def _write_execution_spawned(log_path: Path, event_id: int, execution_id: str,
                             issue_id: str) -> None:
    line = json.dumps({
        "event_id": event_id, "schema_version": 1, "ts": "2026-08-21T00:00:00Z",
        "run_id": None, "type": "ExecutionSpawned", "issue_id": issue_id,
        "execution_id": execution_id, "payload": {},
    }, sort_keys=True, separators=(",", ":")) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def _register_and_ingest(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "before\n", "first")
    c2 = _commit(repo, "file.txt", "after\n", "second")

    log_path = tmp_path / "state" / "events.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.touch()

    artifacts_dir = log_path.parent / "artifacts"
    transcript_dir = artifacts_dir / "42-e1"
    transcript_dir.mkdir(parents=True)
    transcript_file = transcript_dir / "transcript.jsonl"
    transcript_file.write_text('{"stream":"stdout"}\n')

    _write_execution_spawned(log_path, 1, "42-e1", "42")
    _write_execution_finished(log_path, 2, "42-e1", "42", str(transcript_file), c1, c2)

    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]

    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    outcome = asyncio.run(indexer.ingest_repository_tick(
        app.state.db, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    return client, app, repo_id, transcript_file, c1, c2


def test_transcript_endpoint_serves_the_real_file(tmp_path, monkeypatch):
    client, app, repo_id, transcript_file, c1, c2 = _register_and_ingest(tmp_path, monkeypatch)

    resp = client.get(f"/api/repositories/{repo_id}/executions/42-e1/transcript")

    assert resp.status_code == 200
    assert resp.text == transcript_file.read_text()


def test_diff_endpoint_computes_the_real_diff(tmp_path, monkeypatch):
    client, app, repo_id, transcript_file, c1, c2 = _register_and_ingest(tmp_path, monkeypatch)

    resp = client.get(f"/api/repositories/{repo_id}/executions/42-e1/diff")

    assert resp.status_code == 200
    body = resp.json()
    assert "-before" in body["diff"]
    assert "+after" in body["diff"]
    assert body["truncated"] is False


def test_transcript_outside_artifact_root_is_403(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "a\n", "first")

    log_path = tmp_path / "state" / "events.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.touch()

    outside_secret = tmp_path / "outside-secret.txt"
    outside_secret.write_text("do not serve this")

    _write_execution_spawned(log_path, 1, "42-e1", "42")
    _write_execution_finished(log_path, 2, "42-e1", "42", str(outside_secret), c1, c1)

    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]

    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    resp = client.get(f"/api/repositories/{repo_id}/executions/42-e1/transcript")

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ARTIFACT_OUTSIDE_ROOT"


def test_transcript_for_unknown_execution_is_404(tmp_path, monkeypatch):
    client, app, repo_id, transcript_file, c1, c2 = _register_and_ingest(tmp_path, monkeypatch)

    resp = client.get(f"/api/repositories/{repo_id}/executions/never-existed/transcript")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_transcript_contained_but_deleted_from_disk_is_404(tmp_path, monkeypatch):
    client, app, repo_id, transcript_file, c1, c2 = _register_and_ingest(tmp_path, monkeypatch)
    transcript_file.unlink()

    resp = client.get(f"/api/repositories/{repo_id}/executions/42-e1/transcript")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"


def test_diff_for_unknown_execution_is_404(tmp_path, monkeypatch):
    client, app, repo_id, transcript_file, c1, c2 = _register_and_ingest(tmp_path, monkeypatch)

    resp = client.get(f"/api/repositories/{repo_id}/executions/never-existed/diff")

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"
