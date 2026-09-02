"""RED -> GREEN: the Dashboard's own reviewer-model pull action (docs/32
review Blocker 1 follow-up) -- "clone -> launch Dashboard -> register
target -> select issues -> run" must not require a manual `--pull-model`
terminal command. The model pulled is resolved EXCLUSIVELY from the
repository's own registered canonical `.draindeck/config.local.yaml`;
nothing here ever accepts a client-supplied model or config path, and no
pull is ever started without explicit confirmation.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard import app as app_module
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig
from draindeck_dashboard.model_pull import ModelPullTracker


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path, *, model_puller=None):
    app = create_app(_cfg(tmp_path))
    if model_puller is not None:
        app.state.model_pull_tracker = ModelPullTracker(model_puller=model_puller)
    return TestClient(app, base_url="http://127.0.0.1")


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
    model: {model}
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


def _register_repo(client, tmp_path, *, model="qwen2.5-coder"):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo), model=model), encoding="utf-8")
    created = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
    )
    assert created.status_code == 201
    return created.json()["id"]


def test_declined_confirmation_makes_zero_pull_calls(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=calls.append)
    repo_id = _register_repo(client, tmp_path)

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={"confirm": False})

    assert resp.status_code == 400
    assert calls == []


def test_no_confirm_field_at_all_makes_zero_pull_calls(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=calls.append)
    repo_id = _register_repo(client, tmp_path)

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={})

    assert resp.status_code == 400
    assert calls == []


def test_model_name_is_resolved_from_the_repositorys_own_registered_config(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=lambda m: calls.append(m))
    repo_id = _register_repo(client, tmp_path, model="qwen2.5-coder:32b-specific")

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={"confirm": True})

    assert resp.status_code == 200
    assert resp.json()["model"] == "qwen2.5-coder:32b-specific"
    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)
    assert calls == ["qwen2.5-coder:32b-specific"]


def test_an_arbitrary_posted_model_name_is_rejected_and_ignored(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=lambda m: calls.append(m))
    repo_id = _register_repo(client, tmp_path, model="qwen2.5-coder")

    resp = client.post(
        f"/api/repositories/{repo_id}/pull-model",
        json={"confirm": True, "model": "attacker-supplied-model:latest"},
    )

    # The extra field is rejected outright (extra="forbid") -- never
    # silently accepted, and never used as the pull target either way.
    assert resp.status_code == 422
    assert calls == []


def test_an_arbitrary_posted_config_path_is_rejected_and_ignored(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=lambda m: calls.append(m))
    repo_id = _register_repo(client, tmp_path, model="qwen2.5-coder")

    resp = client.post(
        f"/api/repositories/{repo_id}/pull-model",
        json={"confirm": True, "configPath": "/some/other/config.yaml"},
    )

    assert resp.status_code == 422
    assert calls == []


def test_successful_pull_changes_readiness_to_run_ready(tmp_path, monkeypatch):
    calls = []
    client = _client(tmp_path, model_puller=lambda m: calls.append(m))
    repo_id = _register_repo(client, tmp_path, model="qwen2.5-coder")
    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    not_ready = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    assert not_ready.json()["runReady"] is False

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={"confirm": True})
    assert resp.status_code == 200

    import time
    for _ in range(50):
        status = client.get(f"/api/repositories/{repo_id}/pull-model").json()
        if status["status"] == "success":
            break
        time.sleep(0.05)
    assert status["status"] == "success"

    from draindeck_dashboard import launcher as launcher_module

    def _fake_tags(url, timeout=None):
        import json as _json

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return _json.dumps({"models": [{"name": "qwen2.5-coder"}]}).encode()

        return _Resp()

    monkeypatch.setattr(launcher_module.urllib.request, "urlopen", _fake_tags)
    ready = client.get(f"/api/launcher/readiness?repoId={repo_id}")
    assert ready.json()["runReady"] is True


def test_failure_is_shown_honestly(tmp_path):
    def _boom(model):
        raise RuntimeError("ollama pull exited with code 1")

    client = _client(tmp_path, model_puller=_boom)
    repo_id = _register_repo(client, tmp_path, model="qwen2.5-coder")

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={"confirm": True})
    assert resp.status_code == 200

    import time
    status = {}
    for _ in range(50):
        status = client.get(f"/api/repositories/{repo_id}/pull-model").json()
        if status["status"] == "failed":
            break
        time.sleep(0.05)
    assert status["status"] == "failed"
    assert "ollama pull exited with code 1" in status["error"]


def test_status_is_idle_before_any_pull_is_started(tmp_path):
    client = _client(tmp_path, model_puller=lambda m: None)
    repo_id = _register_repo(client, tmp_path)

    status = client.get(f"/api/repositories/{repo_id}/pull-model")
    assert status.status_code == 200
    assert status.json()["status"] == "idle"


def test_unknown_repo_id_returns_not_found(tmp_path):
    client = _client(tmp_path, model_puller=lambda m: None)

    resp = client.post("/api/repositories/999999/pull-model", json={"confirm": True})
    assert resp.status_code == 404

    resp2 = client.get("/api/repositories/999999/pull-model")
    assert resp2.status_code == 404


def test_pull_never_writes_target_config_events_or_run_state(tmp_path):
    calls = []
    client = _client(tmp_path, model_puller=lambda m: calls.append(m))
    repo_id = _register_repo(client, tmp_path)
    config_path_before = (tmp_path / "repo" / ".draindeck" / "config.local.yaml").read_text(encoding="utf-8")

    resp = client.post(f"/api/repositories/{repo_id}/pull-model", json={"confirm": True})
    assert resp.status_code == 200

    import time
    for _ in range(50):
        if calls:
            break
        time.sleep(0.05)

    config_path_after = (tmp_path / "repo" / ".draindeck" / "config.local.yaml").read_text(encoding="utf-8")
    assert config_path_before == config_path_after
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []
