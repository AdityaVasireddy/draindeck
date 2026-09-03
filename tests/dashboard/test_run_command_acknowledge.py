"""Doc 33 Part B: safe abnormal-exit acknowledge/unlock.

Behavioral RED tests (RED B-1..B-12) for
run_queue.acknowledge_abnormal_command. The process-identity probe is
injected (the same read-only PID/creation-time mechanism run_launcher uses)
so these stay hermetic; the API-level end-to-end flow is in
test_run_command_recovery_api.py.
"""
from __future__ import annotations

import threading

import pytest

from runtime.workspace_lease import ControllerIdentityResult, ControllerIdentityState

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import DashboardApiError
from draindeck_dashboard.configured_issues import get_configured_issues
from draindeck_dashboard.repositories import register_repository as _register_repository
from draindeck_dashboard.run_queue import (
    STATUS_ABNORMAL_EXIT,
    STATUS_COMPLETED,
    STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
    STATUS_LAUNCHED,
    enqueue_command,
    get_command,
    repository_has_active_command,
)

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


def _seed_confirmable_run_outcome(conn, repo_id, run_id, outcome):
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, "
        "inconsistent, updated_at) VALUES (?, 1, ?, ?, 0, '2026-08-31T00:00:00Z')",
        (repo_id, run_id, outcome),
    )
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-31T00:00:00Z')",
        (repo_id,),
    )
    conn.commit()


def _dead(_identity):
    return ControllerIdentityResult(ControllerIdentityState.DEAD, "gone")


def _live(_identity):
    return ControllerIdentityResult(ControllerIdentityState.LIVE_MATCH, "alive")


def _reused(_identity):
    return ControllerIdentityResult(ControllerIdentityState.PID_REUSED, "foreign")


def _unknown(_identity):
    return ControllerIdentityResult(ControllerIdentityState.UNKNOWN, "ambiguous")


def _make_abnormal(conn, tmp_path, *, pid=4242, creation="130000000000000000",
                   run_id_correlation=None, status=STATUS_ABNORMAL_EXIT):
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                          expected_issues_digest=digest, idempotency_key="k1")
    conn.execute(
        "UPDATE run_commands SET status = ?, process_pid = ?, process_creation_time = ?, "
        "run_id_correlation = ? WHERE id = ?",
        (status, pid, creation, run_id_correlation, cmd["id"]),
    )
    conn.commit()
    return repo_id, cmd["id"], digest


# ── RED B-1: happy path ────────────────────────────────────────────────────

def test_acknowledge_abnormal_dead_child_unlocks_repository(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_ACKNOWLEDGED, acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path)
    before = get_command(conn, cmd_id)
    result = acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert result["status"] == STATUS_ACKNOWLEDGED
    assert result["acknowledged"] is True
    assert repository_has_active_command(conn, repo_id) is False
    # Original selection left byte-for-byte unchanged (never expanded).
    assert get_command(conn, cmd_id)["issueIds"] == before["issueIds"] == ["a"]


# ── RED B-2/B-3: only ABNORMAL_EXIT may be acknowledged ────────────────────

@pytest.mark.parametrize("status", [STATUS_LAUNCHED, STATUS_COMPLETED,
                                     STATUS_LAUNCH_OWNERSHIP_UNKNOWN])
def test_acknowledge_refuses_non_abnormal_command(tmp_path, status):
    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path, status=status)
    with pytest.raises(DashboardApiError) as exc:
        acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert exc.value.code == "ACK_NOT_ABNORMAL"


# ── RED B-4/B-5/B-6: process ownership must prove DEAD ─────────────────────

@pytest.mark.parametrize("probe", [_live, _reused, _unknown])
def test_acknowledge_refuses_when_child_not_proven_dead(tmp_path, probe):
    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path)
    with pytest.raises(DashboardApiError) as exc:
        acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=probe)
    assert exc.value.code == "ACK_PROCESS_NOT_TERMINAL"


