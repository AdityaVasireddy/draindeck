"""Doc 34: safe Dashboard queue-cancel.

Behavioral RED tests (RED C-1..C-9) for run_queue.cancel_queued_command. Only
a command in exact status QUEUED is cancelable; cancel is an atomic competitor
with claim_next_launchable_command, never kills/interferes with a process,
never touches runtime evidence, and never auto-starts anything. The API-level
end-to-end flow is in test_run_command_cancel_api.py.

New symbols (STATUS_CANCELLED, CancelError, cancel_queued_command) are imported
inside each test body so pre-implementation collection stays valid and failures
are genuinely behavioral, not collection crashes (mirrors
test_run_command_acknowledge.py).
"""
from __future__ import annotations

import threading

import pytest

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import DashboardApiError, NotFoundError
from draindeck_dashboard.configured_issues import get_configured_issues
from draindeck_dashboard.repositories import register_repository as _register_repository
from draindeck_dashboard.run_queue import (
    STATUS_ABNORMAL_EXIT,
    STATUS_ACKNOWLEDGED,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_LAUNCH_FAILED,
    STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
    STATUS_LAUNCHED,
    STATUS_QUEUED,
    STATUS_REFUSED,
    claim_next_launchable_command,
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


def _enqueue(conn, repo_id, digest, *, issue_ids, key):
    return enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=issue_ids,
                           expected_issues_digest=digest, idempotency_key=key)


def _set_status(conn, cmd_id, status):
    conn.execute("UPDATE run_commands SET status = ? WHERE id = ?", (status, cmd_id))
    conn.commit()


# ── RED C-1: happy path -- QUEUED cancels, no spawn ────────────────────────

