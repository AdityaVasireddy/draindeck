"""Doc 34 Amendment 1: queue pause on cancel + explicit Resume (RED P-1..P-7).

Fixes the auto-start blocker: cancelling a QUEUED command must atomically pause
the repository's queue so no launch path (scheduler tick, drain, or
enqueue-triggered try_launch_next) can promote the next waiting command. Only an
explicit Resume clears the pause.

New symbols (is_queue_paused, resume_repository_queue, the run_queue_pauses
table) are imported inside test bodies so pre-implementation collection stays
valid and failures are genuinely behavioral.
"""
from __future__ import annotations

import threading

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.configured_issues import get_configured_issues
from draindeck_dashboard.errors import DashboardApiError
from draindeck_dashboard.repositories import register_repository as _register_repository
from draindeck_dashboard.run_launcher import try_launch_next
from draindeck_dashboard.run_queue import (
    STATUS_CANCELLED,
    STATUS_CLAIMED,
    STATUS_QUEUED,
    STATUS_REFUSED,
    claim_next_launchable_command,
    enqueue_command,
    get_command,
)
from draindeck_dashboard.worktree_preflight import WorktreePreflight

_DIRTY = WorktreePreflight(clean=False, blocking=False, untracked_count=1, detail="untracked")
_CLEAN = WorktreePreflight(clean=True, blocking=False, untracked_count=0, detail="clean")

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


def _bad_exe(tmp_path):
    return str(tmp_path / "does-not-exist.exe")


# ── RED P-1: cancel pauses; no launch path can promote #2 ──────────────────

