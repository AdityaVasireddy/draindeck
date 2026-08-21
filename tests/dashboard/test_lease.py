"""Phase 3 acceptance: single indexer-writer lease — opaque owner, atomic
expired-owner takeover, and follower-visible freshness (docs/19 "SQLite,
lease, and identity generations").

Two independent sqlite3 connections opened against the SAME on-disk
database file is the standard way to exercise SQLite's cross-process
write-serialization guarantees without spawning real OS processes — the
locking behavior under test is file-level, not process-count-based, so
this proves the same atomicity two real Dashboard processes would get.
"""
from __future__ import annotations

import time

from draindeck_dashboard.db import connect, connect_and_init
from draindeck_dashboard.lease import TTL_SECONDS, acquire_or_renew, read_state


def test_unclaimed_lease_is_acquired(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    assert acquire_or_renew(conn, "owner-a") is True
    state = read_state(conn)
    assert state.status == "held"
    assert state.owner_token == "owner-a"


def test_holder_renews_its_own_lease(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    acquire_or_renew(conn, "owner-a")
    first = read_state(conn).heartbeat_at
    time.sleep(0.01)
    assert acquire_or_renew(conn, "owner-a") is True
    second = read_state(conn).heartbeat_at
    assert second >= first


def test_second_process_cannot_take_a_fresh_lease(tmp_path):
    db_path = tmp_path / "dash.sqlite3"
    conn_a = connect_and_init(db_path)
    conn_b = connect(db_path)

    assert acquire_or_renew(conn_a, "owner-a") is True
    assert acquire_or_renew(conn_b, "owner-b") is False

    state = read_state(conn_b)
    assert state.status == "held"
    assert state.owner_token == "owner-a"


def test_second_process_takes_over_an_expired_lease(tmp_path, monkeypatch):
    db_path = tmp_path / "dash.sqlite3"
    conn_a = connect_and_init(db_path)
    conn_b = connect(db_path)

    assert acquire_or_renew(conn_a, "owner-a") is True

    # owner-a stops heartbeating; simulate TTL expiry passing by backdating
    # its heartbeat directly rather than sleeping TTL_SECONDS in a test.
    conn_a.execute(
        "UPDATE indexer_lease SET heartbeat_at = ? WHERE id = 1",
        (_seconds_ago(TTL_SECONDS + 1),),
    )

    assert acquire_or_renew(conn_b, "owner-b") is True
    state = read_state(conn_a)
    assert state.owner_token == "owner-b"
    assert state.status == "held"

    # owner-a can no longer renew — it lost the lease to the takeover.
    assert acquire_or_renew(conn_a, "owner-a") is False


def test_follower_sees_missing_lease_as_unclaimed(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    state = read_state(conn)
    assert state.status == "unclaimed"
    assert state.owner_token is None


def test_follower_sees_expired_lease_before_anyone_takes_it_over(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    acquire_or_renew(conn, "owner-a")
    conn.execute(
        "UPDATE indexer_lease SET heartbeat_at = ? WHERE id = 1",
        (_seconds_ago(TTL_SECONDS + 1),),
    )
    state = read_state(conn)
    assert state.status == "expired"
    assert state.owner_token == "owner-a"


def _seconds_ago(seconds: float) -> str:
    from datetime import datetime, timedelta, timezone
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
