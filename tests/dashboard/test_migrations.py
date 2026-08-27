"""Unit 1 (docs/27 SS8.1): transactional SQLite v1->v2 migration.

Version is read only after BEGIN IMMEDIATE; migration is idempotent under
restart/concurrent process start; a newer-than-supported version is
rejected; a failure mid-migration rolls back instead of leaving a partial
schema; schema_meta always holds exactly one row; existing v1 data
(evidence, registrations, checkpoints, generations, corruptions, lease) is
preserved untouched.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from draindeck_dashboard import db
from draindeck_dashboard.migrations import (
    SCHEMA_VERSION,
    SchemaVersionError,
    run_migrations,
)


def _v1_only_connect(db_path):
    """Open a connection and create *only* the v1 tables/version row --
    i.e. the exact state a pre-ADR-27 database was left in -- without
    calling run_migrations. Mirrors db.py's pre-Unit-1 init_schema."""
    conn = db.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (1)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS repositories ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  project_path TEXT NOT NULL,"
        "  log_path TEXT,"
        "  canonical_log_path TEXT,"
        "  created_at TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS evidence ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  repository_id INTEGER NOT NULL,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  record_cursor TEXT NOT NULL,"
        "  integrity TEXT NOT NULL,"
        "  event_id INTEGER,"
        "  event_type TEXT,"
        "  issue_id TEXT,"
        "  execution_id TEXT,"
        "  run_id TEXT,"
        "  stored_at TEXT NOT NULL"
        ")"
    )
    return conn


class _ExecuteSpyConnection:
    """Wraps a real sqlite3.Connection and records every SQL statement
    passed to .execute(), optionally raising for a matching statement.
    sqlite3.Connection.execute is a read-only slot in this Python build
    and cannot be monkeypatched directly, so run_migrations is driven
    through this proxy instead (it only ever calls .execute() on the
    connection object it's given)."""

    def __init__(self, real: sqlite3.Connection, *, raise_on_substring: str | None = None):
        self._real = real
        self.calls: list[str] = []
        self._raise_on_substring = raise_on_substring

    def execute(self, sql, *args, **kwargs):
        self.calls.append(sql)
        if self._raise_on_substring and self._raise_on_substring in sql and "CREATE TABLE" in sql.upper():
            raise sqlite3.OperationalError("injected failure")
        return self._real.execute(sql, *args, **kwargs)


def test_fresh_database_lands_directly_at_v2_with_all_new_tables(tmp_path):
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        version = conn.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == SCHEMA_VERSION == 3
        for table in (
            "issue_views", "run_views", "execution_views", "containment_views",
            "read_model_state", "attention_conditions",
        ):
            # must not raise -- table exists
            conn.execute(f"SELECT COUNT(*) FROM {table}")
    finally:
        conn.close()


def test_schema_meta_always_holds_exactly_one_row(tmp_path):
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        count = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_v1_database_migrates_to_v2_and_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    v1 = _v1_only_connect(db_path)
    v1.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES (?, ?, ?, ?)",
        ("C:\\repo", None, None, "2026-08-23T00:00:00Z"),
    )
    v1.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, stored_at) "
        "VALUES (1, 1, 'cursor-1', 'OK', '2026-08-23T00:00:00Z')"
    )
    v1.close()

    conn = db.connect(db_path)
    try:
        run_migrations(conn)
        version = conn.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == SCHEMA_VERSION

        repos = conn.execute("SELECT project_path FROM repositories").fetchall()
        assert repos == [("C:\\repo",)]
        ev = conn.execute("SELECT record_cursor, integrity FROM evidence").fetchall()
        assert ev == [("cursor-1", "OK")]

        for table in (
            "issue_views", "run_views", "execution_views", "containment_views",
            "read_model_state", "attention_conditions",
        ):
            conn.execute(f"SELECT COUNT(*) FROM {table}")
    finally:
        conn.close()


