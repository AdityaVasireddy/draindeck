"""ADR-30 decisions 2-3: run planning + the Dashboard-owned run-command
queue. Queue rows are exclusively Dashboard control-plane state -- never
written to `events.jsonl`, never read by `src/runtime` (RED 0's frozen
architecture gate)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from runtime.queue.issues_md import IssueSpec
from runtime.queue.selection import Blocker, TerminalExclusion, plan_run_all, plan_selected

from .configured_issues import get_configured_issues
from .errors import DashboardApiError, NotFoundError


class RunPlanError(DashboardApiError):
    pass


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
    }


def _row_to_command_dict(conn: sqlite3.Connection, row) -> dict:
    (cmd_id, repo_id, mode, issue_ids_json, issues_digest, status, refusal_reason,
     process_pid, run_id_correlation, created_at, claimed_at, finished_at) = row
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
        "queuePosition": position,
        "runIdCorrelation": run_id_correlation,
        "createdAt": created_at,
        "claimedAt": claimed_at,
        "finishedAt": finished_at,
    }


_COMMAND_COLUMNS = (
    "id, repository_id, mode, issue_ids_json, issues_digest, status, refusal_reason, "
    "process_pid, run_id_correlation, created_at, claimed_at, finished_at"
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
                    idempotency_key: str) -> dict:
    """Idempotent enqueue. Repeating the same key with identical normalized
    content returns the existing command (or the prior no-op result); the
    same key with different content raises IdempotencyKeyReusedError. A
    refusal or a genuine empty-run-all result creates NO queue row."""
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

    now = _now()
    cur = conn.execute(
        "INSERT INTO run_commands (repository_id, mode, issue_ids_json, issues_digest, "
        "idempotency_key, normalized_request_json, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (repo_id, mode,
         json.dumps(plan["orderedIds"]) if mode == "SELECTED" else None,
         expected_issues_digest, idempotency_key, normalized_json, STATUS_QUEUED, now),
    )
    return get_command(conn, cur.lastrowid)


def list_commands_for_repository(conn: sqlite3.Connection, repo_id: int) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COMMAND_COLUMNS} FROM run_commands WHERE repository_id = ? ORDER BY id",
        (repo_id,),
    ).fetchall()
    return [_row_to_command_dict(conn, r) for r in rows]