def test_acknowledge_refuses_when_identity_missing(tmp_path):
    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    # No pid/creation_time recorded -> real probe returns UNKNOWN (malformed).
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path, pid=None, creation=None)
    with pytest.raises(DashboardApiError) as exc:
        acknowledge_abnormal_command(conn, repo_id, cmd_id)  # real probe
    assert exc.value.code == "ACK_PROCESS_NOT_TERMINAL"


# ── RED B-7/B-8: correlated runtime run must be terminal ───────────────────

def test_acknowledge_refuses_when_correlated_run_not_terminal(tmp_path):
    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path, run_id_correlation="run-1")
    # run_views row exists but outcome is NULL == no RunFinished observed yet.
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, "
        "inconsistent, updated_at) VALUES (?, 1, 'run-1', NULL, 0, '2026-09-01T00:00:00Z')",
        (repo_id,),
    )
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-09-01T00:00:00Z')",
        (repo_id,),
    )
    conn.commit()
    with pytest.raises(DashboardApiError) as exc:
        acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert exc.value.code == "ACK_RUN_NOT_TERMINAL"


def test_acknowledge_allows_terminal_correlated_run(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_ACKNOWLEDGED, acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path, run_id_correlation="run-1")
    _seed_confirmable_run_outcome(conn, repo_id, "run-1", "CHECKOUT_FAILED")
    result = acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert result["status"] == STATUS_ACKNOWLEDGED


# ── RED B-9: target config / issues must revalidate ────────────────────────

def test_acknowledge_refuses_when_target_unverifiable(tmp_path):
    from pathlib import Path

    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path)
    # Delete the issues file so get_configured_issues can no longer revalidate.
    (tmp_path / "repo" / "Issues.md").unlink()
    with pytest.raises(DashboardApiError) as exc:
        acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert exc.value.code == "ACK_TARGET_UNVERIFIABLE"


# ── RED B-10: acknowledge never mutates runtime evidence ───────────────────

def test_acknowledge_does_not_mutate_run_view_outcome(tmp_path):
    from draindeck_dashboard.run_queue import acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path, run_id_correlation="run-1")
    _seed_confirmable_run_outcome(conn, repo_id, "run-1", "CHECKOUT_FAILED")
    acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    outcome = conn.execute(
        "SELECT outcome FROM run_views WHERE repository_id = ? AND run_id = 'run-1'", (repo_id,),
    ).fetchone()[0]
    assert outcome == "CHECKOUT_FAILED"  # runtime evidence untouched


# ── RED B-11: idempotent repeat ────────────────────────────────────────────

def test_acknowledge_is_idempotent(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_ACKNOWLEDGED, acknowledge_abnormal_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path)
    first = acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    second = acknowledge_abnormal_command(conn, repo_id, cmd_id, identity_probe=_dead)
    assert first["status"] == second["status"] == STATUS_ACKNOWLEDGED
    assert second["alreadyAcknowledged"] is True


# ── RED B-12: concurrent acknowledge is atomic ─────────────────────────────

def test_concurrent_acknowledge_exactly_one_fresh_success(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_ACKNOWLEDGED, acknowledge_abnormal_command

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, cmd_id, _digest = _make_abnormal(conn, tmp_path)

    results = []
    errors = []
    barrier = threading.Barrier(2)

    def worker():
        c = connect_and_init(db)
        try:
            barrier.wait()
            results.append(acknowledge_abnormal_command(c, repo_id, cmd_id, identity_probe=_dead))
        except Exception as exc:  # noqa: BLE001 - record, assert none below
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"no acknowledge may raise under concurrency: {errors}"
    assert len(results) == 2
    fresh = [r for r in results if not r.get("alreadyAcknowledged")]
    idempotent = [r for r in results if r.get("alreadyAcknowledged")]
    assert len(fresh) == 1 and len(idempotent) == 1
    assert get_command(conn, cmd_id)["status"] == STATUS_ACKNOWLEDGED
