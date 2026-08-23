"""SQLite schema-version migration (ADR-27 / docs/27 SS8.1).

``init_schema`` (db.py) creates the v1 tables unconditionally and never
touches ``schema_meta``. This module owns ``schema_meta`` exclusively: it
reads the current version only after ``BEGIN IMMEDIATE`` acquires SQLite's
write lock, so a concurrent starter blocks until the winner's migration
transaction commits and then observes the post-migration version inside
its own transaction -- never a stale pre-migration read. A busy timeout
(db.py's 5-second ``PRAGMA busy_timeout``) turns lock contention into a
clean retryable failure rather than a second migration code path.

The v1->v2 DDL is additive only: new Dashboard-owned read-model/attention
tables and new evidence indexes. It never touches existing evidence,
registration, checkpoint, generation, corruption, or lease rows.
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2


class SchemaVersionError(ValueError):
    """Raised when the database's on-disk schema_meta.version is newer
    than this code supports -- never silently downgraded or ignored."""


def _apply_v1_to_v2_ddl(conn: sqlite3.Connection) -> None:
    # issue_views (docs/27 SS8.2)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS issue_views ("
        "  repository_id          INTEGER NOT NULL,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  issue_id               TEXT NOT NULL,"
        "  state                  TEXT NOT NULL,"
        "  title                  TEXT,"
        "  inconsistent           INTEGER NOT NULL DEFAULT 0,"
        "  last_event_id          INTEGER,"
        "  updated_at             TEXT NOT NULL,"
        "  PRIMARY KEY (repository_id, identity_generation_id, issue_id)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_issue_views_repository_state "
        "ON issue_views(repository_id, identity_generation_id, state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_issue_views_title "
        "ON issue_views(repository_id, identity_generation_id, title)"
    )

    # run_views
    conn.execute(
        "CREATE TABLE IF NOT EXISTS run_views ("
        "  repository_id          INTEGER NOT NULL,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  run_id                 TEXT NOT NULL,"
        "  engine_provider        TEXT,"
        "  engine_model            TEXT,"
        "  reviewer_provider       TEXT,"
        "  reviewer_model          TEXT,"
        "  budget_json             TEXT,"
        "  config_digest           TEXT,"
        "  outcome                 TEXT,"
        "  inconsistent            INTEGER NOT NULL DEFAULT 0,"
        "  last_event_id           INTEGER,"
        "  observed_started_at     TEXT,"
        "  observed_finished_at    TEXT,"
        "  updated_at              TEXT NOT NULL,"
        "  PRIMARY KEY (repository_id, identity_generation_id, run_id)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_run_views_repository_outcome "
        "ON run_views(repository_id, identity_generation_id, outcome)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_run_views_start "
        "ON run_views(repository_id, identity_generation_id, observed_started_at)"
    )

    # execution_views
    conn.execute(
        "CREATE TABLE IF NOT EXISTS execution_views ("
        "  repository_id          INTEGER NOT NULL,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  execution_id           TEXT NOT NULL,"
        "  issue_id               TEXT,"
        "  state                  TEXT NOT NULL,"
        "  inconsistent           INTEGER NOT NULL DEFAULT 0,"
        "  last_event_id          INTEGER,"
        "  run_id                 TEXT,"
        "  updated_at             TEXT NOT NULL,"
        "  PRIMARY KEY (repository_id, identity_generation_id, execution_id)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_views_repository_state "
        "ON execution_views(repository_id, identity_generation_id, state)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_views_issue "
        "ON execution_views(repository_id, identity_generation_id, issue_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_execution_views_run "
        "ON execution_views(repository_id, identity_generation_id, run_id)"
    )

    # containment_views -- exact states PREPARED|ESTABLISHED|UNCONFIRMED|RELEASED
    conn.execute(
        "CREATE TABLE IF NOT EXISTS containment_views ("
        "  repository_id          INTEGER NOT NULL,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  execution_id           TEXT NOT NULL,"
        "  containment_generation INTEGER NOT NULL,"
        "  workspace_key           TEXT,"
        "  state                   TEXT NOT NULL,"
        "  inconsistent            INTEGER NOT NULL DEFAULT 0,"
        "  last_event_id           INTEGER,"
        "  updated_at              TEXT NOT NULL,"
        "  PRIMARY KEY (repository_id, identity_generation_id, execution_id, containment_generation)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_containment_views_execution "
        "ON containment_views(repository_id, identity_generation_id, execution_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_containment_views_state "
        "ON containment_views(repository_id, identity_generation_id, state)"
    )

    # read_model_state -- one current row per repository (docs/27 SS8.2)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS read_model_state ("
        "  repository_id          INTEGER PRIMARY KEY,"
        "  identity_generation_id INTEGER NOT NULL,"
        "  status                 TEXT NOT NULL,"
        "  completed_evidence_id  INTEGER,"
        "  started_at             TEXT,"
        "  completed_at           TEXT,"
        "  error_code             TEXT"
        ")"
    )

    # attention_conditions
    conn.execute(
        "CREATE TABLE IF NOT EXISTS attention_conditions ("
        "  id                      INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  condition_key           TEXT NOT NULL,"
        "  occurrence              INTEGER NOT NULL DEFAULT 1,"
        "  repository_id           INTEGER,"
        "  identity_generation_id  INTEGER,"
        "  kind                    TEXT NOT NULL,"
        "  severity                TEXT NOT NULL,"
        "  subject_type            TEXT,"
        "  subject_id              TEXT,"
        "  message                 TEXT NOT NULL,"
        "  target_url              TEXT,"
        "  first_detected_at       TEXT NOT NULL,"
        "  last_detected_at        TEXT NOT NULL,"
        "  resolved_at             TEXT"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_attention_conditions_key_occurrence "
        "ON attention_conditions(condition_key, occurrence)"
    )
    # Only one unresolved (resolved_at IS NULL) row per condition_key --
    # a condition that resolves and recurs opens a new row/occurrence
    # rather than overwriting history (docs/27 SS8.5).
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_attention_conditions_open_key "
        "ON attention_conditions(condition_key) WHERE resolved_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_attention_conditions_current_severity "
        "ON attention_conditions(severity, first_detected_at) WHERE resolved_at IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_attention_conditions_repository_status "
        "ON attention_conditions(repository_id, resolved_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_attention_conditions_subject "
        "ON attention_conditions(subject_type, subject_id)"
    )

    # New evidence indexes (docs/27 SS8.3) -- evidence itself is untouched.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_by_issue "
        "ON evidence(repository_id, identity_generation_id, issue_id, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_by_execution "
        "ON evidence(repository_id, identity_generation_id, execution_id, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_by_run "
        "ON evidence(repository_id, identity_generation_id, run_id, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_by_integrity "
        "ON evidence(repository_id, identity_generation_id, integrity, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_evidence_by_event_type "
        "ON evidence(repository_id, identity_generation_id, event_type, id)"
    )


def run_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent, concurrent-start-safe v1->v2 migration.

    ``BEGIN IMMEDIATE`` acquires SQLite's write lock before anything else
    happens; the version SELECT below therefore always sees either "no
    migration has ever run" or "the last migration that committed" --
    never a value some other process is mid-write on. On lock contention
    SQLite's busy_timeout (db.py) blocks up to 5s and then raises
    ``sqlite3.OperationalError`` (database is locked) -- a clean,
    retryable startup failure, not a second migration path.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_meta").fetchone()
        if row is None:
            _apply_v1_to_v2_ddl(conn)
            conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,))
        else:
            version = row[0]
            if version > SCHEMA_VERSION:
                raise SchemaVersionError(
                    f"database schema version {version} is newer than "
                    f"supported version {SCHEMA_VERSION}"
                )
            if version < SCHEMA_VERSION:
                _apply_v1_to_v2_ddl(conn)
                conn.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
