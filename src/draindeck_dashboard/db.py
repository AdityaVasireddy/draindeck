"""Dashboard-owned SQLite database (ADR-26 decision 2; docs/19 "SQLite,
lease, and identity generations").

WAL journal mode, a 5-second busy timeout, and one indexed monotonic
``change_sequence`` (SQLite's ``INTEGER PRIMARY KEY`` is the table's rowid
alias, which is inherently indexed) are the load-bearing facts this module
establishes. Later phases add repositories/issues/executions/evidence
tables and the lease table on top of this connection helper; this phase
only needs the connection pragmas, the schema-version record, and the
``changes`` table the SSE cursor (Phase 5) will read.

All statements are parameterized (docs/19 "Local web security") — this
module never builds SQL by string interpolation.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5_000


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Open a WAL-mode connection with a 5-second busy timeout. Creates the
    parent directory if needed (the database is Dashboard-owned, not
    expected to pre-exist)."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: FastAPI async route handlers run synchronous
    # sqlite3 calls directly on the ASGI server's single event-loop thread,
    # which is not necessarily the thread that called connect() (uvicorn
    # itself runs both on the same thread, but Starlette's TestClient runs
    # the app on a separate portal thread) -- access is always serialized
    # onto one thread at a time, never genuinely concurrent, so disabling
    # sqlite3's same-thread check is safe here, not a race.
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Idempotent schema setup. Safe to call on every process start."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "  version INTEGER NOT NULL"
        ")"
    )
    row = conn.execute("SELECT version FROM schema_meta").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,)
        )

    # change_sequence is the one monotonic SSE cursor (docs/19 "REST API,
    # SSE, and UI states"). INTEGER PRIMARY KEY is the SQLite rowid alias
    # and is therefore indexed by construction — no separate CREATE INDEX
    # is needed for lookups/ordering by change_sequence itself.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS changes ("
        "  change_sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  repository_id   INTEGER NOT NULL,"
        "  entity_type     TEXT NOT NULL,"
        "  entity_id       TEXT NOT NULL,"
        "  created_at      TEXT NOT NULL"
        ")"
    )

    # Registration (docs/19 "Registration and polling"). canonical_log_path
    # is NULL when logPath was omitted at registration (valid — becomes
    # NOT_INITIALIZED); the partial unique index below enforces uniqueness
    # only among registrations that DO have a logPath, matching "canonical
    # logPath is unique across registrations; one projectPath may have
    # distinct logs" — projectPath itself is deliberately not constrained.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS repositories ("
        "  id                 INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  project_path       TEXT NOT NULL,"
        "  log_path           TEXT,"
        "  canonical_log_path TEXT,"
        "  created_at         TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_repositories_canonical_log_path "
        "ON repositories(canonical_log_path) WHERE canonical_log_path IS NOT NULL"
    )

    # Single indexer-writer lease (ADR-26 decision 2). One singleton row
    # (id=1, enforced by CHECK) — see lease.py for the acquire/renew/
    # takeover protocol built on top of this table.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS indexer_lease ("
        "  id           INTEGER PRIMARY KEY CHECK (id = 1),"
        "  owner_token  TEXT NOT NULL,"
        "  acquired_at  TEXT NOT NULL,"
        "  heartbeat_at TEXT NOT NULL"
        ")"
    )


def connect_and_init(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    return conn
