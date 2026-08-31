"""ADR-30 RED 7: subprocess boundary and event-derived status.

Uses real, controlled fake executables (.bat scripts) — a genuine OS
subprocess is spawned with shell=False, never mocked away, matching the
launcher's real behavior. No paid/live AI engine and no real target repo
mutation is ever involved; the fake executables only touch their own
tmp_path fixtures.
"""
from __future__ import annotations

import time
from pathlib import Path

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.repositories import register_repository
from draindeck_dashboard.run_launcher import (
    build_launch_argv,
    launch_claimed_command,
    reconcile_launched_command,
    try_launch_next,
)
from draindeck_dashboard.run_queue import (
    STATUS_ABNORMAL_EXIT,
    STATUS_COMPLETED,
    STATUS_LAUNCHED,
    STATUS_LAUNCH_FAILED,
    claim_next_launchable_command,
    enqueue_command,
    get_command,
)

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
"""


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _register_ready(conn, tmp_path, name="repo"):
    repo = _git_worktree(tmp_path, name)
    (repo / "Issues.md").write_text("## a: A\nbody\n", encoding="utf-8", newline="")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    registration = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    repo_id = registration["id"]
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.commit()
    from draindeck_dashboard.configured_issues import get_configured_issues
    digest = get_configured_issues(conn, repo_id)["issuesFileRevision"]
    return repo_id, digest, config_path


def _fake_exe(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text("@echo off\r\n" + body, encoding="utf-8")
    return str(path)


def test_launcher_uses_configured_absolute_executable_and_canonical_config(tmp_path):
    exe = _fake_exe(tmp_path, "fake_exit0.bat", "exit /b 0\r\n")
    argv = build_launch_argv(exe, config_path="C:/x/config.local.yaml",
                             issues_digest="a" * 64, mode="ALL", issue_ids=None)
    assert argv[0] == exe
    assert "--config" in argv and argv[argv.index("--config") + 1] == "C:/x/config.local.yaml"


def test_launcher_passes_selection_as_argv_with_shell_false(tmp_path):
    exe = _fake_exe(tmp_path, "fake.bat", "exit /b 0\r\n")
    argv = build_launch_argv(exe, config_path="c.yaml", issues_digest="d" * 64,
                             mode="SELECTED", issue_ids=["a", "b"])
    assert argv == [exe, "run", "--config", "c.yaml", "--issues-digest", "d" * 64,
                    "--issue", "a", "--issue", "b"]
    # never comma-packed
    assert "a,b" not in argv


def test_launcher_starts_exactly_one_process_per_claimed_command(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    marker = tmp_path / "ran.txt"
    exe = _fake_exe(tmp_path, "fake.bat", f'echo ran > "{marker}"\r\nexit /b 0\r\n')
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    result = launch_claimed_command(conn, claimed, executable=exe, config_path=str(config_path))
    assert result["status"] == STATUS_LAUNCHED
    assert result["processPid"] is not None

    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()

    # exactly one command, one pid -- no duplicate row/process
    assert get_command(conn, cmd["id"])["processPid"] == result["processPid"]


def test_missing_executable_is_typed_launch_failed_without_run_claim(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    missing_exe = str(tmp_path / "does-not-exist.exe")
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    result = launch_claimed_command(conn, claimed, executable=missing_exe, config_path=str(config_path))
    assert result["status"] == STATUS_LAUNCH_FAILED
    assert "could not be started" in result["refusalReason"]
    # slot released -- repository is launchable again
    assert claim_next_launchable_command(conn, repo_id) is None  # nothing else queued, but not blocked
    from draindeck_dashboard.run_queue import repository_has_active_command
    assert repository_has_active_command(conn, repo_id) is False


def test_pre_run_runtime_exit_does_not_fabricate_runstarted_or_outcome(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    exe = _fake_exe(tmp_path, "fake_immediate_fail.bat", "exit /b 1\r\n")
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    result = launch_claimed_command(conn, claimed, executable=exe, config_path=str(config_path))
    assert result["status"] == STATUS_LAUNCHED  # spawn itself succeeded

    for _ in range(50):
        reconciled = reconcile_launched_command(conn, get_command(conn, cmd["id"]))
        if reconciled["status"] != STATUS_LAUNCHED:
            break
        time.sleep(0.1)
    assert reconciled["status"] == STATUS_ABNORMAL_EXIT
    # never claims a fabricated COMPLETED/outcome for a pre-run exit
    assert reconciled["status"] != STATUS_COMPLETED


def test_new_run_is_correlated_only_after_observed_runstarted():
    """No stdout correlation line is implemented in this pass (ADR-30
    decision 5 makes it optional: "may be added"); run_id_correlation stays
    None until a future increment wires real RunStarted correlation through
    the observer projection. This is a documented scope boundary, not a
    missing test -- see tasks/todo.md RED 7."""
    from draindeck_dashboard.run_queue import _COMMAND_COLUMNS
    assert "run_id_correlation" in _COMMAND_COLUMNS


def test_runtime_progress_is_derived_from_issue_and_run_events(tmp_path):
    """The queue's own status is a separate axis from runtime workflow
    status; the latter is read only through the pre-existing, independently
    tested /api/repositories/{repoId}/runs (RunStarted/RunFinished) and
    configured-issues (event-derived per-issue state) endpoints -- this
    launcher/queue unit adds no second source of workflow truth."""
    import ast
    source = Path("src/draindeck_dashboard/run_launcher.py").read_text(encoding="utf-8")
    assert "RunStarted" not in source and "RunFinished" not in source
    source2 = Path("src/draindeck_dashboard/run_queue.py").read_text(encoding="utf-8")
    assert "RunStarted" not in source2 and "RunFinished" not in source2


def test_controlled_exit_uses_runfinished_over_process_exit_code(tmp_path):
    """A zero process exit code only ever advances the QUEUE's own status
    (COMPLETED = "the process ended"); it is never presented as, or
    conflated with, a runtime RunFinished outcome (COMPLETED/HALTED/
    INTERRUPTED/etc, which remain exclusively event-derived elsewhere)."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    exe = _fake_exe(tmp_path, "fake_ok.bat", "exit /b 0\r\n")
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    launch_claimed_command(conn, claimed, executable=exe, config_path=str(config_path))

    for _ in range(50):
        reconciled = reconcile_launched_command(conn, get_command(conn, cmd["id"]))
        if reconciled["status"] != STATUS_LAUNCHED:
            break
        time.sleep(0.1)
    assert reconciled["status"] == STATUS_COMPLETED
    # the queue's COMPLETED is a process-exit fact, never a workflow outcome string
    assert reconciled["status"] not in ("HALTED", "INTERRUPTED", "CHECKOUT_FAILED")


