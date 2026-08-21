"""Repository registration (docs/19 "Registration and polling").

Dashboard never loads a target repo's config.yaml or reproduces
runtime.config.resolve_event_log_path — projectPath and logPath are both
operator-supplied and validated only against the filesystem.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .errors import DashboardApiError, NotFoundError


class RegistrationError(DashboardApiError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonicalize(path_str: str) -> str:
    # normcase folds Windows drive-letter/backslash-case differences;
    # resolve() follows relative segments/symlinks to a final path.
    return os.path.normcase(str(Path(path_str).resolve()))


def validate_project_path(raw: str) -> str:
    path = Path(raw)
    if not path.is_absolute():
        raise RegistrationError(
            "PROJECT_PATH_NOT_ABSOLUTE",
            f"projectPath must be an absolute path, got {raw!r}",
            status_code=400,
        )
    if not path.is_dir():
        raise RegistrationError(
            "PROJECT_PATH_NOT_FOUND",
            f"projectPath does not exist or is not a directory: {raw!r}",
            status_code=400,
        )
    if not (path / ".git").exists():
        raise RegistrationError(
            "PROJECT_PATH_NOT_GIT_WORKTREE",
            f"projectPath is not a Git work-tree: {raw!r}",
            status_code=400,
        )
    return str(path)


def validate_log_path(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise RegistrationError(
            "LOG_PATH_NOT_ABSOLUTE",
            f"logPath must be an absolute path, got {raw!r}",
            status_code=400,
        )
    if path.exists() and not path.is_file():
        raise RegistrationError(
            "LOG_PATH_NOT_REGULAR_FILE",
            f"logPath must name a regular file, got {raw!r}",
            status_code=400,
        )
    return str(path)


def register_repository(conn: sqlite3.Connection, *, project_path: str,
                        log_path: Optional[str]) -> dict:
    validated_project_path = validate_project_path(project_path)
    validated_log_path = validate_log_path(log_path)
    canonical_log_path = (
        _canonicalize(validated_log_path) if validated_log_path else None
    )

    if canonical_log_path is not None:
        existing = conn.execute(
            "SELECT id FROM repositories WHERE canonical_log_path = ?",
            (canonical_log_path,),
        ).fetchone()
        if existing is not None:
            raise RegistrationError(
                "LOG_PATH_ALREADY_REGISTERED",
                f"logPath is already registered under repository {existing[0]}",
                status_code=409,
            )

    now = _now()
    cur = conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES (?, ?, ?, ?)",
        (validated_project_path, validated_log_path, canonical_log_path, now),
    )
    return get_repository(conn, cur.lastrowid)


def _row_to_dict(row: sqlite3.Row | tuple) -> dict:
    return {
        "id": row[0],
        "projectPath": row[1],
        "logPath": row[2],
        "createdAt": row[3],
    }


def list_repositories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, project_path, log_path, created_at FROM repositories ORDER BY id"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_repository(conn: sqlite3.Connection, repo_id: int) -> dict:
    row = conn.execute(
        "SELECT id, project_path, log_path, created_at FROM repositories WHERE id = ?",
        (repo_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"repository {repo_id} not found")
    return _row_to_dict(row)


def delete_repository(conn: sqlite3.Connection, repo_id: int) -> None:
    """Removes only Dashboard-owned rows — never the log, artifacts, or
    repository on disk (docs/19)."""
    get_repository(conn, repo_id)  # raises NotFoundError if missing
    conn.execute("DELETE FROM changes WHERE repository_id = ?", (repo_id,))
    conn.execute("DELETE FROM corruptions WHERE repository_id = ?", (repo_id,))
    conn.execute("DELETE FROM evidence WHERE repository_id = ?", (repo_id,))
    conn.execute("DELETE FROM checkpoints WHERE repository_id = ?", (repo_id,))
    conn.execute("DELETE FROM identity_generations WHERE repository_id = ?", (repo_id,))
    conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
