"""ADR-29 / spec/dashboard-target-configuration.md acceptance: the Dashboard
REST surface for controlled target configuration (preview/apply/read/edit),
end-to-end through the real FastAPI app and the real shared service -- no
mocking of runtime.init.service. Strict request schemas, typed errors, and
registration-only-after-durable-success are asserted here; the service's own
policy/safety guarantees are proven in tests/unit/test_target_configuration_service.py.
"""
from __future__ import annotations

import subprocess
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


def _run(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"setup git {args} failed: {p.stderr}")
    return p.stdout.strip()


def _git_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _run(repo, "init", "-b", "main")
    _run(repo, "config", "core.autocrlf", "false")
    (repo / "README").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "seed")
    return repo


def _yaml(repo: Path, branch: str = "agent-work") -> str:
    return f'''project:
  name: target
  repository: "{repo.as_posix()}"
  branch: {branch}
  validation:
    commands: ["python -m pytest tests/unit/test_x.py"]
engine:
  provider: claude-headless
  auth_mode: subscription
reviewer:
  provider: qwen
  qwen: {{endpoint: "http://localhost:11434", model: qwen2.5-coder:14b}}
budget: {{max_attempts_per_issue: 1, max_executions_per_run: 1, hard_stop_proxy_cost_per_run_usd: 1}}
experiment: {{sample_size: 20, attempt1_success_min: 0.3, cost_per_shipped_issue_max_usd: 3}}
billing: {{posture: x, headless_split_status: x, verified_on: "2026-08-29", reverify_at: x}}
'''


def test_detect_reports_stack_and_proposed_commands(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    resp = client.get("/api/target-configurations/detect", params={"projectPath": str(repo)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["chosenStack"] == "Rust"
    assert body["proposedCommands"] == ["cargo test"]
    assert not (repo / ".draindeck").exists()  # read-only


def test_detect_no_match_returns_empty_proposal(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.get("/api/target-configurations/detect", params={"projectPath": str(repo)})

    assert resp.status_code == 200
    body = resp.json()
    assert body["chosenStack"] is None
    assert body["proposedCommands"] == []


def test_detect_rejects_non_git_path(tmp_path):
    client = _client(tmp_path)

    resp = client.get("/api/target-configurations/detect",
                      params={"projectPath": str(tmp_path / "not-a-repo")})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONFIG_INVALID"


def test_render_produces_exact_config_yaml_that_loads(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    resp = client.post("/api/target-configurations/render", json={
        "projectPath": str(repo), "branch": "agent-work", "commands": ["cargo test"],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["chosenStack"] == "Rust"
    assert "cargo test" in body["renderedYaml"]
    assert not (repo / ".draindeck").exists()  # read-only, no file written


def test_render_empty_commands_produces_acknowledged_no_gate_config(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations/render", json={
        "projectPath": str(repo), "branch": "agent-work", "commands": [],
    })

    assert resp.status_code == 200
    assert "acknowledged_no_gate: true" in resp.json()["renderedYaml"]


def test_render_output_is_directly_usable_by_preview(tmp_path):
    """The render->preview->apply chain never round-trips through browser-
    assembled YAML -- render's output is exactly what preview/apply accept."""
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    rendered = client.post("/api/target-configurations/render", json={
        "projectPath": str(repo), "branch": "agent-work", "commands": ["echo ok"],
    }).json()["renderedYaml"]

    preview = client.post("/api/target-configurations/preview", json={
        "projectPath": str(repo), "renderedYaml": rendered,
    })

    assert preview.status_code == 200


def test_preview_is_side_effect_free(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations/preview", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["currentConfigDigest"] is None
    assert body["proposedConfigDigest"]
    assert not (repo / ".draindeck").exists()
    assert _run(repo, "status", "--porcelain") == ""
    assert _run(repo, "branch", "--show-current") == "main"


def test_preview_reports_predicted_branch_creation(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations/preview", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo, "agent-work"),
    })

    body = resp.json()
    assert body["branchOperation"] == "CREATE"
    assert body["branchConfirmationRequired"] is True


def test_preview_invalid_config_returns_typed_error(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations/preview", json={
        "projectPath": str(repo), "renderedYaml": "not: a valid draindeck config\n",
    })

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONFIG_INVALID"


def test_apply_without_branch_confirmation_creates_no_registration(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
    })

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "BRANCH_CONFIRMATION_REQUIRED"
    assert not (repo / ".draindeck" / "config.local.yaml").exists()
    assert client.get("/api/repositories").json()["repositories"] == []


def test_apply_new_target_writes_config_and_registers(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })

    assert resp.status_code == 201
    body = resp.json()
    assert body["result"]["branchOperation"] == "CREATE"
    assert body["registration"]["projectPath"] == str(repo.resolve())
    dest = repo / ".draindeck" / "config.local.yaml"
    assert dest.is_file()
    assert _run(repo, "branch", "--show-current") == "agent-work"

    listed = client.get("/api/repositories").json()["repositories"]
    assert [r["id"] for r in listed] == [body["registration"]["id"]]


def test_apply_failure_leaves_registration_untouched(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    (repo / "README").write_text("dirty tracked change\n")  # blocks apply

    resp = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DIRTY_WORKTREE"
    assert client.get("/api/repositories").json()["repositories"] == []
    assert not (repo / ".draindeck" / "config.local.yaml").exists()


def test_get_configuration_404_before_any_config_exists(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    registered = client.post("/api/repositories", json={"projectPath": str(repo)})
    repo_id = registered.json()["id"]

    resp = client.get(f"/api/repositories/{repo_id}/configuration")

    assert resp.status_code == 404


def test_get_configuration_after_apply_reports_digest(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    applied = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })
    repo_id = applied.json()["registration"]["id"]

    resp = client.get(f"/api/repositories/{repo_id}/configuration")

    assert resp.status_code == 200
    body = resp.json()
    assert body["currentConfigDigest"] == applied.json()["result"]["configDigest"]


def test_patch_configuration_updates_with_matching_digest(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    applied = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })
    repo_id = applied.json()["registration"]["id"]
    current_digest = applied.json()["result"]["configDigest"]

    resp = client.patch(f"/api/repositories/{repo_id}/configuration", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo, branch="agent-work"),
        "expectedConfigDigest": current_digest,
    })

    assert resp.status_code == 200


def test_patch_configuration_stale_digest_returns_conflict_without_overwrite(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    applied = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })
    repo_id = applied.json()["registration"]["id"]
    dest = repo / ".draindeck" / "config.local.yaml"
    original_bytes = dest.read_bytes()

    resp = client.patch(f"/api/repositories/{repo_id}/configuration", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "expectedConfigDigest": "0" * 64,
    })

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFIG_REVISION_CONFLICT"
    assert dest.read_bytes() == original_bytes


def test_patch_configuration_project_path_mismatch_is_rejected(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)
    other = _git_repo(tmp_path, "other")
    applied = client.post("/api/target-configurations", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo),
        "branchChangeConfirmed": True,
    })
    repo_id = applied.json()["registration"]["id"]

    resp = client.patch(f"/api/repositories/{repo_id}/configuration", json={
        "projectPath": str(other), "renderedYaml": _yaml(other),
    })

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "CONFIG_INVALID"


def test_preview_rejects_unexpected_field(tmp_path):
    client = _client(tmp_path)
    repo = _git_repo(tmp_path)

    resp = client.post("/api/target-configurations/preview", json={
        "projectPath": str(repo), "renderedYaml": _yaml(repo), "extra": "nope",
    })

    assert resp.status_code == 422
