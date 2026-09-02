"""Cross-platform, one-click Dashboard launcher (docs/32, ADR-26 dashboard
extra). This module is the single testable implementation behind the
tracked entry points ``Start-DraindeckDashboard.cmd``/``.command`` and
``start-draindeck-dashboard.sh``.

Process ownership/orchestration lives here; installer policy lives in
``launcher_install.py`` and repository/model run-readiness lives in
``launcher_readiness.py`` (docs/32 review Blocker 7 -- this file had grown
past a healthy single-file size). Every public name from both is imported
and re-exported below unchanged, so ``launcher.X`` keeps resolving exactly
as it did before the split; existing tests monkeypatch through this
module's namespace and are unaffected by where a name is actually defined.

Every side-effecting operation (package manager, model puller, server
starter, process/network probes, the clock) is injected as a callable so
the decision logic here is exercised in unit tests without ever touching a
real OS package manager, network socket, or child process. The real
default callables (``_default_*``) are used only by the ``main()``
orchestration at the bottom of this file, which is what the tracked entry
points actually invoke.

Config boundary (docs/32 "Scope and ownership"): this module never writes
target-repository configuration. ``target_configuration_writer`` is the
shared service function itself -- there is no parallel writer here, and no
``dashboard.local.yaml`` is ever created. Dashboard process settings
(loopback host, port, Dashboard SQLite path, Draindeck executable path)
are constructed in memory from explicit launcher arguments/CLI flags only.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from runtime.init.service import apply_target_configuration

from .launcher_lock import LauncherLockTimeout, launcher_operation_lock  # noqa: F401 -- re-exported public API
from .launcher_install import (  # noqa: F401 -- re-exported public API
    InstallResult,
    ManualLinuxInstallRequiredError,
    PlatformInstaller,
    Prerequisite,
    ResumeResult,
    UnsupportedPlatformError,
    clear_install_state,
    dashboard_deps_present,
    default_dashboard_deps_installer,
    default_install_state_path,
    detect_missing_prerequisites,
    install_command_for,
    install_missing_prerequisites,
    load_install_state,
    prompt_consent,
    prompt_model_pull_consent,
    pull_ollama_model,
    real_package_manager_adapter,
    render_prerequisite_manifest,
    resume_partial_install,
    save_install_state,
    select_platform_installer,
)
from .launcher_readiness import (  # noqa: F401 -- re-exported public API
    ReadinessState,
    RepositoryRunReadiness,
    RunPrerequisiteResult,
    check_reviewer_model_present,
    check_run_prerequisites,
    evaluate_repository_run_readiness,
    readiness_state,
)

# ---------------------------------------------------------------------------
# 1. Target configuration boundary (L-01, L-02)
# ---------------------------------------------------------------------------

# The launcher's ONLY target-configuration write path is the shared service
# function itself -- re-exported, not wrapped, so `target_configuration_writer
# is apply_target_configuration` holds. Never add a second writer here.
target_configuration_writer = apply_target_configuration


# ---------------------------------------------------------------------------
# 2. Owned-process reuse / collision / stop rules (L-07, L-08, L-13)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcessResolution:
    action: str  # "REUSE" | "START_NEW" | "REFUSE_PORT_COLLISION" | "RESTART_STALE_OWNED" | "STARTING_OWNED"
    # Populated only for STARTING_OWNED, so the caller can wait on the
    # exact recorded child without a second state reload: the identity
    # proof and readiness wait still happen against these values, not
    # against blind trust in the PID's mere liveness.
    pid: Optional[int] = None
    token: Optional[str] = None
    started_at_epoch_seconds: Optional[float] = None


def resolve_dashboard_process(
    *,
    recorded_pid: Optional[int],
    port_pid: Optional[int],
    process_alive: Callable[[int], bool],
    health_ok: Callable[[], bool],
    terminate: Callable[[int], None],
) -> ProcessResolution:
    """Decides what to do about the Dashboard's fixed loopback port.

    ``terminate`` is accepted so callers can supply a real stop action, but
    this function itself NEVER calls it -- killing a process is always a
    separate, explicitly authorized step, never a side effect of merely
    resolving what state the port is in (this is what keeps L-08's "never
    kill or trust a foreign process" true even for a process this launcher
    itself previously started but that has since gone unhealthy).
    """
    if port_pid is None:
        return ProcessResolution(action="START_NEW")
    if port_pid == recorded_pid:
        if process_alive(port_pid) and health_ok():
            return ProcessResolution(action="REUSE")
        return ProcessResolution(action="RESTART_STALE_OWNED")
    # Something else is bound to the port. Never kill or trust it, and
    # never open a browser against it (L-08) -- report the collision.
    return ProcessResolution(action="REFUSE_PORT_COLLISION")


# ---------------------------------------------------------------------------
# 3. Exact browser-open readiness contract (L-09)
# ---------------------------------------------------------------------------

def is_browser_open_ready(
    *,
    process_alive: bool,
    port_listening: bool,
    owned: bool,
    health_status: Optional[int],
    health_body: Optional[Mapping[str, str]],
) -> bool:
    """True only when every readiness witness holds: the launcher-owned
    process is alive, the expected loopback port is listening, ownership
    is proven (not merely a port that happens to answer), and
    ``GET /api/health`` returns exactly HTTP 200 with
    ``{"status": "ok"}``. Never returns True unconditionally.
    """
    return bool(
        process_alive
        and port_listening
        and owned
        and health_status == 200
        and health_body == {"status": "ok"}
    )


# ---------------------------------------------------------------------------
# 4. Fast-path timing contract (L-11), injectable-clock wait
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FastPathContract:
    deadline_seconds: float
    browser_open_required: bool

    def within_budget(self, elapsed_seconds: float) -> bool:
        return elapsed_seconds <= self.deadline_seconds


def fast_path_contract() -> FastPathContract:
    """The dependency-present fast path's measured contract: verified
    Dashboard-ready browser-open within 180 seconds. Cold install carries
    no completion-time promise -- only the fast path is timed.
    """
    return FastPathContract(deadline_seconds=180.0, browser_open_required=True)


def _is_within_startup_grace(started_at_epoch_seconds: Optional[float], *, now: float) -> bool:
    """True only for a FRESH startup-generation timestamp (independent-
    review finding, duplicate-start race): a legacy record with no
    timestamp at all, or one whose generation has already expired, must
    never be treated as a still-starting owned process. Trusting either
    would let a stale record either block startup forever or let an
    unrelated PID's mere liveness stand in for real Dashboard readiness
    proof. Bounded by the SAME 180s contract as the fast-path readiness
    wait -- deliberately not a separate, unrelated timeout.
    """
    if started_at_epoch_seconds is None:
        return False
    age = now - started_at_epoch_seconds
    return 0.0 <= age <= fast_path_contract().deadline_seconds


# A short, bounded wait for a stale owned process's port to actually be
# released before spawning its replacement (docs/32 review Blocker 9):
# SIGTERM is asynchronous, especially on POSIX, so terminating and
# immediately Popen-ing a replacement could race the old process's own
# socket teardown. This deadline is intentionally far shorter than the
# 180s fast-path contract -- a plain process exit releasing its own
# listening socket is expected to be near-instant, not a slow bootstrap.
STALE_PORT_RELEASE_DEADLINE_SECONDS = 5.0
STALE_PORT_RELEASE_POLL_SECONDS = 0.1

# How long `main()` waits to acquire the launcher-operation lock (docs/32
# review Blocker 9) before reporting LAUNCH_IN_PROGRESS. A module-level
# constant (rather than a literal at the call site) so tests can shrink it
# to keep a genuine-contention regression test fast and deterministic.
LAUNCHER_LOCK_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class WaitResult:
    ready: bool
    elapsed_seconds: float


def wait_for_readiness(
    *,
    check: Callable[[], bool],
    clock: Callable[[], float],
    deadline_seconds: float,
    poll_interval: Callable[[], None] = lambda: None,
) -> WaitResult:
    """Polls ``check`` until it returns True or ``deadline_seconds`` (per
    ``clock``) elapses. ``clock`` and ``poll_interval`` are injected so
    tests drive this with a fake, instantly-advancing clock instead of a
    real 180-second sleep.
    """
    start = clock()
    while True:
        if check():
            return WaitResult(ready=True, elapsed_seconds=clock() - start)
        elapsed = clock() - start
        if elapsed > deadline_seconds:
            return WaitResult(ready=False, elapsed_seconds=elapsed)
        poll_interval()


# ---------------------------------------------------------------------------
# 5. Argv-only process construction (L-12) and real (non-injected) probes
# ---------------------------------------------------------------------------

def build_dashboard_argv(
    *,
    python_executable: str,
    host: str,
    port: int,
    db_path: str,
    observer_executable: str,
    instance_token: str,
) -> list[str]:
    """An argv VECTOR only -- never a shell string. A path or repo-derived
    value containing shell metacharacters cannot be reinterpreted because
    nothing here is ever passed through a shell (L-12).
    """
    return [
        python_executable, "-m", "draindeck_dashboard.cli",
        "--host", host,
        "--port", str(port),
        "--db-path", db_path,
        "--observer-executable", observer_executable,
        "--instance-token", instance_token,
    ]


def _is_usable_observer_executable(path: Path, *, platform: str) -> bool:
    """The single "usable observer executable" predicate, shared by explicit
    ``--observer-executable`` validation and auto-resolution's sibling/PATH
    fallback (independent-review finding): these two paths previously
    diverged -- explicit validation required the POSIX executable
    permission bit, but auto-resolution accepted any ``sibling.is_file()``
    -- so a non-executable ``.venv/bin/draindeck`` could be auto-selected
    and only fail later, during a real spawn/runtime operation.

    Requires an existing regular file; on POSIX, additionally requires the
    executable permission bit (Windows has no such bit to check).
    """
    if not path.is_file():
        return False
    if platform != "win32" and not os.access(path, os.X_OK):
        return False
    return True


def resolve_observer_executable(
    *,
    platform: str,
    python_executable: str,
    which: Callable[[str], Optional[str]] = shutil.which,
) -> Optional[str]:
    """Resolves the Draindeck console-script executable for the spawned
    Dashboard child (independent-review finding). The tracked wrapper
    scripts invoke the venv Python directly without activating the venv,
    so a bare ``"draindeck"`` is commonly absent from PATH even though the
    console script exists right beside that same interpreter --
    ``DashboardConfig`` requires ``observer_executable`` to be absolute, so
    a relative fallback previously made the spawned child exit immediately
    on a config error while the parent still waited out the full
    180-second readiness window.

    Resolution order: (1) the sibling console script beside
    ``python_executable`` (Windows: ``draindeck.exe``; macOS/Linux:
    ``draindeck``); (2) ``which("draindeck")``, ONLY when it resolves to an
    absolute path. Either candidate must also pass
    ``_is_usable_observer_executable`` -- the SAME usability check explicit
    values are held to -- so a present-but-non-executable sibling or PATH
    result is rejected here too, not just for explicit values. Returns
    ``None`` -- never a bare relative ``"draindeck"`` or an unusable file --
    when nothing resolves, so the caller can fail clearly before ever
    spawning the child.
    """
    sibling_name = "draindeck.exe" if platform == "win32" else "draindeck"
    sibling = Path(python_executable).parent / sibling_name
    if _is_usable_observer_executable(sibling, platform=platform):
        return str(sibling.resolve())

    found = which("draindeck")
    if (
        found is not None
        and Path(found).is_absolute()
        and _is_usable_observer_executable(Path(found), platform=platform)
    ):
        return found

    return None


def validate_explicit_observer_executable(path: str, *, platform: str) -> bool:
    """Validates an operator-supplied ``--observer-executable`` value
    before it is ever handed to the spawned Dashboard child
    (independent-review finding): an explicit flag previously bypassed
    ``resolve_observer_executable`` entirely, so a relative or
    nonexistent value reached ``Popen`` unchanged -- ``DashboardConfig``
    requires an absolute, real ``observer_executable``, so the child
    would exit immediately while the parent still waited out the full
    180-second readiness window.

    Accepts only an absolute path that also passes
    ``_is_usable_observer_executable`` -- the same predicate
    ``resolve_observer_executable`` applies to its own sibling/PATH
    candidates. Never rewrites ``path`` -- only reports whether it is safe
    to pass through unchanged.
    """
    p = Path(path)
    if not p.is_absolute():
        return False
    return _is_usable_observer_executable(p, platform=platform)


def is_process_alive(pid: int) -> bool:
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, shell=False,
        )
        return f'"{pid}"' in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def probe_health(host: str, port: int, timeout: float = 2.0):
    """Returns (status_code, body) for ``GET /api/health``, or
    (None, None) on any connection failure -- a down/unreachable process is
    simply not-ready, never an exception the caller must special-case."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, OSError):
        return None, None


