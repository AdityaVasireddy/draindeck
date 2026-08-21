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
    conn = sqlite3.connect(str(path), isolation_level=None)
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


def connect_and_init(db_path: Path | str) -> sqlite3.Connection:
    conn = connect(db_path)
    init_schema(conn)
    return conn
