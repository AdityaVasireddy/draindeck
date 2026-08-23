"""Unit 16 continuation (docs/27 SS3.2 decision 9 / SS8.4): the scheduler
is rebuild_read_models' real lease-owned production caller. Covers the
required scenario list: initial backfill, unsafe mutation, generation
rollover, preparing, stale/rebuilding, ready, failure, retry, and lease
loss.

Uses the same fake-tick pattern as test_scheduler.py (monkeypatching
`ingest_repository_tick`) so each scenario can precisely control the
TickOutcome and the read-model state it implies, without depending on a
real observer subprocess or file-cursor mechanics.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from draindeck_dashboard import indexer, lease
from draindeck_dashboard import scheduler as scheduler_module
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.read_models import (
    LeaseLostError,
    mark_preparing,
    mark_rebuilding,
    read_model_status,
    rebuild_read_models,
)
from draindeck_dashboard.repositories import register_repository


def _seed_ready_baseline_then_release_lease(conn, repo_id, gen_id):
    """Establishes a READY baseline via a standalone rebuild under a
    throwaway owner, then backdates the lease so the real Scheduler
    started afterward (which uses its own random owner_token) can
    immediately take over -- without this, the Scheduler's own
    acquire_or_renew would see an unexpired lease held by a DIFFERENT
    owner and never become leader (rebuild_read_models now requires the
    caller to actually hold the lease, this session's merge-blocker fix)."""
    owner = "setup-owner"
    lease.acquire_or_renew(conn, owner)
    rebuild_read_models(conn, repo_id, gen_id, owner)
    stale = datetime.now(timezone.utc) - timedelta(seconds=lease.TTL_SECONDS + 1)
    conn.execute("UPDATE indexer_lease SET heartbeat_at = ? WHERE id = 1",
                (stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),))


def _register(conn, tmp_path, name="repo"):
    repo_dir = tmp_path / name
    (repo_dir / ".git").mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / f"{name}-events.jsonl"
    return register_repository(conn, project_path=str(repo_dir), log_path=str(log_path))["id"]


def _seed_generation_and_checkpoint(conn, repo_id):
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 1, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')",
        (repo_id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    return gen_id


def _insert_evidence(conn, repo_id, gen_id, event_id, issue_id="42"):
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, schema_version, issue_id, event_ts, stored_at) "
        "VALUES (?, ?, ?, 'OK', ?, 'IssueCreated', 1, ?, '2026-08-23T00:00:00Z', "
        "'2026-08-23T00:00:00Z')",
        (repo_id, gen_id, f"c{event_id}", event_id, issue_id),
    )


async def _run_scheduler_until(conn, condition, *, timeout_iterations=100):
    """Runs the scheduler until `condition()` is truthy (or the iteration
    budget is exhausted), then stops it and returns whether the condition
    was actually met -- callers query whatever state they care about
    themselves afterward, since `condition` is a boolean predicate, not a
    value producer."""
    s = scheduler_module.Scheduler(conn, "exe")
    s.start()
    met = False
    for _ in range(timeout_iterations):
        await asyncio.sleep(0.02)
        if condition():
            met = True
            break
    await s.stop()
    return met


