"""Focused tests for the launcher's real (non-RED-listed) orchestration
helpers: argv-only process construction (L-12), the injectable-clock
readiness wait used by the 180s fast-path contract (L-11), ownership-
validated stop (L-13), and the independent run-prerequisites preflight
(L-10). These strengthen docs/32's nine RED contracts with genuinely
behavioral coverage of the glue those contracts sit on top of, per
/resolve-item's "add focused tests as needed."
"""
from __future__ import annotations

import pytest

from draindeck_dashboard import launcher
from draindeck_dashboard.launcher_lock import LauncherLockTimeout, launcher_operation_lock


def test_build_dashboard_argv_is_a_plain_list_never_a_shell_string():
    argv = launcher.build_dashboard_argv(
        python_executable="C:/py/python.exe",
        host="127.0.0.1", port=8420,
        db_path="C:/repo & rm -rf /; echo pwned/dashboard.sqlite3",
        observer_executable="C:/bin/draindeck.exe",
        instance_token="tok123",
    )
    assert isinstance(argv, list)
    assert all(isinstance(part, str) for part in argv)
    # The dangerous value survives as ONE argv element, never split or
    # reinterpreted -- proof nothing here is ever joined into a shell string.
    assert "C:/repo & rm -rf /; echo pwned/dashboard.sqlite3" in argv
    assert "--instance-token" in argv and "tok123" in argv


def test_wait_for_readiness_succeeds_within_budget_using_a_fake_clock():
    ticks = iter([0.0, 1.0, 2.0, 3.0])
    fake_now = {"t": 0.0}

    def clock():
        fake_now["t"] = next(ticks)
        return fake_now["t"]

    calls = []

    def check():
        calls.append(1)
        return len(calls) == 3  # ready on the third poll

    result = launcher.wait_for_readiness(
        check=check, clock=clock, deadline_seconds=180.0, poll_interval=lambda: None,
    )
    assert result.ready is True
    assert result.elapsed_seconds <= 180.0


def test_wait_for_readiness_times_out_without_a_real_sleep():
    # A clock that jumps straight past the deadline proves this never
    # requires an actual 180-second sleep to exercise the timeout branch.
    times = iter([0.0, 500.0])

    def clock():
        return next(times)

    result = launcher.wait_for_readiness(
        check=lambda: False, clock=clock, deadline_seconds=180.0, poll_interval=lambda: None,
    )
    assert result.ready is False
    assert result.elapsed_seconds > 180.0


def test_stop_dashboard_refuses_when_the_live_identity_token_does_not_match():
    state = launcher.LauncherState(pid=123, port=8420, host="127.0.0.1", instance_token="mine")
    terminated = []
    status = launcher.stop_dashboard(
        state=state, identity_probe=lambda host, port: "someone-elses-token",
        terminate=terminated.append,
    )
    assert status == "REFUSE_UNVERIFIED_OWNERSHIP"
    assert terminated == []


def test_stop_dashboard_terminates_only_after_matching_identity_proof():
    state = launcher.LauncherState(pid=123, port=8420, host="127.0.0.1", instance_token="mine")
    terminated = []
    status = launcher.stop_dashboard(
        state=state, identity_probe=lambda host, port: "mine", terminate=terminated.append,
    )
    assert status == "STOPPED"
    assert terminated == [123]


def test_stop_dashboard_reports_not_running_with_no_recorded_state():
    terminated = []
    status = launcher.stop_dashboard(
        state=None, identity_probe=lambda host, port: "anything", terminate=terminated.append,
    )
    assert status == "NOT_RUNNING"
    assert terminated == []


def test_check_run_prerequisites_reports_each_missing_item_independently():
    result = launcher.check_run_prerequisites(
        claude_check=lambda: True, ollama_check=lambda: False, model_check=lambda: False,
    )
    assert result.ready is False
    assert result.missing == ("ollama", "reviewer-model")


def test_check_run_prerequisites_ready_when_all_three_succeed():
    result = launcher.check_run_prerequisites(
        claude_check=lambda: True, ollama_check=lambda: True, model_check=lambda: True,
    )
    assert result.ready is True
    assert result.missing == ()


def test_is_process_alive_is_false_for_an_implausible_pid():
    assert launcher.is_process_alive(999_999_999) is False
    assert launcher.is_process_alive(0) is False
    assert launcher.is_process_alive(-1) is False


