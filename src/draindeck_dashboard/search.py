"""Bounded grouped search (docs/27 SS7.1 ``GET /api/search``).

Matching is a case-insensitive substring over stored identifiers/titles/
paths only -- never raw evidence payload, record bytes, transcript/diff
content, or advanced query syntax. Evidence matching is additionally
limited to Dashboard evidenceId, cursor, integer eventId, and exact/
substring event type -- exactly the metadata columns already exposed
elsewhere, nothing new.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .errors import QueryTooShortError

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 200
DEFAULT_GROUP_LIMIT = 5
MAX_GROUP_LIMIT = 10


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _display_name(project_path: str) -> str:
    return project_path.replace("\\", "/").rsplit("/", 1)[-1]


def _search_repositories(conn: sqlite3.Connection, pattern: str, limit: int) -> list:
    rows = conn.execute(
        "SELECT id, project_path FROM repositories WHERE project_path LIKE ? ESCAPE '\\' "
        "ORDER BY id LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [
        {"type": "repository", "repositoryId": repo_id, "id": str(repo_id),
         "label": _display_name(path), "context": path, "url": f"/repositories/{repo_id}"}
        for repo_id, path in rows
    ]


def _search_issues(conn: sqlite3.Connection, pattern: str, exact_id: Optional[str],
                   limit: int) -> list:
    rows = conn.execute(
        "SELECT iv.repository_id, iv.issue_id, iv.title FROM issue_views iv "
        "JOIN checkpoints c ON c.repository_id = iv.repository_id "
        "  AND c.identity_generation_id = iv.identity_generation_id "
        "WHERE (iv.title LIKE ? ESCAPE '\\' OR iv.issue_id = ?) "
        "ORDER BY iv.repository_id, iv.issue_id LIMIT ?",
        (pattern, exact_id, limit),
    ).fetchall()
    return [
        {"type": "issue", "repositoryId": repo_id, "id": issue_id,
         "label": title or issue_id, "context": None,
         "url": f"/repositories/{repo_id}/issues/{issue_id}"}
        for repo_id, issue_id, title in rows
    ]


def _search_runs(conn: sqlite3.Connection, pattern: str, limit: int) -> list:
    rows = conn.execute(
        "SELECT rv.repository_id, rv.run_id FROM run_views rv "
        "JOIN checkpoints c ON c.repository_id = rv.repository_id "
        "  AND c.identity_generation_id = rv.identity_generation_id "
        "WHERE rv.run_id LIKE ? ESCAPE '\\' ORDER BY rv.repository_id, rv.run_id LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [
        {"type": "run", "repositoryId": repo_id, "id": run_id, "label": run_id, "context": None,
         "url": f"/repositories/{repo_id}/runs/{run_id}"}
        for repo_id, run_id in rows
    ]


def _search_executions(conn: sqlite3.Connection, pattern: str, limit: int) -> list:
    rows = conn.execute(
        "SELECT ev.repository_id, ev.execution_id FROM execution_views ev "
        "JOIN checkpoints c ON c.repository_id = ev.repository_id "
        "  AND c.identity_generation_id = ev.identity_generation_id "
        "WHERE ev.execution_id LIKE ? ESCAPE '\\' ORDER BY ev.repository_id, ev.execution_id LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [
        {"type": "execution", "repositoryId": repo_id, "id": execution_id, "label": execution_id,
         "context": None, "url": f"/repositories/{repo_id}/executions/{execution_id}"}
        for repo_id, execution_id in rows
    ]


def _search_evidence(conn: sqlite3.Connection, q: str, pattern: str, limit: int) -> list:
    numeric = int(q) if q.isdigit() else None
    rows = conn.execute(
        "SELECT e.repository_id, e.id, e.record_cursor, e.event_type FROM evidence e "
        "JOIN checkpoints c ON c.repository_id = e.repository_id "
        "  AND c.identity_generation_id = e.identity_generation_id "
        "WHERE e.id = ? OR e.event_id = ? OR e.record_cursor LIKE ? ESCAPE '\\' "
        "  OR e.event_type LIKE ? ESCAPE '\\' "
        "ORDER BY e.repository_id, e.id LIMIT ?",
        (numeric, numeric, pattern, pattern, limit),
    ).fetchall()
    return [
        {"type": "evidence", "repositoryId": repo_id, "id": str(evidence_id),
         "label": event_type or cursor or str(evidence_id), "context": cursor,
         "url": f"/repositories/{repo_id}/evidence/{evidence_id}"}
        for repo_id, evidence_id, cursor, event_type in rows
    ]


def search(conn: sqlite3.Connection, q: str, *, limit: int = DEFAULT_GROUP_LIMIT) -> dict:
    trimmed = q.strip()
    if len(trimmed) < MIN_QUERY_LENGTH or len(trimmed) > MAX_QUERY_LENGTH:
        raise QueryTooShortError(
            f"query must be {MIN_QUERY_LENGTH}-{MAX_QUERY_LENGTH} characters after trimming"
        )
    limit = max(1, min(limit, MAX_GROUP_LIMIT))
    pattern = f"%{_escape_like(trimmed)}%"
    exact_id = trimmed

    return {
        "repositories": _search_repositories(conn, pattern, limit),
        "issues": _search_issues(conn, pattern, exact_id, limit),
        "runs": _search_runs(conn, pattern, limit),
        "executions": _search_executions(conn, pattern, limit),
        "evidence": _search_evidence(conn, trimmed, pattern, limit),
    }