def test_initial_backfill_reaches_ready_once_caught_up(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
        mark_preparing(conn, repo_id_arg, gen_id)
        _insert_evidence(conn, repo_id_arg, gen_id, 1)
        return indexer.TickOutcome(status="ok", pages_ingested=1)  # < MAX_PAGES_PER_TICK: caught up

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    met = asyncio.run(_run_scheduler_until(
        conn, lambda: (read_model_status(conn, repo_id) or {}).get("status") == "READY"))
    assert met
    final = read_model_status(conn, repo_id)
    assert final["status"] == "READY"
    assert final["completedEvidenceId"] == 1


def test_multi_page_backfill_stays_preparing_until_the_final_caught_up_tick(tmp_path, monkeypatch):
    """A backfill spanning more pages than MAX_PAGES_PER_TICK must not pay
    the full-rebuild cost on every intermediate tick -- only once caught
    up. Simulated via two fake ticks: the first reports a FULL page budget
    (not caught up), the second reports fewer pages (caught up)."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    call_count = {"n": 0}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
            mark_preparing(conn, repo_id_arg, gen_id)
            _insert_evidence(conn, repo_id_arg, gen_id, 1)
            from draindeck_dashboard.poller import MAX_PAGES_PER_TICK
            return indexer.TickOutcome(status="ok", pages_ingested=MAX_PAGES_PER_TICK)  # not caught up
        if call_count["n"] == 2:
            # Observed status exactly after the first tick committed but
            # before any second tick started -- deterministic (event-based),
            # not a fixed sleep guess that could race the scheduler's own
            # 0.01s cadence.
            fake_tick.mid_status = (read_model_status(conn, repo_id_arg) or {}).get("status")
        gen_id = conn.execute(
            "SELECT identity_generation_id FROM checkpoints WHERE repository_id = ?", (repo_id_arg,)
        ).fetchone()[0]
        _insert_evidence(conn, repo_id_arg, gen_id, 2)
        return indexer.TickOutcome(status="ok", pages_ingested=1)  # caught up

    fake_tick.mid_status = None
    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    met = asyncio.run(_run_scheduler_until(
        conn, lambda: (read_model_status(conn, repo_id) or {}).get("status") == "READY"))
    assert met
    assert read_model_status(conn, repo_id)["status"] == "READY"
    # At the instant the SECOND tick began (i.e. immediately after the
    # first, not-caught-up tick's rebuild-eligibility check ran), status
    # must still have been PREPARING -- confirming the scheduler did not
    # pay the full-rebuild cost on that first, still-catching-up tick.
    assert fake_tick.mid_status == "PREPARING"


def test_unsafe_mutation_marks_rebuilding_then_rebuild_restores_ready(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    gen_id = _seed_generation_and_checkpoint(conn, repo_id)
    _insert_evidence(conn, repo_id, gen_id, 1)
    _seed_ready_baseline_then_release_lease(conn, repo_id, gen_id)  # establish a READY baseline
    assert read_model_status(conn, repo_id)["status"] == "READY"

    call_count = {"n": 0}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            mark_rebuilding(conn, repo_id_arg)  # simulates indexer.py detecting an unsafe mutation
        return indexer.TickOutcome(status="ok", pages_ingested=1)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    # Status is already READY from the baseline before the scheduler even
    # starts, so "wait for READY" alone would trivially pass without ever
    # observing the REBUILDING transition -- wait for at least a second
    # tick to have started instead (confirming tick 1's mark_rebuilding
    # AND this unit's own rebuild-eligibility check both already ran),
    # then assert the end state.
    met = asyncio.run(_run_scheduler_until(conn, lambda: call_count["n"] >= 2))
    assert met
    assert read_model_status(conn, repo_id)["status"] == "READY"


def test_generation_rollover_reaches_ready_for_the_new_generation(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    old_gen_id = _seed_generation_and_checkpoint(conn, repo_id)
    _insert_evidence(conn, repo_id, old_gen_id, 1)
    _seed_ready_baseline_then_release_lease(conn, repo_id, old_gen_id)

    call_count = {"n": 0}
    old_gen_row_count_during_preparing = {"n": None}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # A real rollover tick (indexer._handle_cursor_log_replaced)
            # only opens the new generation -- it does not itself ingest
            # pages, so pages_ingested=0 and status is NOT "ok" here.
            new_gen_id = conn.execute(
                "INSERT INTO identity_generations (repository_id, generation_number, "
                "content_lineage, file_generation_device, file_generation_file_index, "
                "file_generation_available, opened_at) VALUES (?, 2, 'lineage2', 1, 1, 1, "
                "'2026-08-23T00:00:00Z')",
                (repo_id_arg,),
            ).lastrowid
            mark_preparing(conn, repo_id_arg, new_gen_id)
            conn.execute(
                "UPDATE checkpoints SET identity_generation_id = ? WHERE repository_id = ?",
                (new_gen_id, repo_id_arg),
            )
            return indexer.TickOutcome(status="cursor_replaced_rolled", pages_ingested=0)
        if call_count["n"] == 2:
            # Captured right as the second tick starts -- i.e. immediately
            # after the first (rollover) tick's own rebuild-eligibility
            # check already ran and found nothing to rebuild yet (PREPARING
            # with 0 pages doesn't count as caught up). The old generation's
            # rows must still be intact at this point.
            old_gen_row_count_during_preparing["n"] = conn.execute(
                "SELECT COUNT(*) FROM issue_views WHERE repository_id=? AND identity_generation_id=?",
                (repo_id_arg, old_gen_id),
            ).fetchone()[0]
        # A subsequent, ordinary tick actually catches the new generation up.
        gen_id = conn.execute(
            "SELECT identity_generation_id FROM checkpoints WHERE repository_id = ?", (repo_id_arg,)
        ).fetchone()[0]
        _insert_evidence(conn, repo_id_arg, gen_id, 1)
        return indexer.TickOutcome(status="ok", pages_ingested=1)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    met = asyncio.run(_run_scheduler_until(
        conn, lambda: (read_model_status(conn, repo_id) or {}).get("status") == "READY"
        and read_model_status(conn, repo_id)["identityGenerationId"] != old_gen_id))
    assert met
    final = read_model_status(conn, repo_id)
    assert final["status"] == "READY"
    assert final["identityGenerationId"] != old_gen_id
    # Preserved while PREPARING...
    assert old_gen_row_count_during_preparing["n"] == 1
    # ...and pruned only now, after the new generation's own successful
    # publish (docs/27 SS8.4; this session's merge-blocker fix).
    remaining_old = conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=? AND identity_generation_id=?",
        (repo_id, old_gen_id),
    ).fetchone()[0]
    assert remaining_old == 0


def test_cancellation_mid_rollover_preserves_the_old_generations_snapshot(tmp_path, monkeypatch):
    """Cancellation: stopping the scheduler while the new generation is
    still only PREPARING (its rebuild never got the chance to even be
    dispatched) must leave the old generation's complete snapshot
    entirely intact -- nothing here ever touches the old rows until a
    NEW generation's rebuild actually commits."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    old_gen_id = _seed_generation_and_checkpoint(conn, repo_id)
    _insert_evidence(conn, repo_id, old_gen_id, 1)
    _seed_ready_baseline_then_release_lease(conn, repo_id, old_gen_id)

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        new_gen_id = conn.execute(
            "INSERT INTO identity_generations (repository_id, generation_number, "
            "content_lineage, file_generation_device, file_generation_file_index, "
            "file_generation_available, opened_at) VALUES (?, 2, 'lineage2', 1, 1, 1, "
            "'2026-08-23T00:00:00Z')",
            (repo_id_arg,),
        ).lastrowid
        mark_preparing(conn, repo_id_arg, new_gen_id)
        conn.execute(
            "UPDATE checkpoints SET identity_generation_id = ? WHERE repository_id = ?",
            (new_gen_id, repo_id_arg),
        )
        # No evidence inserted -- pages_ingested=0, so _maybe_rebuild's own
        # "caught_up" check is false and it never even attempts a rebuild
        # this tick, matching a real rollover tick's own shape exactly.
        return indexer.TickOutcome(status="cursor_replaced_rolled", pages_ingested=0)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.03)
        await s.stop()  # cancels the repo task mid-flight

    asyncio.run(run())

    status = read_model_status(conn, repo_id)
    assert status["status"] == "PREPARING"  # the new generation never reached READY
    remaining_old = conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=? AND identity_generation_id=?",
        (repo_id, old_gen_id),
    ).fetchone()[0]
    assert remaining_old == 1  # untouched


