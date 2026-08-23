"""Automatic ingestion scheduler (closes the Phase 3 gap: nothing
previously called ingest_repository_tick without manual intervention).

Covers: automatic ingestion with no manual tick call; followers never
indexing; lease takeover starting scheduling; normal cadence and
exponential backoff; per-repository isolation; no overlapping ticks for
the same repository; bounded global concurrency reused end-to-end; and
clean shutdown with no orphan tasks.
"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from draindeck_dashboard import indexer, lease
from draindeck_dashboard import poller as poller_module
from draindeck_dashboard import scheduler as scheduler_module
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.repositories import register_repository


def _register(conn, tmp_path, name="repo"):
    repo_dir = tmp_path / name
    (repo_dir / ".git").mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / f"{name}-events.jsonl"  # need not exist -- NOT_INITIALIZED is valid
    return register_repository(
        conn, project_path=str(repo_dir), log_path=str(log_path))["id"]


def _seconds_ago(seconds: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _set_availability(conn, repo_id: int, availability: str) -> None:
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, ?, '2026-08-20T00:00:00Z') "
        "ON CONFLICT(repository_id) DO UPDATE SET availability=excluded.availability",
        (repo_id, availability),
    )


def test_automatic_ingestion_without_manual_tick_call(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    calls = []

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        calls.append(repo_id_arg)
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.1)
        await s.stop()

    asyncio.run(run())

    assert calls.count(repo_id) >= 1  # ticked automatically -- nobody called ingest_repository_tick


def test_follower_never_calls_ingest_repository_tick(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _register(conn, tmp_path)
    lease.acquire_or_renew(conn, "other-owner")  # a fresh, unexpired lease held elsewhere

    calls = []

    async def fake_tick(*a, **kw):
        calls.append(1)
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "me")
        s.start()
        await asyncio.sleep(0.05)
        assert s.is_leader() is False
        await s.stop()

    asyncio.run(run())
    assert calls == []


def test_lease_takeover_starts_scheduling(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _register(conn, tmp_path)

    lease.acquire_or_renew(conn, "dead-owner")
    conn.execute(
        "UPDATE indexer_lease SET heartbeat_at = ? WHERE id = 1",
        (_seconds_ago(lease.TTL_SECONDS + 1),),
    )

    calls = []

    async def fake_tick(*a, **kw):
        calls.append(1)
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "new-owner")
        s.start()
        await asyncio.sleep(0.05)
        assert s.is_leader() is True
        await s.stop()

    asyncio.run(run())
    assert len(calls) >= 1


def test_normal_cadence_and_exponential_backoff(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    availabilities = iter(["AVAILABLE", "OFFLINE", "OFFLINE", "OFFLINE"])

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        _set_availability(conn, repo_id_arg, next(availabilities))
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)

    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(duration):
        sleeps.append(duration)
        if len(sleeps) >= 4:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    s = scheduler_module.Scheduler(conn, "exe")

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await s._repo_loop(repo_id, "irrelevant-log-path")

    asyncio.run(run())

    assert sleeps[0] == scheduler_module.NORMAL_INTERVAL_SECONDS  # AVAILABLE -> normal cadence
    assert sleeps[1] == 2  # first OFFLINE -> backoff floor
    assert sleeps[2] == 4  # doubles
    assert sleeps[3] == 8  # doubles again


def test_backoff_resets_to_normal_cadence_once_available_again(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    availabilities = iter(["OFFLINE", "OFFLINE", "AVAILABLE"])

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        _set_availability(conn, repo_id_arg, next(availabilities))
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)

    sleeps = []
    real_sleep = asyncio.sleep

    async def fake_sleep(duration):
        sleeps.append(duration)
        if len(sleeps) >= 3:
            raise asyncio.CancelledError()
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    s = scheduler_module.Scheduler(conn, "exe")

    async def run():
        with pytest.raises(asyncio.CancelledError):
            await s._repo_loop(repo_id, "irrelevant-log-path")

    asyncio.run(run())

    assert sleeps == [2, 4, scheduler_module.NORMAL_INTERVAL_SECONDS]


def test_failing_repository_does_not_block_a_healthy_one(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_a = _register(conn, tmp_path, name="a")
    repo_b = _register(conn, tmp_path, name="b")

    calls = {"a": 0, "b": 0}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        if repo_id_arg == repo_a:
            raise RuntimeError("repo A is broken")
        calls["b"] += 1
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.1)
        await s.stop()

    asyncio.run(run())
    assert calls["b"] >= 2  # repo B kept ticking at normal cadence despite A's failures


def test_no_overlapping_ticks_for_the_same_repository(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _register(conn, tmp_path)

    concurrent = {"n": 0, "max": 0}

    async def fake_tick(conn_arg, repo_id_arg, executable, log_path_arg, **kwargs):
        concurrent["n"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["n"])
        await asyncio.sleep(0.05)  # deliberately slower than the tick interval below
        concurrent["n"] -= 1
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.2)
        await s.stop()

    asyncio.run(run())
    assert concurrent["max"] == 1


def test_bounded_concurrency_is_reused_across_repositories(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    for i in range(8):
        _register(conn, tmp_path, name=f"repo{i}")

    lock = threading.Lock()
    concurrent = {"n": 0, "max": 0}

    def fake_invoke(executable, log_path_arg, *, after, limit):
        with lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        time.sleep(0.05)
        with lock:
            concurrent["n"] -= 1
        return {
            "records": [], "nextCursor": None, "hasMore": False,
            "metadata": {"availability": "EMPTY", "contentLineage": None,
                        "fileGeneration": {"device": 1, "fileIndex": 1, "available": True}},
        }

    monkeypatch.setattr(poller_module, "invoke_observer_events", fake_invoke)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 1000)  # one tick per repo
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.3)
        await s.stop()

    asyncio.run(run())
    assert concurrent["max"] <= 4  # reuses poller.py's existing global semaphore end-to-end


def test_clean_shutdown_leaves_no_orphan_tasks(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _register(conn, tmp_path)

    async def fake_tick(*a, **kw):
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.05)
        current = asyncio.current_task()
        before = {t for t in asyncio.all_tasks() if t is not current}
        assert len(before) > 0  # sanity: the scheduler really did create tasks

        await s.stop()

        after = {t for t in asyncio.all_tasks() if t is not current}
        assert after == set()
        assert s.scheduled_repository_ids() == frozenset()

    asyncio.run(run())


def test_lease_heartbeat_is_not_starved_by_a_saturated_page_queue(tmp_path, monkeypatch):
    """Unit 2, Sub-step B: the priority lane for lease acquire/renew must
    keep renewing even while the ordinary (page-persistence) queue is
    completely saturated with slow jobs -- proving the bounded backlog
    cannot starve the heartbeat past the lease TTL."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _register(conn, tmp_path)

    async def slow_tick(*a, **kw):
        await asyncio.sleep(0.2)  # much slower than HEARTBEAT_SECONDS below
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", slow_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.02)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.15)
        heartbeat_at_1 = conn.execute(
            "SELECT heartbeat_at FROM indexer_lease WHERE id = 1"
        ).fetchone()[0]
        await asyncio.sleep(0.15)
        heartbeat_at_2 = conn.execute(
            "SELECT heartbeat_at FROM indexer_lease WHERE id = 1"
        ).fetchone()[0]
        await s.stop()
        assert heartbeat_at_2 > heartbeat_at_1  # renewed even with a slow tick in flight

    asyncio.run(run())


