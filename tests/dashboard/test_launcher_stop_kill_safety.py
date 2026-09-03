"""RED tests, ULTRA-REVIEW-001 findings 3 and 4: POSIX process-termination
safety in `src/draindeck_dashboard/launcher.py`.

Finding 3 -- identity-check-to-kill race: `stop_dashboard` proves ownership
via a fresh `identity_probe` round-trip, then calls `terminate(state.pid)`.
On POSIX, `terminate_process` calls `os.kill(pid, signal.SIGTERM)`
unconditionally. If the process exits in the narrow window between the
identity check succeeding and the kill actually happening, `os.kill` raises
`ProcessLookupError`, which nothing here catches -- it leaks a raw traceback
out of `_cmd_stop` instead of being treated as "already stopped", and the
stale `launcher-state.json` record is never cleaned up (the `unlink()` call
only runs on the `"STOPPED"` branch).

Finding 4 -- invalid/zero/negative PIDs must never reach `os.kill`:
`terminate_process` has no PID validation at all, unlike `is_process_alive`
(which explicitly guards `pid <= 0`). `_UNVERIFIED_OCCUPANT_PID = -1` is
used internally by `_resolve_process_action` as a sentinel for "something
unverified is on the port" -- but a corrupted or legacy
`launcher-state.json` that happens to record `pid: -1` for an endpoint
whose live identity token matches is currently indistinguishable, by the
`port_pid == recorded_pid` check in `resolve_dashboard_process`, from a
genuinely stale owned process, and reaches
`_spawn_dashboard_under_lock`'s `RESTART_STALE_OWNED` branch --
`terminate_process(-1)` -> `os.kill(-1, SIGTERM)` on POSIX signals EVERY
process this launcher's user can signal, not one process.

Planning-gate only (docs/32 review, ULTRA-REVIEW-001): no `src/` change here.
"""
from __future__ import annotations

from pathlib import Path

from draindeck_dashboard import launcher


def test_stop_dashboard_survives_a_posix_identity_check_to_kill_race_and_cleans_up_state(
    tmp_path, monkeypatch,
):
    state_path = tmp_path / "launcher-state.json"
    state = launcher.LauncherState(pid=4242, port=8420, host="127.0.0.1", instance_token="tok-abc")
    launcher.save_launcher_state(state_path, state)

    def racing_identity_probe(host, port):
        # Ownership is proven -- the process WAS alive and answered with
        # the recorded token a moment ago.
        return "tok-abc"

    def racing_terminate(pid):
        # The process has since exited on its own, in the window between
        # the identity probe above and this call -- the real POSIX failure
        # mode this simulates.
        raise ProcessLookupError(f"[Errno 3] No such process: {pid}")

    monkeypatch.setattr(launcher, "probe_identity", racing_identity_probe)
    monkeypatch.setattr(launcher, "terminate_process", racing_terminate)

    # RED (finding 3): this currently raises ProcessLookupError straight out
    # of _cmd_stop instead of being handled as "already stopped".
    exit_code = launcher._cmd_stop(state_path)

    assert exit_code in (0, 1), "_cmd_stop must return a normal exit code, never raise"
    assert not state_path.exists(), (
        "RED (finding 3): a process that already exited before terminate() ran is "
        "functionally already stopped -- the stale launcher-state.json record must "
        "be cleaned up, not left pointing at a dead PID forever."
    )


def test_terminate_process_never_calls_os_kill_with_an_invalid_pid(monkeypatch):
    # Force the POSIX branch deterministically regardless of the host this
    # test actually runs on.
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    calls = []
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: calls.append(pid))

    for bad_pid in (0, -1, -4242):
        calls.clear()
        launcher.terminate_process(bad_pid)
        assert calls == [], (
            f"RED (finding 4): terminate_process(pid={bad_pid}) called "
            f"os.kill({bad_pid!r}, SIGTERM) -- 0 or a negative PID must be "
            "validated and refused before ever reaching os.kill (POSIX sends "
            "the signal to an entire process GROUP for pid<=0, not one process)."
        )


def test_spawn_under_lock_never_terminates_the_unverified_occupant_sentinel_pid(tmp_path, monkeypatch):
    # A corrupted/legacy state record whose pid (-1) collides with
    # _resolve_process_action's own internal "unverified occupant" sentinel.
    state_path = tmp_path / "launcher-state.json"
    state = launcher.LauncherState(pid=-1, port=8420, host="127.0.0.1", instance_token="tok-x")
    launcher.save_launcher_state(state_path, state)

    class _Args:
        host = "127.0.0.1"
        port = 8420

    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port, timeout=1.0: True)
    # The live identity token matches the recorded one exactly, so
    # _resolve_process_action treats the port occupant as `existing.pid` (-1)
    # -- equal to `recorded_pid` (-1) -- rather than the unverified sentinel.
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "tok-x")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (None, None))
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **kw: launcher.WaitResult(ready=True, elapsed_seconds=0.0),
    )

    class _FakeProc:
        pid = 999

    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **kw: _FakeProc())

    terminate_calls = []
    monkeypatch.setattr(launcher, "terminate_process", lambda pid: terminate_calls.append(pid))

    launcher._spawn_dashboard_under_lock(_Args(), state_path, "db.sqlite3", "/usr/bin/draindeck")

    assert terminate_calls == [], (
        f"RED (finding 4): terminate_process was called with {terminate_calls} -- "
        "pid -1 (the exact sentinel value _resolve_process_action's own "
        "_UNVERIFIED_OCCUPANT_PID uses) must never be passed to "
        "terminate_process/os.kill."
    )
