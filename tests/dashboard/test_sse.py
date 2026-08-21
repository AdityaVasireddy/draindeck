"""Phase 5 acceptance: SSE retention/replay/resync, heartbeat, and one
database tailer fanned out in memory to subscribers (docs/19 "REST API,
SSE, and UI states")."""
from __future__ import annotations

import asyncio

import pytest

from draindeck_dashboard import sse
from draindeck_dashboard.db import connect_and_init


def _insert_change(conn, repo_id=1, entity_type="evidence", entity_id="c"):
    conn.execute(
        "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
        "VALUES (?, ?, ?, '2026-08-20T00:00:00Z')",
        (repo_id, entity_type, entity_id),
    )


# ── needs_resync (pure function) ────────────────────────────────────────

def test_fresh_connect_with_no_cursor_never_needs_resync():
    assert sse.needs_resync(min_retained=1, max_sequence=5000, after=None) is False


def test_cursor_within_retention_and_under_replay_cap_does_not_resync():
    assert sse.needs_resync(min_retained=1, max_sequence=100, after=50) is False


def test_expired_cursor_below_retention_needs_resync():
    assert sse.needs_resync(min_retained=5000, max_sequence=6000, after=10) is True


def test_cursor_requiring_more_than_replay_cap_needs_resync():
    assert sse.needs_resync(min_retained=1, max_sequence=2000, after=0) is True  # 2000 > 1000


def test_cursor_at_exactly_the_replay_cap_boundary_does_not_resync():
    assert sse.needs_resync(min_retained=1, max_sequence=1001, after=1) is False  # exactly 1000


# ── retention pruning ────────────────────────────────────────────────────

def test_prune_keeps_only_the_latest_retention_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(sse, "RETENTION_LIMIT", 3)
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    for i in range(5):
        _insert_change(conn, entity_id=str(i))

    sse.prune_changes(conn)

    remaining = [r[0] for r in conn.execute(
        "SELECT entity_id FROM changes ORDER BY change_sequence")]
    assert remaining == ["2", "3", "4"]


def test_prune_on_empty_table_is_a_no_op(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    sse.prune_changes(conn)  # must not raise
    count = conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    assert count == 0


# ── ChangeTailer: subscribe/replay/fan-out ──────────────────────────────

def test_replay_returns_changes_strictly_after_cursor(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    for i in range(3):
        _insert_change(conn, entity_id=str(i))
    tailer = sse.ChangeTailer(conn)

    records = tailer.replay(after=1)

    assert [r.entity_id for r in records] == ["1", "2"]


def test_poll_once_fans_new_rows_out_to_every_subscriber(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    tailer = sse.ChangeTailer(conn)

    async def run():
        q1 = tailer.subscribe()
        q2 = tailer.subscribe()
        _insert_change(conn, entity_id="new")
        found = tailer.poll_once()
        assert found == 1
        r1 = await q1.get()
        r2 = await q2.get()
        assert r1.entity_id == "new"
        assert r2.entity_id == "new"

    asyncio.run(run())


def test_poll_once_with_no_new_rows_returns_zero(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    _insert_change(conn)
    tailer = sse.ChangeTailer(conn)  # constructed AFTER the row exists
    assert tailer.poll_once() == 0


def test_unsubscribe_stops_fan_out(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    tailer = sse.ChangeTailer(conn)

    q = tailer.subscribe()
    assert tailer.subscriber_count() == 1
    tailer.unsubscribe(q)
    assert tailer.subscriber_count() == 0

    _insert_change(conn)
    tailer.poll_once()
    assert q.empty()  # never received anything after unsubscribing


# ── stream_events: the per-connection generator ─────────────────────────

def test_stream_events_sends_resync_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(sse, "REPLAY_CAP", 2)  # make an over-limit cursor easy to construct
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    for i in range(5):
        _insert_change(conn, entity_id=str(i))
    tailer = sse.ChangeTailer(conn)

    async def run():
        gen = sse.stream_events(tailer, after=0)  # 5 changes to replay > cap of 2
        first = await gen.__anext__()
        assert "CHANGE_RESYNC_REQUIRED" in first
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert tailer.subscriber_count() == 0  # never subscribed on the resync path

    asyncio.run(run())


def test_stream_events_replays_backlog_then_streams_live_updates(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    for i in range(3):
        _insert_change(conn, entity_id=f"backlog-{i}")
    tailer = sse.ChangeTailer(conn)

    async def run():
        gen = sse.stream_events(tailer, after=1)
        first = await gen.__anext__()
        assert first == "retry: 3000\n\n"

        # after=1 leaves change_sequence 2 and 3 to replay, in order.
        replayed_1 = await gen.__anext__()
        assert "id: 2" in replayed_1 and "backlog-1" in replayed_1
        replayed_2 = await gen.__anext__()
        assert "id: 3" in replayed_2 and "backlog-2" in replayed_2

        # The next resumption runs past the replay loop, calls subscribe(),
        # then suspends on queue.get() -- run it as a background task and
        # yield control once so it reaches that suspension point before we
        # push a new change through poll_once().
        next_task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.05)
        assert tailer.subscriber_count() == 1  # now live-subscribed

        _insert_change(conn, entity_id="live")
        tailer.poll_once()
        live = await asyncio.wait_for(next_task, timeout=1)
        assert "live" in live

        await gen.aclose()
        assert tailer.subscriber_count() == 0  # cleaned up on close

    asyncio.run(run())


def test_stream_events_sends_heartbeat_when_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.02)
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    tailer = sse.ChangeTailer(conn)

    async def run():
        gen = sse.stream_events(tailer, after=None)
        first = await gen.__anext__()
        assert first == "retry: 3000\n\n"
        heartbeat = await asyncio.wait_for(gen.__anext__(), timeout=1)
        assert heartbeat == ": heartbeat\n\n"
        await gen.aclose()

    asyncio.run(run())
