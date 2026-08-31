"""ADR-30 decision 4: the safe launcher. Mirrors observer_client.py's
established pattern exactly -- a single configured executable, a fixed argv
vector, ``shell=False``, and the same allowlisted environment -- so this is
the second (not a novel) place the Dashboard reaches outside its own
process. Exactly one child process is spawned per claimed command.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime, timezone
from typing import Optional

from runtime.workspace_lease import ControllerIdentityState, WindowsProcessIdentityApi, probe_controller_identity

from .observer_client import build_observer_env
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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    env = build_observer_env(os.environ)
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
    conn.execute(
        "UPDATE run_commands SET status = ?, process_pid = ?, process_creation_time = ? WHERE id = ?",
        (STATUS_LAUNCHED, proc.pid, creation_time, command["id"]),
    )
    conn.commit()
    return get_command(conn, command["id"])


def _bounded_diagnostics(proc: "subprocess.Popen") -> dict:
    try:
        out, err = proc.communicate(timeout=0)
    except subprocess.TimeoutExpired:
        return {"stdoutBytes": None, "stderrBytes": None}
    return {"stdoutBytes": len(out or b""), "stderrBytes": len(err or b"")}


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
        diagnostics = _bounded_diagnostics(proc)
        if returncode == 0:
            conn.execute(
                "UPDATE run_commands SET status = ?, finished_at = ? WHERE id = ?",
                (STATUS_COMPLETED, _now(), command["id"]),
            )
        else:
            conn.execute(
                "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? WHERE id = ?",
                (STATUS_ABNORMAL_EXIT,
                 f"process exited with code {returncode} (stdout={diagnostics['stdoutBytes']}B, "
                 f"stderr={diagnostics['stderrBytes']}B)",
                 _now(), command["id"]),
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
    now free. Called after every successful enqueue and from the explicit
    drain route (RED 8's SSE-triggered refresh calls the latter) -- there is
    deliberately no background timer in this pass; see tasks/todo.md RED 6-7
    for the documented scope boundary."""
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
