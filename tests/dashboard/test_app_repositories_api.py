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


_VALID_CONFIG_YAML = """
project:
  name: T
  repository: {repository!r}
  branch: agent-work
  issues_file: Issues.md
  validation:
    commands: ["echo ok"]
engine:
  provider: claude-headless
  auth_mode: subscription
  model: default
  max_turns: 30
  timeout_seconds: 1800
reviewer:
  provider: qwen
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
budget:
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  hard_stop_proxy_cost_per_run_usd: 15.0
  proxy_pricing: api_list_rates
experiment:
  sample_size: 20
  attempt1_success_min: 0.3
  cost_per_shipped_issue_max_usd: 3.0
billing:
  posture: p
  headless_split_status: paused
  verified_on: '2026-07-10'
  reverify_at: x
"""


def test_registration_with_valid_config_path_is_launch_capable(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")

    created = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["configPath"] == str(config_path)
    assert body["controlCapability"] == "LAUNCH_CAPABLE"

    fetched = client.get(f"/api/repositories/{body['id']}")
    assert fetched.json()["controlCapability"] == "LAUNCH_CAPABLE"


def test_registration_with_invalid_config_path_returns_typed_error(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    missing = repo / ".draindeck" / "config.local.yaml"

    resp = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(missing)},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONFIG_PATH_NOT_FOUND"

    listed = client.get("/api/repositories")
    assert listed.json()["repositories"] == []


def test_registration_without_config_path_is_observation_only(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    assert created.status_code == 201
    assert created.json()["configPath"] is None
    assert created.json()["controlCapability"] == "OBSERVATION_ONLY"
