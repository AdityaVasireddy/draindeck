"""Focused regression test for launcher.main()'s port-ownership decision.

Guards against a real bug found during self-review: an earlier version
treated ANY listening port as `recorded_pid`'s own process whenever prior
launcher state existed, without ever checking the identity-token proof --
so a foreign process that happened to be listening where our previous
instance used to run would have been silently reused/restarted against
instead of refused. Ownership must be decided by the identity-token
round-trip (docs/32 L-08/L-13), never by "a port is listening and we have
old state."
"""
from __future__ import annotations

import json

from draindeck_dashboard import launcher
from draindeck_dashboard.launcher_lock import launcher_operation_lock


def _write_state(path, *, pid, port, host, token):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "pid": pid, "port": port, "host": host, "instanceToken": token,
    }), encoding="utf-8")


def test_main_refuses_a_listening_port_whose_identity_does_not_match_recorded_state(
    tmp_path, monkeypatch,
):
    state_path = tmp_path / "launcher-state.json"
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-old-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    # Isolate this test from whatever git/claude/ollama happen to be
    # installed on the host running it -- it tests port ownership, not
    # prerequisite installation.
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)

    # Something IS listening on the port, but its identity token does not
    # match what we recorded -- it must never be treated as our own process.
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "a-different-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (200, {"status": "ok"}))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 1
    assert spawned == [], "must never start a duplicate Dashboard against an unverified port"
    assert opened == [], "must never open a browser against an unverified/foreign process"


def test_main_stop_refuses_when_the_live_identity_token_does_not_match(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "not-our-token")
    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    rc = launcher.main(["--stop"])

    assert rc == 1
    assert terminated == []
    assert state_path.is_file(), "an unverified stop must never remove the state record"


def test_main_stop_terminates_and_clears_state_once_ownership_is_proven(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    rc = launcher.main(["--stop"])

    assert rc == 0
    assert terminated == [4242]
    assert not state_path.exists()


def test_main_status_reports_not_running_with_no_recorded_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, "default_state_path", lambda: tmp_path / "missing.json")

    rc = launcher.main(["--status"])

    assert rc == 0
    assert "NOT_RUNNING" in capsys.readouterr().out


def test_main_stops_a_stale_owned_process_before_starting_its_replacement(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)

    # Identity matches (it IS our process) but it's unhealthy/not alive --
    # RESTART_STALE_OWNED, not REUSE and not REFUSE_PORT_COLLISION.
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (None, None))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: False)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)
    spawned = []

    class _FakeProc:
        pid = 5555

    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )
    # Two calls to wait_for_readiness happen in this order: (1) the
    # bounded wait for the stale port to actually release -- reported
    # ready here so the replacement is allowed to start; (2) the 180s
    # fast-path browser-readiness wait -- forced to fail immediately
    # instead of polling for real, so this test still exercises the
    # documented "readiness wait was forced to fail" rc==1 path.
    wait_calls = []

    def _fake_wait(**kwargs):
        wait_calls.append(kwargs["deadline_seconds"])
        if len(wait_calls) == 1:
            return launcher.WaitResult(ready=True, elapsed_seconds=0.0)
        return launcher.WaitResult(ready=False, elapsed_seconds=0.0)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert terminated == [4242], "the proven-owned stale process must be stopped before replacement"
    assert len(spawned) == 1, "exactly one replacement Dashboard is started"
    assert rc == 1  # the second (browser-readiness) wait was forced to fail above
    assert wait_calls == [
        launcher.STALE_PORT_RELEASE_DEADLINE_SECONDS, launcher.fast_path_contract().deadline_seconds,
    ], "the stale-port-release wait must happen, in order, before the browser-readiness wait"


def test_main_waits_for_stale_port_to_release_before_spawning_replacement(tmp_path, monkeypatch):
    """docs/32 review Blocker 9: Popen must never race a stale owned
    process's own (asynchronous) SIGTERM teardown -- it may only run once
    the port-release wait actually reports the port free."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)

    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (None, None))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: False)

    order = []
    monkeypatch.setattr(launcher, "terminate_process", lambda pid: order.append(("terminate", pid)))

    def _fake_wait(**kwargs):
        order.append(("wait", kwargs["deadline_seconds"]))
        if kwargs["deadline_seconds"] == launcher.STALE_PORT_RELEASE_DEADLINE_SECONDS:
            return launcher.WaitResult(ready=True, elapsed_seconds=0.3)
        return launcher.WaitResult(ready=True, elapsed_seconds=0.0)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    class _FakeProc:
        pid = 5555

    def _popen(argv, **k):
        order.append(("popen", argv))
        return _FakeProc()

    monkeypatch.setattr(launcher.subprocess, "Popen", _popen)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: order.append(("open", url)))

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert rc == 0
    kinds = [step[0] for step in order]
    assert kinds.index("terminate") < kinds.index("wait") < kinds.index("popen"), (
        f"must terminate, then wait for port release, then spawn -- got order {kinds!r}"
    )


def test_main_stale_port_release_timeout_prevents_spawn_and_browser_open(tmp_path, monkeypatch):
    """docs/32 review Blocker 9: if the stale port never becomes free
    within the bounded wait, no replacement is spawned, no browser is
    opened, and the result is a clear nonzero failure -- no additional
    process is killed either."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)

    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (None, None))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: False)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=False, elapsed_seconds=5.1),
    )

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert terminated == [4242], "only the one proven-owned stale process is terminated"
    assert spawned == [], "no replacement may be spawned while the stale port is still occupied"
    assert opened == [], "no browser may be opened when the replacement was never started"
    assert rc == 1


