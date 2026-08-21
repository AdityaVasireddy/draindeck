"""Paginated read-model views for issues, executions, and evidence
(docs/19 "REST API, SSE, and UI states": "Lists are paginated.").

All three are scoped to the repository's CURRENT identity generation —
mixing evidence across a CURSOR_LOG_REPLACED rollover would conflate
issue/execution IDs from what is, semantically, a different log.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .projections import build_projection


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
    ordered = sorted(result.issues.values(), key=lambda v: v.issue_id)
    return _paginate([
        {"issueId": v.issue_id, "state": v.state, "title": v.title,
         "inconsistent": v.inconsistent, "lastEventId": v.last_event_id}
        for v in ordered
    ], limit=limit, offset=offset)


def list_executions(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
    generation_id = _current_generation_id(conn, repo_id)
    if generation_id is None:
        return _paginate([], limit=limit, offset=offset)
    result = build_projection(conn, repo_id, generation_id)
    ordered = sorted(result.executions.values(), key=lambda v: v.execution_id)
    return _paginate([
        {"executionId": v.execution_id, "issueId": v.issue_id, "state": v.state,
         "inconsistent": v.inconsistent, "lastEventId": v.last_event_id}
        for v in ordered
    ], limit=limit, offset=offset)


def list_evidence(conn: sqlite3.Connection, repo_id: int, *, limit: int, offset: int) -> dict:
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