def probe_identity(host: str, port: int, timeout: float = 2.0) -> Optional[str]:
    """Returns the running Dashboard's instance token via
    ``GET /api/launcher/identity``, or None if unreachable/absent. This is
    the ownership proof used to distinguish a launcher-owned process from a
    foreign one answering the same port (L-08, L-13)."""
    try:
        url = f"http://{host}:{port}/api/launcher/identity"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("instanceToken")
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, OSError):
        return None


def is_port_listening(host: str, port: int, timeout: float = 1.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def generate_instance_token() -> str:
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# 6. Launcher-owned state record (operational state, never a config file)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LauncherState:
    pid: int
    port: int
    host: str
    instance_token: str
    # Startup-generation timestamp (independent-review finding, duplicate-
    # start race): set only when THIS record was written immediately after
    # a real Popen, so a later invocation can tell "this PID is a fresh
    # child that just hasn't bound its port yet" from "this is an old/
    # legacy record that happens to name a still-alive PID." ``None`` for
    # any record written before this field existed -- a legacy record must
    # never be treated as a fresh startup generation (see
    # ``_is_within_startup_grace``).
    started_at_epoch_seconds: Optional[float] = None


def load_launcher_state(state_path: Path) -> Optional[LauncherState]:
    if not state_path.is_file():
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        started_at = raw.get("startedAtEpochSeconds")
        return LauncherState(
            pid=int(raw["pid"]), port=int(raw["port"]),
            host=str(raw["host"]), instance_token=str(raw["instanceToken"]),
            started_at_epoch_seconds=float(started_at) if started_at is not None else None,
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_launcher_state(state_path: Path, state: LauncherState) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": state.pid, "port": state.port, "host": state.host,
        "instanceToken": state.instance_token,
    }
    if state.started_at_epoch_seconds is not None:
        payload["startedAtEpochSeconds"] = state.started_at_epoch_seconds
    state_path.write_text(json.dumps(payload), encoding="utf-8")


def stop_dashboard(
    *,
    state: Optional[LauncherState],
    identity_probe: Callable[[str, int], Optional[str]],
    terminate: Callable[[int], None],
) -> str:
    """Stops only a PID this launcher can PROVE it owns (L-13): the
    running process's identity token, fetched fresh, must match the
    recorded one before ``terminate`` is ever called.
    """
    if state is None:
        return "NOT_RUNNING"
    live_token = identity_probe(state.host, state.port)
    if live_token != state.instance_token:
        return "REFUSE_UNVERIFIED_OWNERSHIP"
    terminate(state.pid)
    return "STOPPED"


# ---------------------------------------------------------------------------
# 7. Orchestration entry point (invoked by the tracked entry-point scripts)
# ---------------------------------------------------------------------------

def default_state_path() -> Path:
    home = Path(os.environ.get("DRAINDECK_DASHBOARD_HOME", Path.home() / ".draindeck-dashboard"))
    return home / "launcher-state.json"


def default_db_path() -> str:
    home = Path(os.environ.get("DRAINDECK_DASHBOARD_HOME", Path.home() / ".draindeck-dashboard"))
    return str(home / "dashboard.sqlite3")


def default_lock_path() -> Path:
    """Operational lock state only (docs/32 review Blocker 9) -- never a
    config file, and never `dashboard.local.yaml` or target-repository
    `.draindeck/config.local.yaml`."""
    home = Path(os.environ.get("DRAINDECK_DASHBOARD_HOME", Path.home() / ".draindeck-dashboard"))
    return home / "launcher.lock"


def terminate_process(pid: int) -> None:
    """Argv-only process termination (L-12) -- never a shell string."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], shell=False, capture_output=True)
    else:
        import signal
        os.kill(pid, signal.SIGTERM)


def _cmd_status(state_path: Path) -> int:
    state = load_launcher_state(state_path)
    if state is None:
        print(json.dumps({"status": "NOT_RUNNING"}))
        return 0
    owned = probe_identity(state.host, state.port) == state.instance_token
    health_status, health_body = probe_health(state.host, state.port)
    ready = is_browser_open_ready(
        process_alive=is_process_alive(state.pid),
        port_listening=is_port_listening(state.host, state.port),
        owned=owned, health_status=health_status, health_body=health_body,
    )
    print(json.dumps({
        "status": "READY" if ready else "NOT_READY",
        "pid": state.pid, "port": state.port, "owned": owned,
    }))
    return 0


def _cmd_stop(state_path: Path) -> int:
    # L-13: acts ONLY on a PID this launcher can prove it owns, via a fresh
    # identity-token round-trip -- never a raw PID kill.
    state = load_launcher_state(state_path)
    result = stop_dashboard(state=state, identity_probe=probe_identity, terminate=terminate_process)
    print(result)
    if result == "STOPPED":
        try:
            state_path.unlink()
        except OSError:
            pass
        return 0
    return 0 if result == "NOT_RUNNING" else 1


def combined_prerequisite_adapter(installer: PlatformInstaller) -> Callable[[str], None]:
    """The one real adapter used for both a fresh install and a resumed
    partial install (independent-review finding): routes "dashboard-deps"
    to the dedicated local pip adapter -- the OS package manager has no
    such package and ``install_command_for`` raises ``ValueError`` for it
    -- and every other missing item to the real, argv-only OS
    package-manager adapter. ``_ensure_prerequisites`` uses this SAME
    adapter on both the fresh-install and resume-from-partial-state paths,
    so a prior dashboard-deps failure resumes through the pip adapter,
    never the package manager.
    """
    package_manager_install = real_package_manager_adapter(installer)
    pip_install = default_dashboard_deps_installer()

    def _install(item: str) -> None:
        if item == "dashboard-deps":
            pip_install(item)
        else:
            package_manager_install(item)

    return _install


def _ensure_prerequisites(args) -> bool:
    """Detect -> show ONE manifest -> require per-invocation consent ->
    install (docs/32 review Blocker 1). Returns True only when it is safe
    to proceed to starting the Dashboard: everything was already present,
    or consent was given and every missing item installed successfully.

    Declining consent (default: No) makes zero package-manager, pip, or
    model-puller calls -- this function returns before any of them are
    even constructed. The reviewer model itself is NOT part of this
    generic flow (it is per-repository, checked and pulled separately --
    see ``--pull-model`` and Blocker 2's readiness endpoint). An item with
    no vendor-verifiable Linux install path (Blocker 6) is still shown in
    the manifest with manual instructions, but a decline/failure on it is
    reported through the same INSTALL_FAILED/resume machinery as any other
    step -- it never silently succeeds and never runs an unverified script.
    """
    try:
        installer = select_platform_installer(sys.platform)
    except UnsupportedPlatformError as exc:
        print(f"UNSUPPORTED_PLATFORM: {exc}", file=sys.stderr)
        return False

    missing = detect_missing_prerequisites(
        installer=installer,
        git_present=shutil.which("git") is not None,
        claude_present=shutil.which("claude") is not None,
        ollama_present=shutil.which("ollama") is not None,
        dashboard_deps_present=dashboard_deps_present(),
    )
    if not missing:
        return True

    state_path = default_install_state_path()
    persisted = load_install_state(state_path)
    to_show = (
        [p for p in missing if p.name in set(persisted["remaining"])] if persisted is not None
        else list(missing)
    )

    consent = args.yes or prompt_consent(render_prerequisite_manifest(to_show))
    if not consent:
        print("CONSENT_DECLINED", file=sys.stderr)
        return False

    adapter = combined_prerequisite_adapter(installer)

    if persisted is not None:
        resume_result = resume_partial_install(state=persisted, installer=adapter)
        if resume_result.failed_step is not None:
            remaining_from = persisted["remaining"]
            failed_idx = remaining_from.index(resume_result.failed_step)
            save_install_state(
                state_path, completed=resume_result.completed, remaining=remaining_from[failed_idx:],
            )
            print(
                f"INSTALL_FAILED at step {resume_result.failed_step!r}; completed so far: "
                f"{list(resume_result.completed)}. Rerun to resume.", file=sys.stderr,
            )
            return False
        clear_install_state(state_path)
        return True

    names = [p.name for p in missing]
    install_result = install_missing_prerequisites(
        missing=names, consent=True, package_manager=adapter,
        model_puller=lambda item: None, server_starter=lambda item: None,
    )
    if install_result.status == "INSTALL_FAILED":
        failed_idx = names.index(install_result.failed_step)
        save_install_state(state_path, completed=install_result.completed, remaining=names[failed_idx:])
        print(
            f"INSTALL_FAILED at step {install_result.failed_step!r}; completed so far: "
            f"{list(install_result.completed)}. Rerun to resume.", file=sys.stderr,
        )
        return False
    clear_install_state(state_path)
    return True


def _cmd_pull_model(model: str, *, yes: bool) -> int:
    """Separate, explicit consent step for the (potentially large) Ollama
    reviewer-model download -- never folded into ``_ensure_prerequisites``.
    """
    consent = yes or prompt_model_pull_consent(model)
    if not consent:
        print("CONSENT_DECLINED", file=sys.stderr)
        return 1
    try:
        pull_ollama_model(model)
    except Exception as exc:
        print(f"MODEL_PULL_FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"MODEL_PULLED: {model}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Real orchestration used by the tracked entry points. Kept thin and
    imperative on purpose -- every decision it makes delegates to a pure,
    unit-tested function above; this function only wires real I/O
    (network probes, subprocess, the filesystem state record, and the
    browser) around those decisions.
    """
    import argparse

    ap = argparse.ArgumentParser(prog="draindeck-dashboard-launcher")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8420)
    ap.add_argument("--db-path", default=None)
    ap.add_argument(
        "--observer-executable", default=None,
        help="absolute path to the draindeck executable; auto-resolved when omitted",
    )
    ap.add_argument("--yes", action="store_true", help="affirmative consent for this invocation")
    ap.add_argument("--stop", action="store_true", help="stop a launcher-owned Dashboard, if any")
    ap.add_argument("--status", action="store_true", help="report launcher-owned Dashboard status")
    ap.add_argument(
        "--pull-model", default=None, metavar="MODEL",
        help="pull an Ollama reviewer model (separate explicit consent; may be large)",
    )
    args = ap.parse_args(argv)

    state_path = default_state_path()
    if args.status:
        return _cmd_status(state_path)
    if args.stop:
        return _cmd_stop(state_path)
    if args.pull_model:
        return _cmd_pull_model(args.pull_model, yes=args.yes)

    # Phase A -- a SHORT lock-scoped decision: load state, check port/
    # identity, and decide reuse / foreign collision / start / stale-owned
    # restart (docs/32 review Blocker 9, independent-review narrowing). A
    # real OS-held exclusive lock, not a stale-prone "lock file exists"
    # convention, ensures two concurrent launcher invocations (e.g. a
    # double-clicked shortcut) can never both conclude the port is free at
    # the same instant. This never kills anything to acquire it --
    # contention fails clearly and safely instead. The lock is released
    # again immediately after this decision: it is NEVER held across
    # `_ensure_prerequisites` (interactive consent, package/model
    # installation) or the 180s browser-readiness wait below, both of which
    # can run for a long time and must not block a second, unrelated
    # launcher invocation from even checking the Dashboard's current state.
    try:
        with launcher_operation_lock(default_lock_path(), timeout_seconds=LAUNCHER_LOCK_TIMEOUT_SECONDS):
            decision = _decide_dashboard_action(args, state_path)
    except LauncherLockTimeout as exc:
        print(f"LAUNCH_IN_PROGRESS: {exc}", file=sys.stderr)
        return 1

    if decision.action == "REFUSE_PORT_COLLISION":
        print(
            f"REFUSE_PORT_COLLISION: {args.host}:{args.port} is occupied by a process "
            "this launcher does not own. Not starting a duplicate Dashboard and not "
            "opening a browser.", file=sys.stderr,
        )
        return 1

    if decision.action == "REUSE":
        print(f"Reusing healthy launcher-owned Dashboard at http://{args.host}:{args.port}")
        webbrowser.open(f"http://{args.host}:{args.port}")
        return 0

    if decision.action == "STARTING_OWNED":
        # A fresh, launcher-owned child is already Popen'd and hasn't
        # bound its port yet (independent-review finding, duplicate-start
        # race) -- never treated as START_NEW. Wait for it, bounded and
        # outside the lock; never spawn a second child or run prerequisite
        # bootstrapping for this invocation.
        return _finish_starting_owned(
            args, pid=decision.pid, token=decision.token,
            started_at_epoch_seconds=decision.started_at_epoch_seconds,
        )

    # Only START_NEW/RESTART_STALE_OWNED reach here -- a healthy owned
    # process is already reused above, and a collision already refused,
    # neither of which needs (or should be slowed or blocked by) a fresh
    # prerequisite/consent check. Bootstrapping runs OUTSIDE the lock: it
    # can prompt, install packages, and take a long time, and must never
    # make a second, unrelated launcher invocation wait behind it.
    if not _ensure_prerequisites(args):
        return 1

    # Resolve the observer executable BEFORE spawning, also outside the
    # lock -- a bare relative "draindeck" passed to the child fails
    # DashboardConfig's absolute-path requirement, so the child exits
    # immediately while the parent would otherwise still wait out the full
    # 180-second readiness window for a process that could never become
    # ready (independent-review finding). An explicit --observer-executable
    # always wins over auto-resolution.
    observer_executable = _resolve_observer_executable_for_launch(args)
    if observer_executable is None:
        return 1

    db_path = args.db_path or default_db_path()

    # Phase B -- reacquire the SAME short lock and fully re-evaluate
    # state/port/ownership immediately before any stale-process termination
    # or Popen (docs/32 review Blocker 9, independent-review narrowing):
    # another launcher invocation may have already started a healthy owned
    # Dashboard while prerequisites ran above -- that must be reused, never
    # duplicated. Only the final lock holder terminates a stale owned
    # process, waits for its port to release, spawns, and persists the new
    # launcher state. The lock is released again immediately after that --
    # the child's browser-readiness wait and the browser open below both
    # run outside it.
    try:
        with launcher_operation_lock(default_lock_path(), timeout_seconds=LAUNCHER_LOCK_TIMEOUT_SECONDS):
            spawn = _spawn_dashboard_under_lock(args, state_path, db_path, observer_executable)
    except LauncherLockTimeout as exc:
        print(f"LAUNCH_IN_PROGRESS: {exc}", file=sys.stderr)
        return 1

    if spawn.action == "REFUSE_PORT_COLLISION":
        print(
            f"REFUSE_PORT_COLLISION: {args.host}:{args.port} is occupied by a process "
            "this launcher does not own. Not starting a duplicate Dashboard and not "
            "opening a browser.", file=sys.stderr,
        )
        return 1

    if spawn.action == "REUSE":
        # Another launcher invocation already started (and this one proved
        # healthy) while this invocation was busy with prerequisites above.
        print(f"Reusing healthy launcher-owned Dashboard at http://{args.host}:{args.port}")
        webbrowser.open(f"http://{args.host}:{args.port}")
        return 0

    if spawn.action == "STARTING_OWNED":
        # Another launcher invocation Popen'd a fresh child while this one
        # ran prerequisites -- reuse it once it proves ready, never spawn a
        # second one.
        return _finish_starting_owned(
            args, pid=spawn.pid, token=spawn.token,
            started_at_epoch_seconds=spawn.started_at_epoch_seconds,
        )

    if spawn.action == "STALE_PORT_NOT_RELEASED":
        print(
            f"STALE_PORT_NOT_RELEASED: {args.host}:{args.port} was still listening "
            f"{spawn.stale_elapsed_seconds:.1f}s after terminating the stale owned "
            f"process (pid {spawn.stale_pid}). Not starting a replacement and not "
            "opening a browser.", file=sys.stderr,
        )
        return 1

    # spawn.action == "SPAWNED": the lock is already released. Wait for the
    # newly-spawned child to become ready, and open the browser, both
    # outside the lock -- a long wait here must never block any other
    # launcher invocation from observing this now-owned Dashboard.
    contract = fast_path_contract()

    def _ready() -> bool:
        status, body = probe_health(args.host, args.port)
        owned = probe_identity(args.host, args.port) == spawn.token
        return is_browser_open_ready(
            process_alive=is_process_alive(spawn.pid),
            port_listening=is_port_listening(args.host, args.port),
            owned=owned, health_status=status, health_body=body,
        )

    result = wait_for_readiness(
        check=_ready, clock=time.monotonic, deadline_seconds=contract.deadline_seconds,
        poll_interval=lambda: time.sleep(0.5),
    )
    if not result.ready:
        print(
            f"Dashboard did not become ready within {contract.deadline_seconds}s "
            f"(waited {result.elapsed_seconds:.1f}s). Not opening a browser.",
            file=sys.stderr,
        )
        return 1

    webbrowser.open(f"http://{args.host}:{args.port}")
    return 0


def _decide_dashboard_action(args, state_path: Path) -> ProcessResolution:
    """Phase A: the SHORT lock-scoped read-only decision -- load launcher
    state, check port occupancy/ownership, and decide reuse / foreign
    collision / start / stale-owned restart. Run under
    ``launcher_operation_lock`` by ``main()``; never terminates or spawns
    anything itself (docs/32 review Blocker 9, independent-review
    narrowing).
    """
    existing = load_launcher_state(state_path)
    return _resolve_process_action(args, existing)


def _resolve_process_action(args, existing: Optional[LauncherState]) -> ProcessResolution:
    """Ownership of whatever is on the port is decided by the identity-token
    proof, never by raw PID matching (a PID can be reused by an unrelated
    process). Only when the live identity token round-trips back exactly
    what this launcher recorded do we treat the occupant as `existing.pid`
    -- otherwise it's a sentinel PID that can never equal `recorded_pid`, so
    an unverified occupant always resolves to REFUSE_PORT_COLLISION. Shared
    by both lock phases so Phase B's re-evaluation applies the exact same
    rule as Phase A's initial one.

    Checked BEFORE that: the normal startup window (independent-review
    finding, duplicate-start race) -- a freshly-Popen'd, still-alive child
    that simply hasn't bound its port yet reads as `port_pid=None` to
    ``resolve_dashboard_process`` below, which would otherwise report
    START_NEW and let a second invocation spawn a duplicate. Only a record
    with a FRESH startup-generation timestamp (``_is_within_startup_grace``)
    is trusted for this -- an expired or legacy (no-timestamp) record falls
    straight through to the normal port/identity logic below instead,
    which never kills or trusts an unrelated PID and simply proceeds to a
    normal start.

    Also required (independent-review finding, endpoint-mismatch): the
    recorded state's own ``host``/``port`` must match the REQUESTED
    ``args.host``/``args.port`` exactly. Without this, a live, fresh
    record for one endpoint (e.g. still starting on 127.0.0.1:9000) would
    make an unrelated request for a different, genuinely free endpoint
    (e.g. 127.0.0.1:8420) wait on that unrelated PID instead of starting
    normally -- the recorded PID never belongs to the requested endpoint
    in that case, so it must never be trusted, waited on, or terminated
    on this request's behalf.
    """
    port_listening = is_port_listening(args.host, args.port)
    if (
        not port_listening
        and existing is not None
        and existing.host == args.host
        and existing.port == args.port
        and is_process_alive(existing.pid)
        and _is_within_startup_grace(existing.started_at_epoch_seconds, now=time.time())
    ):
        return ProcessResolution(
            action="STARTING_OWNED", pid=existing.pid, token=existing.instance_token,
            started_at_epoch_seconds=existing.started_at_epoch_seconds,
        )

    _UNVERIFIED_OCCUPANT_PID = -1
    if not port_listening:
        observed_port_pid = None
    elif existing is not None and probe_identity(args.host, args.port) == existing.instance_token:
        observed_port_pid = existing.pid
    else:
        observed_port_pid = _UNVERIFIED_OCCUPANT_PID

    return resolve_dashboard_process(
        recorded_pid=existing.pid if existing else None,
        port_pid=observed_port_pid,
        process_alive=is_process_alive,
        health_ok=lambda: probe_health(args.host, args.port) == (200, {"status": "ok"}),
        terminate=lambda pid: None,
    )


def _resolve_observer_executable_for_launch(args) -> Optional[str]:
    """Resolves (or validates an explicit) observer executable, printing
    the same diagnostics this always has on failure. Runs outside both lock
    phases -- a pure local filesystem check, never a network probe or
    process action on the shared Dashboard port.
    """
    observer_executable = args.observer_executable
    if observer_executable is None:
        observer_executable = resolve_observer_executable(
            platform=sys.platform, python_executable=sys.executable,
        )
        if observer_executable is None:
            print(
                "OBSERVER_EXECUTABLE_NOT_FOUND: could not locate the draindeck "
                "console script beside this Python interpreter or on PATH. "
                "Reinstall with `pip install -e .` or pass "
                "--observer-executable explicitly.", file=sys.stderr,
            )
            return None
        return observer_executable

    if not validate_explicit_observer_executable(observer_executable, platform=sys.platform):
        # An explicit value is never silently rewritten -- it is reported
        # back to the operator verbatim so they can see exactly what they
        # passed, then either fix it or omit the flag to auto-resolve.
        executable_note = " executable" if sys.platform != "win32" else ""
        print(
            f"OBSERVER_EXECUTABLE_INVALID: {observer_executable!r} is not usable as "
            f"--observer-executable (must be an absolute path to an existing{executable_note} "
            "file). Provide a valid absolute path, or omit the flag to auto-resolve it.",
            file=sys.stderr,
        )
        return None
    return observer_executable


def _wait_for_starting_owned(
    args, *, pid: int, token: str, started_at_epoch_seconds: Optional[float],
) -> WaitResult:
    """Bounded, outside-either-lock wait for a fresh, launcher-owned child
    that has already been Popen'd (by this invocation's own earlier phase,
    or by a concurrent launcher invocation) but had not yet bound its port
    (independent-review finding, duplicate-start race). Proves readiness
    via the exact same identity-token + health witnesses as a normal spawn
    (``is_browser_open_ready``) -- never calls Popen or terminates anything.

    Bounded by the REMAINING startup grace time, not a fresh full 180s:
    the deadline is anchored to when the child was actually Popen'd, so
    repeated launcher invocations during the same startup can't each reset
    the clock and wait far longer, in aggregate, than the fast-path
    contract promises.
    """
    grace = fast_path_contract().deadline_seconds
    elapsed_already = (
        0.0 if started_at_epoch_seconds is None
        else max(0.0, time.time() - started_at_epoch_seconds)
    )
    remaining = max(0.0, grace - elapsed_already)

    def _ready() -> bool:
        status, body = probe_health(args.host, args.port)
        owned = probe_identity(args.host, args.port) == token
        return is_browser_open_ready(
            process_alive=is_process_alive(pid),
            port_listening=is_port_listening(args.host, args.port),
            owned=owned, health_status=status, health_body=body,
        )

    return wait_for_readiness(
        check=_ready, clock=time.monotonic, deadline_seconds=remaining,
        poll_interval=lambda: time.sleep(0.5),
    )


def _finish_starting_owned(
    args, *, pid: int, token: str, started_at_epoch_seconds: Optional[float],
) -> int:
    """Shared tail for a STARTING_OWNED outcome from EITHER lock phase:
    waits (bounded, outside any lock) for the already-Popen'd, not-yet-
    proven child to become verifiably ready, then reuses it. Never spawns a
    duplicate and never kills anything on this path (independent-review
    finding, duplicate-start race).
    """
    result = _wait_for_starting_owned(
        args, pid=pid, token=token, started_at_epoch_seconds=started_at_epoch_seconds,
    )
    if not result.ready:
        print(
            f"DASHBOARD_STARTING_TIMEOUT: a launcher-owned Dashboard at "
            f"{args.host}:{args.port} (pid {pid}) was starting but never became "
            f"verifiably ready within {result.elapsed_seconds:.1f}s. Not spawning "
            "a duplicate and not opening a browser.", file=sys.stderr,
        )
        return 1

    print(f"Reusing healthy launcher-owned Dashboard at http://{args.host}:{args.port}")
    webbrowser.open(f"http://{args.host}:{args.port}")
    return 0


@dataclass(frozen=True)
class _SpawnOutcome:
    action: str  # "REUSE" | "REFUSE_PORT_COLLISION" | "STALE_PORT_NOT_RELEASED" | "STARTING_OWNED" | "SPAWNED"
    pid: Optional[int] = None
    token: Optional[str] = None
    stale_pid: Optional[int] = None
    stale_elapsed_seconds: Optional[float] = None
    started_at_epoch_seconds: Optional[float] = None


def _spawn_dashboard_under_lock(
    args, state_path: Path, db_path: str, observer_executable: str,
) -> _SpawnOutcome:
    """Phase B: the SHORT lock-scoped act critical section -- re-evaluate
    state/port/ownership from scratch (another launcher invocation may have
    started a healthy owned Dashboard, or one that is still starting, while
    this one ran prerequisites), then terminate a proven-stale owned
    process, wait for its port to release, spawn the replacement, and
    persist the new launcher state. Run under ``launcher_operation_lock``
    by ``main()``; the bounded stale-port-release wait stays inside this
    lock because it protects the start transition, but the child's own
    180s readiness wait (and the STARTING_OWNED wait) do NOT -- both happen
    in ``main()``, after this lock is released.
    """
    existing = load_launcher_state(state_path)
    resolution = _resolve_process_action(args, existing)

    if resolution.action == "REFUSE_PORT_COLLISION":
        return _SpawnOutcome(action="REFUSE_PORT_COLLISION")
    if resolution.action == "REUSE":
        return _SpawnOutcome(action="REUSE")
    if resolution.action == "STARTING_OWNED":
        # Another launcher invocation already Popen'd a fresh child (while
        # this one ran prerequisites) that hasn't proven ready yet -- never
        # spawn a second one; the bounded wait happens in main(), outside
        # this lock.
        return _SpawnOutcome(
            action="STARTING_OWNED", pid=resolution.pid, token=resolution.token,
            started_at_epoch_seconds=resolution.started_at_epoch_seconds,
        )

    if resolution.action == "RESTART_STALE_OWNED":
        # Ownership was already proven above (identity token matched) --
        # safe to stop this launcher's own unhealthy process before
        # starting its replacement on the same port. SIGTERM is
        # asynchronous (especially on POSIX), so wait, bounded, for the
        # port to actually be released before spawning a replacement on it
        # -- never Popen a replacement while the old process might still be
        # holding the socket (docs/32 review Blocker 9).
        terminate_process(existing.pid)
        release = wait_for_readiness(
            check=lambda: not is_port_listening(args.host, args.port),
            clock=time.monotonic,
            deadline_seconds=STALE_PORT_RELEASE_DEADLINE_SECONDS,
            poll_interval=lambda: time.sleep(STALE_PORT_RELEASE_POLL_SECONDS),
        )
        if not release.ready:
            return _SpawnOutcome(
                action="STALE_PORT_NOT_RELEASED",
                stale_pid=existing.pid, stale_elapsed_seconds=release.elapsed_seconds,
            )

    # START_NEW, or a successfully-released RESTART_STALE_OWNED: start
    # exactly one local Dashboard.
    token = generate_instance_token()
    started_at = time.time()
    dashboard_argv = build_dashboard_argv(
        python_executable=sys.executable, host=args.host, port=args.port,
        db_path=db_path, observer_executable=observer_executable,
        instance_token=token,
    )
    proc = subprocess.Popen(dashboard_argv, shell=False)
    save_launcher_state(
        state_path,
        LauncherState(
            pid=proc.pid, port=args.port, host=args.host, instance_token=token,
            started_at_epoch_seconds=started_at,
        ),
    )
    return _SpawnOutcome(action="SPAWNED", pid=proc.pid, token=token, started_at_epoch_seconds=started_at)


if __name__ == "__main__":
    sys.exit(main())
