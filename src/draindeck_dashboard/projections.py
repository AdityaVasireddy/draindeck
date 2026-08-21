"""Tolerant issue/execution projection (docs/19: unknown event types and
illegal or out-of-order transitions must degrade gracefully — a torn,
reordered, or replayed-across-generations observation must never crash
the issues/executions view).

Reuses doc 03's public state vocabulary and transition tables
(``runtime.state.model`` / ``runtime.state.transitions`` — pure enums and
dict lookups, no file/lock/subprocess access, the same shape ADR-26's
allowlist and docs/19 already require Dashboard to understand) so state
names never drift from the core runtime. This deliberately does NOT call
``runtime.events.projections.StateProjection.apply`` — that replay engine
raises on any illegal transition, which is correct for the core runtime
(a log that does not replay cleanly is corruption) but wrong for
Dashboard's tolerant, read-only observation of a log ADR-25 may hand back
torn or reordered. An illegal transition here is recorded as
``inconsistent`` on the entity, never raised.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from runtime.events.schema import EventType
from runtime.state.model import ExecutionState, IssueState
from runtime.state.transitions import EXECUTION_TRANSITIONS, ISSUE_TRANSITIONS

_ISSUE_TRANSITION_TYPES = frozenset({
    EventType.ISSUE_ACTIVATED, EventType.ISSUE_COMPLETED, EventType.ISSUE_ESCALATED,
})
_EXECUTION_TRANSITION_TYPES = frozenset({
    EventType.EXECUTION_FINISHED, EventType.EXECUTION_CRASHED,
    EventType.VALIDATION_PASSED, EventType.VALIDATION_FAILED,
    EventType.REVIEW_APPROVED, EventType.REVIEW_REJECTED,
})

# ADR-25 hardcodes writerState UNKNOWN — every EXECUTING execution is
# "Pending reconciliation" in Part 2; Running is unreachable and Dashboard
# must never invent a liveness probe (docs/19).
PENDING_RECONCILIATION = "Pending reconciliation"


@dataclass
class IssueView:
    issue_id: str
    state: str
    title: str = ""
    last_event_id: Optional[int] = None
    inconsistent: bool = False


@dataclass
class ExecutionView:
    execution_id: str
    issue_id: Optional[str]
    state: str
    last_event_id: Optional[int] = None
    inconsistent: bool = False


@dataclass
class ProjectionResult:
    issues: dict = field(default_factory=dict)
    executions: dict = field(default_factory=dict)
    unknown_event_type_count: int = 0


def _try_event_type(raw: Optional[str]) -> Optional[EventType]:
    if raw is None:
        return None
    try:
        return EventType(raw)
    except ValueError:
        return None  # unknown event type: evidence, not projected, not a crash


def build_projection(conn: sqlite3.Connection, repo_id: int,
                     identity_generation_id: int) -> ProjectionResult:
    result = ProjectionResult()
    rows = conn.execute(
        "SELECT event_id, event_type, issue_id, execution_id, payload_json FROM evidence "
        "WHERE repository_id = ? AND identity_generation_id = ? AND integrity = 'OK' "
        "ORDER BY event_id",
        (repo_id, identity_generation_id),
    ).fetchall()

    for event_id, event_type_str, issue_id, execution_id, payload_json in rows:
        etype = _try_event_type(event_type_str)
        if etype is None:
            result.unknown_event_type_count += 1
            continue

        if etype is EventType.ISSUE_CREATED:
            _apply_issue_created(result, issue_id, payload_json, event_id)
        elif etype in _ISSUE_TRANSITION_TYPES:
            _apply_issue_transition(result, etype, issue_id, payload_json, event_id)
        elif etype is EventType.EXECUTION_SPAWNED:
            _apply_execution_spawned(result, execution_id, issue_id, event_id)
        elif etype in _EXECUTION_TRANSITION_TYPES:
            _apply_execution_transition(result, etype, execution_id, payload_json, event_id)
        # CommitIntent/CommitCreated/HumanIntervention/GuidelinePromoted:
        # not modeled in Part 2's issues/executions summary view.

    for view in result.executions.values():
        if not view.inconsistent and view.state == ExecutionState.EXECUTING.value:
            view.state = PENDING_RECONCILIATION

    return result


def _load_payload(payload_json: Optional[str]) -> dict:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_issue_created(result: ProjectionResult, issue_id: Optional[str],
                         payload_json: Optional[str], event_id: int) -> None:
    if issue_id is None:
        return
    if issue_id in result.issues:
        result.issues[issue_id].inconsistent = True
        return
    payload = _load_payload(payload_json)
    result.issues[issue_id] = IssueView(
        issue_id, IssueState.PENDING.value,
        title=payload.get("title", "") if isinstance(payload.get("title"), str) else "",
        last_event_id=event_id,
    )


def _apply_issue_transition(result: ProjectionResult, etype: EventType,
                            issue_id: Optional[str], payload_json: Optional[str],
                            event_id: int) -> None:
    if issue_id is None:
        return
    view = result.issues.get(issue_id)
    if view is None or view.inconsistent:
        return
    try:
        cur_state = IssueState(view.state)
    except ValueError:
        view.inconsistent = True
        return
    fn = ISSUE_TRANSITIONS.get((cur_state, etype))
    if fn is None:
        view.inconsistent = True
        return
    try:
        view.state = fn(_load_payload(payload_json)).value
    except Exception:
        view.inconsistent = True
        return
    view.last_event_id = event_id


def _apply_execution_spawned(result: ProjectionResult, execution_id: Optional[str],
                             issue_id: Optional[str], event_id: int) -> None:
    if execution_id is None:
        return
    if execution_id in result.executions:
        result.executions[execution_id].inconsistent = True
        return
    result.executions[execution_id] = ExecutionView(
        execution_id, issue_id, ExecutionState.EXECUTING.value, last_event_id=event_id,
    )


def _apply_execution_transition(result: ProjectionResult, etype: EventType,
                                execution_id: Optional[str], payload_json: Optional[str],
                                event_id: int) -> None:
    if execution_id is None:
        return
    view = result.executions.get(execution_id)
    if view is None or view.inconsistent:
        return
    try:
        cur_state = ExecutionState(view.state)
    except ValueError:
        view.inconsistent = True
        return
    fn = EXECUTION_TRANSITIONS.get((cur_state, etype))
    if fn is None:
        view.inconsistent = True
        return
    try:
        view.state = fn(_load_payload(payload_json)).value
    except Exception:
        view.inconsistent = True
        return
    view.last_event_id = event_id