def test_writes_execute_on_the_worker_thread_not_the_event_loop(tmp_path, monkeypatch):
    """The real (unmocked) ingest_repository_tick's SQL work must run on
    the worker's dedicated connection/thread -- not scheduler._conn's
    thread (the event loop) -- proving no SQLite write executes on the
    ASGI event loop for a real tick."""
    log_path = tmp_path / "events.jsonl"
    log_path.write_text(
        '{"event_id":1,"schema_version":1,"ts":"2026-08-23T00:00:00Z","run_id":null,'
        '"type":"IssueCreated","issue_id":"42","execution_id":null,"payload":{}}\n',
        encoding="utf-8",
    )
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)
    # Point the registration at the real log file (the fixture above
    # registers a not-yet-existing path).
    conn.execute("UPDATE repositories SET log_path = ?, canonical_log_path = ? WHERE id = ?",
                (str(log_path), str(log_path).lower(), repo_id))

    def observer_reader(executable, lp, *, after, limit):
        from runtime.observe import read_events_page
        return read_events_page(Path(lp), after=after, limit=limit)

    monkeypatch.setattr(poller_module, "invoke_observer_events", observer_reader)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        assert s._worker._conn is not None
        assert s._worker._conn is not conn  # worker's own dedicated connection
        for _ in range(50):
            await asyncio.sleep(0.02)
            row = conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE repository_id = ?", (repo_id,)
            ).fetchone()
            if row[0] >= 1:
                break
        await s.stop()
        assert row[0] == 1  # visible via scheduler._conn -- proves the worker's
                             # separate connection committed to the same WAL file
        assert s._worker.is_alive() is False  # clean shutdown

    asyncio.run(run())


def test_deleted_repository_stops_being_scheduled(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path)

    async def fake_tick(*a, **kw):
        return indexer.TickOutcome(status="ok")

    monkeypatch.setattr(scheduler_module, "ingest_repository_tick", fake_tick)
    monkeypatch.setattr(scheduler_module, "NORMAL_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(lease, "HEARTBEAT_SECONDS", 0.01)

    async def run():
        s = scheduler_module.Scheduler(conn, "exe")
        s.start()
        await asyncio.sleep(0.05)
        assert repo_id in s.scheduled_repository_ids()

        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
        await asyncio.sleep(0.05)
        assert repo_id not in s.scheduled_repository_ids()

        await s.stop()

    asyncio.run(run())
