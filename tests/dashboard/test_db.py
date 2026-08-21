"""Phase 2 acceptance: WAL journal mode, 5-second busy timeout, and an
indexed monotonic change_sequence."""
from __future__ import annotations

from draindeck_dashboard.db import connect_and_init


def test_wal_mode_and_five_second_busy_timeout(tmp_path):
    conn = connect_and_init(tmp_path / "dashboard.sqlite3")
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert journal_mode.lower() == "wal"
        assert busy_timeout == 5000
    finally:
        conn.close()


def test_change_sequence_is_the_indexed_primary_key(tmp_path):
    conn = connect_and_init(tmp_path / "dashboard.sqlite3")
    try:
        cols = conn.execute("PRAGMA table_info(changes)").fetchall()
        change_seq_col = next(c for c in cols if c[1] == "change_sequence")
        assert change_seq_col[5] == 1  # pk flag: INTEGER PRIMARY KEY, not a plain column

        conn.execute(
            "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (1, "issue", "42", "2026-08-20T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            (1, "issue", "43", "2026-08-20T00:00:01Z"),
        )
        seqs = [row[0] for row in conn.execute(
            "SELECT change_sequence FROM changes ORDER BY change_sequence")]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == 2
    finally:
        conn.close()


def test_init_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "dashboard.sqlite3"
    conn1 = connect_and_init(db_path)
    conn1.close()
    conn2 = connect_and_init(db_path)  # must not raise on re-init
    try:
        version = conn2.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == 1
        count = conn2.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
        assert count == 1
    finally:
        conn2.close()


def test_db_is_created_at_the_configured_dashboard_owned_path(tmp_path):
    db_path = tmp_path / "nested" / "dashboard.sqlite3"
    conn = connect_and_init(db_path)
    try:
        assert db_path.exists()
    finally:
        conn.close()
