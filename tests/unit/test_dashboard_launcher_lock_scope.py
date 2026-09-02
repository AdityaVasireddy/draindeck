"""RED -> GREEN: independent-review finding -- launcher.main() previously
held the launcher-operation lock around the ENTIRE `_launch_dashboard()`
body, including interactive consent, prerequisite/package installation, and
the full 180-second Dashboard browser-readiness wait. That meant a second
double-click returned LAUNCH_IN_PROGRESS after three seconds even while the
first Dashboard was already healthy or merely waiting for readiness,
instead of reusing it.

These tests prove the narrowed two-phase design with REAL threads and
Events/Barriers (never sleep-based races):

  A. the lock is free while `_ensure_prerequisites` runs;
  B. the lock is free during the 180s browser-readiness wait, and a second
     invocation started during that wait is classified STARTING_OWNED and
     cleanly reuses the now-owned (but not-yet-listening) Dashboard instead
     of spawning a duplicate or reporting LAUNCH_IN_PROGRESS;
  C. two contending launch paths racing the actual spawn/state-write step
     can never both call Popen -- the loser safely reuses instead.

A SECOND independent-review finding, fixed in the same module: narrowing
the lock created a normal startup window where a fresh Popen'd child is
alive but has not yet bound its port. The original test for B masked this
because its fake `is_port_listening()` flipped true immediately after the
fake Popen -- real child startup is asynchronous. `LauncherState` now
carries a `startedAtEpochSeconds` startup-generation timestamp, and
`_resolve_process_action` classifies a fresh, still-alive, not-yet-
listening recorded child as STARTING_OWNED (never START_NEW, never
RESTART_STALE_OWNED) so no second invocation ever spawns a duplicate
during that gap. The tests below cover:

  - the direct single-invocation startup window (STARTING_OWNED reuse, and
    its bounded DASHBOARD_STARTING_TIMEOUT failure mode);
  - the real two-launcher startup window (test B, rewritten so the port
    never actually binds during the test);
  - expired/legacy safety: a state with no startup-generation timestamp,
    or one outside the grace window, must never be treated as proven-owned
    or kill its recorded PID, and must not block startup.
"""
from __future__ import annotations

import json
import threading
import time

from draindeck_dashboard import launcher
from draindeck_dashboard.launcher_lock import launcher_operation_lock


def test_lock_is_not_held_during_prerequisite_installation(tmp_path, monkeypatch):
    lock_path = tmp_path / "launcher.lock"
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_lock_path", lambda: lock_path)
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    # Port is free -- Phase A resolves START_NEW, so `_ensure_prerequisites`
    # is actually reached.
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)

    entered_prereqs = threading.Event()
    release_prereqs = threading.Event()

    def _blocking_prereqs(args):
        entered_prereqs.set()
        release_prereqs.wait(timeout=2.0)
        # Decline so this test can never spawn a second Dashboard child.
        return False

    monkeypatch.setattr(launcher, "_ensure_prerequisites", _blocking_prereqs)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)

    t = threading.Thread(
        target=lambda: launcher.main(["--host", "127.0.0.1", "--port", "8420"])
    )
    t.start()
    try:
        assert entered_prereqs.wait(timeout=2.0), "prerequisite installation was never reached"

        # The launcher-operation lock must be immediately acquirable while
        # `_ensure_prerequisites` is blocked -- proof it was released after
        # Phase A's decision, before this potentially slow work began.
        with launcher_operation_lock(lock_path, timeout_seconds=0.5, poll_seconds=0.01):
            pass
    finally:
        release_prereqs.set()
        t.join(timeout=2.0)

    assert spawned == [], "no Dashboard child may be spawned in this test"


