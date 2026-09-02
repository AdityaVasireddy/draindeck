"""The Dashboard's own launcher-readiness API (docs/32 L-10, review
Blocker 2): Dashboard-ready and Run-ready are independent facts, and
Run-ready is a TRUTHFUL, per-registered-repository check -- Claude,
Ollama, and the actual reviewer model configured in that repository's
canonical `.draindeck/config.local.yaml` -- never a hard-coded True.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard import app as app_module
from draindeck_dashboard import launcher
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1")


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


def _fake_tags_urlopen(model_names):
    def _urlopen(url, timeout=None):
        assert "api/tags" in url

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"models": [{"name": n} for n in model_names]}).encode()

        return _Resp()
    return _urlopen


def test_readiness_reports_no_repository_selected_when_repo_id_is_omitted(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/launcher/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dashboardReady"] is True
    assert body["runConfigured"] is False
    assert body["runReady"] is False
    assert "repository-not-selected" in body["missing"]
    assert body["repositoryId"] is None


def test_readiness_is_true_when_claude_ollama_and_the_configured_model_are_all_present(
    tmp_path, monkeypatch,
):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["qwen2.5-coder"]))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    body = resp.json()
    assert body["runConfigured"] is True
    assert body["runReady"] is True
    assert body["missing"] == []
    assert body["model"] == "qwen2.5-coder"
    assert body["repositoryId"] == repo_id


def test_readiness_reports_missing_reviewer_model_when_not_pulled(tmp_path, monkeypatch):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    # The configured model is "qwen2.5-coder"; Ollama reports a DIFFERENT
    # model pulled -- the exact configured one is genuinely absent.
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["llama3"]))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    body = resp.json()
    assert body["runReady"] is False
    assert "reviewer-model" in body["missing"]
    assert body["model"] == "qwen2.5-coder"


def test_readiness_reports_missing_ollama(tmp_path, monkeypatch):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)

    def which(cmd):
        return None if cmd == "ollama" else f"/usr/bin/{cmd}"

    monkeypatch.setattr(app_module.shutil, "which", which)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["qwen2.5-coder"]))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    body = resp.json()
    assert body["runReady"] is False
    assert "ollama" in body["missing"]


def test_readiness_reports_missing_claude(tmp_path, monkeypatch):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)

    def which(cmd):
        return None if cmd == "claude" else f"/usr/bin/{cmd}"

    monkeypatch.setattr(app_module.shutil, "which", which)
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["qwen2.5-coder"]))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    body = resp.json()
    assert body["runReady"] is False
    assert "claude" in body["missing"]


def test_readiness_never_auto_selects_a_repository_even_when_one_is_registered(
    tmp_path, monkeypatch,
):
    # Review Blocker 3: omitting repoId must NEVER silently pick some
    # registered repository -- not even when exactly one exists.
    client = _client(tmp_path)
    _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["qwen2.5-coder"]))

    resp = client.get("/api/launcher/readiness")
    body = resp.json()
    assert body["repositoryId"] is None
    assert body["runReady"] is False
    assert body["runConfigured"] is False
    assert "repository-not-selected" in body["missing"]


def test_readiness_returns_not_found_for_an_unknown_repo_id_never_falls_back(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/launcher/readiness?repoId=999999")
    assert resp.status_code == 404


def test_readiness_with_explicit_repo_id_never_falls_back_to_a_different_registered_repository(
    tmp_path, monkeypatch,
):
    client = _client(tmp_path)
    repo_a_id = _register_repo_with_config(client, tmp_path)
    repo_b = _git_worktree(tmp_path, name="repo-b")
    draindeck_dir = repo_b / ".draindeck"
    draindeck_dir.mkdir()
    config_path_b = draindeck_dir / "config.local.yaml"
    config_path_b.write_text(
        _VALID_CONFIG_YAML.format(repository=str(repo_b)).replace("qwen2.5-coder", "a-different-model"),
        encoding="utf-8",
    )
    created_b = client.post(
        "/api/repositories", json={"projectPath": str(repo_b), "configPath": str(config_path_b)},
    )
    assert created_b.status_code == 201
    repo_b_id = created_b.json()["id"]

    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher.urllib.request, "urlopen", _fake_tags_urlopen(["a-different-model"]))

    resp = client.get(f"/api/launcher/readiness?repoId={repo_b_id}")
    body = resp.json()
    assert body["repositoryId"] == repo_b_id
    assert body["model"] == "a-different-model"
    assert repo_a_id != repo_b_id


def test_readiness_returns_200_with_config_unavailable_when_registered_config_is_deleted(
    tmp_path, monkeypatch,
):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    registration = client.get(f"/api/repositories/{repo_id}").json()
    Path(registration["configPath"]).unlink()

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runReady"] is False
    assert body["runConfigured"] is False
    assert "config-unavailable" in body["missing"]


def test_readiness_returns_200_with_config_invalid_when_config_yaml_is_malformed(tmp_path, monkeypatch):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    registration = client.get(f"/api/repositories/{repo_id}").json()
    Path(registration["configPath"]).write_text("not: [valid, yaml, :::", encoding="utf-8")

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runReady"] is False
    assert "config-invalid" in body["missing"]


def test_readiness_returns_200_with_config_invalid_when_config_schema_is_invalid(tmp_path, monkeypatch):
    client = _client(tmp_path)
    repo_id = _register_repo_with_config(client, tmp_path)
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    registration = client.get(f"/api/repositories/{repo_id}").json()
    # Present, valid YAML, but the schema itself is now invalid: an empty
    # reviewer model.
    Path(registration["configPath"]).write_text(
        _VALID_CONFIG_YAML.format(repository=registration["projectPath"]).replace(
            "model: qwen2.5-coder", "model: ''",
        ),
        encoding="utf-8",
    )

    resp = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runReady"] is False
    assert "config-invalid" in body["missing"]


def test_readiness_dashboard_ready_is_independent_of_run_ready_being_false(tmp_path):
    # No repository registered at all -- Dashboard itself is still usable
    # (this very request succeeded), only Run-ready is false.
    client = _client(tmp_path)
    resp = client.get("/api/launcher/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dashboardReady"] is True
    assert body["runReady"] is False