def test_resolve_dashboard_process_starts_new_when_port_is_free():
    resolution = launcher.resolve_dashboard_process(
        recorded_pid=None, port_pid=None,
        process_alive=lambda _: False, health_ok=lambda: False, terminate=lambda _: None,
    )
    assert resolution.action == "START_NEW"


def test_resolve_dashboard_process_restarts_a_stale_owned_pid_without_terminating_it():
    terminated = []
    resolution = launcher.resolve_dashboard_process(
        recorded_pid=41, port_pid=41,
        process_alive=lambda _: False, health_ok=lambda: False, terminate=terminated.append,
    )
    assert resolution.action == "RESTART_STALE_OWNED"
    assert terminated == []


def test_launcher_operation_lock_blocks_a_concurrent_acquisition_and_times_out(tmp_path):
    """A real, OS-held exclusive lock (docs/32 review Blocker 9): a second
    attempt to acquire the SAME lock file -- via its own independent
    ``open()``, exactly as a second process would see it -- must actually
    be refused by the OS, not merely by some in-process convention, and
    must give up after its bounded wait rather than blocking forever."""
    lock_path = tmp_path / "launcher.lock"
    sleeps = []
    ticks = iter([0.0, 0.4, 0.8, 1.2])

    with launcher_operation_lock(lock_path):
        with pytest.raises(LauncherLockTimeout):
            with launcher_operation_lock(
                lock_path, timeout_seconds=1.0, poll_seconds=0.05,
                sleep=sleeps.append, clock=lambda: next(ticks),
            ):
                raise AssertionError("must never enter the body while contended")

    assert sleeps, "must retry at least once (via injected sleep) before timing out"


def test_launcher_operation_lock_is_released_on_normal_exit_and_reacquirable(tmp_path):
    lock_path = tmp_path / "launcher.lock"
    with launcher_operation_lock(lock_path):
        pass
    # Released -- an immediate second acquisition must succeed without
    # ever needing to retry.
    with launcher_operation_lock(lock_path, timeout_seconds=0.2, poll_seconds=0.01):
        pass


def test_launcher_operation_lock_is_released_on_exception_and_reacquirable(tmp_path):
    lock_path = tmp_path / "launcher.lock"

    class _Boom(Exception):
        pass

    with pytest.raises(_Boom):
        with launcher_operation_lock(lock_path):
            raise _Boom()

    # The exception must not have left the lock held.
    with launcher_operation_lock(lock_path, timeout_seconds=0.2, poll_seconds=0.01):
        pass


def test_launcher_operation_lock_two_concurrent_operations_actually_serialize(tmp_path):
    """Deterministic proof, using REAL threads plus ``threading.Event``
    (never sleep-based timing), that two launcher operations contending for
    the same lock never both believe they hold it at once: the second
    acquisition only succeeds once the first's ``with`` block has fully
    exited. A prior version of this test called both operations
    sequentially from a single thread, so it never actually proved
    concurrent contention -- it always passed even with no locking at all."""
    import threading

    lock_path = tmp_path / "launcher.lock"
    active = []
    max_concurrent = []
    active_guard = threading.Lock()

    first_holds = threading.Event()
    release_first = threading.Event()

    def _first_operation():
        with launcher_operation_lock(lock_path, timeout_seconds=2.0, poll_seconds=0.01):
            with active_guard:
                active.append(1)
                max_concurrent.append(len(active))
            first_holds.set()
            release_first.wait(timeout=2.0)
            with active_guard:
                active.pop()

    holder = threading.Thread(target=_first_operation)
    holder.start()
    assert first_holds.wait(timeout=2.0), "the first operation never acquired the lock"

    second_done = threading.Event()

    def _second_operation():
        with launcher_operation_lock(lock_path, timeout_seconds=2.0, poll_seconds=0.01):
            with active_guard:
                active.append(1)
                max_concurrent.append(len(active))
                active.pop()
        second_done.set()

    contender = threading.Thread(target=_second_operation)
    contender.start()
    try:
        # The second operation must actually block while the first still
        # holds the lock -- a bounded wait for it to have NOT finished yet,
        # not a fixed sleep used to time an assertion.
        assert not second_done.wait(timeout=0.3), (
            "the second operation acquired the lock while the first still held it"
        )
    finally:
        release_first.set()
        holder.join(timeout=2.0)
        contender.join(timeout=2.0)

    assert max_concurrent == [1, 1], "no two operations may ever be inside the lock simultaneously"