def test_lock_is_not_held_during_browser_readiness_wait(tmp_path, monkeypatch):
    """The lock is free during the post-Popen readiness wait, AND (real
    child startup is asynchronous, per the independent-review finding) a
    second invocation launched while the port genuinely has not bound yet
    must be handled as STARTING_OWNED -- waiting on the already-spawned
    child -- rather than being told the port is free and spawning a
    duplicate. ``is_port_listening`` deliberately never flips true here: a
    prior version of this test had it flip immediately after the fake
    Popen, which masked exactly this bug."""
    lock_path = tmp_path / "launcher.lock"
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")

    monkeypatch.setattr(launcher, "default_lock_path", lambda: lock_path)
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "generate_instance_token", lambda: "fixed-token")

    spawned = []
    spawn_guard = threading.Lock()

    def _fake_popen(argv, **k):
        with spawn_guard:
            spawned.append(argv)

        class _FakeProc:
            pid = 4321

        return _FakeProc()

    monkeypatch.setattr(launcher.subprocess, "Popen", _fake_popen)
    # The port never actually binds during this test -- the real
    # asynchronous startup interval the independent-review finding
    # describes. Readiness is instead proven via the mocked
    # `wait_for_readiness` below, exactly as it would be once the child
    # really does become reachable.
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    entered_count = {"n": 0}
    entered_guard = threading.Lock()
    first_entered = threading.Event()
    both_entered = threading.Event()
    release_waits = threading.Event()

    def _fake_wait(**kwargs):
        with entered_guard:
            entered_count["n"] += 1
            n = entered_count["n"]
        if n == 1:
            first_entered.set()
        if n >= 2:
            both_entered.set()
        release_waits.wait(timeout=2.0)
        return launcher.WaitResult(ready=True, elapsed_seconds=0.1)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    results = {}

    def _launch(key):
        results[key] = launcher.main([
            "--host", "127.0.0.1", "--port", "8420",
            "--observer-executable", str(observer),
        ])

    t1 = threading.Thread(target=_launch, args=("a",))
    t2 = threading.Thread(target=_launch, args=("b",))
    try:
        t1.start()
        assert first_entered.wait(timeout=2.0), "launcher A never reached its post-Popen readiness wait"
        assert len(spawned) == 1, "Popen must have already run before the readiness wait"

        t2.start()
        assert both_entered.wait(timeout=2.0), (
            "launcher B never reached a bounded readiness wait -- it must be classified "
            "STARTING_OWNED (not START_NEW) while A's child is alive but not yet listening"
        )
    finally:
        release_waits.set()
        t1.join(timeout=2.0)
        t2.join(timeout=2.0)

    assert len(spawned) == 1, "launcher B must never call Popen a second time"
    assert results == {"a": 0, "b": 0}
    assert opened == ["http://127.0.0.1:8420", "http://127.0.0.1:8420"], (
        "both invocations report success by opening the browser -- A via its normal "
        "SPAWNED readiness wait, B via the STARTING_OWNED reuse path"
    )


def test_final_spawn_never_lets_two_launch_paths_both_call_popen(tmp_path, monkeypatch):
    """Two contending launch paths, synchronized with a real
    ``threading.Barrier`` (not a sleep) so they attempt the spawn/state-
    write critical section at effectively the same instant, must never
    both call Popen -- the real OS-held lock in Phase B must serialize
    them, and the loser must re-observe the winner's now-healthy Dashboard
    and reuse it instead of spawning a duplicate."""
    lock_path = tmp_path / "launcher.lock"
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")

    monkeypatch.setattr(launcher, "default_lock_path", lambda: lock_path)
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "LAUNCHER_LOCK_TIMEOUT_SECONDS", 2.0)

    token_counter = {"n": 0}
    token_guard = threading.Lock()

    def _next_token():
        with token_guard:
            token_counter["n"] += 1
            return f"token-{token_counter['n']}"

    monkeypatch.setattr(launcher, "generate_instance_token", _next_token)
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=True, elapsed_seconds=0.0),
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    spawned = []
    spawn_guard = threading.Lock()

    def _fake_popen(argv, **k):
        with spawn_guard:
            spawned.append(argv)

            class _FakeProc:
                pid = 9000 + len(spawned)

            return _FakeProc()

    monkeypatch.setattr(launcher.subprocess, "Popen", _fake_popen)

    def _port_listening(host, port):
        with spawn_guard:
            return len(spawned) > 0

    monkeypatch.setattr(launcher, "is_port_listening", _port_listening)
    monkeypatch.setattr(launcher, "probe_health", lambda host, port: (200, {"status": "ok"}))
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    def _probe_identity(host, port):
        existing = launcher.load_launcher_state(state_path)
        return existing.instance_token if existing else None

    monkeypatch.setattr(launcher, "probe_identity", _probe_identity)

    barrier = threading.Barrier(2, timeout=2.0)

    def _prereqs(args):
        barrier.wait()
        return True

    monkeypatch.setattr(launcher, "_ensure_prerequisites", _prereqs)

    results = [None, None]

    def _run(i):
        results[i] = launcher.main([
            "--host", "127.0.0.1", "--port", "8420",
            "--observer-executable", str(observer),
        ])

    t1 = threading.Thread(target=_run, args=(0,))
    t2 = threading.Thread(target=_run, args=(1,))
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert len(spawned) == 1, "exactly one of the two contending launch paths may call Popen"
    assert results == [0, 0], "the loser must reuse safely, not error, and never spawn"


