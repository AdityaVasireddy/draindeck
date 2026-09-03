"""ADR-30 decisions 2-3: run planning + the Dashboard-owned run-command
queue. Queue rows are exclusively Dashboard control-plane state -- never
written to `events.jsonl`, never read by `src/runtime` (RED 0's frozen
architecture gate)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Callable, Optional

from runtime.queue.issues_md import IssueSpec
from runtime.queue.selection import Blocker, TerminalExclusion, plan_run_all, plan_selected
from runtime.workspace_lease import ControllerIdentityState, probe_controller_identity

from .configured_issues import get_configured_issues
from .errors import DashboardApiError, NotFoundError
from .worktree_preflight import WorktreeNotCleanError, WorktreePreflight

# A worktree preflight is injected as a callable(conn, repo_id) -> WorktreePreflight
# (doc 33 Part A). It defaults to None so the queue's own unit suite -- which
# registers fake `.git` directories -- keeps its existing behavior; the API
# layer (app.py) always injects the real, GitCliAdapter-backed probe, so
# backend enforcement is authoritative in production.
WorktreeProbe = Callable[[sqlite3.Connection, int], WorktreePreflight]


class RunPlanError(DashboardApiError):
    pass


class AcknowledgeError(DashboardApiError):
    """Doc 33 Part B: a safe-recovery refusal. Every gate a failed-command
    acknowledgement must clear (status, process ownership, correlated runtime
    outcome, target revalidation) fails closed through this typed error rather
    than releasing the repository on ambiguity."""
    status_code = 409


class CancelError(DashboardApiError):
    """Doc 34: a queue-cancel refusal. Only a command in exact status QUEUED is
    cancelable; every other status fails closed through this typed error with an
    actionable reason, and no state changes."""
    status_code = 409


class IdempotencyKeyReusedError(DashboardApiError):
    status_code = 409

    def __init__(self, message: str = "Idempotency-Key already used with different content",
                **kw) -> None:
        super().__init__("IDEMPOTENCY_KEY_REUSED", message, **kw)


# Control-plane statuses (never runtime workflow states -- ADR-30 decision 3).
STATUS_QUEUED = "QUEUED"
STATUS_CLAIMED = "CLAIMED"
STATUS_LAUNCHED = "LAUNCHED"
STATUS_LAUNCH_FAILED = "LAUNCH_FAILED"
STATUS_LAUNCH_OWNERSHIP_UNKNOWN = "LAUNCH_OWNERSHIP_UNKNOWN"
STATUS_REFUSED = "REFUSED"
STATUS_COMPLETED = "COMPLETED"
STATUS_ABNORMAL_EXIT = "ABNORMAL_EXIT"
# Dashboard-only terminal status (doc 33 Part B): an operator has safely
# acknowledged an ABNORMAL_EXIT command. Never an event, never a runtime
# workflow state -- it only records that the failure was accepted and the
# repository released for a later, freshly-requested command. Deliberately
# NOT in _BLOCKING_STATUSES, so acknowledging unlocks the queue.
STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
# Dashboard-only terminal status (doc 34): an operator safely cancelled a
# still-QUEUED command before it was ever claimed. Never an event, never a
# runtime workflow state -- it only records that a waiting batch was removed.
# Deliberately NOT in _BLOCKING_STATUSES: a cancelled command holds nothing and
# releases nothing, and its queue-position count drops out automatically.
STATUS_CANCELLED = "CANCELLED"

# Statuses that keep a repository closed to a further automatic claim
# (ADR-30 decision 4: an abnormal or ambiguous exit pauses later commands
# for that repository rather than cascading further launches).
_BLOCKING_STATUSES = (
    STATUS_CLAIMED, STATUS_LAUNCHED, STATUS_LAUNCH_OWNERSHIP_UNKNOWN, STATUS_ABNORMAL_EXIT,
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blocker_dict(b: Blocker) -> dict:
    return {"issueId": b.issue_id, "missingDependencyId": b.missing_dependency_id,
            "dependencyState": b.dependency_state}


def _exclusion_dict(e: TerminalExclusion) -> dict:
    return {"issueId": e.issue_id, "state": e.state}


def plan_run(conn: sqlite3.Connection, repo_id: int, *, mode: str,
            issue_ids: Optional[list[str]], expected_issues_digest: str) -> dict:
    """Re-reads configured issues fresh (never cached) and re-validates the
    complete batch through the RED-3 pure planner. Raises RunPlanError only
    for a structural problem (digest conflict, unavailable/inconsistent
    projection); an ordinary admission refusal (unknown/terminal/blocked/
    cyclic/omitted-active) is returned, not raised, so every blocker can be
    reported in one typed response."""
    configured = get_configured_issues(conn, repo_id)  # NotFoundError / ConfiguredIssuesError
    if configured["issuesFileRevision"] != expected_issues_digest:
        raise RunPlanError(
            "ISSUES_REVISION_CONFLICT",
            "the issue file has changed since the digest was computed", status_code=409,
        )
    if configured["readModelStatus"] != "READY":
        raise RunPlanError(
            "PROJECTION_UNAVAILABLE",
            f"event projection is {configured['readModelStatus']}; no runnable "
            f"conclusion is permitted", status_code=409,
        )

    specs = [
        IssueSpec(id=i["issueId"], title=i["title"], body=i["body"],
                 depends_on=i["dependsOn"], acceptance_criteria=i["acceptanceCriteria"])
        for i in configured["issues"]
    ]
    states = {
        i["issueId"]: i["state"] for i in configured["issues"]
        if i["state"] not in ("NOT_INGESTED", "UNAVAILABLE")
    }
    for iid in configured["activeIssuesOutsideFile"]:
        states[iid] = "ACTIVE"

    if mode == "ALL":
        result = plan_run_all(specs, states)
    else:
        result = plan_selected(specs, states, issue_ids or [])

    # ADR-30 review finding 9: explicit, deterministic summary fields so the
    # UI can show a count summary before confirmation, and treat "zero
    # non-terminal issues" as a clean no-op rather than silently returning
    # to an unchanged, unexplained queue view.
    terminal_exclusions = result.excluded if mode == "ALL" else result.terminal_selected
    terminal_counts = {"DONE": 0, "NEEDS_HUMAN": 0, "NEEDS_DECOMPOSITION": 0}
    for exclusion in terminal_exclusions:
        if exclusion.state in terminal_counts:
            terminal_counts[exclusion.state] += 1

    return {
        "ok": result.ok,
        "orderedIds": list(result.ordered_ids),
        "unknownIds": list(result.unknown_ids),
        "duplicateIds": list(result.duplicate_ids),
        "terminalSelected": [_exclusion_dict(t) for t in result.terminal_selected],
        "blockers": [_blocker_dict(b) for b in result.blockers],
        "cycleMembers": list(result.cycle_members),
        "omittedActiveIds": list(result.omitted_active_ids),
        "excluded": [_exclusion_dict(e) for e in result.excluded],
        "emptySelection": result.empty_selection,
        "toRunCount": len(result.ordered_ids),
        "totalTerminalCount": len(terminal_exclusions),
        "terminalCounts": terminal_counts,
    }


def _resolve_runtime_outcome(conn: sqlite3.Connection, repo_id: int,
                             run_id_correlation: Optional[str]) -> Optional[str]:
    """ADR-30 review blocker 1: `run_commands.status` (e.g. COMPLETED) is
    exclusively a process-exit fact -- `runtime.main` documents that both
    the runtime's own COMPLETED and INTERRUPTED outcomes can leave a
    process exit code of 0, so process-exit-0 alone can never be read as
    "the batch completed". The real, event-derived outcome is resolved
    fresh on every read (never persisted, never written to events.jsonl)
    through the same current-generation run_views/checkpoints join
    app.py's `_run_metadata_field` and run_launcher.py's
    `_confirm_correlated_run` already use -- and only once a stdout hint
    has actually been confirmed (`run_id_correlation` is set); an
    unconfirmed or not-yet-finished run correctly resolves to None here,
    the same "no controlled finish observed" case the pre-existing
    event-derived /runs endpoint already renders honestly."""
    if run_id_correlation is None:
        return None
    row = conn.execute(
        "SELECT rv.outcome FROM run_views rv JOIN checkpoints c "
        "ON c.repository_id = rv.repository_id AND c.identity_generation_id = rv.identity_generation_id "
        "WHERE rv.repository_id = ? AND rv.run_id = ?",
        (repo_id, run_id_correlation),
    ).fetchone()
    return row[0] if row is not None else None


def _row_to_command_dict(conn: sqlite3.Connection, row) -> dict:
    (cmd_id, repo_id, mode, issue_ids_json, issues_digest, status, refusal_reason,
     process_pid, process_creation_time, run_id_correlation, created_at, claimed_at,
     finished_at) = row
    position = None
    if status in (STATUS_QUEUED, STATUS_CLAIMED):
        position = conn.execute(
            "SELECT COUNT(*) FROM run_commands WHERE repository_id = ? "
            "AND status IN ('QUEUED','CLAIMED') AND id <= ?",
            (repo_id, cmd_id),
        ).fetchone()[0]
    return {
        "id": cmd_id,
        "repositoryId": repo_id,
        "mode": mode,
        "issueIds": json.loads(issue_ids_json) if issue_ids_json else None,
        "issuesDigest": issues_digest,
        "status": status,
        "refusalReason": refusal_reason,
        "processPid": process_pid,
        "processCreationTime": process_creation_time,
        "queuePosition": position,
        "runIdCorrelation": run_id_correlation,
        "runtimeOutcome": _resolve_runtime_outcome(conn, repo_id, run_id_correlation),
        "createdAt": created_at,
        "claimedAt": claimed_at,
        "finishedAt": finished_at,
    }


_COMMAND_COLUMNS = (
    "id, repository_id, mode, issue_ids_json, issues_digest, status, refusal_reason, "
    "process_pid, process_creation_time, run_id_correlation, created_at, claimed_at, finished_at"
)


def get_command(conn: sqlite3.Connection, command_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_COMMAND_COLUMNS} FROM run_commands WHERE id = ?", (command_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"run command {command_id} not found")
    return _row_to_command_dict(conn, row)


def enqueue_command(conn: sqlite3.Connection, repo_id: int, *, mode: str,
                    issue_ids: Optional[list[str]], expected_issues_digest: str,
                    idempotency_key: str,
                    worktree_probe: Optional[WorktreeProbe] = None) -> dict:
    """Idempotent enqueue. Repeating the same key with identical normalized
    content returns the existing command (or the prior no-op result); the
    same key with different content raises IdempotencyKeyReusedError. A
    refusal or a genuine empty-run-all result creates NO queue row.

    When ``worktree_probe`` is supplied (always, from the API layer -- doc 33
    Part A), a launchable request against a dirty target worktree is refused
    with ``WorktreeNotCleanError`` *before* any queue row is created, so an
    untracked ``Issues.md`` never reaches a subprocess that would fail
    ``CHECKOUT_FAILED`` and block the queue."""
    normalized = {
        "mode": mode,
        "issueIds": sorted(issue_ids) if issue_ids else None,
        "expectedIssuesDigest": expected_issues_digest,
    }
    normalized_json = json.dumps(normalized, sort_keys=True)

    existing = conn.execute(
        "SELECT id, normalized_request_json FROM run_commands "
        "WHERE repository_id = ? AND idempotency_key = ?",
        (repo_id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if existing[1] != normalized_json:
            raise IdempotencyKeyReusedError()
        return get_command(conn, existing[0])

    plan = plan_run(conn, repo_id, mode=mode, issue_ids=issue_ids,
                    expected_issues_digest=expected_issues_digest)
    if not plan["ok"]:
        raise RunPlanError(
            "SELECTION_REFUSED", "the proposed batch was refused", status_code=422,
            details=plan,
        )
    if not plan["orderedIds"]:
        # A valid, empty run-all (or, defensively, an empty selected result)
        # is a successful no-op: no queue row, no process (ADR-30 decision 2).
        return {"noop": True, "excluded": plan["excluded"]}

    # Doc 33 Part A: only a request that would actually launch requires a clean
    # worktree; a refusal or a no-op above never spawns anything and is exempt.
    if worktree_probe is not None:
        preflight = worktree_probe(conn, repo_id)
        if not preflight.clean:
            raise WorktreeNotCleanError(preflight.message)

    now = _now()
    try:
        cur = conn.execute(
            "INSERT INTO run_commands (repository_id, mode, issue_ids_json, issues_digest, "
            "idempotency_key, normalized_request_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (repo_id, mode,
             json.dumps(plan["orderedIds"]) if mode == "SELECTED" else None,
             expected_issues_digest, idempotency_key, normalized_json, STATUS_QUEUED, now),
        )
    except sqlite3.IntegrityError:
        # A genuine double-click race: two concurrent requests both passed
        # the SELECT-based idempotency check above before either committed.
        # ux_run_commands_repo_idempotency is the real enforcement point;
        # this falls back to it exactly like an ordinary repeat would.
        conn.rollback()
        existing = conn.execute(
            "SELECT id, normalized_request_json FROM run_commands "
            "WHERE repository_id = ? AND idempotency_key = ?",
            (repo_id, idempotency_key),
        ).fetchone()
        if existing is None:
            raise  # not actually an idempotency-key collision -- re-raise
        if existing[1] != normalized_json:
            raise IdempotencyKeyReusedError()
        return get_command(conn, existing[0])
    conn.commit()
    return get_command(conn, cur.lastrowid)


def list_commands_for_repository(conn: sqlite3.Connection, repo_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COMMAND_COLUMNS} FROM run_commands WHERE repository_id = ? ORDER BY id",
        (repo_id,),
    ).fetchall()
    return [_row_to_command_dict(conn, r) for r in rows]


def delete_commands_for_repository(conn: sqlite3.Connection, repo_id: int) -> None:
    """Removes only Dashboard-owned queue rows -- never target files, never
    events.jsonl. Callers (app.py) must refuse the unregister first if
    `repository_has_active_command` is true; this function does not itself
    guard against deleting an active command's row."""
    conn.execute("DELETE FROM run_commands WHERE repository_id = ?", (repo_id,))
    # doc 34 Amendment 1: the per-repository queue pause is Dashboard-owned queue
    # state too, so it is removed with the commands rather than left orphaned.
    conn.execute("DELETE FROM run_queue_pauses WHERE repository_id = ?", (repo_id,))
    conn.commit()


