"""Persistent tolerant read models (ADR-27 decision 2; docs/27 SS8.4).

Two ways to publish the pure reducer's (`projections.py`) output into the
`issue_views`/`run_views`/`execution_views`/`containment_views` tables:

- ``rebuild_read_models``: the full-generation candidate-rebuild-and-publish
  primitive. Recomputes every entity in one identity generation from its OK
  evidence and atomically replaces that generation's view rows in one
  transaction. Used for first-time backfill and forced full rebuilds
  (read_model_worker.py, Sub-step B) -- always correct, retryable, and
  idempotent, but O(evidence in the generation).

- ``apply_changed_entities``: the ordinary-tick incremental path. Replays
  only the OK evidence belonging to the SPECIFIC issue/execution/run ids
  (and, for containment, the execution ids) named by the caller --
  O(that entity's own evidence), never a full-generation scan -- and
  upserts just those entities' rows. Because each call fully re-derives
  the named entity's view from its own current evidence (not a stateful
  merge into old data), a TORN->OK tail repair, a reordered append, or a
  previously-OK row's content changing are all handled correctly by
  construction: there is no separate "is this safe to apply incrementally"
  branch to get wrong. This is what makes a normal tail repair or fresh
  append never force a full-generation rebuild.

Both paths reuse the exact same per-event dispatch functions in
projections.py (via ``fetch_ok_evidence_rows``/``apply_ok_evidence_rows``),
so there is exactly one implementation of transition semantics -- no risk
of the incremental and full-rebuild paths drifting apart.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterable, Optional

from .projections import (
    ContainmentGenView,
    ExecutionView,
    IssueView,
    ProjectionResult,
    RunView,
    apply_ok_evidence_rows,
    fetch_ok_evidence_rows,
)

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_model_status(conn: sqlite3.Connection, repo_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT identity_generation_id, status, completed_evidence_id, started_at, "
        "completed_at, error_code FROM read_model_state WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "identityGenerationId": row[0],
        "status": row[1],
        "completedEvidenceId": row[2],
        "startedAt": row[3],
        "completedAt": row[4],
        "errorCode": row[5],
    }


def _max_evidence_id(conn: sqlite3.Connection, repo_id: int, identity_generation_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT MAX(id) FROM evidence WHERE repository_id = ? AND identity_generation_id = ?",
        (repo_id, identity_generation_id),
    ).fetchone()
    return row[0]


def _write_issue_view(conn, repo_id, gen_id, view: IssueView) -> None:
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
        "title, inconsistent, last_event_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id, identity_generation_id, issue_id) DO UPDATE SET "
        "state=excluded.state, title=excluded.title, inconsistent=excluded.inconsistent, "
        "last_event_id=excluded.last_event_id, updated_at=excluded.updated_at",
        (repo_id, gen_id, view.issue_id, view.state, view.title, int(view.inconsistent),
         view.last_event_id, _now()),
    )


def _write_execution_view(conn, repo_id, gen_id, view: ExecutionView) -> None:
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, inconsistent, last_event_id, run_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id, identity_generation_id, execution_id) DO UPDATE SET "
        "issue_id=excluded.issue_id, state=excluded.state, inconsistent=excluded.inconsistent, "
        "last_event_id=excluded.last_event_id, run_id=excluded.run_id, updated_at=excluded.updated_at",
        (repo_id, gen_id, view.execution_id, view.issue_id, view.state, int(view.inconsistent),
         view.last_event_id, view.run_id, _now()),
    )


def _write_run_view(conn, repo_id, gen_id, view: RunView) -> None:
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, engine_provider, "
        "engine_model, reviewer_provider, reviewer_model, budget_json, config_digest, outcome, "
        "inconsistent, last_event_id, observed_started_at, observed_finished_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id, identity_generation_id, run_id) DO UPDATE SET "
        "engine_provider=excluded.engine_provider, engine_model=excluded.engine_model, "
        "reviewer_provider=excluded.reviewer_provider, reviewer_model=excluded.reviewer_model, "
        "budget_json=excluded.budget_json, config_digest=excluded.config_digest, "
        "outcome=excluded.outcome, inconsistent=excluded.inconsistent, "
        "last_event_id=excluded.last_event_id, observed_started_at=excluded.observed_started_at, "
        "observed_finished_at=excluded.observed_finished_at, updated_at=excluded.updated_at",
        (repo_id, gen_id, view.run_id, view.engine_provider, view.engine_model,
         view.reviewer_provider, view.reviewer_model,
         json.dumps(view.budget) if view.budget else None, view.config_digest, view.outcome,
         int(view.inconsistent), view.last_event_id, view.observed_started_at,
         view.observed_finished_at, _now()),
    )


def _write_containment_view(conn, repo_id, gen_id, view: ContainmentGenView) -> None:
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, workspace_key, state, inconsistent, last_event_id, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id, identity_generation_id, execution_id, containment_generation) "
        "DO UPDATE SET workspace_key=excluded.workspace_key, state=excluded.state, "
        "inconsistent=excluded.inconsistent, last_event_id=excluded.last_event_id, "
        "updated_at=excluded.updated_at",
        (repo_id, gen_id, view.execution_id, view.containment_generation, view.workspace_key,
         view.state, int(view.inconsistent), view.last_event_id, _now()),
    )


def _publish(conn: sqlite3.Connection, repo_id: int, gen_id: int, result: ProjectionResult) -> None:
    for view in result.issues.values():
        _write_issue_view(conn, repo_id, gen_id, view)
    for view in result.executions.values():
        _write_execution_view(conn, repo_id, gen_id, view)
    for view in result.runs.values():
        _write_run_view(conn, repo_id, gen_id, view)
    for view in result.containments.values():
        _write_containment_view(conn, repo_id, gen_id, view)


def rebuild_read_models(conn: sqlite3.Connection, repo_id: int, identity_generation_id: int) -> None:
    """Full-generation candidate rebuild: recompute every entity from its
    OK evidence and atomically replace this generation's view rows in one
    transaction. Idempotent -- safe to call repeatedly/on retry."""
    started_at = _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = fetch_ok_evidence_rows(conn, repo_id, identity_generation_id)
        result = apply_ok_evidence_rows(rows)

        conn.execute(
            "DELETE FROM issue_views WHERE repository_id = ? AND identity_generation_id = ?",
            (repo_id, identity_generation_id),
        )
        conn.execute(
            "DELETE FROM execution_views WHERE repository_id = ? AND identity_generation_id = ?",
            (repo_id, identity_generation_id),
        )
        conn.execute(
            "DELETE FROM run_views WHERE repository_id = ? AND identity_generation_id = ?",
            (repo_id, identity_generation_id),
        )
        conn.execute(
            "DELETE FROM containment_views WHERE repository_id = ? AND identity_generation_id = ?",
            (repo_id, identity_generation_id),
        )
        _publish(conn, repo_id, identity_generation_id, result)

        completed_evidence_id = _max_evidence_id(conn, repo_id, identity_generation_id)
        completed_at = _now()
        conn.execute(
            "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
            "completed_evidence_id, started_at, completed_at, error_code) "
            "VALUES (?, ?, 'READY', ?, ?, ?, NULL) "
            "ON CONFLICT(repository_id) DO UPDATE SET "
            "identity_generation_id=excluded.identity_generation_id, status='READY', "
            "completed_evidence_id=excluded.completed_evidence_id, "
            "started_at=excluded.started_at, completed_at=excluded.completed_at, error_code=NULL",
            (repo_id, identity_generation_id, completed_evidence_id, started_at, completed_at),
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def apply_changed_entities(conn: sqlite3.Connection, repo_id: int, identity_generation_id: int,
                           *, issue_ids: Iterable[str] = (), execution_ids: Iterable[str] = (),
                           run_ids: Iterable[str] = ()) -> None:
    """Entity-scoped incremental recompute, owning its own transaction --
    for standalone callers (tests, the read-model worker's own job unit).
    indexer.py calls ``apply_changed_entities_locked`` instead, since it
    must run inside its own already-open per-page transaction (nested
    BEGIN IMMEDIATE raises in sqlite3)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_changed_entities_locked(
            conn, repo_id, identity_generation_id,
            issue_ids=issue_ids, execution_ids=execution_ids, run_ids=run_ids,
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def apply_changed_entities_locked(conn: sqlite3.Connection, repo_id: int,
                                  identity_generation_id: int, *, issue_ids: Iterable[str] = (),
                                  execution_ids: Iterable[str] = (),
                                  run_ids: Iterable[str] = ()) -> None:
    """Same as ``apply_changed_entities`` but assumes the caller already
    holds a write transaction (BEGIN IMMEDIATE) on ``conn`` -- does not
    commit or roll back itself."""
    for issue_id in set(issue_ids):
        rows = fetch_ok_evidence_rows(conn, repo_id, identity_generation_id, issue_id=issue_id)
        result = apply_ok_evidence_rows(rows)
        view = result.issues.get(issue_id)
        if view is not None:
            _write_issue_view(conn, repo_id, identity_generation_id, view)

    for execution_id in set(execution_ids):
        rows = fetch_ok_evidence_rows(
            conn, repo_id, identity_generation_id, execution_id=execution_id)
        result = apply_ok_evidence_rows(rows)
        view = result.executions.get(execution_id)
        if view is not None:
            _write_execution_view(conn, repo_id, identity_generation_id, view)
        conn.execute(
            "DELETE FROM containment_views WHERE repository_id = ? AND "
            "identity_generation_id = ? AND execution_id = ?",
            (repo_id, identity_generation_id, execution_id),
        )
        for cview in result.containments.values():
            if cview.execution_id == execution_id:
                _write_containment_view(conn, repo_id, identity_generation_id, cview)

    for run_id in set(run_ids):
        rows = fetch_ok_evidence_rows(conn, repo_id, identity_generation_id, run_id=run_id)
        result = apply_ok_evidence_rows(rows)
        view = result.runs.get(run_id)
        if view is not None:
            _write_run_view(conn, repo_id, identity_generation_id, view)

    if issue_ids or execution_ids or run_ids:
        completed_evidence_id = _max_evidence_id(conn, repo_id, identity_generation_id)
        conn.execute(
            "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
            "completed_evidence_id, started_at, completed_at, error_code) "
            "VALUES (?, ?, 'READY', ?, ?, ?, NULL) "
            "ON CONFLICT(repository_id) DO UPDATE SET "
            "identity_generation_id=excluded.identity_generation_id, status='READY', "
            "completed_evidence_id=excluded.completed_evidence_id, "
            "completed_at=excluded.completed_at, error_code=NULL",
            (repo_id, identity_generation_id, completed_evidence_id, _now(), _now()),
        )


def prune_old_generation_views(conn: sqlite3.Connection, repo_id: int, keep_generation_id: int) -> None:
    """Generation rollover (docs/27 SS8.4): delete every view/readiness row
    for this repository NOT belonging to the current generation. Source
    evidence/history is never touched."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for table in ("issue_views", "run_views", "execution_views", "containment_views"):
            conn.execute(
                f"DELETE FROM {table} WHERE repository_id = ? AND identity_generation_id != ?",
                (repo_id, keep_generation_id),
            )
        conn.execute(
            "DELETE FROM read_model_state WHERE repository_id = ? AND identity_generation_id != ?",
            (repo_id, keep_generation_id),
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
