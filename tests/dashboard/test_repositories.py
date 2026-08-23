"""Phase 3 acceptance: registration validation, canonical-logPath
uniqueness, and safe DELETE (docs/19 "Registration and polling")."""
from __future__ import annotations

import pytest

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import NotFoundError
from draindeck_dashboard.repositories import (
    RegistrationError,
    delete_repository,
    get_repository,
    list_repositories,
    register_repository,
)


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def test_project_path_must_be_absolute(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path="relative/path", log_path=None)
    assert exc_info.value.code == "PROJECT_PATH_NOT_ABSOLUTE"


def test_project_path_must_exist(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(tmp_path / "missing"), log_path=None)
    assert exc_info.value.code == "PROJECT_PATH_NOT_FOUND"


def test_project_path_must_be_a_git_worktree(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    plain_dir = tmp_path / "not_git"
    plain_dir.mkdir()
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(plain_dir), log_path=None)
    assert exc_info.value.code == "PROJECT_PATH_NOT_GIT_WORKTREE"


def test_missing_log_path_is_valid(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    result = register_repository(conn, project_path=str(repo), log_path=None)
    assert result["logPath"] is None


def test_log_path_must_be_absolute(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), log_path="relative/events.jsonl")
    assert exc_info.value.code == "LOG_PATH_NOT_ABSOLUTE"


def test_existing_non_file_log_path_is_rejected(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    a_directory = tmp_path / "not_a_file"
    a_directory.mkdir()
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), log_path=str(a_directory))
    assert exc_info.value.code == "LOG_PATH_NOT_REGULAR_FILE"


def test_nonexistent_log_path_is_valid(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    log = tmp_path / "not_yet_created" / "events.jsonl"
    result = register_repository(conn, project_path=str(repo), log_path=str(log))
    assert result["logPath"] == str(log)


def test_canonical_log_path_is_unique_across_registrations(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_a = _git_worktree(tmp_path, "a")
    repo_b = _git_worktree(tmp_path, "b")
    log = tmp_path / "events.jsonl"
    register_repository(conn, project_path=str(repo_a), log_path=str(log))
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo_b), log_path=str(log))
    assert exc_info.value.code == "LOG_PATH_ALREADY_REGISTERED"


def test_same_project_path_with_different_logs_is_allowed(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    log_a = tmp_path / "a.jsonl"
    log_b = tmp_path / "b.jsonl"
    r1 = register_repository(conn, project_path=str(repo), log_path=str(log_a))
    r2 = register_repository(conn, project_path=str(repo), log_path=str(log_b))
    assert r1["id"] != r2["id"]


def test_multiple_missing_log_path_registrations_are_allowed(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_a = _git_worktree(tmp_path, "a")
    repo_b = _git_worktree(tmp_path, "b")
    r1 = register_repository(conn, project_path=str(repo_a), log_path=None)
    r2 = register_repository(conn, project_path=str(repo_b), log_path=None)
    assert r1["id"] != r2["id"]


def test_get_unknown_repository_raises_not_found(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    with pytest.raises(NotFoundError):
        get_repository(conn, 999)


def test_delete_removes_only_dashboard_rows(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    log = tmp_path / "events.jsonl"
    log.write_text("")  # the log file itself must survive deletion
    created = register_repository(conn, project_path=str(repo), log_path=str(log))
    conn.execute(
        "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
        "VALUES (?, 'issue', '1', '2026-08-20T00:00:00Z')",
        (created["id"],),
    )

    delete_repository(conn, created["id"])

    with pytest.raises(NotFoundError):
        get_repository(conn, created["id"])
    remaining_changes = conn.execute(
        "SELECT COUNT(*) FROM changes WHERE repository_id = ?", (created["id"],)
    ).fetchone()[0]
    assert remaining_changes == 0
    assert log.exists()  # never touches the log on disk
    assert repo.exists()  # never touches the repository on disk


def test_delete_removes_every_v2_read_model_and_attention_row(tmp_path):
    """Unit 1 (docs/27 SS8.2): delete_repository must transactionally
    remove attention_conditions, containment_views, execution_views,
    run_views, issue_views, and read_model_state -- never the target
    path -- alongside the pre-existing v1 cleanup."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    created = register_repository(conn, project_path=str(repo), log_path=None)
    repo_id = created["id"]
    now = "2026-08-23T00:00:00Z"

    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'issue-1', 'PENDING', ?)", (repo_id, now),
    )
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, updated_at) "
        "VALUES (?, 1, 'run-1', ?)", (repo_id, now),
    )
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, updated_at) "
        "VALUES (?, 1, 'exec-1', 'ACCEPTED', ?)", (repo_id, now),
    )
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, state, updated_at) VALUES (?, 1, 'exec-1', 1, 'RELEASED', ?)",
        (repo_id, now),
    )
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO attention_conditions (condition_key, repository_id, kind, severity, "
        "message, first_detected_at, last_detected_at) "
        "VALUES ('k1', ?, 'REPOSITORY_OFFLINE', 'warning', 'm', ?, ?)",
        (repo_id, now, now),
    )

    delete_repository(conn, repo_id)

    for table in (
        "issue_views", "run_views", "execution_views", "containment_views",
        "read_model_state", "attention_conditions",
    ):
        remaining = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE repository_id = ?", (repo_id,)
        ).fetchone()[0]
        assert remaining == 0, f"{table} still has rows for deleted repository {repo_id}"


def test_list_repositories_orders_by_id(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_a = _git_worktree(tmp_path, "a")
    repo_b = _git_worktree(tmp_path, "b")
    register_repository(conn, project_path=str(repo_a), log_path=None)
    register_repository(conn, project_path=str(repo_b), log_path=None)
    rows = list_repositories(conn)
    assert [r["id"] for r in rows] == sorted(r["id"] for r in rows)
    assert len(rows) == 2