def repository_has_active_command(conn: sqlite3.Connection, repo_id: int) -> bool:
    placeholders = ",".join("?" for _ in _BLOCKING_STATUSES)
    row = conn.execute(
        f"SELECT 1 FROM run_commands WHERE repository_id = ? AND status IN ({placeholders}) LIMIT 1",
        (repo_id, *_BLOCKING_STATUSES),
    ).fetchone()
    return row is not None


def has_launchable_command(conn: sqlite3.Connection, repo_id: int) -> bool:
    """Read-only: whether `try_launch_next` could claim a command right now --
    the repository is free (no active/blocking command), not paused, and at
    least one QUEUED command is waiting. Used only to decide whether to run the
    pre-claim clean-worktree preflight (doc 34 Amendment 2), so a dirty worktree
    defers a real launch rather than claiming-then-refusing it; the actual claim
    stays atomic in `claim_next_launchable_command`, which re-checks all of this
    under BEGIN IMMEDIATE, so this peek being momentarily stale is harmless."""
    if repository_has_active_command(conn, repo_id):
        return False
    if is_queue_paused(conn, repo_id):
        return False
    row = conn.execute(
        "SELECT 1 FROM run_commands WHERE repository_id = ? AND status = ? LIMIT 1",
        (repo_id, STATUS_QUEUED),
    ).fetchone()
    return row is not None


