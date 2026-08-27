"""Paginated read-model views for issues, executions, and evidence
(docs/19 "REST API, SSE, and UI states": "Lists are paginated.").

All three are scoped to the repository's CURRENT identity generation —
mixing evidence across a CURSOR_LOG_REPLACED rollover would conflate
issue/execution IDs from what is, semantically, a different log.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .api_queries import LEGACY_EVIDENCE_OFFSET_CAP, check_offset_cap
from .projections import (
    RUN_METADATA_UNAVAILABLE,
    RUN_NO_CONTROLLED_FINISH_OBSERVED,
    build_projection,
    has_run_metadata,
)
from .proxy_cost import aggregate_execution_costs


def _current_generation_id(conn: sqlite3.Connection, repo_id: int) -> Optional[int]:
    row = conn.execute(
        "SELECT identity_generation_id FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    return row[0] if row is not None else None


def _paginate(items: list, *, limit: int, offset: int) -> dict:
    total = len(items)
    page = items[offset: offset + limit]
    return {"items": page, "limit": limit, "offset": offset, "total": total}


def list_issues(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return _paginate([], limit=limit, offset=offset)
    result = build_projection(conn, repo_id, generation_id)
    execs_by_issue: dict = {}
    for ev in result.executions.values():
        execs_by_issue.setdefault(ev.issue_id, []).append(ev)
    ordered = sorted(result.issues.values(), key=lambda v: v.issue_id)
    return _paginate([
        {"issueId": v.issue_id, "state": v.state, "title": v.title,
         "inconsistent": v.inconsistent, "lastEventId": v.last_event_id,
         "proxyCost": aggregate_execution_costs(execs_by_issue.get(v.issue_id, []))}
        for v in ordered
    ], limit=limit, offset=offset)


def _run_metadata_field(result, run_id: Optional[str]) -> dict:
    """Always a populated object -- never blank/absent (docs/19: "must never
    show a blank metadata panel"). Availability comes from build_projection's
    own RunStarted evidence, never from run_id's string shape."""
    if not has_run_metadata(result, run_id):
        return {"available": False, "message": RUN_METADATA_UNAVAILABLE}
    run = result.runs[run_id]
    return {
        "available": True,
        "runId": run.run_id,
        "engineProvider": run.engine_provider,
        "engineModel": run.engine_model,
        "reviewerProvider": run.reviewer_provider,
        "reviewerModel": run.reviewer_model,
        "budget": run.budget,
        "configDigest": run.config_digest,
        "outcome": run.outcome,
        "inconsistent": run.inconsistent,
    }


def list_executions(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return _paginate([], limit=limit, offset=offset)
    result = build_projection(conn, repo_id, generation_id)
    ordered = sorted(result.executions.values(), key=lambda v: v.execution_id)
    return _paginate([
        {"executionId": v.execution_id, "issueId": v.issue_id, "state": v.state,
         "inconsistent": v.inconsistent, "lastEventId": v.last_event_id,
         "runId": v.run_id, "runMetadata": _run_metadata_field(result, v.run_id),
         "proxyCost": aggregate_execution_costs([v])}
        for v in ordered
    ], limit=limit, offset=offset)


def list_runs(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
    """Every observed RunStarted, independent of whether any execution was
    ever spawned under it -- a RunStarted followed by CHECKOUT_FAILED/
    REVIEWER_UNREACHABLE/BASELINE_FAILED/INGEST_FAILED never reaches issue
    ingestion, so it would otherwise be invisible from the executions view
    alone (review requirement: "A RunStarted must produce a visible run
    even if no ExecutionSpawned ever occurs")."""
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return _paginate([], limit=limit, offset=offset)
    result = build_projection(conn, repo_id, generation_id)
    execs_by_run: dict = {}
    for ev in result.executions.values():
        execs_by_run.setdefault(ev.run_id, []).append(ev)
    ordered = sorted(result.runs.values(), key=lambda v: v.run_id)
    return _paginate([
        {
            "runId": v.run_id,
            "engineProvider": v.engine_provider,
            "engineModel": v.engine_model,
            "reviewerProvider": v.reviewer_provider,
            "reviewerModel": v.reviewer_model,
            "budget": v.budget,
            "configDigest": v.config_digest,
            "outcome": v.outcome,
            # Never "Running" -- ADR-25 gives no liveness signal (docs/19).
            "displayOutcome": v.outcome or RUN_NO_CONTROLLED_FINISH_OBSERVED,
            "inconsistent": v.inconsistent,
            "lastEventId": v.last_event_id,
            "proxyCost": aggregate_execution_costs(execs_by_run.get(v.run_id, [])),
        }
        for v in ordered
    ], limit=limit, offset=offset)


def list_evidence(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
    # docs/27 SS7.4: the one documented pre-GA narrowing of this endpoint's
    # existing range -- its order/shape remain otherwise unchanged.
    check_offset_cap(offset, cap=LEGACY_EVIDENCE_OFFSET_CAP)
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return _paginate([], limit=limit, offset=offset)
    total = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE repository_id = ? AND identity_generation_id = ?",
        (repo_id, generation_id),
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT record_cursor, integrity, event_id, event_type, schema_version, issue_id, "
        "execution_id, event_ts, record_hash, length_bytes FROM evidence WHERE repository_id = ? "
        "AND identity_generation_id = ? ORDER BY id LIMIT ? OFFSET ?",
        (repo_id, generation_id, limit, offset),
    ).fetchall()
    items = [
        {"cursor": r[0], "integrity": r[1], "eventId": r[2], "eventType": r[3],
         "schemaVersion": r[4], "issueId": r[5], "executionId": r[6], "ts": r[7],
         "recordHash": r[8], "lengthBytes": r[9]}
        for r in rows
    ]
    return {"items": items, "limit": limit, "offset": offset, "total": total}


def get_execution_finished_payload(conn: sqlite3.Connection, repo_id: int,
                                    execution_id: str) -> Optional[dict]:
    """The decoded payload of the latest OK `ExecutionFinished` evidence
    row for this execution, scoped to the repository's current identity
    generation -- the source of `transcript_path`/`start_commit`/
    `end_commit` for the Phase 6 artifact/diff endpoints. None if no such
    evidence exists yet, or its payload failed to decode (never raises)."""
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return None
    row = conn.execute(
        "SELECT payload_json FROM evidence WHERE repository_id = ? "
        "AND identity_generation_id = ? AND execution_id = ? "
        "AND event_type = 'ExecutionFinished' AND integrity = 'OK' "
        "ORDER BY event_id DESC LIMIT 1",
        (repo_id, generation_id, execution_id),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        payload = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