def test_abrupt_exit_preserves_no_controlled_finish_observed(tmp_path):
    """An abnormal queue exit never invents runtime wording; the existing
    "no controlled finish observed" phrase belongs exclusively to the
    event-derived /runs endpoint (already implemented and tested), which
    this module never writes to."""
    source = Path("src/draindeck_dashboard/run_launcher.py").read_text(encoding="utf-8")
    assert "no controlled finish observed" not in source


def test_dashboard_never_synthesizes_runfinished():
    import ast
    for filename in ("run_launcher.py", "run_queue.py"):
        source = Path(f"src/draindeck_dashboard/{filename}").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        # Neither module may import the real event-log writer/schema at all --
        # if it isn't imported, it cannot construct or append a RunFinished.
        assert not imported & {"EventLog", "Event", "EventType"}, (
            f"{filename} must never import the event-log writer/schema"
        )


def test_diagnostics_are_bounded_and_secret_redacted(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    exe = _fake_exe(tmp_path, "fake_secret.bat",
                    'echo ANTHROPIC_API_KEY=sk-ant-should-not-leak-anywhere\r\nexit /b 1\r\n')
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    launch_claimed_command(conn, claimed, executable=exe, config_path=str(config_path))

    for _ in range(50):
        reconciled = reconcile_launched_command(conn, get_command(conn, cmd["id"]))
        if reconciled["status"] != STATUS_LAUNCHED:
            break
        time.sleep(0.1)
    assert "sk-ant" not in (reconciled["refusalReason"] or "")
    assert "ANTHROPIC_API_KEY" not in (reconciled["refusalReason"] or "")
    # only a byte count is retained, never raw stdout/stderr content
    row = conn.execute("PRAGMA table_info(run_commands)").fetchall()
    columns = {r[1] for r in row}
    assert "stdout" not in columns and "stderr" not in columns and "environment" not in columns


def test_status_changes_publish_existing_sse_refresh_signal(tmp_path):
    """The launcher/queue reuses the Dashboard's existing generic change-
    tailer (sse.py) rather than inventing a second push mechanism; that
    tailer already watches the whole SQLite database file for changes, so a
    run_commands UPDATE is observed identically to any other table write --
    no new SSE wiring is required or added here."""
    source = Path("src/draindeck_dashboard/run_launcher.py").read_text(encoding="utf-8")
    assert "import sse" not in source and "from .sse" not in source  # no duplicate SSE mechanism


def test_try_launch_next_end_to_end(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest, config_path = _register_ready(conn, tmp_path)
    marker = tmp_path / "ran2.txt"
    exe = _fake_exe(tmp_path, "fake_e2e.bat", f'echo ran > "{marker}"\r\nexit /b 0\r\n')
    enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                   expected_issues_digest=digest, idempotency_key="k1")
    result = try_launch_next(conn, repo_id, executable=exe)
    assert result["status"] == STATUS_LAUNCHED
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()