def test_main_reuses_only_after_the_identity_token_actually_matches(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)

    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (200, {"status": "ok"}))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: pid == 4242)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 0
    assert spawned == [], "a verified healthy owned process must be reused, not duplicated"
    assert opened == ["http://127.0.0.1:8420"]


def test_main_reuse_never_triggers_a_prerequisite_or_consent_check(tmp_path, monkeypatch):
    """Regression guard: reopening an already-healthy, launcher-owned
    Dashboard must be instant and never gated on git/claude/ollama
    presence or an install-consent prompt -- that bootstrap concern only
    applies when a new Dashboard process is actually about to start."""
    state_path = tmp_path / "launcher-state.json"
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="our-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)

    def _boom(args):
        raise AssertionError("_ensure_prerequisites must not be called on the REUSE path")

    monkeypatch.setattr(launcher, "_ensure_prerequisites", _boom)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: "our-token")
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (200, {"status": "ok"}))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 0


def test_main_refuses_clearly_when_the_launcher_lock_is_already_held(tmp_path, monkeypatch, capsys):
    """docs/32 review Blocker 9: a second concurrent launcher invocation
    must not spawn a second child -- it fails clearly and safely
    (LAUNCH_IN_PROGRESS) instead. Uses a REAL temporary OS-held lock (not
    a mock) held by this test itself, exactly as a second real process
    would see it."""
    lock_path = tmp_path / "launcher.lock"
    monkeypatch.setattr(launcher, "default_lock_path", lambda: lock_path)
    monkeypatch.setattr(launcher, "LAUNCHER_LOCK_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(launcher, "default_state_path", lambda: tmp_path / "missing.json")

    def _boom(args, state_path):
        raise AssertionError("_decide_dashboard_action must never run while the lock is held elsewhere")

    monkeypatch.setattr(launcher, "_decide_dashboard_action", _boom)
    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)

    with launcher_operation_lock(lock_path):
        rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 1
    assert spawned == [], "must never spawn a competing Dashboard while another launch holds the lock"
    assert "LAUNCH_IN_PROGRESS" in capsys.readouterr().err


def test_main_concurrent_start_guard_never_lets_two_launch_paths_reach_popen(tmp_path, monkeypatch):
    """docs/32 review Blocker 9: two launch paths contending for the same
    lock can never both reach Popen. Uses real threads plus
    ``threading.Event`` for deterministic ordering (the second path only
    calls ``main()`` once the first has provably acquired the lock) --
    not a sleep-based race."""
    import threading

    lock_path = tmp_path / "launcher.lock"
    monkeypatch.setattr(launcher, "default_lock_path", lambda: lock_path)
    monkeypatch.setattr(launcher, "LAUNCHER_LOCK_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(launcher, "default_state_path", lambda: tmp_path / "missing.json")

    def _boom(args, state_path):
        raise AssertionError("_decide_dashboard_action must never run while the lock is held elsewhere")

    monkeypatch.setattr(launcher, "_decide_dashboard_action", _boom)
    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)

    held = threading.Event()
    release = threading.Event()

    def _first_launch_path():
        with launcher_operation_lock(lock_path):
            held.set()
            release.wait(timeout=2.0)

    holder = threading.Thread(target=_first_launch_path)
    holder.start()
    assert held.wait(timeout=2.0), "the first launch path never acquired the lock"

    try:
        rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])
    finally:
        release.set()
        holder.join(timeout=2.0)

    assert rc == 1
    assert spawned == [], "the second launch path must never reach Popen while the first holds the lock"


def test_main_refuse_port_collision_never_triggers_a_prerequisite_check(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "default_state_path", lambda: tmp_path / "missing.json")

    def _boom(args):
        raise AssertionError("_ensure_prerequisites must not be called on the REFUSE path")

    monkeypatch.setattr(launcher, "_ensure_prerequisites", _boom)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: True)
    monkeypatch.setattr(launcher, "probe_identity", lambda host, port: None)

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 1
