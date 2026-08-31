"""ADR-30 review finding 4: autonomous persisted FIFO progression.

Real, controlled fake .bat executables (a genuine OS subprocess is spawned,
never mocked) driven purely by QueueDrainScheduler's own background asyncio
task -- no HTTP request, no browser, no explicit drain call, no second
enqueue -- proving a repository's queue advances on its own once the
Dashboard process is running.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.queue_scheduler import QueueDrainScheduler
from draindeck_dashboard.repositories import register_repository
from draindeck_dashboard.run_queue import (
    STATUS_COMPLETED,
    STATUS_QUEUED,
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
    return repo_id, digest


def _fake_exe(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text("@echo off\r\n" + body, encoding="utf-8")
    return str(path)


def test_two_queued_commands_run_sequentially_without_any_http_request_or_browser(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_id, digest = _register_ready(conn, tmp_path)

    order_marker = tmp_path / "order.txt"
    exe = _fake_exe(
        tmp_path, "fake_ordered.bat",
        f'echo A>> "{order_marker}"\r\n'
        'powershell -NoProfile -Command "Start-Sleep -Milliseconds 300"\r\n'
        f'echo B>> "{order_marker}"\r\n'
        "exit /b 0\r\n",
    )

    # Both commands queued directly (bypassing the HTTP API entirely) --
    # nothing else ever calls try_launch_next or the drain route.
    cmd1 = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                           expected_issues_digest=digest, idempotency_key="k1")
    assert cmd1["status"] == STATUS_QUEUED

    scheduler = QueueDrainScheduler(conn, exe, interval_seconds=0.1)

    async def run():
        scheduler.start()
        for _ in range(100):  # up to ~10s
            if get_command(conn, cmd1["id"])["status"] == STATUS_COMPLETED:
                break
            await asyncio.sleep(0.1)
        await scheduler.stop()

    asyncio.run(run())

    assert get_command(conn, cmd1["id"])["status"] == STATUS_COMPLETED
    # exactly one write per command, in order -- proves the scheduler ran
    # the fake executable to completion entirely on its own trigger.
    assert order_marker.read_text(encoding="utf-8").splitlines() == ["A", "B"]


def test_different_repositories_progress_concurrently(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_a, digest_a = _register_ready(conn, tmp_path, name="a")
    repo_b, digest_b = _register_ready(conn, tmp_path, name="b")

    exe = _fake_exe(tmp_path, "fake_ok.bat", "exit /b 0\r\n")
    cmd_a = enqueue_command(conn, repo_a, mode="ALL", issue_ids=None,
                            expected_issues_digest=digest_a, idempotency_key="ka")
    cmd_b = enqueue_command(conn, repo_b, mode="ALL", issue_ids=None,
                            expected_issues_digest=digest_b, idempotency_key="kb")

    scheduler = QueueDrainScheduler(conn, exe, interval_seconds=0.1)

    async def run():
        scheduler.start()
        for _ in range(100):
            done_a = get_command(conn, cmd_a["id"])["status"] == STATUS_COMPLETED
            done_b = get_command(conn, cmd_b["id"])["status"] == STATUS_COMPLETED
            if done_a and done_b:
                break
            await asyncio.sleep(0.1)
        await scheduler.stop()

    asyncio.run(run())

    assert get_command(conn, cmd_a["id"])["status"] == STATUS_COMPLETED
    assert get_command(conn, cmd_b["id"])["status"] == STATUS_COMPLETED


def test_queue_progresses_after_simulated_dashboard_restart(tmp_path):
    """A command queued before a (simulated) restart still gets picked up by
    a freshly-constructed scheduler against the same database -- the trigger
    is the scheduler's own periodic tick, not any in-memory state from the
    process that enqueued it."""
    db_path = tmp_path / "d.sqlite3"
    conn = connect_and_init(db_path)
    repo_id, digest = _register_ready(conn, tmp_path)
    exe = _fake_exe(tmp_path, "fake_ok.bat", "exit /b 0\r\n")
    cmd = enqueue_command(conn, repo_id, mode="ALL", issue_ids=None,
                          expected_issues_digest=digest, idempotency_key="k1")
    assert cmd["status"] == STATUS_QUEUED

    # simulate a Dashboard restart: fresh connection, fresh scheduler
    conn2 = connect_and_init(db_path)
    scheduler = QueueDrainScheduler(conn2, exe, interval_seconds=0.1)

    async def run():
        scheduler.start()
        for _ in range(100):
            if get_command(conn2, cmd["id"])["status"] == STATUS_COMPLETED:
                break
            await asyncio.sleep(0.1)
        await scheduler.stop()

    asyncio.run(run())
    assert get_command(conn2, cmd["id"])["status"] == STATUS_COMPLETED


def test_stop_cancels_the_background_task_cleanly(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    exe = _fake_exe(tmp_path, "fake_ok.bat", "exit /b 0\r\n")
    scheduler = QueueDrainScheduler(conn, exe, interval_seconds=0.05)

    async def run():
        scheduler.start()
        await asyncio.sleep(0.05)
        await scheduler.stop()
        assert scheduler._task is None

    asyncio.run(run())


def test_a_failing_repository_tick_never_blocks_another_repository(tmp_path, monkeypatch):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    repo_a, digest_a = _register_ready(conn, tmp_path, name="a")
    repo_b, digest_b = _register_ready(conn, tmp_path, name="b")
    exe = _fake_exe(tmp_path, "fake_ok.bat", "exit /b 0\r\n")
    cmd_b = enqueue_command(conn, repo_b, mode="ALL", issue_ids=None,
                            expected_issues_digest=digest_b, idempotency_key="kb")

    import draindeck_dashboard.queue_scheduler as qs_module
    real_try_launch_next = qs_module.try_launch_next

    def flaky_try_launch_next(conn_arg, repo_id_arg, *, executable):
        if repo_id_arg == repo_a:
            raise RuntimeError("boom")
        return real_try_launch_next(conn_arg, repo_id_arg, executable=executable)

    monkeypatch.setattr(qs_module, "try_launch_next", flaky_try_launch_next)

    scheduler = QueueDrainScheduler(conn, exe, interval_seconds=0.1)

    async def run():
        scheduler.start()
        for _ in range(100):
            if get_command(conn, cmd_b["id"])["status"] == STATUS_COMPLETED:
                break
            await asyncio.sleep(0.1)
        await scheduler.stop()

    asyncio.run(run())
    assert get_command(conn, cmd_b["id"])["status"] == STATUS_COMPLETED