def test_cancel_pauses_queue_and_scheduler_cannot_launch_next(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command, is_queue_paused

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    second = _enqueue(conn, repo_id, digest, issue_ids=["b"], key="k2")

    cancel_queued_command(conn, repo_id, first["id"])
    assert get_command(conn, first["id"])["status"] == STATUS_CANCELLED
    assert is_queue_paused(conn, repo_id) is True

    # Every launch path funnels through try_launch_next; repeated ticks must not
    # claim or launch #2 while paused.
    for _ in range(3):
        try_launch_next(conn, repo_id, executable=_bad_exe(tmp_path))
    assert get_command(conn, second["id"])["status"] == STATUS_QUEUED


# ── RED P-2: pause survives a fresh connection (durability) ─────────────────

def test_pause_survives_fresh_connection(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command, is_queue_paused

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    _enqueue(conn, repo_id, digest, issue_ids=["b"], key="k2")
    cancel_queued_command(conn, repo_id, first["id"])
    conn.close()

    fresh = connect_and_init(db)
    assert is_queue_paused(fresh, repo_id) is True
    assert claim_next_launchable_command(fresh, repo_id) is None


# ── RED P-3: resume clears the pause and re-enables FIFO progression ────────

def test_resume_clears_pause_and_allows_progression(tmp_path):
    from draindeck_dashboard.run_queue import (
        cancel_queued_command, is_queue_paused, resume_repository_queue,
    )

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    second = _enqueue(conn, repo_id, digest, issue_ids=["b"], key="k2")
    cancel_queued_command(conn, repo_id, first["id"])
    assert claim_next_launchable_command(conn, repo_id) is None  # paused

    result = resume_repository_queue(conn, repo_id)
    assert result["queuePaused"] is False
    assert is_queue_paused(conn, repo_id) is False
    claimed = claim_next_launchable_command(conn, repo_id)
    assert claimed is not None and claimed["id"] == second["id"]
    assert get_command(conn, second["id"])["status"] == STATUS_CLAIMED


# ── RED P-4: cancel-vs-claim race stays atomic under the pause rule ─────────

def test_cancel_vs_claim_race_atomic_with_pause(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command, is_queue_paused

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, digest = _register_ready(conn, tmp_path)

    for i in range(12):
        # Fresh single-command race each loop: clear any prior pause and
        # neutralize any prior CLAIMED so the repository is free to claim.
        conn.execute("DELETE FROM run_queue_pauses WHERE repository_id = ?", (repo_id,))
        conn.execute("UPDATE run_commands SET status = 'CANCELLED' WHERE repository_id = ? "
                     "AND status = 'CLAIMED'", (repo_id,))
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

        assert errors == [], f"no unexpected exception may escape: {errors}"
        final = get_command(conn, cmd["id"])["status"]
        assert final in (STATUS_CANCELLED, STATUS_CLAIMED), final
        if final == STATUS_CANCELLED:
            assert is_queue_paused(conn, repo_id) is True
            claimed = outcomes.get("claim")
            assert claimed is None or claimed["id"] != cmd["id"]
        else:  # claim won
            assert "cancel_err" in outcomes and outcomes["cancel_err"].code == "CANCEL_NOT_QUEUED"


# ── RED P-5: concurrent cancel + resume is atomic ──────────────────────────

def test_concurrent_cancel_and_resume_atomic(tmp_path):
    from draindeck_dashboard.run_queue import (
        cancel_queued_command, is_queue_paused, resume_repository_queue,
    )

    db = tmp_path / "d.sqlite3"
    conn = connect_and_init(db)
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")

    errors = []
    barrier = threading.Barrier(2)

    def do_cancel():
        c = connect_and_init(db)
        try:
            barrier.wait()
            cancel_queued_command(c, repo_id, cmd["id"])
        except DashboardApiError:
            pass
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    def do_resume():
        c = connect_and_init(db)
        try:
            barrier.wait()
            resume_repository_queue(c, repo_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            c.close()

    threads = [threading.Thread(target=do_cancel), threading.Thread(target=do_resume)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"no exception may escape a concurrent cancel/resume: {errors}"
    # Whatever serialized last decides; the state is internally consistent: if
    # the command is CANCELLED and the pause exists, they agree; a non-paused
    # repository simply means resume serialized after the cancel.
    final_status = get_command(conn, cmd["id"])["status"]
    paused = is_queue_paused(conn, repo_id)
    assert final_status in (STATUS_CANCELLED, STATUS_QUEUED)
    if final_status == STATUS_QUEUED:
        assert paused is False  # cancel refused/never ran -> no pause


# ── RED P-6: pause write never mutates runtime evidence ────────────────────

def test_pause_does_not_mutate_run_view_outcome(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    conn.execute("UPDATE run_commands SET run_id_correlation = 'run-1' WHERE id = ?", (cmd["id"],))
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
    assert outcome == "CHECKOUT_FAILED"


# ── RED D-U1: a dirty worktree defers before the claim (no claim, no refuse) ─

def test_try_launch_next_defers_on_dirty_worktree_without_claiming(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")

    # Always-dirty probe: progression must be deferred BEFORE the atomic claim,
    # so the command is never claimed and never marked REFUSED.
    result = try_launch_next(conn, repo_id, executable=_bad_exe(tmp_path),
                             worktree_probe=lambda c, r: _DIRTY)
    assert result is None  # nothing launched
    reloaded = get_command(conn, cmd["id"])
    assert reloaded["status"] == STATUS_QUEUED
    assert reloaded["claimedAt"] is None
    # No pause is created by a deferral (only a cancel pauses).
    assert conn.execute(
        "SELECT COUNT(*) FROM run_queue_pauses WHERE repository_id = ?", (repo_id,),
    ).fetchone()[0] == 0


# ── RED D-U2: race defense -- clean pre-claim, dirty before spawn -> REFUSED ─

def test_post_claim_revalidation_still_refuses_on_dirty_race(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")

    calls = {"n": 0}

    def flaky_probe(c, r):
        # Clean at the pre-claim check, dirty at the post-claim revalidation.
        calls["n"] += 1
        return _CLEAN if calls["n"] == 1 else _DIRTY

    result = try_launch_next(conn, repo_id, executable=_bad_exe(tmp_path),
                             worktree_probe=flaky_probe)
    assert result is not None and result["status"] == STATUS_REFUSED
    assert get_command(conn, cmd["id"])["status"] == STATUS_REFUSED
    assert calls["n"] >= 2  # both the pre-claim and post-claim checks ran


# ── RED D-U3: has_launchable_command guard ─────────────────────────────────

def test_has_launchable_command_guard(tmp_path):
    from draindeck_dashboard.run_queue import cancel_queued_command, has_launchable_command

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    # No commands -> nothing launchable.
    assert has_launchable_command(conn, repo_id) is False
    first = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    second = _enqueue(conn, repo_id, digest, issue_ids=["b"], key="k2")
    assert has_launchable_command(conn, repo_id) is True
    # A paused repository is not launchable.
    cancel_queued_command(conn, repo_id, first["id"])
    assert has_launchable_command(conn, repo_id) is False
    # An active (CLAIMED) command also blocks (one active batch per repo).
    conn.execute("DELETE FROM run_queue_pauses WHERE repository_id = ?", (repo_id,))
    conn.execute("UPDATE run_commands SET status = 'CLAIMED' WHERE id = ?", (second["id"],))
    conn.commit()
    assert has_launchable_command(conn, repo_id) is False


# ── delete_commands_for_repository also clears the pause (no orphan row) ────

def test_delete_commands_for_repository_clears_pause(tmp_path):
    from draindeck_dashboard.run_queue import (
        cancel_queued_command, delete_commands_for_repository, is_queue_paused,
    )

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    cancel_queued_command(conn, repo_id, cmd["id"])
    assert is_queue_paused(conn, repo_id) is True
    delete_commands_for_repository(conn, repo_id)
    assert is_queue_paused(conn, repo_id) is False


# ── RED P-7: migration creates the pause table additively ──────────────────

def test_migration_adds_pause_table_without_touching_run_commands(tmp_path):
    # A DB migrated to the current schema has run_queue_pauses.
    conn = connect_and_init(tmp_path / "d.sqlite3")
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_queue_pauses'"
    ).fetchone()
    assert exists is not None
    # And an existing run_commands row is untouched by the pause migration.
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue(conn, repo_id, digest, issue_ids=["a"], key="k1")
    assert get_command(conn, cmd["id"])["status"] == STATUS_QUEUED