def is_queue_paused(conn: sqlite3.Connection, repo_id: int) -> bool:
    """Doc 34 Amendment 1: whether the repository's FIFO queue is paused. A
    persisted row in `run_queue_pauses` (written atomically by a successful
    cancel) means paused; it survives a Dashboard restart. Only an explicit
    Resume clears it."""
    row = conn.execute(
        "SELECT 1 FROM run_queue_pauses WHERE repository_id = ? LIMIT 1", (repo_id,),
    ).fetchone()
    return row is not None


def resume_repository_queue(conn: sqlite3.Connection, repo_id: int) -> dict:
    """Doc 34 Amendment 1: the only action that clears a queue pause. Deletes the
    persisted pause row (idempotent -- resuming an unpaused repository is a
    no-op success). This is pure control-plane state: it never launches anything
    itself, never touches events.jsonl/Git/leases/processes. After it returns,
    ordinary FIFO progression (scheduler/drain/enqueue) may claim and launch the
    next QUEUED command again."""
    conn.execute("DELETE FROM run_queue_pauses WHERE repository_id = ?", (repo_id,))
    conn.commit()
    return {"repositoryId": repo_id, "queuePaused": False, "resumed": True}


def claim_next_launchable_command(conn: sqlite3.Connection, repo_id: int) -> Optional[dict]:
    """Atomically claims the earliest still-QUEUED command for this
    repository, or returns None if there is none or the repository already
    has an active/blocked command. The claim (durable spawn intent) commits
    before any process is spawned -- see run_launcher.py."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if repository_has_active_command(conn, repo_id):
            conn.execute("ROLLBACK")
            return None
        # Doc 34 Amendment 1: a persisted queue pause (written atomically by a
        # cancel) blocks every launch path -- scheduler tick, explicit drain,
        # and enqueue-triggered launch all funnel through this one claim. The
        # pause is read INSIDE this BEGIN IMMEDIATE transaction, before any row
        # is selected, so a concurrent cancel that committed its pause is always
        # observed here and no QUEUED row is claimed until an explicit Resume.
        if is_queue_paused(conn, repo_id):
            conn.execute("ROLLBACK")
            return None
        next_row = conn.execute(
            "SELECT id FROM run_commands WHERE repository_id = ? AND status = ? "
            "ORDER BY id LIMIT 1",
            (repo_id, STATUS_QUEUED),
        ).fetchone()
        if next_row is None:
            conn.execute("ROLLBACK")
            return None
        conn.execute(
            "UPDATE run_commands SET status = ?, claimed_at = ? WHERE id = ?",
            (STATUS_CLAIMED, _now(), next_row[0]),
        )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    return get_command(conn, next_row[0])


def revalidate_claimed_command(conn: sqlite3.Connection, command: dict, *,
                               worktree_probe: Optional[WorktreeProbe] = None) -> dict:
    """Re-checks a CLAIMED command against current state immediately before
    launch (ADR-30 decision 3: "dequeue revalidates config, issue digest,
    selection, dependencies"). A stale selected id or a changed issue file
    refuses the exact command (REFUSED, slot released); a run-all command
    that has recomputed to zero remaining completes as a clean no-op
    (COMPLETED, slot released) rather than spawning anything.

    Doc 33 Part A: a target worktree that became dirty after enqueue is
    refused here too (REFUSED, slot released), so the check is enforced at both
    the run-request and the dequeue gate -- never only advisory."""
    try:
        plan = plan_run(
            conn, command["repositoryId"], mode=command["mode"],
            issue_ids=command["issueIds"], expected_issues_digest=command["issuesDigest"],
        )
    except DashboardApiError as exc:
        # Catches RunPlanError (digest/projection problems) and any other
        # typed refusal the planning stack can raise -- e.g.
        # ConfiguredIssuesError CONFIG_REPOSITORY_DRIFT/CONFIG_LOG_PATH_DRIFT
        # (ADR-30 review finding 3) -- so dequeue always fails closed to
        # REFUSED rather than propagating an unhandled exception out of the
        # launch orchestration path with the claim left dangling.
        conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? WHERE id = ?",
            (STATUS_REFUSED, str(exc), _now(), command["id"]),
        )
        conn.commit()
        return get_command(conn, command["id"])

    if not plan["ok"]:
        conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? WHERE id = ?",
            (STATUS_REFUSED, "selection is no longer valid at dequeue time", _now(), command["id"]),
        )
        conn.commit()
        return get_command(conn, command["id"])

    if not plan["orderedIds"]:
        conn.execute(
            "UPDATE run_commands SET status = ?, finished_at = ? WHERE id = ?",
            (STATUS_COMPLETED, _now(), command["id"]),
        )
        conn.commit()
        return get_command(conn, command["id"])

    if worktree_probe is not None:
        preflight = worktree_probe(conn, command["repositoryId"])
        if not preflight.clean:
            conn.execute(
                "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? WHERE id = ?",
                (STATUS_REFUSED, f"WORKTREE_NOT_CLEAN: {preflight.detail}", _now(), command["id"]),
            )
            conn.commit()
            return get_command(conn, command["id"])

    return command  # still valid -- caller proceeds to launch


def reconcile_ambiguous_claims_on_startup(conn: sqlite3.Connection) -> list[dict]:
    """Called once per Dashboard process startup. Any command left CLAIMED
    (spawn intent recorded, outcome never confirmed) is an ambiguous crash
    window -- the prior process may have died before, during, or just after
    the OS spawn call. Never auto-retried: marked LAUNCH_OWNERSHIP_UNKNOWN,
    which keeps that repository closed to further automatic launch until an
    operator resolves it (ADR-30 decision 4)."""
    rows = conn.execute(
        "SELECT id FROM run_commands WHERE status = ?", (STATUS_CLAIMED,),
    ).fetchall()
    for (cmd_id,) in rows:
        conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ? WHERE id = ?",
            (STATUS_LAUNCH_OWNERSHIP_UNKNOWN,
             "Dashboard restarted with an unresolved spawn claim for this command",
             cmd_id),
        )
    if rows:
        conn.commit()
    return [get_command(conn, r[0]) for r in rows]


def acknowledge_abnormal_command(
    conn: sqlite3.Connection, repo_id: int, command_id: int, *,
    identity_probe=probe_controller_identity,
    configured_issues_check=get_configured_issues,
) -> dict:
    """Doc 33 Part B: safely acknowledge an ABNORMAL_EXIT command and release
    the repository for a later, freshly-requested command.

    This UNLOCKS ONLY. It never retries, re-plans, or expands the original
    selection; it never writes/repairs the runtime event log, never
    synthesises a runtime run-finished event, never mutates the workspace
    lease or the git target, and never changes the command's own
    `issue_ids_json`. Every gate below fails closed (the command stays
    blocked) rather than releasing on ambiguity:

    1. Only an ABNORMAL_EXIT command is acknowledgeable (a
       LAUNCH_OWNERSHIP_UNKNOWN or any live/other status is refused).
    2. The recorded child must be proven DEAD via the same read-only
       PID/creation-time probe run_launcher uses -- an alive (LIVE_MATCH),
       foreign (PID_REUSED), or unknown/malformed identity is refused. This
       DEAD proof is also the workspace-ownership witness for the spawned
       child.
    3. Any Dashboard-confirmed correlated runtime run must be terminal
       (an observed terminal outcome in the current-generation run_views,
       resolved through the same read model the /runs endpoint uses).
    4. The target configuration and configured issues must still revalidate.

    The final ABNORMAL_EXIT -> ACKNOWLEDGED flip is atomic: exactly one of two
    concurrent acknowledgements transitions the row; the other observes it
    already ACKNOWLEDGED and returns an idempotent success."""
    command = get_command(conn, command_id)  # NotFoundError if unknown
    if command["repositoryId"] != repo_id:
        raise NotFoundError(f"run command {command_id} not found for repository {repo_id}")

    if command["status"] == STATUS_ACKNOWLEDGED:
        return {**command, "acknowledged": True, "alreadyAcknowledged": True}

    if command["status"] != STATUS_ABNORMAL_EXIT:
        raise AcknowledgeError(
            "ACK_NOT_ABNORMAL",
            f"only an ABNORMAL_EXIT command can be acknowledged (status is {command['status']})",
        )

    # Gate 1: the recorded child must be proven no longer running.
    identity = {"pid": command["processPid"], "creation_time": command["processCreationTime"]}
    id_result = identity_probe(identity)
    if id_result.state != ControllerIdentityState.DEAD:
        raise AcknowledgeError(
            "ACK_PROCESS_NOT_TERMINAL",
            f"recorded child is not proven terminal ({id_result.state.value}: "
            f"{id_result.detail}); refusing to unlock while ownership is alive, "
            "foreign, or unknown",
        )

    # Gate 2: any Dashboard-confirmed correlated runtime run must be terminal.
    if command["runIdCorrelation"] is not None:
        outcome = _resolve_runtime_outcome(conn, repo_id, command["runIdCorrelation"])
        if outcome is None:
            raise AcknowledgeError(
                "ACK_RUN_NOT_TERMINAL",
                "the correlated runtime run has no observed terminal outcome yet; "
                "refusing to unlock until the runtime event state is terminal",
            )

    # Gate 3: the target configuration + configured issues must still revalidate.
    try:
        configured_issues_check(conn, repo_id)
    except DashboardApiError as exc:
        raise AcknowledgeError(
            "ACK_TARGET_UNVERIFIABLE",
            f"target configuration/issues could not be revalidated: {exc}",
        ) from exc

    # Atomic terminal flip. Serialized by BEGIN IMMEDIATE; the conditional
    # UPDATE (WHERE status = ABNORMAL_EXIT) is the linearization point.
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute(
            "SELECT status FROM run_commands WHERE id = ?", (command_id,),
        ).fetchone()
        current_status = current[0] if current is not None else None
        if current_status == STATUS_ABNORMAL_EXIT:
            conn.execute(
                "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? "
                "WHERE id = ? AND status = ?",
                (STATUS_ACKNOWLEDGED,
                 "acknowledged by operator; queue unlocked (no retry, selection unchanged)",
                 _now(), command_id, STATUS_ABNORMAL_EXIT),
            )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    final = get_command(conn, command_id)
    if final["status"] == STATUS_ACKNOWLEDGED:
        return {**final, "acknowledged": True,
                "alreadyAcknowledged": current_status != STATUS_ABNORMAL_EXIT}
    # The row changed out from under us to some other status between the gates
    # and the flip -- report honestly rather than pretend success.
    raise AcknowledgeError(
        "ACK_NOT_ABNORMAL",
        f"command changed to {final['status']} before acknowledgement completed",
    )


def _cancel_refusal_reason(status: str) -> str:
    """A typed, actionable reason for why a non-QUEUED command cannot be
    cancelled (doc 34). An ABNORMAL_EXIT is steered to the doc 33
    acknowledge/unlock path, not cancel."""
    if status == STATUS_ABNORMAL_EXIT:
        return (
            "only a QUEUED command can be cancelled; this command is ABNORMAL_EXIT. "
            "Use 'Acknowledge failed command and unlock queue' to release the repository "
            "-- cancellation never discards a failed run."
        )
    if status in (STATUS_CLAIMED, STATUS_LAUNCHED, STATUS_LAUNCH_OWNERSHIP_UNKNOWN):
        return (
            f"only a QUEUED command can be cancelled; this command is {status} and is "
            "already claimed or launching. Cancellation never touches a running process."
        )
    if status == STATUS_CANCELLED:
        return "this command is already CANCELLED; no action is needed."
    return (
        f"only a QUEUED command can be cancelled; this command is already {status} "
        "and is not a waiting batch."
    )


def cancel_queued_command(conn: sqlite3.Connection, repo_id: int, command_id: int) -> dict:
    """Doc 34: safely cancel a still-QUEUED command, removing only the waiting
    batch. Sets the command to the Dashboard-only terminal, non-blocking status
    CANCELLED.

    This is a pure control-plane status flip. It never parses/writes
    events.jsonl, never synthesises a runtime run-finished event, never mutates
    the workspace lease or the git target, never kills or signals a process,
    never runs the clean-worktree launch preflight (cancellation is state-safe
    even while the worktree is dirty), and never retries, re-plans, expands a
    selection, or auto-starts another command. It touches only the one cancelled
    row; every other command's status/selection is left unchanged.

    Only a command in exact status QUEUED is cancelable; every other status is
    refused with a typed, actionable CancelError and no state change.

    Cancel and claim_next_launchable_command are atomic competitors for the same
    row: both serialize through BEGIN IMMEDIATE, and the conditional UPDATE
    (WHERE status = QUEUED) is the linearization point. Exactly one of
    {cancel, claim} transitions the row. If claim won first, cancel's UPDATE
    matches zero rows and refuses -- it never interferes with the process the
    claim is about to spawn. Two concurrent cancels likewise resolve to exactly
    one success and one honest CANCEL_NOT_QUEUED conflict, never a double
    transition or a 500."""
    command = get_command(conn, command_id)  # NotFoundError if unknown
    if command["repositoryId"] != repo_id:
        raise NotFoundError(f"run command {command_id} not found for repository {repo_id}")

    if command["status"] != STATUS_QUEUED:
        raise CancelError("CANCEL_NOT_QUEUED", _cancel_refusal_reason(command["status"]))

    now = _now()
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE run_commands SET status = ?, refusal_reason = ?, finished_at = ? "
            "WHERE id = ? AND status = ?",
            (STATUS_CANCELLED, "cancelled by operator; waiting batch removed "
             "(no process affected, no runtime state changed); queue paused until resume",
             now, command_id, STATUS_QUEUED),
        )
        changed = cur.rowcount
        if changed == 1:
            # Doc 34 Amendment 1: atomically pause the repository's queue in the
            # SAME transaction as the CANCELLED flip, so a cancel never lets the
            # scheduler auto-start the next waiting batch. OR IGNORE keeps an
            # existing pause's original timestamp (idempotent); only an explicit
            # Resume clears it. This writes a Dashboard-only control-plane row --
            # never events.jsonl, a lease, Git, or a process.
            conn.execute(
                "INSERT OR IGNORE INTO run_queue_pauses (repository_id, paused_at, reason) "
                "VALUES (?, ?, ?)",
                (repo_id, now, f"queue paused by cancellation of command {command_id}"),
            )
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")

    if changed == 1:
        return {**get_command(conn, command_id), "cancelled": True, "queuePaused": True}

    # Lost the race: the row was claimed/launched or concurrently cancelled
    # between the QUEUED gate above and this conditional flip. Report the
    # current status honestly -- never a fake success, never a 500.
    final = get_command(conn, command_id)
    raise CancelError("CANCEL_NOT_QUEUED", _cancel_refusal_reason(final["status"]))
