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

SCHEMA_VERSION = 4

# The conceptual version of a fresh database once db.py's ``init_schema`` has
# created the v1 base tables but before any migration step runs. The runner
# treats a fresh DB as sitting at this baseline and applies every step above it.
_BASELINE_VERSION = 1


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
        # runtime.events.projections._containment_key validates this as a
        # string ("g1", ...), never an integer -- see
        # src/runtime/engine/claude_headless.py's `containment_generation: str`.
        "  containment_generation TEXT NOT NULL,"
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


def _apply_v2_to_v3_ddl(conn: sqlite3.Connection) -> None:
    """v2->v3 (spec `spec/coding-engine-proxy-cost.md` §4): add nullable
    proxy-cost/token columns to execution_views, and mark existing complete
    read models for the lease-owned async rebuild so historical cost is
    backfilled honestly -- WITHOUT scanning evidence at startup.

    Additive only: ``ALTER TABLE ... ADD COLUMN`` never rewrites existing
    execution_views rows (the new value columns are NULL, the validity flags
    default 0 = "unknown, never zero"). None/0 is exactly the correct
    pre-backfill state -- cost stays unknown until a genuine rebuild republishes
    it. Every step runs inside ``run_migrations``' single BEGIN IMMEDIATE
    transaction, so a failure here rolls the whole chain back."""
    conn.execute("ALTER TABLE execution_views ADD COLUMN proxy_micro_usd INTEGER")
    conn.execute("ALTER TABLE execution_views ADD COLUMN cost_valid INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE execution_views ADD COLUMN input_tokens INTEGER")
    conn.execute("ALTER TABLE execution_views ADD COLUMN output_tokens INTEGER")
    conn.execute("ALTER TABLE execution_views ADD COLUMN tokens_valid INTEGER NOT NULL DEFAULT 0")

    # Backfill trigger, NOT an evidence scan (spec §4.3): flip every currently
    # complete (READY) read model to REBUILDING. The scheduler's existing
    # _maybe_rebuild treats REBUILDING as urgent and runs a real full-generation
    # rebuild_read_models on its next tick, populating the new columns from OK
    # evidence and returning the model to READY (or ERROR on failure). Read
    # models that were not READY (PREPARING/ERROR/absent) are already scheduled
    # for rebuild by the existing logic, so they need no flip. This lives inside
    # the v2->v3 step (not the every-startup section below) so it fires exactly
    # once, at the moment of migration -- never re-flipping a READY snapshot on
    # a later restart of an already-v3 database.
    conn.execute("UPDATE read_model_state SET status = 'REBUILDING' WHERE status = 'READY'")


def _apply_v3_to_v4_ddl(conn: sqlite3.Connection) -> None:
    """v3->v4 (ADR-30 / spec `spec/dashboard-issue-run-control.md` "Registration
    and configured issue source"): add nullable ``config_path``/
    ``canonical_config_path`` columns to ``repositories`` so registration can
    own a validated canonical `.draindeck/config.local.yaml` path.

    Additive only, mirroring the existing ``log_path``/``canonical_log_path``
    pair: ``ALTER TABLE ... ADD COLUMN`` never rewrites existing rows (both
    new columns are NULL), so a pre-existing registration remains a valid,
    observation-only row -- it does not gain launch capability until an
    operator explicitly supplies a valid config path through the ordinary
    registration/repair path. No existing row's project_path/log_path is
    touched."""
    conn.execute("ALTER TABLE repositories ADD COLUMN config_path TEXT")
    conn.execute("ALTER TABLE repositories ADD COLUMN canonical_config_path TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_repositories_canonical_config_path "
        "ON repositories(canonical_config_path) WHERE canonical_config_path IS NOT NULL"
    )


# Ordered migration chain (spec §4.2). Each step (from_version, to_version,
# apply_fn) is additive and idempotent within its own version gap; the runner
# applies every step whose to_version exceeds the database's current version, in
# order, inside one transaction. ``_apply_v1_to_v2_ddl`` is unchanged from the
# original single-step migration.
_MIGRATIONS = [
    (1, 2, _apply_v1_to_v2_ddl),
    (2, 3, _apply_v2_to_v3_ddl),
    (3, 4, _apply_v3_to_v4_ddl),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Idempotent, concurrent-start-safe ordered v1->v2->v3 migration chain.

    ``BEGIN IMMEDIATE`` acquires SQLite's write lock before anything else
    happens; the version SELECT below therefore always sees either "no
    migration has ever run" or "the last migration that committed" --
    never a value some other process is mid-write on. On lock contention
    SQLite's busy_timeout (db.py) blocks up to 5s and then raises
    ``sqlite3.OperationalError`` (database is locked) -- a clean,
    retryable startup failure, not a second migration path.

    A fresh database (no ``schema_meta`` row) is treated as sitting at
    ``_BASELINE_VERSION`` (its v1 base tables were just created by
    ``db.init_schema``) and the whole chain is applied to reach
    ``SCHEMA_VERSION``. An existing database applies only the steps above its
    recorded version. A newer-than-supported version is refused. The entire
    chain commits (or, on any failure, rolls back) as one transaction.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_meta").fetchone()
        fresh = row is None
        version = _BASELINE_VERSION if fresh else row[0]
        if not fresh and version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"database schema version {version} is newer than "
                f"supported version {SCHEMA_VERSION}"
            )
        for _from_v, to_v, apply_fn in _MIGRATIONS:
            if version < to_v:
                apply_fn(conn)
        if fresh:
            conn.execute("INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,))
        elif version < SCHEMA_VERSION:
            conn.execute("UPDATE schema_meta SET version = ?", (SCHEMA_VERSION,))
        # One-time idempotent data correction (this session's merge-blocker
        # security review), not a schema/DDL change so it doesn't need its
        # own SCHEMA_VERSION bump: an earlier, undocumented deviation wrote
        # the read_model_state status value 'FAILED' where docs/27 SS8.4's
        # frozen contract requires 'ERROR'. Runs every startup -- a no-op
        # once corrected, since the table can no longer contain 'FAILED'
        # rows after the first successful run. Table always exists by this
        # point (created unconditionally by _apply_v1_to_v2_ddl above,
        # whichever branch ran) except on a fresh database whose very
        # first CREATE just happened in this same transaction -- harmless
        # either way since IF NOT EXISTS already guarantees the table.
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='read_model_state'"
        ).fetchone()
        if table_exists:
            conn.execute("UPDATE read_model_state SET status = 'ERROR' WHERE status = 'FAILED'")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
