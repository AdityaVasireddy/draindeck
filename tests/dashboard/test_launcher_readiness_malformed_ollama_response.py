"""RED tests, ULTRA-REVIEW-001 finding 1: a malformed-but-VALID-JSON
response from Ollama's `GET /api/tags` (an empty list, `null`, or a
`models` array whose entries are not dicts) must not turn the Dashboard's
`/api/launcher/readiness` endpoint into an unhandled 500.

Root cause under test:
`src/draindeck_dashboard/launcher_readiness.py`'s
`check_reviewer_model_present` only catches
`(URLError, ConnectionError, TimeoutError, ValueError, OSError)` around
`json.loads(...)`. A body that parses fine as JSON but isn't the expected
`{"models": [{"name": ...}, ...]}` shape (e.g. `[]`, `null`, or
`{"models": [1, 2, 3]}`) makes `body.get(...)` or `entry.get(...)` raise
`AttributeError`, which is NOT in that except clause and propagates
uncaught through `evaluate_repository_run_readiness` into
`src/draindeck_dashboard/app.py`'s `launcher_readiness` route.

Planning-gate only (docs/32 review, ULTRA-REVIEW-001): no `src/` change
here. `TestClient(..., raise_server_exceptions=False)` is used so an
uncaught exception surfaces as a real 500 response instead of re-raising
into the test process, matching how a real deployed server would behave.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from draindeck_dashboard import app as app_module
from draindeck_dashboard import launcher_readiness
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path) -> TestClient:
    # raise_server_exceptions=False: an uncaught AttributeError must show up
    # as a real 500 HTTP response (what a deployed server would send), not
    # re-raise into the test process.
    return TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1", raise_server_exceptions=False)


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


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


def _register_repo_with_config(client, tmp_path):
    repo = _git_worktree(tmp_path)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    created = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
    )
    assert created.status_code == 201
    return created.json()["id"]


def _fake_raw_urlopen(raw_body_obj):
    """A fake `urllib.request.urlopen` returning a body that IS valid JSON
    (`json.dumps` never fails on these inputs) but is shaped nothing like
    Ollama's real `{"models": [...]}` envelope."""
    def _urlopen(url, timeout=None):
        assert "api/tags" in url

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(raw_body_obj).encode()

        return _Resp()
    return _urlopen


@pytest.mark.parametrize(
    "malformed_body",
    [
        pytest.param([], id="empty-list"),
        pytest.param(None, id="null"),
        pytest.param({"models": [1, 2, 3]}, id="wrong-item-shapes"),
        pytest.param({"models": "not-a-list"}, id="models-not-a-list"),
    ],
)
def test_readiness_endpoint_does_not_500_on_malformed_but_valid_ollama_json(
    tmp_path, monkeypatch, malformed_body,
):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher_readiness.urllib.request, "urlopen", _fake_raw_urlopen(malformed_body))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")

    assert resp.status_code != 500, (
        f"RED (finding 1): a malformed-but-valid Ollama /api/tags JSON body "
        f"({malformed_body!r}) crashed /api/launcher/readiness with an unhandled "
        f"exception instead of reporting the reviewer model as simply not present. "
        f"src/draindeck_dashboard/launcher_readiness.py:check_reviewer_model_present "
        f"only catches (URLError, ConnectionError, TimeoutError, ValueError, OSError) "
        f"-- an unexpected-shape body raises AttributeError, which is not caught."
    )
    body = resp.json()
    assert body["runReady"] is False
    assert "reviewer-model" in body["missing"]
