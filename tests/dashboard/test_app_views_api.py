"""Phase 5 acceptance: paginated repositories/health/issues/executions/
evidence endpoints with a consistent error envelope, exercised end-to-end
(register -> ingest via the real runtime.observe logic -> query)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard import indexer, poller
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig
from runtime.observe import read_events_page


def _observer_reader(executable, log_path, *, after, limit):
    return read_events_page(Path(log_path), after=after, limit=limit)


def _write_event_line(log_path: Path, event_id: int, event_type: str, *,
                      issue_id: str | None = None, execution_id: str | None = None,
                      run_id: str | None = None, payload: dict | None = None) -> None:
    line = json.dumps({
        "event_id": event_id, "schema_version": 1, "ts": "2026-08-20T00:00:00Z",
        "run_id": run_id, "type": event_type, "issue_id": issue_id,
        "execution_id": execution_id, "payload": payload or {},
    }, sort_keys=True, separators=(",", ":")) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client_and_app(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
    return TestClient(app, base_url="http://127.0.0.1"), app


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_health_for_unregistered_repository_is_404(tmp_path):
    client, _ = _client_and_app(tmp_path)
    resp = client.get("/api/repositories/999/health")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_health_before_any_tick_reports_null_availability(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    repo_id = created.json()["id"]

    resp = client.get(f"/api/repositories/{repo_id}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["availability"] is None
    assert body["haltedOversized"] is False
    assert body["lease"]["status"] == "unclaimed"


def test_issues_and_executions_reflect_ingested_evidence(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, "IssueCreated", issue_id="42", payload={"title": "fix it"})
    _write_event_line(log_path, 2, "IssueActivated", issue_id="42", payload={})
    _write_event_line(log_path, 3, "ExecutionSpawned", issue_id="42", execution_id="42-e1")

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]

    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    outcome = asyncio.run(indexer.ingest_repository_tick(
        app.state.db, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    issues = client.get(f"/api/repositories/{repo_id}/issues").json()
    assert issues["total"] == 1
    item = issues["items"][0]
    # proxyCost is an additive key (this issue has no finished execution yet).
    proxy_cost = item.pop("proxyCost")
    assert proxy_cost["completeness"] == "UNAVAILABLE"
    assert item == {
        "issueId": "42", "state": "ACTIVE", "title": "fix it",
        "inconsistent": False, "lastEventId": 2,
    }

    executions = client.get(f"/api/repositories/{repo_id}/executions").json()
    assert executions["total"] == 1
    assert executions["items"][0]["executionId"] == "42-e1"
    assert executions["items"][0]["state"] == "Pending reconciliation"

    evidence = client.get(f"/api/repositories/{repo_id}/evidence").json()
    assert evidence["total"] == 3
    assert [e["eventId"] for e in evidence["items"]] == [1, 2, 3]

    health = client.get(f"/api/repositories/{repo_id}/health").json()
    assert health["availability"] == "AVAILABLE"
    assert health["identityGeneration"]["number"] == 1
    assert health["corruptCount"] == 0
    assert health["unknownEventTypeCount"] == 0


def test_health_reports_unknown_event_type_count(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, "IssueCreated", issue_id="42")
    _write_event_line(log_path, 2, "SomeFutureEventType", issue_id="42")

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    health = client.get(f"/api/repositories/{repo_id}/health").json()
    assert health["unknownEventTypeCount"] == 1


def test_pagination_bounds_are_enforced(tmp_path):
    client, _ = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    repo_id = created.json()["id"]

    too_big = client.get(f"/api/repositories/{repo_id}/issues?limit=99999")
    assert too_big.status_code == 422

    negative_offset = client.get(f"/api/repositories/{repo_id}/issues?offset=-1")
    assert negative_offset.status_code == 422


def test_evidence_pagination_slices_correctly(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    for i in range(1, 6):
        _write_event_line(log_path, i, "IssueCreated", issue_id=str(i))

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    page1 = client.get(f"/api/repositories/{repo_id}/evidence?limit=2&offset=0").json()
    page2 = client.get(f"/api/repositories/{repo_id}/evidence?limit=2&offset=2").json()
    assert [e["eventId"] for e in page1["items"]] == [1, 2]
    assert [e["eventId"] for e in page2["items"]] == [3, 4]
    assert page1["total"] == 5


def test_evidence_offset_above_100k_is_rejected(tmp_path):
    """docs/27 SS7.4: the one documented pre-GA narrowing of an existing
    query range -- offsets above 100,000 on the legacy repository-scoped
    evidence endpoint are now rejected."""
    client, _ = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    repo_id = created.json()["id"]

    resp = client.get(f"/api/repositories/{repo_id}/evidence?limit=1&offset=100001")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "PAGE_OUT_OF_RANGE"

    ok = client.get(f"/api/repositories/{repo_id}/evidence?limit=1&offset=100000")
    assert ok.status_code == 200


# ── /runs (Phase 7 follow-up: paginated Runs resource) ──────────────────
_RUN_ID_A = "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6"

_RUN_STARTED_PAYLOAD = {
    "engine": {"provider": "claude-headless", "model": "default"},
    "reviewer": {"provider": "qwen", "model": "qwen2.5-coder"},
    "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
              "hard_stop_proxy_cost_per_run_usd": 15.0, "proxy_pricing": "api_list_rates"},
    "config_digest": "a" * 64,
}


def test_runs_endpoint_for_unregistered_repository_is_404(tmp_path):
    client, _ = _client_and_app(tmp_path)
    resp = client.get("/api/repositories/999/runs")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_runs_endpoint_reflects_completed_run_with_full_metadata(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, "RunStarted", run_id=_RUN_ID_A, payload=_RUN_STARTED_PAYLOAD)
    _write_event_line(log_path, 2, "IssueCreated", issue_id="1", run_id=_RUN_ID_A)
    _write_event_line(log_path, 3, "IssueActivated", issue_id="1", run_id=_RUN_ID_A)
    _write_event_line(log_path, 4, "ExecutionSpawned", issue_id="1", execution_id="1-e1",
                      run_id=_RUN_ID_A)
    _write_event_line(log_path, 5, "RunFinished", run_id=_RUN_ID_A,
                      payload={"outcome": "COMPLETED", "detail": None})

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    runs = client.get(f"/api/repositories/{repo_id}/runs").json()
    assert runs["total"] == 1
    run = runs["items"][0]
    assert run["runId"] == _RUN_ID_A
    assert run["engineProvider"] == "claude-headless"
    assert run["reviewerModel"] == "qwen2.5-coder"
    assert run["configDigest"] == "a" * 64
    assert run["outcome"] == "COMPLETED"
    assert run["displayOutcome"] == "COMPLETED"

    executions = client.get(f"/api/repositories/{repo_id}/executions").json()
    assert executions["items"][0]["runId"] == _RUN_ID_A
    assert executions["items"][0]["runMetadata"]["available"] is True


def test_runs_endpoint_shows_early_failure_run_with_zero_executions(tmp_path, monkeypatch):
    """A CHECKOUT_FAILED run never reaches issue ingestion -- no execution
    row can exist for it -- but /runs must still surface it."""
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, "RunStarted", run_id=_RUN_ID_A, payload=_RUN_STARTED_PAYLOAD)
    _write_event_line(log_path, 2, "RunFinished", run_id=_RUN_ID_A,
                      payload={"outcome": "CHECKOUT_FAILED", "detail": None})

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    runs = client.get(f"/api/repositories/{repo_id}/runs").json()
    executions = client.get(f"/api/repositories/{repo_id}/executions").json()

    assert runs["total"] == 1
    assert runs["items"][0]["outcome"] == "CHECKOUT_FAILED"
    assert executions["total"] == 0


def test_runs_endpoint_unresolved_run_reports_no_controlled_finish(tmp_path, monkeypatch):
    client, app = _client_and_app(tmp_path)
    repo = _git_worktree(tmp_path)
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, "RunStarted", run_id=_RUN_ID_A, payload=_RUN_STARTED_PAYLOAD)

    created = client.post("/api/repositories",
                          json={"projectPath": str(repo), "logPath": str(log_path)})
    repo_id = created.json()["id"]
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    asyncio.run(indexer.ingest_repository_tick(app.state.db, repo_id, "exe", str(log_path)))

    runs = client.get(f"/api/repositories/{repo_id}/runs").json()
    run = runs["items"][0]
    assert run["outcome"] is None
    assert run["displayOutcome"] == "no controlled finish observed"
    assert "running" not in run["displayOutcome"].lower()