def _write_state(path, *, pid, port, host, token, started_at_epoch_seconds=None):
    payload = {"pid": pid, "port": port, "host": host, "instanceToken": token}
    if started_at_epoch_seconds is not None:
        payload["startedAtEpochSeconds"] = started_at_epoch_seconds
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_direct_startup_window_regression_reuses_instead_of_spawning_a_duplicate(
    tmp_path, monkeypatch,
):
    """Requirement A: a freshly-recorded child (current startup-generation
    timestamp, recorded PID alive, port not yet listening) must be
    classified STARTING_OWNED, not START_NEW -- Popen must never run while
    that record is fresh, and once readiness is proven the result is a
    successful reuse/open, never a duplicate spawn."""
    state_path = tmp_path / "launcher-state.json"
    _write_state(
        state_path, pid=4242, port=8420, host="127.0.0.1", token="child-token",
        started_at_epoch_seconds=time.time(),
    )
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)

    def _boom_prereqs(args):
        raise AssertionError("_ensure_prerequisites must not run on the STARTING_OWNED path")

    monkeypatch.setattr(launcher, "_ensure_prerequisites", _boom_prereqs)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)

    wait_calls = []

    def _fake_wait(**kwargs):
        wait_calls.append(kwargs["deadline_seconds"])
        return launcher.WaitResult(ready=True, elapsed_seconds=0.2)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 0
    assert spawned == [], "must never spawn a duplicate while the recorded child is still starting"
    assert opened == ["http://127.0.0.1:8420"]
    assert len(wait_calls) == 1
    # Bounded by the remaining startup grace window (~180s, just started),
    # not zero and not an unrelated/unbounded timeout.
    assert 0 < wait_calls[0] <= launcher.fast_path_contract().deadline_seconds


def test_direct_startup_window_regression_times_out_clearly_without_spawning(
    tmp_path, monkeypatch,
):
    """The other half of requirement A's contract: if the already-Popen'd
    child never proves ready within its bounded window, the result is a
    clear nonzero failure -- still never a duplicate spawn."""
    state_path = tmp_path / "launcher-state.json"
    _write_state(
        state_path, pid=4242, port=8420, host="127.0.0.1", token="child-token",
        started_at_epoch_seconds=time.time(),
    )
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=False, elapsed_seconds=180.2),
    )
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 1
    assert spawned == [], "a timed-out starting-owned child must never be duplicated"
    assert opened == []


