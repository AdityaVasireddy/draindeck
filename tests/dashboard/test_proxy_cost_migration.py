"""Unit 2: SCHEMA_VERSION 2->3 ordered migration chain (spec §4.2/§4.3).

Adds nullable proxy-cost/token columns to execution_views; the whole
fresh/v1/v2/v3 chain applies in order; a real v2 database migrates to v3
preserving all rows and flipping READY read models to REBUILDING so the
existing async rebuild backfills historical cost -- WITHOUT scanning evidence
at startup. Concurrency, rollback, and newer-version refusal are preserved.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from draindeck_dashboard import db
from draindeck_dashboard.migrations import (
    SCHEMA_VERSION,
    _apply_v1_to_v2_ddl,
    run_migrations,
)

_NEW_COLS = {"proxy_micro_usd", "cost_valid", "input_tokens", "output_tokens", "tokens_valid"}


def _execution_views_columns(conn):
    return {row[1] for row in conn.execute("PRAGMA table_info(execution_views)").fetchall()}


def _v2_connect(db_path):
    """Create a genuine v2 database: v1 base tables + the v1->v2 DDL +
    schema_meta=2, but WITHOUT the v3 columns -- the exact on-disk state a
    current-production (pre-this-feature) database is in."""
    conn = db.connect(db_path)
    db.init_schema(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
    _apply_v1_to_v2_ddl(conn)
    conn.execute("INSERT INTO schema_meta (version) VALUES (2)")
    return conn


def _seed_repo_and_gen(conn):
    conn.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, 'C:/repo', NULL, NULL, '2026-08-26T00:00:00Z')"
    )
    return conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 1, 'lineage', 1, 1, 1, '2026-08-26T00:00:00Z')"
    ).lastrowid


def test_schema_version_is_3():
    assert SCHEMA_VERSION == 3


def test_fresh_database_has_new_execution_views_columns(tmp_path):
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 3
        assert _NEW_COLS <= _execution_views_columns(conn)
    finally:
        conn.close()


def test_new_columns_default_and_nullability(tmp_path):
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        info = {row[1]: row for row in conn.execute("PRAGMA table_info(execution_views)")}
        # nullable cost/token value columns
        assert info["proxy_micro_usd"][3] == 0  # notnull flag == 0 (nullable)
        assert info["input_tokens"][3] == 0
        assert info["output_tokens"][3] == 0
        # NOT NULL validity flags default 0
        assert info["cost_valid"][3] == 1
        assert str(info["cost_valid"][4]) == "0"
        assert info["tokens_valid"][3] == 1
        assert str(info["tokens_valid"][4]) == "0"
    finally:
        conn.close()


def test_v2_database_migrates_to_v3_preserving_rows_and_adding_columns(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    v2 = _v2_connect(db_path)
    gen_id = _seed_repo_and_gen(v2)
    v2.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, inconsistent, last_event_id, run_id, updated_at) "
        "VALUES (1, ?, 'e1', '42', 'DONE', 0, 5, 'run-1', '2026-08-26T00:00:00Z')",
        (gen_id,),
    )
    assert _NEW_COLS.isdisjoint(_execution_views_columns(v2))  # not present at v2
    v2.close()

    conn = db.connect(db_path)
    try:
        run_migrations(conn)
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 3
        assert _NEW_COLS <= _execution_views_columns(conn)
        # existing row preserved; new columns are NULL/0
        row = conn.execute(
            "SELECT execution_id, state, run_id, proxy_micro_usd, cost_valid, tokens_valid "
            "FROM execution_views WHERE execution_id = 'e1'"
        ).fetchone()
        assert row == ("e1", "DONE", "run-1", None, 0, 0)
    finally:
        conn.close()


def test_v2_to_v3_flips_ready_read_models_to_rebuilding(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    v2 = _v2_connect(db_path)
    gen_id = _seed_repo_and_gen(v2)
    v2.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (1, ?, 'READY', 5, '2026-08-26T00:00:00Z', '2026-08-26T00:00:01Z', NULL)",
        (gen_id,),
    )
    v2.close()

    conn = db.connect(db_path)
    try:
        run_migrations(conn)
        status = conn.execute(
            "SELECT status FROM read_model_state WHERE repository_id = 1"
        ).fetchone()[0]
        assert status == "REBUILDING"
    finally:
        conn.close()


def test_fresh_start_does_not_leave_spurious_rebuilding(tmp_path):
    # No read_model_state rows on a fresh DB -> the flip is a harmless no-op.
    conn = db.connect_and_init(tmp_path / "d.sqlite3")
    try:
        assert conn.execute("SELECT COUNT(*) FROM read_model_state").fetchone()[0] == 0
    finally:
        conn.close()


def test_reopening_v3_database_does_not_reflip_ready(tmp_path):
    # The READY->REBUILDING flip is one-time (v2->v3 only). A later restart on
    # an already-v3 DB must NOT re-flip a READY row, or every restart would
    # force a perpetual rebuild.
    db_path = tmp_path / "d.sqlite3"
    conn = db.connect_and_init(db_path)
    gen_id = _seed_repo_and_gen(conn)
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (1, ?, 'READY', 5, '2026-08-26T00:00:00Z', '2026-08-26T00:00:01Z', NULL)",
        (gen_id,),
    )
    conn.close()

    conn2 = db.connect(db_path)
    try:
        run_migrations(conn2)  # simulates a restart on an already-v3 DB
        status = conn2.execute(
            "SELECT status FROM read_model_state WHERE repository_id = 1"
        ).fetchone()[0]
        assert status == "READY"
    finally:
        conn2.close()


def test_concurrent_start_converges_on_v3(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    _v2_connect(db_path).close()
    errors: list[BaseException] = []

    def worker():
        c = db.connect(db_path)
        try:
            run_migrations(c)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent migration raised: {errors}"
    conn = db.connect(db_path)
    try:
        assert conn.execute("SELECT version FROM schema_meta").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0] == 1
    finally:
        conn.close()


def test_rollback_on_injected_v2_to_v3_failure_stays_at_v2(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    _v2_connect(db_path).close()

    real = db.connect(db_path)

    class _Spy:
        def __init__(self, r):
            self._r = r

        def execute(self, sql, *a, **k):
            if "ADD COLUMN" in sql.upper():
                raise sqlite3.OperationalError("injected failure")
            return self._r.execute(sql, *a, **k)

    with pytest.raises(sqlite3.OperationalError):
        run_migrations(_Spy(real))
    real.close()

    conn2 = db.connect(db_path)
    try:
        assert conn2.execute("SELECT version FROM schema_meta").fetchone()[0] == 2
        assert _NEW_COLS.isdisjoint(_execution_views_columns(conn2))
    finally:
        conn2.close()
