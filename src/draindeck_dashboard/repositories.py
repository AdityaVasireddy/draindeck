"""Repository registration (docs/19 "Registration and polling").

ADR-30 (docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md)
additionally lets registration own a validated canonical
`.draindeck/config.local.yaml` path: when supplied, it is validated through
the existing `runtime.config.load_config` (never a second Dashboard-side YAML
schema), must live at `runtime.init.service.canonical_config_path` for the
registered project, and its parsed `project.repository` must resolve to the
same registered project. `logPath` remains independently operator-supplied
when no config is given, but is derived via `runtime.config.
resolve_event_log_path` when a config is supplied and no explicit logPath is
given. A registration with no config path remains a valid, observation-only
row (`controlCapability: OBSERVATION_ONLY`) until a valid config is supplied.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from runtime.config import Config, ConfigError, load_config, resolve_event_log_path
from runtime.init.service import canonical_config_path as _runtime_canonical_config_path

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


def validate_config_path(raw: str, *, project_path: str) -> tuple[str, Config]:
    """Validates an absolute canonical config path and returns it together
    with the loaded ``Config`` (so ``register_repository`` never parses the
    file twice). Raises typed ``RegistrationError`` on any failure; never
    partially validates."""
    path = Path(raw)
    if not path.is_absolute():
        raise RegistrationError(
            "CONFIG_PATH_NOT_ABSOLUTE",
            f"configPath must be an absolute path, got {raw!r}",
            status_code=400,
        )
    if not path.exists():
        raise RegistrationError(
            "CONFIG_PATH_NOT_FOUND",
            f"configPath does not exist: {raw!r}",
            status_code=400,
        )
    if not path.is_file():
        raise RegistrationError(
            "CONFIG_PATH_NOT_REGULAR_FILE",
            f"configPath must name a regular file, got {raw!r}",
            status_code=400,
        )

    expected = _runtime_canonical_config_path(Path(project_path))
    if os.path.normcase(str(path.resolve())) != os.path.normcase(str(expected.resolve())):
        raise RegistrationError(
            "CONFIG_PATH_MISMATCH",
            f"configPath must be the repository's canonical {expected}, got {raw!r}",
            status_code=400,
        )

    try:
        cfg = load_config(path)
    except ConfigError as exc:
        raise RegistrationError("CONFIG_INVALID", str(exc), status_code=400) from exc

    cfg_repo = os.path.normcase(str(Path(cfg.project.repository).resolve()))
    registered_repo = os.path.normcase(str(Path(project_path).resolve()))
    if cfg_repo != registered_repo:
        raise RegistrationError(
            "CONFIG_REPOSITORY_MISMATCH",
            f"config's project.repository ({cfg.project.repository!r}) does not "
            f"resolve to the registered repository ({project_path!r})",
            status_code=400,
        )

    return str(path), cfg


def register_repository(conn: sqlite3.Connection, *, project_path: str,
                        log_path: Optional[str] = None,
                        config_path: Optional[str] = None) -> dict:
    validated_project_path = validate_project_path(project_path)

    validated_config_path: Optional[str] = None
    canonical_config_path: Optional[str] = None
    loaded_cfg: Optional[Config] = None
    if config_path is not None:
        validated_config_path, loaded_cfg = validate_config_path(
            config_path, project_path=validated_project_path,
        )
        canonical_config_path = _canonicalize(validated_config_path)

    validated_log_path = validate_log_path(log_path)
    if validated_log_path is None and loaded_cfg is not None:
        validated_log_path = str(resolve_event_log_path(loaded_cfg))
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
    if canonical_config_path is not None:
        existing = conn.execute(
            "SELECT id FROM repositories WHERE canonical_config_path = ?",
            (canonical_config_path,),
        ).fetchone()
        if existing is not None:
            raise RegistrationError(
                "CONFIG_PATH_ALREADY_REGISTERED",
                f"configPath is already registered under repository {existing[0]}",
                status_code=409,
            )

    now = _now()
    cur = conn.execute(
        "INSERT INTO repositories "
        "(project_path, log_path, canonical_log_path, config_path, canonical_config_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (validated_project_path, validated_log_path, canonical_log_path,
         validated_config_path, canonical_config_path, now),
    )
    return get_repository(conn, cur.lastrowid)


def _row_to_dict(row: sqlite3.Row | tuple) -> dict:
    config_path = row[4]
    return {
        "id": row[0],
        "projectPath": row[1],
        "logPath": row[2],
        "createdAt": row[3],
        "configPath": config_path,
        "controlCapability": "LAUNCH_CAPABLE" if config_path else "OBSERVATION_ONLY",
    }


_SELECT_COLUMNS = "id, project_path, log_path, created_at, config_path"


def list_repositories(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM repositories ORDER BY id"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_repository(conn: sqlite3.Connection, repo_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_SELECT_COLUMNS} FROM repositories WHERE id = ?",
        (repo_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"repository {repo_id} not found")
    return _row_to_dict(row)


def delete_repository(conn: sqlite3.Connection, repo_id: int) -> None:
    """Removes only Dashboard-owned rows — never the log, artifacts, or
    repository on disk (docs/19). Transactionally removes every v2
    read-model/attention row (docs/27 SS8.2) before the v1 cleanup."""
    get_repository(conn, repo_id)  # raises NotFoundError if missing
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM attention_conditions WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM containment_views WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM execution_views WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM run_views WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM issue_views WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM read_model_state WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM changes WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM corruptions WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM evidence WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM checkpoints WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM identity_generations WHERE repository_id = ?", (repo_id,))
        conn.execute("DELETE FROM repositories WHERE id = ?", (repo_id,))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
