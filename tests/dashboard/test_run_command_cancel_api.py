"""Doc 34, end to end through the real FastAPI app and a real git worktree
(RED A-1..A-5).

Proves the authoritative backend behavior: the cancel endpoint removes only a
QUEUED waiting batch, is never blocked by launch preflight (cancel works with a
dirty worktree), refuses a non-QUEUED command, 404s an unknown command, and
never auto-starts anything after a cancel.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

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


def _seed_command(client: TestClient, repo_id: int, digest: str, *, status: str,
                  key: str = "seed") -> int:
    """Insert a run command directly in a chosen status (no real subprocess)."""
    conn = client.app.state.db
    conn.execute(
        "INSERT INTO run_commands (repository_id, mode, issue_ids_json, issues_digest, "
        "idempotency_key, normalized_request_json, status, created_at) "
        "VALUES (?, 'SELECTED', '[\"a\"]', ?, ?, '{}', ?, '2026-09-01T00:00:00Z')",
        (repo_id, digest, key, status),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# ── RED A-1: cancel a QUEUED command ───────────────────────────────────────

def test_cancel_endpoint_cancels_queued_command(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED")
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"


# ── RED A-2: cancel is NOT blocked by a dirty worktree ─────────────────────

def test_cancel_endpoint_works_with_dirty_worktree(tmp_path):
    client = _client(tmp_path)
    # Uncommitted Issues.md -> worktree is dirty; a launch would be refused, but
    # cancel is state-safe and must still remove a waiting batch.
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED")
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "CANCELLED"


# ── RED A-3: cancel refuses a non-QUEUED command ───────────────────────────

def test_cancel_endpoint_refuses_abnormal_exit(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="ABNORMAL_EXIT")
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "CANCEL_NOT_QUEUED"


# ── RED A-4: unknown command 404s ──────────────────────────────────────────

def test_cancel_endpoint_unknown_command_is_404(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, _digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    resp = client.post(f"/api/repositories/{repo_id}/run-commands/999999/cancel")
    assert resp.status_code == 404, resp.text


# ── RED A-5: cancel never auto-starts another command ──────────────────────

def test_cancel_endpoint_does_not_auto_start_anything(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    other = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-2")
    client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    # Cancelling one command must not claim/launch the other one.
    got = client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]
    by_id = {c["id"]: c for c in got}
    assert by_id[cmd_id]["status"] == "CANCELLED"
    assert by_id[other]["status"] == "QUEUED"


# ── RED A-6: cancel pauses; drain while paused does not launch #2 ───────────

def test_cancel_pauses_queue_and_drain_does_not_launch(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    other = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-2")
    cancel = client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    assert cancel.status_code == 200, cancel.text

    listing = client.get(f"/api/repositories/{repo_id}/run-commands").json()
    assert listing["queuePaused"] is True

    drain = client.post(f"/api/repositories/{repo_id}/run-commands/drain")
    assert drain.status_code == 200, drain.text
    assert drain.json()["launched"] is None
    after = client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]
    assert {c["id"]: c["status"] for c in after}[other] == "QUEUED"


# ── RED A-7: a new run request while paused queues but does not launch ─────

def test_new_run_request_while_paused_queues_but_does_not_launch(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")

    fresh = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "fresh-1"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert fresh.status_code == 201, fresh.text
    assert fresh.json()["status"] == "QUEUED"
    listing = client.get(f"/api/repositories/{repo_id}/run-commands").json()
    assert listing["queuePaused"] is True  # a new request never clears the pause


# ── RED A-8: resume endpoint clears the pause; unknown repo 404s ───────────

def test_resume_endpoint_clears_pause(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=True)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    client.post(f"/api/repositories/{repo_id}/run-commands/{cmd_id}/cancel")
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["queuePaused"] is True

    resume = client.post(f"/api/repositories/{repo_id}/run-commands/resume")
    assert resume.status_code == 200, resume.text
    assert resume.json()["queuePaused"] is False
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["queuePaused"] is False


def test_resume_endpoint_unknown_repo_is_404(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/api/repositories/999999/run-commands/resume")
    assert resp.status_code == 404, resp.text


# ── Doc 34 Amendment 2: deferred progression on a dirty worktree ───────────

# ── RED D-1: Resume while dirty defers -- command stays QUEUED, not REFUSED ─

def test_resume_while_dirty_defers_and_preserves_queued_command(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    first = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    # Cancel #1 to pause the queue; #2 waits.
    client.post(f"/api/repositories/{repo_id}/run-commands/{first}/cancel")
    second = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-2")

    resume = client.post(f"/api/repositories/{repo_id}/run-commands/resume")
    assert resume.status_code == 200, resume.text
    body = resume.json()
    assert body["queuePaused"] is False
    assert body["progressionDeferred"] is True
    # The waiting batch must survive -- never claimed, never REFUSED.
    got = {c["id"]: c["status"] for c in
           client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]}
    assert got[second] == "QUEUED"


# ── RED D-2: drain while dirty leaves the command QUEUED ────────────────────

def test_drain_while_dirty_leaves_command_queued(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    drain = client.post(f"/api/repositories/{repo_id}/run-commands/drain")
    assert drain.status_code == 200, drain.text
    assert drain.json()["launched"] is None
    got = {c["id"]: c["status"] for c in
           client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]}
    assert got[cmd_id] == "QUEUED"


# ── RED D-3: scheduler tick while dirty leaves the command QUEUED ───────────

def test_scheduler_tick_while_dirty_leaves_command_queued(tmp_path):
    from draindeck_dashboard.queue_scheduler import QueueDrainScheduler

    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    QueueDrainScheduler(client.app.state.db, str(tmp_path / "nope.exe")).tick()
    got = {c["id"]: c["status"] for c in
           client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]}
    assert got[cmd_id] == "QUEUED"


# ── RED D-4: once clean, the next drain claims the command (FIFO progresses) ─

def test_progression_resumes_once_worktree_is_clean(tmp_path):
    client = _client(tmp_path)
    repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    cmd_id = _seed_command(client, repo_id, digest, status="QUEUED", key="seed-1")
    # Dirty: drain defers, command stays QUEUED.
    client.post(f"/api/repositories/{repo_id}/run-commands/drain")
    assert {c["id"]: c["status"] for c in
            client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]
            }[cmd_id] == "QUEUED"
    # Commit everything -> clean. The next drain claims (and, with the fake
    # executable, launch-fails) -- the point is the command left QUEUED.
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "commit issues + config")
    client.post(f"/api/repositories/{repo_id}/run-commands/drain")
    status_after = {c["id"]: c["status"] for c in
                    client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]}[cmd_id]
    assert status_after != "QUEUED", status_after


# ── RED D-5: a direct new run request while dirty still creates no row ──────

def test_new_run_request_while_dirty_creates_no_row(tmp_path):
    client = _client(tmp_path)
    _repo, repo_id, digest = _make_repo_and_register(tmp_path, client, commit_issues=False)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        headers={"Idempotency-Key": "k1"},
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "WORKTREE_NOT_CLEAN"
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []
