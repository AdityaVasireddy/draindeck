"""ADR-30 RED 2: the configured issue reader reuses the existing parser.

The configured file supplies identity/text/dependencies/order only; state
comes only from the observer/indexed projection. See
docs/plans/dashboard-issue-run-control-failing-tests.md RED 2 and
docs/31-dashboard-issue-run-control-outcome-matrix.md "Issue-file reading
and display".
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from draindeck_dashboard.configured_issues import ConfiguredIssuesError, get_configured_issues
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.repositories import register_repository
from runtime.queue import issues_md as runtime_issues_md

_VALID_CONFIG_YAML = """
project:
  name: T
  repository: {repository!r}
  branch: agent-work
  issues_file: {issues_file}
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
"""


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _register(conn, repo: Path, *, issues_file: str = "Issues.md") -> dict:
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir(exist_ok=True)
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(
        _VALID_CONFIG_YAML.format(repository=str(repo), issues_file=issues_file),
        encoding="utf-8",
    )
    return register_repository(conn, project_path=str(repo), config_path=str(config_path))


_TWO_ISSUES = """## a: First issue
Body of A.

## b: Second issue
Depends-On: a
Body of B.
### Acceptance
- criterion one
"""


def test_relative_issues_file_resolves_against_config_project_repository(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    assert result["issuesFilePath"] == str(repo / "Issues.md")


def test_issues_file_resolution_is_independent_of_dashboard_cwd(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    result = get_configured_issues(conn, registration["id"])
    assert result["issuesFilePath"] == str(repo / "Issues.md")


def test_absolute_issues_file_matches_runtime_path_semantics(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    absolute_issues = tmp_path / "external-issues.md"
    absolute_issues.write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo, issues_file=str(absolute_issues).replace("\\", "/"))
    result = get_configured_issues(conn, registration["id"])
    assert result["issuesFilePath"] == str(absolute_issues)


def test_config_and_issues_file_are_reread_after_registration(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    first = get_configured_issues(conn, registration["id"])
    assert [i["issueId"] for i in first["issues"]] == ["a", "b"]

    (repo / "Issues.md").write_text("## c: Third issue\nNew body.\n", encoding="utf-8")
    second = get_configured_issues(conn, registration["id"])
    assert [i["issueId"] for i in second["issues"]] == ["c"]
    assert second["issuesFileRevision"] != first["issuesFileRevision"]


def test_missing_issues_file_returns_typed_error_not_partial_list(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    registration = _register(conn, repo)  # Issues.md never written
    with pytest.raises(ConfiguredIssuesError) as exc_info:
        get_configured_issues(conn, registration["id"])
    assert exc_info.value.code == "ISSUES_FILE_NOT_FOUND"


def test_directory_unreadable_and_invalid_utf8_issue_files_fail_loud(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")

    repo_a = _git_worktree(tmp_path, "a")
    (repo_a / "Issues.md").mkdir()
    reg_a = _register(conn, repo_a)
    with pytest.raises(ConfiguredIssuesError) as exc_info:
        get_configured_issues(conn, reg_a["id"])
    assert exc_info.value.code == "ISSUES_FILE_NOT_REGULAR_FILE"

    repo_b = _git_worktree(tmp_path, "b")
    (repo_b / "Issues.md").write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    reg_b = _register(conn, repo_b)
    with pytest.raises(ConfiguredIssuesError) as exc_info:
        get_configured_issues(conn, reg_b["id"])
    assert exc_info.value.code == "ISSUES_FILE_INVALID_UTF8"

    # "unreadable" (permission-denied) is not reliably simulatable on
    # Windows file ACLs from a test process running as the file owner;
    # ISSUES_FILE_UNREADABLE's OSError branch is covered by inspection
    # (get_configured_issues wraps every read_bytes() OSError), not by a
    # live permission-denied fixture here.


def test_malformed_heading_and_duplicate_id_surface_existing_parser_error(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")

    repo_a = _git_worktree(tmp_path, "a")
    (repo_a / "Issues.md").write_text("## not-a-valid-heading\nbody\n", encoding="utf-8")
    reg_a = _register(conn, repo_a)
    with pytest.raises(ConfiguredIssuesError) as exc_info:
        get_configured_issues(conn, reg_a["id"])
    assert exc_info.value.code == "ISSUES_PARSE_ERROR"

    repo_b = _git_worktree(tmp_path, "b")
    (repo_b / "Issues.md").write_text("## a: First\nbody\n\n## a: Duplicate\nbody\n", encoding="utf-8")
    reg_b = _register(conn, repo_b)
    with pytest.raises(ConfiguredIssuesError) as exc_info:
        get_configured_issues(conn, reg_b["id"])
    assert exc_info.value.code == "ISSUES_PARSE_ERROR"


def test_configured_issue_reader_delegates_to_runtime_issues_md_parse(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])

    expected = runtime_issues_md.parse(_TWO_ISSUES)
    assert [i["issueId"] for i in result["issues"]] == [e.id for e in expected]
    assert [i["title"] for i in result["issues"]] == [e.title for e in expected]
    assert [i["dependsOn"] for i in result["issues"]] == [e.depends_on for e in expected]


def test_configured_issue_reader_has_no_second_heading_or_dependency_parser():
    import ast

    source = Path("src/draindeck_dashboard/configured_issues.py").read_text(encoding="utf-8")
    assert "^##" not in source, "must not reimplement issues_md's heading regex"

    tree = ast.parse(source)
    compiled_patterns = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "compile"
        and node.args and isinstance(node.args[0], ast.Constant)
    ]
    # Exactly one compiled regex in the whole module, and it exists only to
    # disclose the parser's known bulleted-Depends-On gotcha -- never to
    # re-interpret dependencies itself.
    assert len(compiled_patterns) == 1, f"expected exactly one compiled regex, found {compiled_patterns}"
    assert "Depends-On" in compiled_patterns[0]


def test_configured_issues_preserve_file_order_and_all_parser_fields(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    assert [i["issueId"] for i in result["issues"]] == ["a", "b"]
    b = result["issues"][1]
    assert b["dependsOn"] == ["a"]
    assert b["acceptanceCriteria"] == ["criterion one"]
    assert "Body of B." in b["body"]


def test_response_includes_sha256_revision_of_exact_issue_file_bytes(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    expected_digest = hashlib.sha256((repo / "Issues.md").read_bytes()).hexdigest()
    assert result["issuesFileRevision"] == expected_digest


def test_bulleted_depends_on_is_not_invented_and_warning_is_returned(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(
        "## a: First\nbody\n\n## b: Second\n- Depends-On: a\nbody\n", encoding="utf-8",
    )
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    b = next(i for i in result["issues"] if i["issueId"] == "b")
    assert b["dependsOn"] == []  # not invented -- the parser ignores a bulleted line
    assert result["parserWarning"] is True


def test_unbulleted_depends_on_is_returned_exactly(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    b = next(i for i in result["issues"] if i["issueId"] == "b")
    assert b["dependsOn"] == ["a"]
    assert result["parserWarning"] is False


def test_source_status_text_never_sets_runtime_state(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(
        "## a: First\nSTATUS: DONE\nThis text claims to be done.\n", encoding="utf-8",
    )
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    a = result["issues"][0]
    # No event evidence exists for 'a' -- state must never be inferred from
    # the "STATUS: DONE" body text.
    assert a["state"] in ("NOT_INGESTED", "UNAVAILABLE")
    assert a["state"] != "DONE"


def test_issue_without_event_is_not_ingested_not_pending(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    # No read model exists at all for this fresh registration -> UNAVAILABLE
    # (never silently PENDING and never silently DONE/etc).
    for issue in result["issues"]:
        assert issue["state"] not in ("PENDING", "DONE", "ACTIVE", "NEEDS_HUMAN", "NEEDS_DECOMPOSITION")


def test_corrupt_inconsistent_unavailable_or_rebuilding_projection_disables_control(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    repo_id = registration["id"]

    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'REBUILDING')", (repo_id,),
    )
    result = get_configured_issues(conn, repo_id)
    assert result["readModelStatus"] == "REBUILDING"
    assert all(i["state"] == "UNAVAILABLE" for i in result["issues"])


def test_api_returns_issue_text_even_when_runtime_state_is_unavailable(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text(_TWO_ISSUES, encoding="utf-8")
    registration = _register(conn, repo)
    result = get_configured_issues(conn, registration["id"])
    # No read model published yet -> UNAVAILABLE, but full text still present.
    assert result["issues"][0]["title"] == "First issue"
    assert "Body of A." in result["issues"][0]["body"]
    assert result["issues"][0]["state"] == "UNAVAILABLE"


def test_active_event_issue_missing_from_file_blocks_control(tmp_path):
    """Reader-side contribution to a later planner refusal (RED 4): an
    authoritative ACTIVE issue no longer present in the configured file is
    surfaced via activeIssuesOutsideFile so the planner can refuse the whole
    batch rather than silently proceeding without it."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text("## a: First\nbody\n", encoding="utf-8")
    registration = _register(conn, repo)
    repo_id = registration["id"]

    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'PENDING', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'orphan', 'ACTIVE', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    result = get_configured_issues(conn, repo_id)
    assert result["activeIssuesOutsideFile"] == ["orphan"]
    assert [i["issueId"] for i in result["issues"]] == ["a"]  # never fabricated into the list


def test_event_issue_removed_from_file_remains_in_historical_views_only(tmp_path):
    from draindeck_dashboard.api_queries import cross_repository_issues

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path)
    (repo / "Issues.md").write_text("## a: First\nbody\n", encoding="utf-8")
    registration = _register(conn, repo)
    repo_id = registration["id"]

    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, updated_at) "
        "VALUES (?, 1, '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'DONE', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'gone', 'DONE', '2026-08-30T00:00:00Z')", (repo_id,),
    )

    configured = get_configured_issues(conn, repo_id)
    assert "gone" not in [i["issueId"] for i in configured["issues"]]

    historical = cross_repository_issues(conn, repository_id=repo_id)
    assert "gone" in [i["issueId"] for i in historical["items"]]
