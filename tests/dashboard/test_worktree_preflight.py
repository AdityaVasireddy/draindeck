"""Doc 33 Part A: clean-worktree preflight (WORKTREE_NOT_CLEAN).

Behavioral RED tests (RED A-1..A-8) for the injected worktree preflight and
its enforcement at run-request (enqueue) and dequeue-revalidation time. The
status probe is injected so these stay hermetic (fake ``.git`` dirs, no real
git); the real end-to-end enforcement against a live git repo is proven in
test_run_command_recovery_api.py.
"""
from __future__ import annotations

import pytest

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import DashboardApiError
from draindeck_dashboard.repositories import register_repository
from draindeck_dashboard.run_queue import (
    STATUS_QUEUED,
    STATUS_REFUSED,
    enqueue_command,
    get_command,
    list_commands_for_repository,
    revalidate_claimed_command,
)

from draindeck_dashboard.configured_issues import get_configured_issues
from draindeck_dashboard.repositories import register_repository as _register_repository

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


def _register_ready(conn, tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    (repo / "Issues.md").write_text("## a: A\nbody\n\n## b: B\nbody\n",
                                    encoding="utf-8", newline="")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    registration = _register_repository(conn, project_path=str(repo), config_path=str(config_path))
    repo_id = registration["id"]
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.commit()
    digest = get_configured_issues(conn, repo_id)["issuesFileRevision"]
    return repo_id, digest


def _clean_probe(conn, repo_id):
    from draindeck_dashboard.worktree_preflight import WorktreePreflight
    return WorktreePreflight(clean=True, blocking=False, untracked_count=0, detail="clean")


def _dirty_untracked_probe(conn, repo_id):
    from draindeck_dashboard.worktree_preflight import WorktreePreflight
    return WorktreePreflight(clean=False, blocking=False, untracked_count=1,
                             detail="1 untracked file(s)")


def _dirty_blocking_probe(conn, repo_id):
    from draindeck_dashboard.worktree_preflight import WorktreePreflight
    return WorktreePreflight(clean=False, blocking=True, untracked_count=0,
                             detail="tracked/staged changes present")


# ── RED A-1..A-4: the evaluator itself ─────────────────────────────────────

def test_evaluate_reports_clean_when_status_probe_clean(tmp_path):
    from draindeck_dashboard.worktree_preflight import evaluate_worktree_preflight
    from runtime.repo.git_adapter import WorktreeStatus

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, _digest = _register_ready(conn, tmp_path)
    pf = evaluate_worktree_preflight(
        conn, repo_id,
        status_probe=lambda p: WorktreeStatus(untracked_only=False, untracked_count=0, blocking=False),
    )
    assert pf.clean is True


def test_evaluate_reports_not_clean_for_untracked_only(tmp_path):
    from draindeck_dashboard.worktree_preflight import evaluate_worktree_preflight
    from runtime.repo.git_adapter import WorktreeStatus

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, _digest = _register_ready(conn, tmp_path)
    pf = evaluate_worktree_preflight(
        conn, repo_id,
        status_probe=lambda p: WorktreeStatus(untracked_only=True, untracked_count=1, blocking=False),
    )
    assert pf.clean is False
    assert pf.untracked_count == 1


def test_evaluate_reports_not_clean_for_blocking_changes(tmp_path):
    from draindeck_dashboard.worktree_preflight import evaluate_worktree_preflight
    from runtime.repo.git_adapter import WorktreeStatus

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, _digest = _register_ready(conn, tmp_path)
    pf = evaluate_worktree_preflight(
        conn, repo_id,
        status_probe=lambda p: WorktreeStatus(untracked_only=False, untracked_count=0, blocking=True),
    )
    assert pf.clean is False
    assert pf.blocking is True


def test_evaluate_fails_closed_when_probe_raises(tmp_path):
    from draindeck_dashboard.worktree_preflight import evaluate_worktree_preflight

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, _digest = _register_ready(conn, tmp_path)

    def _raises(_path):
        raise RuntimeError("not a git repository")

    pf = evaluate_worktree_preflight(conn, repo_id, status_probe=_raises)
    assert pf.clean is False  # fail-closed, never propagates


# ── RED A-5..A-7: enforcement at enqueue + dequeue ─────────────────────────

def test_enqueue_refuses_dirty_worktree_and_creates_no_row(tmp_path):
    from draindeck_dashboard.worktree_preflight import WorktreeNotCleanError

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    with pytest.raises(WorktreeNotCleanError) as exc:
        enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                        expected_issues_digest=digest, idempotency_key="k1",
                        worktree_probe=_dirty_untracked_probe)
    assert exc.value.code == "WORKTREE_NOT_CLEAN"
    assert list_commands_for_repository(conn, repo_id) == []


def test_enqueue_clean_worktree_creates_row(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1",
                          worktree_probe=_clean_probe)
    assert cmd["status"] == STATUS_QUEUED


def test_revalidate_refuses_dirty_worktree_and_releases_slot(tmp_path):
    from draindeck_dashboard.run_queue import claim_next_launchable_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                    expected_issues_digest=digest, idempotency_key="k1",
                    worktree_probe=_clean_probe)
    claimed = claim_next_launchable_command(conn, repo_id)
    revalidated = revalidate_claimed_command(conn, claimed, worktree_probe=_dirty_blocking_probe)
    assert revalidated["status"] == STATUS_REFUSED
    assert "WORKTREE_NOT_CLEAN" in (revalidated["refusalReason"] or "")


# ── RED A-8: default (no probe) skips the check (existing-suite compat) ─────

def test_enqueue_without_probe_skips_worktree_check(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    assert cmd["status"] == STATUS_QUEUED