def test_preparing_status_visible_immediately_before_any_rebuild_completes(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
        mark_preparing(conn, repo_id_arg, gen_id)
        # Report NOT caught up (a full page budget) so the scheduler must
        # NOT rebuild yet -- status must still read PREPARING right after
        # this first tick, honestly reflecting "no complete snapshot yet."
        from draindeck_dashboard.poller import MAX_PAGES_PER_TICK
        return indexer.TickOutcome(status="ok", pages_ingested=MAX_PAGES_PER_TICK)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.5)  # slow enough to observe mid-state
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.1)
        status = (read_model_status(conn, repo_id) or {}).get("status")
        await s.stop()
        return status

    assert asyncio.run(run()) == "PREPARING"


def test_rebuilding_status_serves_the_last_complete_snapshot_labelled_stale(tmp_path, monkeypatch):
    """docs/27 SS3.2 decision 9: while REBUILDING, the prior READY
    snapshot's identity/evidence marker must remain queryable (not wiped)
    so a caller can serve it labelled stale rather than blocking."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    gen_id = _seed_generation_and_checkpoint(conn, repo_id)
    _insert_evidence(conn, repo_id, gen_id, 1)
    _seed_ready_baseline_then_release_lease(conn, repo_id, gen_id)
    ready_status = read_model_status(conn, repo_id)

    mark_rebuilding(conn, repo_id)
    rebuilding_status = read_model_status(conn, repo_id)
    assert rebuilding_status["status"] == "REBUILDING"
    assert rebuilding_status["completedEvidenceId"] == ready_status["completedEvidenceId"]
    assert rebuilding_status["identityGenerationId"] == ready_status["identityGenerationId"]


def test_rebuild_failure_marks_failed_and_is_retried_on_a_later_tick(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    call_count = {"n": 0}
    real_rebuild = scheduler_module.rebuild_read_models

    def flaky_rebuild(conn_arg, repo_id_arg, gen_id_arg, owner_token_arg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated rebuild crash")
        return real_rebuild(conn_arg, repo_id_arg, gen_id_arg, owner_token_arg)

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        if call_count["n"] == 0:
            gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
            mark_preparing(conn, repo_id_arg, gen_id)
            _insert_evidence(conn, repo_id_arg, gen_id, 1)
        return indexer.TickOutcome(status="ok", pages_ingested=1)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "rebuild_read_models", flaky_rebuild)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    met = asyncio.run(_run_scheduler_until(
        conn, lambda: (read_model_status(conn, repo_id) or {}).get("status") == "READY"))
    assert met
    assert read_model_status(conn, repo_id)["status"] == "READY"
    assert call_count["n"] >= 2  # the first (failed) attempt, plus at least one retry


def test_lease_loss_rejects_publication_instead_of_permitting_it(tmp_path, monkeypatch):
    """Merge-blocker regression (replaces a prior test that only asserted
    generic internal consistency -- weak enough to still pass even if
    lease loss silently permitted publication, which it did before this
    session's fix). This test asserts the actual required property: once
    the lease is no longer held by the candidate rebuild's owner_token,
    NOTHING is published -- no READY status, no view rows -- regardless
    of how much candidate work had already been computed.

    Simulated deterministically (single-threaded, no real second process
    needed): `rebuild_read_models`'s own pre-publication ownership
    re-check is exercised for real, against a lease row that a fake
    `ingest_repository_tick` mutates to a DIFFERENT owner partway through
    the scheduler's normal tick/rebuild cycle -- by the time the
    scheduler's dispatched rebuild reaches its pre-publication check, the
    lease it re-reads genuinely no longer matches its own owner_token."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    call_count = {"n": 0}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        call_count["n"] += 1
        if call_count["n"] > 1:
            # Once the lease is gone, _lease_loop's own next heartbeat
            # check stops this process's repo tasks -- but if a second
            # tick manages to slip in first, it must stay a harmless no-op
            # rather than re-seeding a duplicate generation/checkpoint.
            return indexer.TickOutcome(status="ok", pages_ingested=0)
        gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
        mark_preparing(conn, repo_id_arg, gen_id)
        _insert_evidence(conn, repo_id_arg, gen_id, 1)
        # Simulates a competing process winning the lease in the window
        # between this tick's own lease renewal and the rebuild job the
        # scheduler is about to dispatch -- a real cross-process takeover
        # would only succeed once this process's heartbeat goes stale, so
        # backdate it to make the takeover itself legitimate, not just the
        # owner_token swap.
        stale = datetime.now(timezone.utc) - timedelta(seconds=lease.TTL_SECONDS + 1)
        conn.execute(
            "UPDATE indexer_lease SET owner_token = 'competing-process', heartbeat_at = ? "
            "WHERE id = 1", (stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),),
        )
        lease.acquire_or_renew(conn, "competing-process")
        return indexer.TickOutcome(status="ok", pages_ingested=1)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    mark_error_calls = []
    real_mark_error = scheduler_module.mark_error

    def spy_mark_error(conn_arg, repo_id_arg, gen_id_arg, error_code_arg):
        mark_error_calls.append(error_code_arg)
        return real_mark_error(conn_arg, repo_id_arg, gen_id_arg, error_code_arg)

    monkeypatch.setattr(scheduler_module, "mark_error", spy_mark_error)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.05)  # let the tick run, the lease get stolen, and the rebuild attempt
        await s.stop()

    asyncio.run(run())

    # The core property: lease loss must never permit publication.
    status = read_model_status(conn, repo_id)
    assert status is None or status["status"] != "READY"
    row = conn.execute(
        "SELECT 1 FROM issue_views WHERE repository_id = ? AND issue_id = '42'", (repo_id,)
    ).fetchone()
    assert row is None  # the candidate rebuild's view rows were never published

    # And lease loss must never trigger a mark_error() write either --
    # that write would be exactly as illegitimate post-loss as publishing
    # the rebuild itself; the new lease holder owns this repository now.
    assert mark_error_calls == []


