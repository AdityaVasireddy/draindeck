"""ADR-30 RED 2: GET /api/repositories/{repoId}/configured-issues end-to-end."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig

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


def test_configured_issues_route_returns_parsed_issues_and_revision(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text("## a: First\nbody\n", encoding="utf-8")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")

    created = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
    )
    repo_id = created.json()["id"]

    resp = client.get(f"/api/repositories/{repo_id}/configured-issues")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["issueId"] for i in body["issues"]] == ["a"]
    assert len(body["issuesFileRevision"]) == 64
    assert body["issues"][0]["state"] == "UNAVAILABLE"


def test_configured_issues_route_without_config_returns_typed_error(tmp_path):
    client = _client(tmp_path)
    repo = _git_worktree(tmp_path)
    created = client.post("/api/repositories", json={"projectPath": str(repo)})
    repo_id = created.json()["id"]

    resp = client.get(f"/api/repositories/{repo_id}/configured-issues")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFIG_NOT_REGISTERED"


def test_configured_issues_route_unknown_repo_is_404(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/repositories/999/configured-issues")
    assert resp.status_code == 404
