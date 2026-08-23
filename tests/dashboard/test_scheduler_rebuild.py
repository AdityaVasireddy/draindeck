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

from draindeck_dashboard import indexer, lease
from draindeck_dashboard import scheduler as scheduler_module
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.read_models import mark_preparing, mark_rebuilding, read_model_status
from draindeck_dashboard.repositories import register_repository


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
    from draindeck_dashboard.read_models import rebuild_read_models
    rebuild_read_models(conn, repo_id, gen_id)  # establish a READY baseline
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
    from draindeck_dashboard.read_models import rebuild_read_models
    rebuild_read_models(conn, repo_id, old_gen_id)

    call_count = {"n": 0}

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
    from draindeck_dashboard.read_models import rebuild_read_models
    rebuild_read_models(conn, repo_id, gen_id)
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

    def flaky_rebuild(conn_arg, repo_id_arg, gen_id_arg):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated rebuild crash")
        return real_rebuild(conn_arg, repo_id_arg, gen_id_arg)

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


def test_lease_loss_mid_rebuild_leaves_the_database_in_a_consistent_state(tmp_path, monkeypatch):
    """A rebuild job already dispatched to the worker thread runs to
    completion even if the awaiting task is cancelled by a lease-loss
    stop() (asyncio cancellation cannot interrupt synchronous SQL already
    executing on a separate thread) -- rebuild_read_models' own atomic
    BEGIN IMMEDIATE/COMMIT means this is safe by construction: either the
    full rebuild committed, or it didn't, never a torn intermediate state."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        gen_id = _seed_generation_and_checkpoint(conn, repo_id_arg)
        mark_preparing(conn, repo_id_arg, gen_id)
        _insert_evidence(conn, repo_id_arg, gen_id, 1)
        return indexer.TickOutcome(status="ok", pages_ingested=1)

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.03)  # let the tick + rebuild dispatch, but stop almost immediately
        await s.stop()  # cancels the repo task while a rebuild job may still be in flight

    asyncio.run(run())

    # Whatever state resulted, it must be internally consistent -- never a
    # status of READY with a NULL completed_evidence_id, or vice versa.
    status = read_model_status(conn, repo_id)
    if status is not None and status["status"] == "READY":
        assert status["completedEvidenceId"] is not None
    # And the view tables themselves must never be left half-written --
    # rebuild_read_models' DELETE+re-INSERT is one atomic transaction, so
    # either the issue exists with real state or the whole rebuild never
    # committed at all.
    row = conn.execute(
        "SELECT state FROM issue_views WHERE repository_id = ? AND issue_id = '42'", (repo_id,)
    ).fetchone()
    assert row is None or row[0] is not None