def test_rebuild_read_models_rejects_publication_when_lease_changes_before_publish(tmp_path, monkeypatch):
    """Unit-level proof of the mechanism itself (docs/27 SS8.4, this
    session's merge-blocker fix): `rebuild_read_models`'s own
    pre-publication re-check, exercised directly rather than through the
    scheduler, must raise LeaseLostError and publish nothing when the
    lease no longer matches `owner_token` by the time it re-checks --
    even though the pre-check at the very start of the call passed."""
    import draindeck_dashboard.read_models as read_models_module

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    gen_id = _seed_generation_and_checkpoint(conn, repo_id)
    _insert_evidence(conn, repo_id, gen_id, 1)
    lease.acquire_or_renew(conn, "original-owner")

    real_fetch = read_models_module.fetch_ok_evidence_rows

    def fetch_then_steal_lease(conn_arg, repo_id_arg, gen_id_arg):
        rows = real_fetch(conn_arg, repo_id_arg, gen_id_arg)
        # Simulates the lease already having been taken over by another
        # process before this rebuild's BEGIN IMMEDIATE acquired SQLite's
        # exclusive write lock (the only window a real takeover could
        # happen in -- see rebuild_read_models' own docstring).
        conn_arg.execute(
            "UPDATE indexer_lease SET owner_token = 'other-owner' WHERE id = 1"
        )
        return rows

    monkeypatch.setattr(read_models_module, "fetch_ok_evidence_rows", fetch_then_steal_lease)

    try:
        rebuild_read_models(conn, repo_id, gen_id, "original-owner")
        assert False, "expected LeaseLostError"
    except LeaseLostError:
        pass

    status = read_model_status(conn, repo_id)
    assert status is None or status["status"] != "READY"
    row = conn.execute(
        "SELECT 1 FROM issue_views WHERE repository_id = ? AND issue_id = '42'", (repo_id,)
    ).fetchone()
    assert row is None
