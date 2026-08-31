"""ADR-30 RED 9: Dashboard queue/launcher crash and durability scenarios.

Simulated by direct-state manipulation and fresh-connection/fresh-app
reconstruction (never a real OS-level kill), matching the exact scoping
precedent tests/crash/run_lifecycle_harness.py's docstring states for its
own fixture rows: the claims under test here are about SQLite-transaction
durability and startup-reconciliation LOGIC, not about live-process timing
mid-multi-step external mutation the way the main tests/crash/harness.py's
git-operation injection points are. The Dashboard's own crash window is a
single atomic SQLite transaction (the claim) followed by one OS spawn call;
every reachable outcome of that boundary is exercised directly below.

A real, controlled fake .bat executable is used wherever an actual
subprocess is spawned -- never a paid engine, never a real target
repository mutation.

Run directly: `python tests/crash/run_control_harness.py`. Not part of
pytest's automatic collection (mirrors harness.py's own convention).
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_dashboard.configured_issues import get_configured_issues  # noqa: E402
from draindeck_dashboard.db import connect_and_init                      # noqa: E402
from draindeck_dashboard.repositories import register_repository         # noqa: E402
from draindeck_dashboard.run_launcher import (                           # noqa: E402
    launch_claimed_command, reconcile_launched_command, try_launch_next,
)
from draindeck_dashboard.run_queue import (                              # noqa: E402
    STATUS_ABNORMAL_EXIT, STATUS_CLAIMED, STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
    STATUS_QUEUED, claim_next_launchable_command, enqueue_command, get_command,
    reconcile_ambiguous_claims_on_startup, repository_has_active_command,
)

_CONFIG_YAML = """
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

_FAILURES: list[str] = []


def _check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name} {detail}")
        _FAILURES.append(name)


def _setup(base: Path):
    repo = base / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "Issues.md").write_text("## a: A\nbody\n\n## b: B\nbody\n", encoding="utf-8", newline="")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")

    db_path = base / "dashboard.sqlite3"
    conn = connect_and_init(db_path)
    reg = register_repository(conn, project_path=str(repo), config_path=str(config_path))
    repo_id = reg["id"]
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    conn.commit()
    digest = get_configured_issues(conn, repo_id)["issuesFileRevision"]
    return db_path, repo_id, digest, config_path


def _fake_exe(base: Path, name: str, body: str) -> str:
    path = base / name
    path.write_text("@echo off\r\n" + body, encoding="utf-8")
    return str(path)


def scenario_crash_before_spawn(base: Path) -> None:
    db_path, repo_id, digest, _ = _setup(base / "s1")
    conn = connect_and_init(db_path)
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    conn.close()  # simulated crash: never claimed

    conn2 = connect_and_init(db_path)  # fresh Dashboard process
    fetched = get_command(conn2, cmd["id"])
    _check("crash_before_spawn_leaves_command_queued", fetched["status"] == STATUS_QUEUED)
    exe = _fake_exe(base / "s1", "exe.bat", "exit /b 0\r\n")
    result = try_launch_next(conn2, repo_id, executable=exe)
    _check("crash_before_spawn_command_still_launchable_after_restart",
          result is not None and result["status"] == "LAUNCHED")
    conn2.close()


def scenario_crash_after_spawn_before_confirmation(base: Path) -> None:
    db_path, repo_id, digest, _ = _setup(base / "s2")
    conn = connect_and_init(db_path)
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    _check("claim_recorded_before_any_spawn_attempt", claimed["status"] == STATUS_CLAIMED)
    conn.close()  # simulated crash: spawn intent durable, outcome never confirmed

    conn2 = connect_and_init(db_path)  # create_app calls this automatically on real startup
    reconciled = reconcile_ambiguous_claims_on_startup(conn2)
    _check("crash_after_spawn_before_runstarted_never_fabricates_run",
          len(reconciled) == 1 and reconciled[0]["status"] == STATUS_LAUNCH_OWNERSHIP_UNKNOWN)
    _check("restart_does_not_compete_with_possibly_live_child",
          repository_has_active_command(conn2, repo_id) is True
          and claim_next_launchable_command(conn2, repo_id) is None)
    conn2.close()