def test_cancel_queued_command_marks_cancelled_and_spawns_nothing(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_CANCELLED, cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    assert cmd["status"] == STATUS_QUEUED

    result = cancel_queued_command(conn, repo_id, cmd["id"])
    assert result["status"] == STATUS_CANCELLED
    assert result.get("cancelled") is True
    # Never claimed/launched: the command went straight from QUEUED to CANCELLED.
    reloaded = get_command(conn, cmd["id"])
    assert reloaded["status"] == STATUS_CANCELLED
    assert reloaded["claimedAt"] is None
    assert reloaded["processPid"] is None
    # A non-blocking terminal state releases nothing it should not, holds nothing.
    assert repository_has_active_command(conn, repo_id) is False


# ── RED C-2: only exact QUEUED may be cancelled ────────────────────────────

@pytest.mark.parametrize("status", [
    STATUS_CLAIMED, STATUS_LAUNCHED, STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
    STATUS_ABNORMAL_EXIT, STATUS_ACKNOWLEDGED, STATUS_COMPLETED,
    STATUS_REFUSED, STATUS_LAUNCH_FAILED,
])
def test_cancel_refuses_every_non_queued_status(tmp_path, status):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    _set_status(conn, cmd["id"], status)

    with pytest.raises(DashboardApiError) as exc:
        cancel_queued_command(conn, repo_id, cmd["id"])
    assert exc.value.code == "CANCEL_NOT_QUEUED"
    # No state change on refusal.
    assert get_command(conn, cmd["id"])["status"] == status


def test_cancel_of_already_cancelled_is_refused(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_CANCELLED, cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    cancel_queued_command(conn, repo_id, cmd["id"])
    with pytest.raises(DashboardApiError) as exc:
        cancel_queued_command(conn, repo_id, cmd["id"])
    assert exc.value.code == "CANCEL_NOT_QUEUED"
    assert get_command(conn, cmd["id"])["status"] == STATUS_CANCELLED


# ── RED C-3: ABNORMAL_EXIT refusal steers to acknowledge/unlock ────────────

def test_cancel_of_abnormal_exit_points_at_acknowledge(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    _set_status(conn, cmd["id"], STATUS_ABNORMAL_EXIT)
    with pytest.raises(DashboardApiError) as exc:
        cancel_queued_command(conn, repo_id, cmd["id"])
    assert exc.value.code == "CANCEL_NOT_QUEUED"
    assert "acknowledge" in str(exc.value).lower()


# ── RED C-4: FIFO positions recompute after cancellation ───────────────────

def test_cancel_recomputes_fifo_positions(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    second = _enqueue(conn, repo_id, digest, issue_ids=["b"], key="k2")
    assert get_command(conn, first["id"])["queuePosition"] == 1
    assert get_command(conn, second["id"])["queuePosition"] == 2

    cancel_queued_command(conn, repo_id, first["id"])
    # The surviving queued command moves up to position 1 (FIFO preserved).
    assert get_command(conn, second["id"])["queuePosition"] == 1
    assert get_command(conn, first["id"])["queuePosition"] is None


# ── RED C-5: cancel never mutates runtime evidence ─────────────────────────

def test_cancel_does_not_mutate_run_view_outcome(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    conn.execute(
        "UPDATE run_commands SET run_id_correlation = 'run-1' WHERE id = ?", (cmd["id"],),
    )
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, "
        "inconsistent, updated_at) VALUES (?, 1, 'run-1', 'CHECKOUT_FAILED', 0, "
        "'2026-09-01T00:00:00Z')", (repo_id,),
    )
    conn.commit()

    cancel_queued_command(conn, repo_id, cmd["id"])
    outcome = conn.execute(
        "SELECT outcome FROM run_views WHERE repository_id = ? AND run_id = 'run-1'", (repo_id,),
    ).fetchone()[0]
    assert outcome == "CHECKOUT_FAILED"  # runtime evidence untouched


# ── RED C-6: unknown command / cross-repository refusal ────────────────────

def test_cancel_unknown_command_raises_not_found(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, _digest = _register_ready(conn, tmp_path)
    with pytest.raises(NotFoundError):
        cancel_queued_command(conn, repo_id, 999999)


def test_cancel_refuses_cross_repository_command(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_a, digest_a = _register_ready(conn, tmp_path, name="a")
    repo_b, _digest_b = _register_ready(conn, tmp_path, name="b")
    cmd = _enqueue(conn, repo_a, digest_a, issue_ids=["a"], key="k1")
    # Try to cancel repo_a's command through repo_b's id: not found for that repo.
    with pytest.raises(NotFoundError):
        cancel_queued_command(conn, repo_b, cmd["id"])
    assert get_command(conn, cmd["id"])["status"] == STATUS_QUEUED


# ── RED C-7: two concurrent cancels -> exactly one success, one conflict ────

def test_concurrent_cancel_exactly_one_success(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_CANCELLED, cancel_queued_command

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")

    results = []
    errors = []
    barrier = threading.Barrier(2)

    def worker():
        c = connect_and_init(db)
        try:
            barrier.wait()
            results.append(cancel_queued_command(c, repo_id, cmd["id"]))
        except DashboardApiError as exc:
            errors.append(exc)
        except Exception as exc:  # noqa: BLE001 -- any other exception is a bug
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one success, exactly one CANCEL_NOT_QUEUED conflict, no 500-shaped
    # exception (KeyError/IntegrityError/OperationalError) escaping.
    assert len(results) == 1, f"exactly one cancel may succeed: {results}, {errors}"
    assert len(errors) == 1
    assert isinstance(errors[0], DashboardApiError) and errors[0].code == "CANCEL_NOT_QUEUED"
    assert results[0]["status"] == STATUS_CANCELLED
    assert get_command(conn, cmd["id"])["status"] == STATUS_CANCELLED


# ── RED C-8: cancel vs. claim race -- atomic competitors ───────────────────

def test_cancel_and_claim_are_atomic_competitors(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_CANCELLED, cancel_queued_command

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, digest = _register_ready(conn, tmp_path)

    for i in range(12):
        # Reset the repository to free for a fresh single-command race each loop:
        # clear any pause a prior iteration's winning cancel wrote (doc 34
        # Amendment 1), and neutralize any prior CLAIMED command.
        conn.execute("DELETE FROM run_queue_pauses WHERE repository_id = ?", (repo_id,))
        conn.execute(
            "UPDATE run_commands SET status = 'CANCELLED' WHERE repository_id = ? "
            "AND status = 'CLAIMED'", (repo_id,),
        )
        conn.commit()
        cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key=f"k{i}")

        outcomes = {}
        errors = []
        barrier = threading.Barrier(2)

        def do_cancel():
            c = connect_and_init(db)
            try:
                barrier.wait()
                outcomes["cancel"] = cancel_queued_command(c, repo_id, cmd["id"])
            except DashboardApiError as exc:
                outcomes["cancel_err"] = exc
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                c.close()

        def do_claim():
            c = connect_and_init(db)
            try:
                barrier.wait()
                outcomes["claim"] = claim_next_launchable_command(c, repo_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                c.close()

        threads = [threading.Thread(target=do_cancel), threading.Thread(target=do_claim)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"no unexpected exception may escape the race: {errors}"
        final = get_command(conn, cmd["id"])["status"]
        # The invariant: exactly one of {cancel, claim} won this row.
        assert final in (STATUS_CANCELLED, STATUS_CLAIMED), final
        if final == STATUS_CANCELLED:
            # Cancel won: it succeeded and the claim did not claim THIS command.
            assert "cancel" in outcomes and outcomes["cancel"]["status"] == STATUS_CANCELLED
            claimed = outcomes.get("claim")
            assert claimed is None or claimed["id"] != cmd["id"]
        else:  # STATUS_CLAIMED
            # Claim won: cancel refused; the process the claim will spawn is untouched.
            assert "cancel_err" in outcomes
            assert outcomes["cancel_err"].code == "CANCEL_NOT_QUEUED"


# ── RED C-9: CANCELLED is a non-blocking terminal status ───────────────────

def test_cancelled_status_is_non_blocking(tmp_path):
    from draindeck_dashboard.run_queue import STATUS_CANCELLED, _BLOCKING_STATUSES

    assert STATUS_CANCELLED not in _BLOCKING_STATUSES
