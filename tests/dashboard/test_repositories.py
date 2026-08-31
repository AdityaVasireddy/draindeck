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


# ── ADR-30 RED 1: registration owns a validated canonical config path ──────

_VALID_CONFIG_YAML = """
project:
  name: T
  repository: {repository!r}
  branch: agent-work
  issues_file: Issues.md
  validation:
    commands: ["echo ok"]
engine:
  provider: claude-headless
  auth_mode: subscription
  model: default
  max_turns: 30
  timeout_seconds: 1800
reviewer:
  provider: qwen
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
budget:
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  hard_stop_proxy_cost_per_run_usd: 15.0
  proxy_pricing: api_list_rates
experiment:
  sample_size: 20
  attempt1_success_min: 0.3
  cost_per_shipped_issue_max_usd: 3.0
billing:
  posture: p
  headless_split_status: paused
  verified_on: '2026-07-10'
  reverify_at: x
event_log:
  path: state/events.jsonl
"""


def _write_canonical_config(repo: "Path", *, repository: Optional[str] = None) -> "Path":
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir(exist_ok=True)
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(
        _VALID_CONFIG_YAML.format(repository=str(repository or repo)), encoding="utf-8",
    )
    return config_path


def test_registration_requires_absolute_config_path(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path="relative/config.local.yaml")
    assert exc_info.value.code == "CONFIG_PATH_NOT_ABSOLUTE"


def test_registration_rejects_missing_config_without_database_row(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    missing = repo / ".draindeck" / "config.local.yaml"
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(missing))
    assert exc_info.value.code == "CONFIG_PATH_NOT_FOUND"
    assert list_repositories(conn) == []


def test_registration_rejects_directory_and_non_regular_config(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    a_directory = repo / ".draindeck" / "config.local.yaml"
    a_directory.mkdir(parents=True)
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(a_directory))
    assert exc_info.value.code == "CONFIG_PATH_NOT_REGULAR_FILE"


def test_registration_rejects_invalid_yaml_with_clear_error(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text("not: valid: yaml: [", encoding="utf-8")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert exc_info.value.code == "CONFIG_INVALID"


def test_registration_rejects_non_mapping_and_schema_invalid_config(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert exc_info.value.code == "CONFIG_INVALID"


def test_registration_uses_runtime_load_config_not_dashboard_yaml_schema(tmp_path):
    """A field the runtime schema forbids (extra="forbid" at the Config
    level) must be rejected identically here -- proving this delegates to
    runtime.config.load_config rather than a separate, possibly-looser
    Dashboard schema."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    text = config_path.read_text(encoding="utf-8")
    config_path.write_text(text + "\nunknown_top_level_field: true\n", encoding="utf-8")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert exc_info.value.code == "CONFIG_INVALID"


def test_registration_rejects_noncanonical_config_location(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    elsewhere = repo / "config.local.yaml"
    elsewhere.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(elsewhere))
    assert exc_info.value.code == "CONFIG_PATH_MISMATCH"


def test_registration_rejects_config_for_different_project_repository(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    other_repo = _git_worktree(tmp_path, "other")
    config_path = _write_canonical_config(repo, repository=other_repo)
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert exc_info.value.code == "CONFIG_REPOSITORY_MISMATCH"
    assert list_repositories(conn) == []


def test_registration_canonicalizes_and_persists_config_path(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    result = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert result["configPath"] == str(config_path)
    assert result["controlCapability"] == "LAUNCH_CAPABLE"
    fetched = get_repository(conn, result["id"])
    assert fetched["configPath"] == str(config_path)


def test_registration_derives_log_path_with_resolve_event_log_path(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    result = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    assert result["logPath"] == str(repo / "state" / "events.jsonl")


def test_registration_remains_atomic_when_config_validation_fails(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    bad_config = repo / ".draindeck" / "config.local.yaml"
    bad_config.parent.mkdir()
    bad_config.write_text("not valid yaml: [", encoding="utf-8")
    with pytest.raises(RegistrationError):
        register_repository(conn, project_path=str(repo), config_path=str(bad_config))
    assert list_repositories(conn) == []


def test_duplicate_canonical_config_or_log_path_is_conflict(tmp_path):
    """Mirrors test_canonical_log_path_is_unique_across_registrations: a
    canonical config path (deterministic per project_path, per
    runtime.init.service.canonical_config_path) can only back one
    registration row. Re-registering the same repository a second time hits
    that uniqueness constraint rather than silently creating a second
    launch-capable row for the same target."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    register_repository(conn, project_path=str(repo), config_path=str(config_path))

    # Give the second attempt a distinct explicit logPath so only the
    # config-path collision is under test (both would otherwise collide,
    # since the derived logPath is also deterministic per repository).
    with pytest.raises(RegistrationError) as exc_info:
        register_repository(
            conn, project_path=str(repo), config_path=str(config_path),
            log_path=str(tmp_path / "a-different-log.jsonl"),
        )
    assert exc_info.value.code == "CONFIG_PATH_ALREADY_REGISTERED"


def test_legacy_registration_without_config_is_observation_only_until_repaired(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    result = register_repository(conn, project_path=str(repo), log_path=None)
    assert result["configPath"] is None
    assert result["controlCapability"] == "OBSERVATION_ONLY"


def test_repository_api_returns_config_path_and_capability_state(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    result = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    fetched = get_repository(conn, result["id"])
    assert fetched["configPath"] == str(config_path)
    assert fetched["controlCapability"] == "LAUNCH_CAPABLE"
    listed = list_repositories(conn)
    assert listed[0]["controlCapability"] == "LAUNCH_CAPABLE"


def test_unregister_deletes_queue_control_rows_but_never_target_files(tmp_path):
    """No Dashboard-owned run-control queue table exists yet (that arrives in
    Unit 7 / RED 6); this test currently proves the pre-existing invariant
    (delete never touches target files/repo) and will be extended in Unit 7
    to also assert queue rows are cleaned up, per
    docs/plans/dashboard-issue-run-control-failing-tests.md RED 1."""
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo = _git_worktree(tmp_path)
    config_path = _write_canonical_config(repo)
    result = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    delete_repository(conn, result["id"])
    with pytest.raises(NotFoundError):
        get_repository(conn, result["id"])
    assert config_path.exists()
    assert repo.exists()