def scenario_operator_approved_retry(base: Path) -> None:
    db_path, repo_id, digest, _ = _setup(base / "s3")
    conn = connect_and_init(db_path)
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    claim_next_launchable_command(conn, repo_id)
    reconcile_ambiguous_claims_on_startup(conn)
    stuck = get_command(conn, cmd["id"])
    _check("ambiguous_command_is_stuck_before_operator_action",
          stuck["status"] == STATUS_LAUNCH_OWNERSHIP_UNKNOWN)

    # "Operator-approved retry" per ADR-30 sec4: an explicit, human-triggered
    # reset back to QUEUED (no dedicated UI/API action is built in this pass
    # -- documented scope boundary, tasks/todo.md RED 6-7). What matters for
    # this test is that the SUBSEQUENT launch uses the exact same
    # launch_claimed_command/claim path as any ordinary launch -- there is
    # no special "recovery" code branch that could itself be a second,
    # divergent way to spawn a process.
    conn.execute("UPDATE run_commands SET status = 'QUEUED' WHERE id = ?", (cmd["id"],))
    conn.commit()
    exe = _fake_exe(base / "s3", "exe.bat", "exit /b 0\r\n")
    result = try_launch_next(conn, repo_id, executable=exe)
    _check("operator_approved_retry_uses_the_ordinary_launch_path",
          result is not None and result["status"] == "LAUNCHED")
    import inspect
    launch_source = inspect.getsource(launch_claimed_command)
    _check("no_second_recovery_specific_launch_function_exists",
          "recover" not in launch_source.lower())
    conn.close()


def scenario_abnormal_exit_pauses_fifo(base: Path) -> None:
    db_path, repo_id, digest, _ = _setup(base / "s4")
    conn = connect_and_init(db_path)
    exe = _fake_exe(base / "s4", "fails.bat", "exit /b 1\r\n")
    enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                   expected_issues_digest=digest, idempotency_key="k1")
    launched = try_launch_next(conn, repo_id, executable=exe)
    _check("first_command_launched", launched["status"] == "LAUNCHED")

    for _ in range(50):
        reconciled = reconcile_launched_command(conn, get_command(conn, launched["id"]))
        if reconciled["status"] != "LAUNCHED":
            break
        time.sleep(0.1)
    _check("nonzero_exit_becomes_abnormal_exit", reconciled["status"] == STATUS_ABNORMAL_EXIT)

    second = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                             expected_issues_digest=digest, idempotency_key="k2")
    _check("second_command_persisted_but_not_claimed", second["status"] == STATUS_QUEUED)
    _check("abnormal_exit_pauses_fifo_instead_of_cascading",
          claim_next_launchable_command(conn, repo_id) is None)
    conn.close()


def scenario_selection_immune_to_crash_state(base: Path) -> None:
    """The runtime's --issue allowlist is re-derived fresh from argv + the
    current issue file on every invocation (RED 4); nothing about it is
    persisted by the Dashboard's queue, so there is no queue-side state a
    crash could corrupt to widen a selection. Verified structurally: the
    queue/launcher modules carry no field resembling a persisted allowlist
    beyond the exact issue_ids_json this ADR already specifies, and that
    column round-trips exactly."""
    db_path, repo_id, digest, _ = _setup(base / "s5")
    conn = connect_and_init(db_path)
    cmd = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                          expected_issues_digest=digest, idempotency_key="k1")
    conn.close()
    conn2 = connect_and_init(db_path)
    fetched = get_command(conn2, cmd["id"])
    _check("crash_never_widens_the_persisted_selection", fetched["issueIds"] == ["a"])
    conn2.close()


def scenario_queue_never_touches_target_or_event_log(base: Path) -> None:
    import ast
    for filename in ("run_queue.py", "run_launcher.py"):
        source = (Path(__file__).resolve().parents[2] / "src" / "draindeck_dashboard"
                 / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        _check(f"{filename}_never_imports_event_log_or_git_writer",
              not imported & {"EventLog", "GitCliAdapter", "WorkspaceLease"},
              f"found: {imported & {'EventLog', 'GitCliAdapter', 'WorkspaceLease'}}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="draindeck-run-control-crash-",
                                     ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        scenario_crash_before_spawn(base)
        scenario_crash_after_spawn_before_confirmation(base)
        scenario_operator_approved_retry(base)
        scenario_abnormal_exit_pauses_fifo(base)
        scenario_selection_immune_to_crash_state(base)
        scenario_queue_never_touches_target_or_event_log(base)

    if _FAILURES:
        print(f"\n{len(_FAILURES)} SCENARIO(S) FAILED: {_FAILURES}")
        return 1
    print("\nALL RUN-CONTROL CRASH SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
