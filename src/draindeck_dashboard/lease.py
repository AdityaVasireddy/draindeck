"""Single indexer-writer lease (ADR-26 decision 2; docs/19 "SQLite, lease,
and identity generations").

Exactly one Dashboard process indexes at a time; every other process
sharing the same database serves API/SSE reads only. The lease has an
opaque owner token, a 2-second heartbeat, a 10-second TTL, and atomic
conditional takeover after expiry: ``acquire_or_renew``'s single
conditional ``UPDATE`` is the whole takeover mechanism. It is race-free
across processes because SQLite serializes writers on one database file —
two connections racing the same conditional UPDATE execute one after the
other, never concurrently, so the second one's WHERE clause re-reads the
first one's already-committed result rather than a stale snapshot.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

HEARTBEAT_SECONDS = 2
TTL_SECONDS = 10

_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime(_TS_FORMAT)


def _parse(s: str) -> datetime:
    return datetime.strptime(s, _TS_FORMAT).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class LeaseState:
    status: str  # "unclaimed" | "held" | "expired"
    owner_token: Optional[str]
    heartbeat_at: Optional[str]
    age_seconds: Optional[float]


def acquire_or_renew(conn: sqlite3.Connection, owner_token: str) -> bool:
    """Returns True iff `owner_token` holds the lease after this call —
    freshly acquired (no prior holder), renewed (already the holder), or
    taken over (the prior holder's heartbeat is older than TTL_SECONDS)."""
    now_s = _fmt(_now())
    row = conn.execute(
        "SELECT owner_token FROM indexer_lease WHERE id = 1"
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO indexer_lease (id, owner_token, acquired_at, heartbeat_at) "
            "VALUES (1, ?, ?, ?)",
            (owner_token, now_s, now_s),
        )
        return True

    if row[0] == owner_token:
        conn.execute(
            "UPDATE indexer_lease SET heartbeat_at = ? WHERE id = 1 AND owner_token = ?",
            (now_s, owner_token),
        )
        return True

    expiry_cutoff = _fmt(_now() - timedelta(seconds=TTL_SECONDS))
    cur = conn.execute(
        "UPDATE indexer_lease SET owner_token = ?, acquired_at = ?, heartbeat_at = ? "
        "WHERE id = 1 AND heartbeat_at < ?",
        (owner_token, now_s, now_s, expiry_cutoff),
    )
    return cur.rowcount == 1


def read_state(conn: sqlite3.Connection) -> LeaseState:
    """For followers: surfaces whether the lease is fresh, missing, or
    expired (docs/19 "Followers show a stale-indexer banner...")."""
    row = conn.execute(
        "SELECT owner_token, heartbeat_at FROM indexer_lease WHERE id = 1"
    ).fetchone()
    if row is None:
        return LeaseState(status="unclaimed", owner_token=None,
                          heartbeat_at=None, age_seconds=None)
    owner_token, heartbeat_at = row
    age = (_now() - _parse(heartbeat_at)).total_seconds()
    status = "expired" if age > TTL_SECONDS else "held"
    return LeaseState(status=status, owner_token=owner_token,
                      heartbeat_at=heartbeat_at, age_seconds=age)