def test_legacy_state_without_startup_generation_is_never_treated_as_starting_owned(
    tmp_path, monkeypatch,
):
    """Requirement C: a legacy launcher-state.json (written before this
    field existed) naming a PID that happens to still be alive must never
    be trusted as a fresh startup generation -- it must not be killed, must
    not block startup, and normal start logic must proceed."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(state_path, pid=4242, port=8420, host="127.0.0.1", token="old-token")
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    # An unrelated process happens to be alive under this reused/legacy PID.
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    class _FakeProc:
        pid = 9999

    spawned = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=True, elapsed_seconds=0.1),
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert terminated == [], "an unrelated/legacy-recorded PID must never be killed"
    assert rc == 0
    assert len(spawned) == 1, "normal start logic must proceed -- a legacy record must not block startup"


def test_expired_startup_generation_falls_back_to_normal_start_without_trusting_the_pid(
    tmp_path, monkeypatch,
):
    """Requirement C, second half: a startup-generation timestamp outside
    the grace window is exactly as untrusted as a missing one -- it must
    not be treated as proven-owned, and must not wait forever."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    expired = time.time() - (launcher.fast_path_contract().deadline_seconds + 60.0)
    _write_state(
        state_path, pid=4242, port=8420, host="127.0.0.1", token="old-token",
        started_at_epoch_seconds=expired,
    )
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    class _FakeProc:
        pid = 9999

    spawned = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=True, elapsed_seconds=0.1),
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert terminated == [], "an expired startup-generation record must never make its PID killable"
    assert rc == 0
    assert len(spawned) == 1


def test_starting_owned_never_triggered_by_a_different_ports_fresh_state(tmp_path, monkeypatch):
    """Independent-review finding: STARTING_OWNED must require the saved
    endpoint to match the REQUESTED endpoint, not just "some fresh, alive,
    recorded PID exists." A launcher started for 127.0.0.1:9000 (still
    starting, fresh state) must never make an unrelated launcher invocation
    for the free port 127.0.0.1:8420 wait on 9000's PID or skip its own
    normal start -- that PID belongs to a different endpoint entirely and
    must never be trusted, waited on, or terminated on this request's
    behalf."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(
        state_path, pid=4242, port=9000, host="127.0.0.1", token="other-endpoint-token",
        started_at_epoch_seconds=time.time(),
    )
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    # The REQUESTED port (8420) is free; the unrelated recorded PID (for
    # 9000) is alive -- a buggy STARTING_OWNED check that ignores host/port
    # would treat that alive PID as proof this (unrelated) request is
    # already starting.
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    class _FakeProc:
        pid = 9999

    spawned = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )

    wait_calls = []

    def _fake_wait(**kwargs):
        wait_calls.append(kwargs)
        return launcher.WaitResult(ready=True, elapsed_seconds=0.1)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert rc == 0
    assert terminated == [], "the unrelated PID recorded for a different port must never be killed"
    assert len(spawned) == 1, "normal launch logic must proceed and spawn exactly once for 8420"
    assert spawned[0][spawned[0].index("--port") + 1] == "8420"
    assert opened == ["http://127.0.0.1:8420"]
    # Never entered the STARTING_OWNED wait path for the unrelated record --
    # the only wait call is the normal post-spawn readiness wait for the
    # freshly spawned 8420 child.
    assert len(wait_calls) == 1


def test_starting_owned_never_triggered_by_a_different_hosts_fresh_state(tmp_path, monkeypatch):
    """Same requirement as the different-port regression, for host instead
    of port: a fresh, alive, recorded PID for a DIFFERENT host on the same
    port must never be trusted, waited on, or terminated on behalf of a
    request for a different host."""
    state_path = tmp_path / "launcher-state.json"
    observer = tmp_path / "draindeck"
    observer.write_text("")
    _write_state(
        state_path, pid=4243, port=8420, host="192.168.1.5", token="other-host-token",
        started_at_epoch_seconds=time.time(),
    )
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher, "is_process_alive", lambda pid: True)

    terminated = []
    monkeypatch.setattr(launcher, "terminate_process", terminated.append)

    class _FakeProc:
        pid = 9998

    spawned = []
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )

    wait_calls = []

    def _fake_wait(**kwargs):
        wait_calls.append(kwargs)
        return launcher.WaitResult(ready=True, elapsed_seconds=0.1)

    monkeypatch.setattr(launcher, "wait_for_readiness", _fake_wait)

    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url))

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", str(observer),
    ])

    assert rc == 0
    assert terminated == [], "the unrelated PID recorded for a different host must never be killed"
    assert len(spawned) == 1, "normal launch logic must proceed and spawn exactly once for the requested host"
    assert spawned[0][spawned[0].index("--host") + 1] == "127.0.0.1"
    assert opened == ["http://127.0.0.1:8420"]
    assert len(wait_calls) == 1
