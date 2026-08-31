"""ADR-30 RED 6: one-process-per-repository FIFO queue.

Pure queue-mechanics tests (no real subprocess -- that's RED 7's
test_run_launcher.py). See
docs/plans/dashboard-issue-run-control-failing-tests.md RED 6.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import DashboardApiError
from draindeck_dashboard.repositories import register_repository
from draindeck_dashboard.run_queue import (
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
    STATUS_QUEUED,
    STATUS_REFUSED,
    claim_next_launchable_command,
    delete_commands_for_repository,
    enqueue_command,
    get_command,
    reconcile_ambiguous_claims_on_startup,
    repository_has_active_command,
    revalidate_claimed_command,
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
    (repo / "Issues.md").write_text("## a: A\nbody\n\n## b: B\nbody\n", encoding="utf-8", newline="")
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
    return repo_id, digest


def _enqueue_all(conn, repo_id, digest, key):
    return enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                           expected_issues_digest=digest, idempotency_key=key)


# ── ADR-30 review finding 9: explicit terminal count summaries ─────────────

def test_plan_run_reports_torun_and_terminal_state_counts(tmp_path):
    from draindeck_dashboard.run_queue import plan_run

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)  # issues a, b, both PENDING
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'DONE', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.commit()
    result = plan_run(conn, repo_id, mode="ALL", issue_ids=None, expected_issues_digest=digest)
    assert result["ok"] is True
    assert result["toRunCount"] == 1  # only b
    assert result["totalTerminalCount"] == 1
    assert result["terminalCounts"] == {"DONE": 1, "NEEDS_HUMAN": 0, "NEEDS_DECOMPOSITION": 0}


def test_plan_run_terminal_counts_cover_all_three_states(tmp_path):
    from draindeck_dashboard.run_queue import plan_run

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo = _git_worktree(tmp_path, "three")
    (repo / "Issues.md").write_text(
        "## a: A\nbody\n\n## b: B\nbody\n\n## c: C\nbody\n", encoding="utf-8", newline="",
    )
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
    for iid, state in (("a", "DONE"), ("b", "NEEDS_HUMAN"), ("c", "NEEDS_DECOMPOSITION")):
        conn.execute(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
            "VALUES (?, 1, ?, ?, '2026-08-30T00:00:00Z')", (repo_id, iid, state),
        )
    conn.commit()
    from draindeck_dashboard.configured_issues import get_configured_issues
    digest = get_configured_issues(conn, repo_id)["issuesFileRevision"]

    result = plan_run(conn, repo_id, mode="ALL", issue_ids=None, expected_issues_digest=digest)
    assert result["ok"] is True
    assert result["toRunCount"] == 0
    assert result["totalTerminalCount"] == 3
    assert result["terminalCounts"] == {"DONE": 1, "NEEDS_HUMAN": 1, "NEEDS_DECOMPOSITION": 1}


# ── ADR-30 review blocker 1: process exit is not runtime batch completion ──

def _seed_confirmable_run_outcome(conn, repo_id: int, run_id: str, outcome) -> None:
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, "
        "inconsistent, updated_at) VALUES (?, 1, ?, ?, 0, '2026-08-31T00:00:00Z')",
        (repo_id, run_id, outcome),
    )
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-31T00:00:00Z')",
        (repo_id,),
    )
    conn.commit()


def test_command_has_no_runtime_outcome_without_confirmed_correlation(tmp_path):
    """An exit-0 process with no confirmed event correlation must not be
    displayed as completed -- runtimeOutcome stays None even though the
    queue's own status is COMPLETED."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    fetched = get_command(conn, cmd["id"])
    assert fetched["runtimeOutcome"] is None
    assert fetched["runIdCorrelation"] is None


