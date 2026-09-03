"""Doc 33 Parts A+B, end to end through the real FastAPI app and a real git
worktree (RED A-9..A-11, B-13..B-15).

Proves the *authoritative* backend enforcement: the API refuses a dirty
target before any subprocess, the worktree-preflight advisory endpoint tells
the truth, and the acknowledge endpoint safely unlocks a genuinely-dead
ABNORMAL_EXIT command so a fresh explicit request is admitted.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig
from draindeck_dashboard.repositories import register_repository

_CONFIG_YAML = """
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


def _git(cwd: Path, *args: str) -> None:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"git {args} failed: {p.stderr}")


def _client(tmp_path: Path) -> TestClient:
    cfg = DashboardConfig(db_path=str(tmp_path / "dashboard.sqlite3"),
                          observer_executable=str(tmp_path / "nope.exe"))
    return TestClient(create_app(cfg), base_url="http://127.0.0.1")


def _make_repo_and_register(tmp_path: Path, client: TestClient, *, commit_issues: bool):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "agent-work")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    (repo / "Issues.md").write_text("## a: A\nbody\n", encoding="utf-8", newline="")
    if commit_issues:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "issues")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    if commit_issues:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "config")

    conn = client.app.state.db
    reg = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    repo_id = reg["id"]
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'PENDING', '2026-09-01T00:00:00Z')", (repo_id,),
    )
    conn.commit()
    from draindeck_dashboard.configured_issues import get_configured_issues
    digest = get_configured_issues(conn, repo_id)["issuesFileRevision"]
    return repo, repo_id, digest


# ── RED A-9/A-10: enqueue refuses a dirty target, admits a clean one ───────

def test_run_command_refused_when_issues_md_untracked(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "k1"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "WORKTREE_NOT_CLEAN"
    got = client.get(f"/api/repositories/{repo_id}/run-commands").json()
    assert got["commands"] == []


def test_run_command_admitted_after_issues_md_committed(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "k1"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 201, resp.text
    got = client.get(f"/api/repositories/{repo_id}/run-commands").json()
    assert len(got["commands"]) == 1


# ── RED A-11: advisory worktree-preflight endpoint ─────────────────────────

def test_worktree_preflight_endpoint_reports_dirty_then_clean(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    dirty = client.get(f"/api/repositories/{repo_id}/worktree-preflight").json()
    assert dirty["clean"] is False
    assert "Issues.md" in dirty["message"]

    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "issues+config")
    clean = client.get(f"/api/repositories/{repo_id}/worktree-preflight").json()
    assert clean["clean"] is True


# ── RED B-13/B-14: acknowledge endpoint ────────────────────────────────────

def _seed_abnormal(client: TestClient, repo_id: int, digest: str, *, status: str) -> int:
    """Insert an ABNORMAL_EXIT (or other) command directly (no real subprocess).
    A bogus, almost-certainly-absent PID makes the real identity probe report
    DEAD for the acknowledge happy path."""
    conn = client.app.state.db
    conn.execute(
        "INSERT INTO run_commands (repository_id, mode, issue_ids_json, issues_digest, "
        "idempotency_key, normalized_request_json, status, process_pid, process_creation_time, "
        "created_at) VALUES (?, 'SELECTED', '[\"a\"]', ?, 'seed', '{}', ?, 999999, "
        "'130000000000000000', '2026-09-01T00:00:00Z')",
        (repo_id, digest, status),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_acknowledge_endpoint_unlocks_abnormal_exit(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_abnormal(client, repo_id, digest, status="ABNORMAL_EXIT")
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/acknowledge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ACKNOWLEDGED"


def test_acknowledge_endpoint_refuses_non_abnormal(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_abnormal(client, repo_id, digest, status="LAUNCHED")
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/acknowledge")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "ACK_NOT_ABNORMAL"


# ── RED B-15: full reproduced flow ─────────────────────────────────────────

def test_reproduced_flow_dirty_refused_then_acknowledge_then_fresh_admitted(tmp_path):
    client = _client(tmp_path)
    # Uncommitted Issues.md -> a fresh run is refused.
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    refused = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "k1"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert refused.status_code == 409

    # A prior failed batch is stuck ABNORMAL_EXIT, blocking the repository.
    cmd_id = _seed_abnormal(client, repo_id, digest, status="ABNORMAL_EXIT")

    # Operator commits Issues.md (and config), then acknowledges the failure.
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "commit issues + config")
    ack = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/acknowledge")
    assert ack.status_code == 200, ack.text

    # A fresh, explicitly requested command is now admitted (never auto-retried).
    fresh = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "k2"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert fresh.status_code == 201, fresh.text
