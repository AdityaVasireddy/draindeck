"""Replay engine — RECONCILED against doc 03. State is a projection of
the log (rows are authoritative); projections are disposable and
rebuildable. Replay is strict: an event illegal under doc 03's tables
raises, because a log that does not replay cleanly is corrupted history.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterable, Optional

from ..state.model import EXECUTION_TERMINAL, ExecutionState, IssueState
from ..state.transitions import (
    COMMIT_SEQUENCE_STATE,
    EXECUTION_TRANSITIONS,
    ISSUE_TRANSITIONS,
    TransitionError,
)
from .schema import Event, EventType


@dataclass
class ExecutionView:
    execution_id: str
    issue_id: str
    state: ExecutionState
    commit_intended: bool = False   # CommitIntent seen (intent, I5/I6)
    commit_created: bool = False    # CommitCreated seen (fact)


@dataclass
class StateProjection:
    issues: dict[str, IssueState] = field(default_factory=dict)
    executions: dict[str, ExecutionView] = field(default_factory=dict)
    issue_executions: dict[str, list[str]] = field(default_factory=dict)
    last_event_id: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    def apply(self, ev: Event) -> None:
        self.last_event_id = ev.event_id
        self.counts[ev.type.value] = self.counts.get(ev.type.value, 0) + 1
        handler = _HANDLERS.get(ev.type)
        if handler:
            handler(self, ev)

    def rebuild(self, events: Iterable[Event]) -> "StateProjection":
        for ev in events:
            self.apply(ev)
        return self

    # ── queries ──────────────────────────────────────────────────
    def latest_execution(self, issue_id: str) -> Optional[ExecutionView]:
        ids = self.issue_executions.get(issue_id) or []
        return self.executions[ids[-1]] if ids else None

    def open_executions(self) -> list[ExecutionView]:
        """EXECUTING views — unresolved ExecutionSpawned intents.
        Reconciler check-1 input (doc 03: abandonable, never resumed)."""
        return [x for x in self.executions.values()
                if x.state == ExecutionState.EXECUTING]

    def attempts(self, issue_id: str) -> int:
        return len(self.issue_executions.get(issue_id) or [])

    def digest(self) -> str:
        canon = {
            "issues": {k: v.value for k, v in sorted(self.issues.items())},
            "executions": {
                k: [v.issue_id, v.state.value, v.commit_intended, v.commit_created]
                for k, v in sorted(self.executions.items())
            },
            "issue_executions": dict(sorted(self.issue_executions.items())),
            "last_event_id": self.last_event_id,
            "counts": dict(sorted(self.counts.items())),
        }
        raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


# ── handlers ─────────────────────────────────────────────────────
def _need(ev: Event, attr: str) -> str:
    v = getattr(ev, attr)
    if not v:
        raise TransitionError(f"{ev.type.value} (event {ev.event_id}) missing {attr}")
    return v


def _issue_created(p: StateProjection, ev: Event) -> None:
    iid = _need(ev, "issue_id")
    if iid in p.issues:
        raise TransitionError(f"duplicate IssueCreated for {iid} (event {ev.event_id})")
    p.issues[iid] = IssueState.PENDING


def _issue_transition(p: StateProjection, ev: Event) -> None:
    iid = _need(ev, "issue_id")
    cur = p.issues.get(iid)
    if cur is None:
        raise TransitionError(
            f"{ev.type.value} for unknown issue {iid} (event {ev.event_id})")
    fn = ISSUE_TRANSITIONS.get((cur, ev.type))
    if fn is None:
        raise TransitionError(
            f"illegal {ev.type.value} for issue {iid} in {cur.value} "
            f"(event {ev.event_id})")
    p.issues[iid] = fn(ev.payload)


def _execution_spawned(p: StateProjection, ev: Event) -> None:
    xid, iid = _need(ev, "execution_id"), _need(ev, "issue_id")
    if xid in p.executions:
        raise TransitionError(f"duplicate ExecutionSpawned for {xid} (event {ev.event_id})")
    if p.issues.get(iid) is not IssueState.ACTIVE:
        raise TransitionError(
            f"ExecutionSpawned for {iid} which is "
            f"{p.issues.get(iid) and p.issues[iid].value} (event {ev.event_id})")
    prev = p.latest_execution(iid)
    if prev is not None and prev.state not in EXECUTION_TERMINAL:
        raise TransitionError(
            f"ExecutionSpawned for {iid} while {prev.execution_id} is "
            f"{prev.state.value} (event {ev.event_id})")
    # SPAWNED is unobservable from the log (see model.py) — enter EXECUTING.
    p.executions[xid] = ExecutionView(xid, iid, ExecutionState.EXECUTING)
    p.issue_executions.setdefault(iid, []).append(xid)


def _execution_transition(p: StateProjection, ev: Event) -> None:
    xid = _need(ev, "execution_id")
    view = p.executions.get(xid)
    if view is None:
        raise TransitionError(
            f"{ev.type.value} for unknown execution {xid} (event {ev.event_id})")
    fn = EXECUTION_TRANSITIONS.get((view.state, ev.type))
    if fn is None:
        raise TransitionError(
            f"illegal {ev.type.value} for execution {xid} in "
            f"{view.state.value} (event {ev.event_id})")
    view.state = fn(ev.payload)


def _commit_intent(p: StateProjection, ev: Event) -> None:
    view = _accepted_view(p, ev)
    if view.commit_intended:
        raise TransitionError(
            f"duplicate CommitIntent for {view.execution_id} (event {ev.event_id})")
    view.commit_intended = True


def _commit_created(p: StateProjection, ev: Event) -> None:
    view = _accepted_view(p, ev)
    if not view.commit_intended:
        raise TransitionError(
            f"CommitCreated without CommitIntent for {view.execution_id} "
            f"(event {ev.event_id}) — violates I5/I6 ordering")
    if view.commit_created:
        raise TransitionError(
            f"duplicate CommitCreated for {view.execution_id} (event {ev.event_id})")
    view.commit_created = True


def _accepted_view(p: StateProjection, ev: Event) -> ExecutionView:
    xid = _need(ev, "execution_id")
    view = p.executions.get(xid)
    if view is None:
        raise TransitionError(
            f"{ev.type.value} for unknown execution {xid} (event {ev.event_id})")
    if view.state is not COMMIT_SEQUENCE_STATE:
        raise TransitionError(
            f"{ev.type.value} illegal in {view.state.value} for {xid} "
            f"(event {ev.event_id})")
    return view


_HANDLERS = {
    EventType.ISSUE_CREATED: _issue_created,
    EventType.ISSUE_ACTIVATED: _issue_transition,
    EventType.ISSUE_COMPLETED: _issue_transition,
    EventType.ISSUE_ESCALATED: _issue_transition,
    EventType.EXECUTION_SPAWNED: _execution_spawned,
    EventType.EXECUTION_FINISHED: _execution_transition,
    EventType.EXECUTION_CRASHED: _execution_transition,
    EventType.VALIDATION_PASSED: _execution_transition,
    EventType.VALIDATION_FAILED: _execution_transition,
    EventType.REVIEW_APPROVED: _execution_transition,
    EventType.REVIEW_REJECTED: _execution_transition,
    EventType.COMMIT_INTENT: _commit_intent,
    EventType.COMMIT_CREATED: _commit_created,
    # HumanIntervention / GuidelinePromoted: counted; no state machine in
    # the foundation (escalation handling arrives with the orchestrator).
}