def test_command_shows_confirmed_interrupted_outcome_not_completed(tmp_path):
    """An exit-0 process whose confirmed event outcome is INTERRUPTED must
    surface INTERRUPTED, never a fabricated/implied COMPLETED."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    run_id = "run-interrupted-1"
    _seed_confirmable_run_outcome(conn, repo_id, run_id, "INTERRUPTED")
    conn.execute("UPDATE run_commands SET status = ?, run_id_correlation = ? WHERE id = ?",
                (STATUS_COMPLETED, run_id, cmd["id"]))
    conn.commit()

    fetched = get_command(conn, cmd["id"])
    assert fetched["status"] == STATUS_COMPLETED  # the queue's own process-exit fact, unchanged
    assert fetched["runtimeOutcome"] == "INTERRUPTED"  # the real, event-derived outcome


def test_command_shows_confirmed_completed_outcome_correctly(tmp_path):
    """An observed event-derived COMPLETED outcome is displayed correctly."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    run_id = "run-completed-1"
    _seed_confirmable_run_outcome(conn, repo_id, run_id, "COMPLETED")
    conn.execute("UPDATE run_commands SET status = ?, run_id_correlation = ? WHERE id = ?",
                (STATUS_COMPLETED, run_id, cmd["id"]))
    conn.commit()

    fetched = get_command(conn, cmd["id"])
    assert fetched["runtimeOutcome"] == "COMPLETED"


