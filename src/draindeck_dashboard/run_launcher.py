"""ADR-30 decision 4: the safe launcher. Mirrors observer_client.py's
established pattern exactly -- a single configured executable, a fixed argv
vector, ``shell=False``, and the same allowlisted environment -- so this is
the second (not a novel) place the Dashboard reaches outside its own
process. Exactly one child process is spawned per claimed command.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional

from runtime.config import load_config
from runtime.workspace_lease import ControllerIdentityState, WindowsProcessIdentityApi, probe_controller_identity

from .repositories import get_repository
from .run_queue import (
    STATUS_ABNORMAL_EXIT,
    STATUS_CLAIMED,
    STATUS_COMPLETED,
    STATUS_LAUNCHED,
    STATUS_LAUNCH_FAILED,
    claim_next_launchable_command,
    get_command,
    revalidate_claimed_command,
)

# Diagnostics are bounded and never expose environment/secrets (ADR-30
# decision 4 / spec "Safe launcher"): only a capped byte count of stdout/
# stderr, never their content, is ever persisted.
_MAX_DIAGNOSTIC_BYTES = 4096

# This process's own live handles, keyed by command id. A Popen object
# cannot survive a Dashboard restart -- only useful for reconciliation
# within this process's own lifetime; the cross-restart fallback in
# reconcile_launched_command uses PID/creation-time probing instead, exactly
# like the runtime's own orphan detection (runtime.workspace_lease).
_LIVE_PROCESSES: dict[int, "subprocess.Popen"] = {}

# ADR-30 review finding 5: a child producing output larger than the OS pipe
# buffer (~64KB on Windows) must still finish. subprocess.Popen with
# stdout=PIPE/stderr=PIPE only has a bounded kernel buffer for each stream;
# nothing reads it until something calls communicate()/read() -- if that
# only happens once, non-blockingly, after the process has already exited
# (the pre-fix behavior), a still-running child that fills either pipe
# blocks forever on its own write() call, and this Dashboard never notices
# because poll() keeps returning None. A background thread per stream reads
# continuously and discards content, retaining only a running byte count --
# bounded diagnostics need a count, never raw content -- so the pipe is
# always being drained and the child can never block on a full buffer.
_STREAM_COUNTERS: dict[int, tuple["_StreamByteCounter", "_StreamByteCounter"]] = {}


class _StreamByteCounter:
    """Tracks a running byte count for a drained stream and, separately, a
    small bounded head buffer (capped at _MAX_DIAGNOSTIC_BYTES) -- never the
    full content. The head buffer exists only so a bounded, machine-readable
    run-correlation hint (ADR-30 review finding 6; spec "Frozen event
    schema") can be looked for on stdout; it is read once at reconciliation
    time and discarded immediately after -- never persisted, logged, or
    returned as diagnostics itself (see _bounded_diagnostics, which only
    ever exposes the count)."""

    __slots__ = ("bytes_read", "_head", "_lock")

    def __init__(self) -> None:
        self.bytes_read = 0
        self._head = bytearray()
        self._lock = threading.Lock()

    def add(self, chunk: bytes) -> None:
        with self._lock:
            self.bytes_read += len(chunk)
            if len(self._head) < _MAX_DIAGNOSTIC_BYTES:
                self._head += chunk[:_MAX_DIAGNOSTIC_BYTES - len(self._head)]

    def get(self) -> int:
        with self._lock:
            return self.bytes_read

    def get_head(self) -> bytes:
        with self._lock:
            return bytes(self._head)


def _drain_stream(stream, counter: "_StreamByteCounter") -> None:
    """Runs in a daemon thread for the lifetime of the child's stdout/
    stderr pipe. Never persists or returns content beyond the small bounded
    head buffer above -- and never raises into the caller (a read/close
    failure just ends the drain; the OS reclaims the pipe when the process
    exits either way)."""
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            counter.add(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


# ADR-30 review finding 6 / spec "Frozen event schema": runtime.main prints
# this line to stdout immediately after the run-lifecycle-start event is
# durably fsynced -- a bounded correlation HINT only, never trusted on its
# own. The Dashboard
# must confirm the same run_id through the existing observer/indexed
# run_views evidence (see _confirm_correlated_run) before ever persisting
# or exposing it.
_RUN_ID_HINT_PREFIX = "DRAINDECK_RUN_ID="
_RUN_ID_HINT = re.compile(re.escape(_RUN_ID_HINT_PREFIX).encode("ascii") + rb"(\S+)")


def _extract_correlation_hint(stdout_head: bytes) -> Optional[str]:
    match = _RUN_ID_HINT.search(stdout_head)
    if match is None:
        return None
    try:
        return match.group(1).decode("ascii")
    except UnicodeDecodeError:
        return None


def _confirm_correlated_run(conn: sqlite3.Connection, repo_id: int, run_id: str) -> bool:
    """A hint is only ever a hint (spec "Frozen event schema"): confirms the
    run_id through the same observer/indexed run_views + current-generation
    checkpoints join app.py's own _run_metadata_field uses -- never trusted
    from stdout alone, and never confirmed against a stale/rolled-over
    generation."""
    row = conn.execute(
        "SELECT 1 FROM run_views rv JOIN checkpoints c ON c.repository_id = rv.repository_id "
        "AND c.identity_generation_id = rv.identity_generation_id "
        "WHERE rv.repository_id = ? AND rv.run_id = ?",
        (repo_id, run_id),
    ).fetchone()
    return row is not None


def _start_stream_drain(proc: "subprocess.Popen", command_id: int) -> None:
    stdout_counter = _StreamByteCounter()
    stderr_counter = _StreamByteCounter()
    _STREAM_COUNTERS[command_id] = (stdout_counter, stderr_counter)
    threading.Thread(target=_drain_stream, args=(proc.stdout, stdout_counter), daemon=True).start()
    threading.Thread(target=_drain_stream, args=(proc.stderr, stderr_counter), daemon=True).start()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ADR-30 review finding 1: a distinct environment policy for launching a
# full `draindeck run` process. observer_client.build_observer_env's
# allowlist is deliberately minimal for a short-lived, read-only `observe`
# invocation -- correct for that, but it excludes exactly the Windows
# profile/config-discovery variables a real runtime invocation needs to
# find its engine's own config/credentials, and it unconditionally
# denylists ANTHROPIC_API_KEY, which is wrong for engine.auth_mode=api_key
# (ADR-18/CLAUDE.md requires the key to actually reach the engine in that
# mode). build_observer_env itself is untouched and remains observer-only.
_RUNTIME_LAUNCH_ALLOWED_ENV_KEY_NAMES = frozenset({
    "PATH", "SYSTEMROOT", "PATHEXT", "TEMP", "TMP", "WINDIR", "COMSPEC",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "CLAUDE_CONFIG_DIR",
})

_SUBSCRIPTION_CREDENTIAL_DENYLIST = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")


def build_runtime_launch_env(base_env: dict, *, auth_mode: str) -> dict:
    """Builds the child environment for an actual `draindeck run` launch.

    Always an allowlist (never strip-after-inherit): only the OS-required
    keys plus Windows profile/config discovery. ANTHROPIC_API_KEY is carried
    through only for engine.auth_mode="api_key"; for "subscription" it (and
    the other billing/routing credential keys) is explicitly excluded even
    if present in the parent process's own environment -- ADR-18's rule
    that billing/routing credentials must not leak into the engine."""
    env = {
        key: value for key, value in base_env.items()
        if key.upper() in _RUNTIME_LAUNCH_ALLOWED_ENV_KEY_NAMES
    }
    if auth_mode == "api_key":
        for key, value in base_env.items():
            if key.upper() == "ANTHROPIC_API_KEY":
                env[key] = value
    else:
        for credential_key in _SUBSCRIPTION_CREDENTIAL_DENYLIST:
            env.pop(credential_key, None)
    return env


def build_launch_argv(executable: str, *, config_path: str, issues_digest: str,
                      mode: str, issue_ids: Optional[list[str]]) -> list[str]:
    """Every value here is either the server-derived config path or an
    already-validated issue id / digest -- never a browser-supplied
    executable, shell fragment, or arbitrary path (ADR-30 decision 2)."""
    argv = [executable, "run", "--config", config_path, "--issues-digest", issues_digest]
    if mode == "ALL":
        argv.append("--all-issues")
    else:
        for issue_id in (issue_ids or []):
            argv += ["--issue", issue_id]
    return argv


def launch_claimed_command(conn: sqlite3.Connection, command: dict, *, executable: str,
                           config_path: str) -> dict:
    """Spawns exactly one process for an already-CLAIMED command (the claim
    itself, committed by run_queue.claim_next_launchable_command, is the
    durable spawn intent -- persisted before this function is ever called).
    A missing/invalid executable produces a typed LAUNCH_FAILED with no
    fabricated run; the queue slot releases safely either way."""
    argv = build_launch_argv(
        executable, config_path=config_path, issues_digest=command["issuesDigest"],
        mode=command["mode"], issue_ids=command["issueIds"],
    )
    # Config ownership was already revalidated at dequeue time
    # (run_queue.revalidate_claimed_command -> plan_run ->
    # get_configured_issues); reloading here only reads engine.auth_mode,
    # never a second source of truth for the config path itself.
    cfg = load_config(config_path)
    env = build_runtime_launch_env(os.environ, auth_mode=cfg.engine.auth_mode)
    try:
        proc = subprocess.Popen(argv, shell=False, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? WHERE id = ?",
            (STATUS_LAUNCH_FAILED, f"executable could not be started: {exc}", _now(), command["id"]),
        )
        conn.commit()
        return get_command(conn, command["id"])

    try:
        _, creation_time, _ = WindowsProcessIdentityApi().probe(proc.pid)
    except OSError:
        creation_time = None
    _LIVE_PROCESSES[command["id"]] = proc
    _start_stream_drain(proc, command["id"])
    conn.execute(
        "UPDATE run_commands SET status = ?, process_pid = ?, process_creation_time = ? WHERE id = ?",
        (STATUS_LAUNCHED, proc.pid, creation_time, command["id"]),
    )
    conn.commit()
    return get_command(conn, command["id"])


def _bounded_diagnostics(command_id: int) -> dict:
    """Reads the running byte counts the background drain threads have
    accumulated (see _start_stream_drain) -- never calls
    proc.communicate() here, which would only report anything once the
    process has already exited and would otherwise be the same
    read-nothing-until-exit gap this fix closes."""
    counters = _STREAM_COUNTERS.get(command_id)
    if counters is None:
        return {"stdoutBytes": None, "stderrBytes": None}
    stdout_counter, stderr_counter = counters
    return {"stdoutBytes": stdout_counter.get(), "stderrBytes": stderr_counter.get()}


def reconcile_launched_command(conn: sqlite3.Connection, command: dict) -> dict:
    """Checks whether a LAUNCHED command's process has exited, releasing the
    per-repository slot only on a CONFIRMED exit. A normal (exit code 0)
    exit within this process's own lifetime completes cleanly. Any other
    observed exit -- nonzero code, or DEAD-while-unwatched after a Dashboard
    restart (exit code unknowable) -- is conservatively ABNORMAL_EXIT,
    pausing later commands for that repository rather than cascading a
    launch on an uncertain outcome (fail-closed, ADR-30 decision 4). A
    process that is still LIVE, or whose state cannot be determined
    (UNKNOWN), is left exactly as-is -- a lost process handle never implies
    the repository is launchable again."""
    if command["status"] != STATUS_LAUNCHED:
        return command

    proc = _LIVE_PROCESSES.get(command["id"])
    if proc is not None:
        returncode = proc.poll()
        if returncode is None:
            return command  # still running
        _LIVE_PROCESSES.pop(command["id"], None)
        diagnostics = _bounded_diagnostics(command["id"])
        counters = _STREAM_COUNTERS.pop(command["id"], None)

        # ADR-30 review finding 6: a bounded stdout hint is only ever
        # trusted after being confirmed against real observer/indexed
        # evidence -- never persisted otherwise. This never changes
        # `status`, which remains the queue's own process-exit fact, not a
        # runtime workflow outcome (that stays exclusively event-derived,
        # read through the pre-existing /api/repositories/{id}/runs
        # endpoint using this confirmed run_id).
        run_id_correlation = None
        if counters is not None:
            stdout_counter, _stderr_counter = counters
            hint = _extract_correlation_hint(stdout_counter.get_head())
            if hint is not None and _confirm_correlated_run(conn, command["repositoryId"], hint):
                run_id_correlation = hint

        if returncode == 0:
            conn.execute(
                "UPDATE run_commands SET status = ?, finished_at = ?, run_id_correlation = ? WHERE id = ?",
                (STATUS_COMPLETED, _now(), run_id_correlation, command["id"]),
            )
        else:
            conn.execute(
                "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ?, "
                "run_id_correlation = ? WHERE id = ?",
                (STATUS_ABNORMAL_EXIT,
                 f"process exited with code {returncode} (stdout={diagnostics['stdoutBytes']}B, "
                 f"stderr={diagnostics['stderrBytes']}B)",
                 _now(), run_id_correlation, command["id"]),
            )
        conn.commit()
        return get_command(conn, command["id"])

    # No in-memory handle: either a different Dashboard process launched it,
    # or this process restarted since. Probe by PID/creation-time only --
    # the exact same mechanism runtime.workspace_lease uses for orphan
    # detection, never anything Dashboard-specific.
    identity = {"pid": command["processPid"], "creation_time": command["processCreationTime"]}
    result = probe_controller_identity(identity)
    if result.state in (ControllerIdentityState.DEAD, ControllerIdentityState.PID_REUSED):
        conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ? WHERE id = ?",
            (STATUS_ABNORMAL_EXIT,
             "process exited while no Dashboard process was observing it; exit code unknown",
             command["id"]),
        )
        conn.commit()
        return get_command(conn, command["id"])
    return command  # LIVE_MATCH or UNKNOWN: no change


def try_launch_next(conn: sqlite3.Connection, repo_id: int, *, executable: str) -> Optional[dict]:
    """The one orchestration entry point: reconciles any existing LAUNCHED
    command for this repository (releasing its slot on a confirmed exit),
    then claims and launches the next QUEUED command if the repository is
    now free. Called after every successful enqueue, from the explicit
    drain route (an idempotent administrative trigger), and periodically by
    queue_scheduler.QueueDrainScheduler (ADR-30 review finding 4) -- so a
    queue keeps progressing without depending on any of those callers
    actually happening."""
    launched_row = conn.execute(
        "SELECT id FROM run_commands WHERE repository_id = ? AND status = ?",
        (repo_id, STATUS_LAUNCHED),
    ).fetchone()
    if launched_row is not None:
        reconcile_launched_command(conn, get_command(conn, launched_row[0]))

    claimed = claim_next_launchable_command(conn, repo_id)
    if claimed is None:
        return None

    revalidated = revalidate_claimed_command(conn, claimed)
    if revalidated["status"] != STATUS_CLAIMED:
        return revalidated  # became REFUSED or COMPLETED (empty run-all) at dequeue

    registration = get_repository(conn, repo_id)
    return launch_claimed_command(
        conn, revalidated, executable=executable, config_path=registration["configPath"],
    )
