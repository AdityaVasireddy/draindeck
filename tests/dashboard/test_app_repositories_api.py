"""Phase 3 acceptance: registration REST surface end-to-end, plus the
request-body-size bound (docs/19 "Local web security")."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(_cfg(tmp_path))
    return TestClient(app, base_url="http://127.0.0.1")


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_register_list_get_delete_round_trip(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)

    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    assert created.status_code == 201
    repo_id = created.json()["id"]

    listed = client.get("/api/repositories")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()["repositories"]] == [repo_id]

    fetched = client.get(f"/api/repositories/{repo_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == repo_id

    deleted = client.delete(f"/api/repositories/{repo_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/api/repositories/{repo_id}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_duplicate_log_path_registration_is_rejected(tmp_path):
    client = _client(tmp_path)
    repo_a = _git_worktree(tmp_path, "a")
    repo_b = _git_worktree(tmp_path, "b")
    log = tmp_path / "events.jsonl"

    first = client.post("/api/repositories",
                        json={"projectPath": str(repo_a), "logPath": str(log)})
    assert first.status_code == 201

    second = client.post("/api/repositories",
                         json={"projectPath": str(repo_b), "logPath": str(log)})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "LOG_PATH_ALREADY_REGISTERED"


def test_invalid_project_path_returns_typed_error(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/repositories", json={"projectPath": "relative/path"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "PROJECT_PATH_NOT_ABSOLUTE"


def test_unexpected_field_is_rejected(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    resp = client.post("/api/repositories",
                       json={"projectPath": str(repo), "extra": "nope"})
    assert resp.status_code == 422


def test_oversized_request_body_is_rejected(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    huge_path = str(repo) + ("x" * 200_000)
    resp = client.post("/api/repositories", json={"projectPath": huge_path})
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "REQUEST_BODY_TOO_LARGE"