def test_command_with_confirmed_correlation_but_no_finish_yet_has_no_outcome(tmp_path):
    """RunStarted observed and confirmed, but no RunFinished yet -- the
    projection's own outcome column is NULL. Must not be displayed as
    completed either (never fabricates an outcome the projection itself
    doesn't have)."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    run_id = "run-unresolved-1"
    _seed_confirmable_run_outcome(conn, repo_id, run_id, None)
    conn.execute("UPDATE run_commands SET status = ?, run_id_correlation = ? WHERE id = ?",
                (STATUS_COMPLETED, run_id, cmd["id"]))
    conn.commit()

    fetched = get_command(conn, cmd["id"])
    assert fetched["runtimeOutcome"] is None


# ── ADR-30 review finding 3: planning and dequeue refuse on config drift ───

def test_plan_and_dequeue_refuse_when_registered_config_drifts_to_another_repository(tmp_path):
    from draindeck_dashboard.repositories import get_repository
    from draindeck_dashboard.run_queue import plan_run

    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path, name="repo")
    queued = _enqueue_all(conn, repo_id, digest, "drift-k1")
    assert queued["status"] == STATUS_QUEUED

    other_repo = _git_worktree(tmp_path, "other")
    (other_repo / "Issues.md").write_text(
        "## a: A\nbody\n\n## b: B\nbody\n", encoding="utf-8", newline="",
    )  # byte-identical to repo's Issues.md
    registration = get_repository(conn, repo_id)
    Path(registration["configPath"]).write_text(
        _VALID_CONFIG_YAML.format(repository=str(other_repo)), encoding="utf-8",
    )

    with pytest.raises(DashboardApiError) as exc_info:
        plan_run(conn, repo_id, mode="ALL", issue_ids=None, expected_issues_digest=digest)
    assert exc_info.value.code == "CONFIG_REPOSITORY_DRIFT"

    claimed = claim_next_launchable_command(conn, repo_id)
    assert claimed is not None
    revalidated = revalidate_claimed_command(conn, claimed)
    assert revalidated["status"] == STATUS_REFUSED
    assert "no longer resolves to the registered repository" in (revalidated["refusalReason"] or "")


def test_first_valid_command_for_repo_becomes_launch_candidate(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    assert claimed is not None
    assert claimed["id"] == cmd["id"]
    assert claimed["status"] == STATUS_CLAIMED


def test_second_command_for_active_repo_is_persisted_fifo_without_spawn(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue_all(conn, repo_id, digest, "k1")
    claim_next_launchable_command(conn, repo_id)  # first becomes CLAIMED

    second = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                             expected_issues_digest=digest, idempotency_key="k2")
    assert second["status"] == STATUS_QUEUED
    # repository already has an active (CLAIMED) command -- no second claim.
    assert claim_next_launchable_command(conn, repo_id) is None


def test_three_queued_commands_launch_in_submission_order(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    # enqueue_command never auto-claims -- three plain enqueues all land QUEUED.
    ids = [
        enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                        expected_issues_digest=digest, idempotency_key=f"k{i}")["id"]
        for i in range(3)
    ]

    order = []
    for _ in range(3):
        claimed = claim_next_launchable_command(conn, repo_id)
        order.append(claimed["id"])
        conn.execute("UPDATE run_commands SET status='COMPLETED' WHERE id=?", (claimed["id"],))
        conn.commit()
    assert order == ids


def test_different_repositories_may_each_launch_one_process(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_a, digest_a = _register_ready(conn, tmp_path, "a")
    repo_b, digest_b = _register_ready(conn, tmp_path, "b")
    _enqueue_all(conn, repo_a, digest_a, "ka")
    _enqueue_all(conn, repo_b, digest_b, "kb")
    claimed_a = claim_next_launchable_command(conn, repo_a)
    claimed_b = claim_next_launchable_command(conn, repo_b)
    assert claimed_a is not None and claimed_b is not None
    assert claimed_a["repositoryId"] == repo_a
    assert claimed_b["repositoryId"] == repo_b


def test_atomic_claim_prevents_two_dashboard_workers_launching_same_command(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    _enqueue_all(conn, repo_id, digest, "k1")
    first = claim_next_launchable_command(conn, repo_id)
    second = claim_next_launchable_command(conn, repo_id)  # same connection, simulating a second worker
    assert first is not None
    assert second is None  # already CLAIMED -- repo has an active command


def test_queue_survives_dashboard_restart(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    conn = connect_and_init(db_path)
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    conn.close()

    conn2 = connect_and_init(db_path)  # simulates a fresh Dashboard process
    fetched = get_command(conn2, cmd["id"])
    assert fetched["status"] == STATUS_QUEUED


def test_dequeue_revalidates_issue_file_revision(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    # issue file changes after the command was queued
    from draindeck_dashboard.repositories import get_repository
    project_path = Path(get_repository(conn, repo_id)["projectPath"])
    (project_path / "Issues.md").write_text("## c: New\nbody\n", encoding="utf-8", newline="")

    result = revalidate_claimed_command(conn, claimed)
    assert result["status"] == STATUS_REFUSED


def test_dequeue_selected_issue_now_terminal_refuses_exact_command(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                          expected_issues_digest=digest, idempotency_key="k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'DONE', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.commit()

    result = revalidate_claimed_command(conn, claimed)
    assert result["status"] == STATUS_REFUSED


def test_dequeue_run_all_recomputes_terminal_exclusions(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'a', 'DONE', '2026-08-30T00:00:00Z')", (repo_id,),
    )
    conn.commit()

    result = revalidate_claimed_command(conn, claimed)
    assert result["status"] == STATUS_CLAIMED  # 'b' remains runnable -- not refused


def test_dequeue_run_all_now_empty_completes_as_noop_without_spawn(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claimed = claim_next_launchable_command(conn, repo_id)

    for iid in ("a", "b"):
        conn.execute(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
            "VALUES (?, 1, ?, 'DONE', '2026-08-30T00:00:00Z')", (repo_id, iid),
        )
    conn.commit()

    result = revalidate_claimed_command(conn, claimed)
    assert result["status"] == STATUS_COMPLETED
    assert claim_next_launchable_command(conn, repo_id) is None  # slot released, nothing else queued


def test_abnormal_prior_exit_pauses_later_commands_for_operator_attention(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue_all(conn, repo_id, digest, "k1")
    second = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                             expected_issues_digest=digest, idempotency_key="k2")
    conn.execute("UPDATE run_commands SET status = 'ABNORMAL_EXIT' WHERE id = ?", (first["id"],))
    conn.commit()
    assert repository_has_active_command(conn, repo_id) is True
    assert claim_next_launchable_command(conn, repo_id) is None


def test_normal_process_exit_releases_slot_then_revalidates_next_command(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    first = _enqueue_all(conn, repo_id, digest, "k1")
    second = enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                             expected_issues_digest=digest, idempotency_key="k2")
    conn.execute("UPDATE run_commands SET status = 'COMPLETED' WHERE id = ?", (first["id"],))
    conn.commit()
    claimed = claim_next_launchable_command(conn, repo_id)
    assert claimed["id"] == second["id"]


def test_lost_process_handle_never_implies_repository_is_launchable(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claim_next_launchable_command(conn, repo_id)
    conn.execute("UPDATE run_commands SET status = 'LAUNCHED', process_pid = 999999 WHERE id = ?",
                (cmd["id"],))
    conn.commit()
    # No in-memory Popen handle exists for this pid in this test process, and
    # nothing has confirmed it DEAD -- the repository must stay blocked.
    assert repository_has_active_command(conn, repo_id) is True
    assert claim_next_launchable_command(conn, repo_id) is None


def test_unresolved_runstarted_is_not_labeled_running(tmp_path):
    """The queue's own status vocabulary never includes "Running" -- that
    word belongs only to a (nonexistent) runtime liveness signal ADR-25
    explicitly does not provide. LAUNCHED is the correct control-plane
    status regardless of what the runtime process is actually doing."""
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claimed = claim_next_launchable_command(conn, repo_id)
    conn.execute("UPDATE run_commands SET status = 'LAUNCHED' WHERE id = ?", (claimed["id"],))
    conn.commit()
    fetched = get_command(conn, claimed["id"])
    assert fetched["status"] != "RUNNING" and fetched["status"] == "LAUNCHED"


def test_unregister_with_active_process_refuses_and_does_not_orphan_control(tmp_path):
    from fastapi.testclient import TestClient
    from draindeck_dashboard.app import create_app
    from draindeck_dashboard.config import DashboardConfig

    cfg = DashboardConfig(db_path=str(tmp_path / "dashboard.sqlite3"),
                          observer_executable=str(tmp_path / "draindeck.exe"))
    client = TestClient(create_app(cfg), base_url="http://127.0.0.1")
    conn = client.app.state.db
    repo_id, digest = _register_ready(conn, tmp_path)
    _enqueue_all(conn, repo_id, digest, "k1")
    claim_next_launchable_command(conn, repo_id)

    resp = client.delete(f"/api/repositories/{repo_id}")
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "REPOSITORY_HAS_ACTIVE_RUN"
    assert client.get(f"/api/repositories/{repo_id}").status_code == 200  # not orphaned/deleted


def test_queue_rows_are_dashboard_owned_and_never_written_to_event_log(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    log_path = tmp_path / "events.jsonl"
    _enqueue_all(conn, repo_id, digest, "k1")
    assert not log_path.exists()  # nothing in run_queue.py ever opens/writes it


def test_reconcile_ambiguous_claims_on_startup_marks_ownership_unknown(tmp_path):
    db_path = tmp_path / "d.sqlite3"
    conn = connect_and_init(db_path)
    repo_id, digest = _register_ready(conn, tmp_path)
    cmd = _enqueue_all(conn, repo_id, digest, "k1")
    claim_next_launchable_command(conn, repo_id)  # left CLAIMED -- simulates a crash before launch
    conn.close()

    conn2 = connect_and_init(db_path)  # this call itself must NOT auto-reconcile
    fetched = get_command(conn2, cmd["id"])
    assert fetched["status"] == STATUS_CLAIMED

    reconciled = reconcile_ambiguous_claims_on_startup(conn2)
    assert len(reconciled) == 1
    assert reconciled[0]["status"] == STATUS_LAUNCH_OWNERSHIP_UNKNOWN
    assert repository_has_active_command(conn2, repo_id) is True  # repo stays closed


def test_delete_commands_for_repository_removes_only_queue_rows(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)
    _enqueue_all(conn, repo_id, digest, "k1")
    delete_commands_for_repository(conn, repo_id)
    remaining = conn.execute(
        "SELECT COUNT(*) FROM run_commands WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert remaining == 0


# ── fresh-context adversarial review additions ──────────────────────────

def test_concurrent_claims_from_two_real_connections_never_double_claim(tmp_path):
    """Stronger than same-connection reuse: two genuinely separate sqlite3
    connections (simulating two Dashboard worker threads/processes) race to
    claim the same repository's queued commands. BEGIN IMMEDIATE's RESERVED
    lock must serialize them -- exactly one winner per command, never both,
    and never a lost update."""
    import threading
    db_path = tmp_path / "d.sqlite3"
    conn = connect_and_init(db_path)
    repo_id, digest = _register_ready(conn, tmp_path)
    ids = [
        enqueue_command(conn, repo_id, mode="SELECTED", issue_ids=["a"],
                        expected_issues_digest=digest, idempotency_key=f"k{i}")["id"]
        for i in range(5)
    ]
    conn.close()

    claimed_by: dict[int, list] = {0: [], 1: []}
    errors: list[BaseException] = []

    def worker(idx):
        worker_conn = connect_and_init(db_path)
        try:
            for _ in range(10):
                result = claim_next_launchable_command(worker_conn, repo_id)
                if result is not None:
                    claimed_by[idx].append(result["id"])
                    worker_conn.execute(
                        "UPDATE run_commands SET status = 'COMPLETED' WHERE id = ?", (result["id"],),
                    )
                    worker_conn.commit()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"concurrent claim raised: {errors}"
    all_claimed = claimed_by[0] + claimed_by[1]
    assert sorted(all_claimed) == ids, f"expected exactly {ids}, got {sorted(all_claimed)}"
    assert len(all_claimed) == len(set(all_claimed)), "a command was claimed more than once"


def test_concurrent_double_click_same_idempotency_key_creates_exactly_one_row(tmp_path):
    """A genuine race: two connections race past the idempotency SELECT
    check before either commits its INSERT. ux_run_commands_repo_idempotency
    (the DB-level UNIQUE constraint) is the real enforcement point;
    enqueue_command must catch the resulting IntegrityError and fall back to
    returning the winner's row, never propagate a 500 or create two rows."""
    import threading
    db_path = tmp_path / "d.sqlite3"
    conn = connect_and_init(db_path)
    repo_id, digest = _register_ready(conn, tmp_path)
    conn.close()

    barrier = threading.Barrier(8)
    results: list[dict] = []
    errors: list[BaseException] = []

    def worker():
        worker_conn = connect_and_init(db_path)
        try:
            barrier.wait(timeout=5)  # maximize the chance all threads pass
            # the idempotency SELECT before any INSERT commits
            result = enqueue_command(worker_conn, repo_id, mode="ALL", issue_ids=None,
                                     expected_issues_digest=digest, idempotency_key="race-key")
            results.append(result)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            worker_conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"enqueue_command raised under a real double-click race: {errors}"
    assert len(results) == 8
    ids = {r["id"] for r in results}
    assert len(ids) == 1, f"expected every racer to converge on one row, got ids {ids}"

    conn2 = connect_and_init(db_path)
    total = conn2.execute(
        "SELECT COUNT(*) FROM run_commands WHERE repository_id = ?", (repo_id,),
    ).fetchone()[0]
    assert total == 1