def test_migration_is_idempotent_under_restart(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    conn1 = db.connect_and_init(db_path)
    conn1.close()
    conn2 = db.connect(db_path)
    try:
        run_migrations(conn2)  # must not raise on an already-v2 database
        version = conn2.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == SCHEMA_VERSION
        count = conn2.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
        assert count == 1
    finally:
        conn2.close()


def test_legacy_failed_status_rows_are_corrected_to_error_on_migration(tmp_path):
    """Merge-blocker regression (security review, this session): an
    earlier, undocumented deviation wrote read_model_state.status='FAILED'
    where docs/27 SS8.4's frozen contract requires 'ERROR'. No structural
    DDL change is needed for this table (it already exists), but any
    row already written with the old value must be corrected on the next
    startup -- otherwise api_queries.py's fail-closed readiness gate has
    nothing to protect against a database that already has such a row."""
    db_path = tmp_path / "d.sqlite3"
    conn = db.connect_and_init(db_path)
    conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES ('C:/repo', NULL, NULL, '2026-08-23T00:00:00Z')"
    )
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 1, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')"
    ).lastrowid
    # Simulates a row a pre-rename version of this codebase actually wrote.
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (1, ?, 'FAILED', NULL, '2026-08-23T00:00:00Z', NULL, 'RuntimeError')",
        (gen_id,),
    )

    run_migrations(conn)  # simulates the next process startup, post-rename code

    status = conn.execute(
        "SELECT status FROM read_model_state WHERE repository_id = 1"
    ).fetchone()[0]
    assert status == "ERROR"


def test_newer_than_supported_version_is_rejected(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    conn = db.connect(db_path)
    conn.execute("CREATE TABLE schema_meta (version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION + 1,))
    try:
        with pytest.raises(SchemaVersionError):
            run_migrations(conn)
    finally:
        conn.close()


def test_version_is_read_only_after_begin_immediate(tmp_path):
    """The version SELECT must happen inside the locked transaction, not
    before it -- otherwise a concurrent migrator could race past a stale
    read. Assert by recording call order through the spy proxy."""
    db_path = tmp_path / "d.sqlite3"
    real = _v1_only_connect(db_path)

    spy = _ExecuteSpyConnection(real)
    try:
        run_migrations(spy)
    finally:
        real.close()

    begin_idx = next(i for i, c in enumerate(spy.calls) if c.strip().upper().startswith("BEGIN"))
    version_select_idx = next(
        i for i, c in enumerate(spy.calls)
        if c.strip().upper().startswith("SELECT") and "schema_meta" in c
    )
    assert version_select_idx > begin_idx


def test_rollback_on_injected_failure_leaves_no_partial_schema(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    v1 = _v1_only_connect(db_path)
    v1.close()

    real = db.connect(db_path)
    spy = _ExecuteSpyConnection(real, raise_on_substring="issue_views")
    with pytest.raises(sqlite3.OperationalError):
        run_migrations(spy)
    real.close()

    # A fresh connection must see the pre-migration state: still version
    # 1, no v2 tables -- not a half-applied schema.
    conn2 = db.connect(db_path)
    try:
        version = conn2.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == 1
        with pytest.raises(sqlite3.OperationalError):
            conn2.execute("SELECT COUNT(*) FROM issue_views")
    finally:
        conn2.close()


def test_simultaneous_process_start_serializes_and_both_converge_on_v2(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    v1 = _v1_only_connect(db_path)
    v1.close()

    errors: list[BaseException] = []

    def worker():
        conn = db.connect(db_path)
        try:
            run_migrations(conn)
        except BaseException as e:  # noqa: BLE001 -- capture across threads
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent migration raised: {errors}"
    conn = db.connect(db_path)
    try:
        version = conn.execute("SELECT version FROM schema_meta").fetchone()[0]
        assert version == SCHEMA_VERSION
        count = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
        assert count == 1
    finally:
        conn.close()


def test_required_new_indexes_exist(tmp_path):
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            ).fetchall()
        }
        expected = {
            "ix_evidence_by_issue", "ix_evidence_by_execution", "ix_evidence_by_run",
            "ix_evidence_by_integrity", "ix_evidence_by_event_type",
            "ix_issue_views_repository_state", "ix_issue_views_title",
            "ix_run_views_repository_outcome", "ix_run_views_start",
            "ix_execution_views_repository_state", "ix_execution_views_issue",
            "ix_execution_views_run",
            "ix_containment_views_execution", "ix_containment_views_state",
            "ux_attention_conditions_key_occurrence",
            "ux_attention_conditions_open_key",
            "ix_attention_conditions_current_severity",
            "ix_attention_conditions_repository_status",
            "ix_attention_conditions_subject",
        }
        missing = expected - names
        assert not missing, f"missing indexes: {missing}"
    finally:
        conn.close()