def test_run_command_id_cannot_be_read_across_repositories(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_a, digest_a = _register_ready(conn, tmp_path, "a")
    repo_b, digest_b = _register_ready(conn, tmp_path, "b")
    cmd_a = _enqueue_all(conn, repo_a, digest_a, "ka")

    from fastapi.testclient import TestClient
    from draindeck_dashboard.app import create_app
    from draindeck_dashboard.config import DashboardConfig
    cfg = DashboardConfig(db_path=str(tmp_path / "d.sqlite3"), observer_executable=str(tmp_path / "x.exe"))
    # A separate app instance over the SAME db file, matching how a real
    # browser session would query it.
    client = TestClient(create_app(cfg), base_url="http://127.0.0.1")
    resp = client.get(f"/api/repositories/{repo_b}/run-commands/{cmd_a['id']}")
    assert resp.status_code == 404


def test_non_loopback_host_cannot_call_drain_route(tmp_path):
    from fastapi.testclient import TestClient
    from draindeck_dashboard.app import create_app
    from draindeck_dashboard.config import DashboardConfig
    cfg = DashboardConfig(db_path=str(tmp_path / "d.sqlite3"), observer_executable=str(tmp_path / "x.exe"))
    app = create_app(cfg)
    loopback_client = TestClient(app, base_url="http://127.0.0.1")
    repo_id, _digest = _register_ready(loopback_client.app.state.db, tmp_path)

    evil_client = TestClient(app, base_url="http://evil.example.com")
    resp = evil_client.post(f"/api/repositories/{repo_id}/run-commands/drain")
    assert resp.status_code == 403
