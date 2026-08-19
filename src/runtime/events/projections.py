"""Replay engine — RECONCILED against doc 03. State is a projection of
the log (rows are authoritative); projections are disposable and
rebuildable. Replay is strict: an event illegal under doc 03's tables
raises, because a log that does not replay cleanly is corrupted history.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
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
    # Widened for the reconciler seams (docs/11 §2). All derived straight
    # from doc 03 §3 payloads — no new events, no schema change.
    base_commit: Optional[str] = None          # issue's IssueActivated.base_commit
    end_commit: Optional[str] = None           # ExecutionFinished.end_commit
    intent_end_commit: Optional[str] = None     # CommitIntent.end_commit
    intent_target_branch: Optional[str] = None  # CommitIntent.target_branch
    # Session-5 additions for the orchestrator loop: the I3 pin gate needs the
    # commits validation and review pinned, and the retry/escalate policy needs
    # each rejection's taxonomy + reviewer feedback. All from doc 03 §3 payloads.
    validated_commit: Optional[str] = None      # ValidationPassed.validated_commit
    reviewed_commit: Optional[str] = None        # ReviewApproved.reviewed_commit
    taxonomy_category: Optional[str] = None      # set on any REJECTED/CRASHED exit
    feedback: list = field(default_factory=list)  # ReviewRejected.feedback[]
    # Untracked-file provenance (resolve-item, 2026-08-18): the workspace's
    # untracked paths at ExecutionSpawned time, before the engine could
    # touch anything -- ExecutionSpawned.payload.pre_execution_untracked,
    # additive (no new event, no schema change, same pattern as base_commit
    # above). Reconciler check 3's baseline for "did THIS execution create
    # this untracked file" -- see recovery/bindings.py.
    pre_execution_untracked: list = field(default_factory=list)


class ContainmentState(str, Enum):
    """Durable containment boundary state, orthogonal to issue/execution state."""

    PREPARED = "PREPARED"
    ESTABLISHED = "ESTABLISHED"
    UNCONFIRMED = "UNCONFIRMED"
    RELEASED = "RELEASED"


@dataclass
class ContainmentView:
    """One append-once containment generation for an execution."""

    execution_id: str
    workspace_key: str
    generation: str
    state: ContainmentState
    prepared: dict
    established: Optional[dict] = None
    unconfirmed: Optional[dict] = None
    released: Optional[dict] = None


@dataclass
class StateProjection:
    issues: dict[str, IssueState] = field(default_factory=dict)
    executions: dict[str, ExecutionView] = field(default_factory=dict)
    issue_executions: dict[str, list[str]] = field(default_factory=dict)
    issue_base_commit: dict[str, str] = field(default_factory=dict)  # IssueActivated
    issue_depends_on: dict[str, list[str]] = field(default_factory=dict)  # IssueCreated
    # Static issue reference text (IssueCreated) for the context pack. Excluded
    # from digest() — it is deterministic reference data, not state identity.
    issue_meta: dict[str, dict] = field(default_factory=dict)
    containments: dict[tuple[str, str], ContainmentView] = field(default_factory=dict)
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

    def unreleased_containments(
        self, workspace_key: Optional[str] = None,
    ) -> list[ContainmentView]:
        """Containment generations that still block their workspace."""
        return [view for view in self.containments.values()
                if view.state is not ContainmentState.RELEASED
                and (workspace_key is None or view.workspace_key == workspace_key)]

    def is_workspace_blocked(self, workspace_key: str) -> bool:
        return bool(self.unreleased_containments(workspace_key))

    def attempts(self, issue_id: str) -> int:
        return len(self.issue_executions.get(issue_id) or [])

    def deps_met(self, issue_id: str) -> bool:
        """True iff every dependency of ``issue_id`` is DONE (idle-row guard,
        doc 03 §5 'deps (if any) DONE'). Unknown deps count as unmet."""
        return all(
            self.issues.get(dep) is IssueState.DONE
            for dep in self.issue_depends_on.get(issue_id, [])
        )

    def reviewer_feedback_categories(self, issue_id: str) -> list[str]:
        """Reviewer-feedback categories across this issue's executions, in
        order. Doc 02 §2 dedupe rule: a category appearing twice means the loop
        will not converge → escalate. Reviewer categories ONLY — repeated
        validation taxonomies are normal retry fodder, so they are not here."""
        cats: list[str] = []
        for xid in self.issue_executions.get(issue_id, []):
            for fb in self.executions[xid].feedback:
                c = fb.get("category") if isinstance(fb, dict) else None
                if c:
                    cats.append(c)
        return cats

    def digest(self) -> str:
        canon = {
            "issues": {k: v.value for k, v in sorted(self.issues.items())},
            "executions": {
                k: [v.issue_id, v.state.value, v.commit_intended,
                    v.commit_created, v.base_commit, v.end_commit,
                    v.intent_end_commit, v.intent_target_branch,
                    v.validated_commit, v.reviewed_commit, v.taxonomy_category,
                    v.feedback, v.pre_execution_untracked]
                for k, v in sorted(self.executions.items())
            },
            "issue_executions": dict(sorted(self.issue_executions.items())),
            "issue_base_commit": dict(sorted(self.issue_base_commit.items())),
            "issue_depends_on": dict(sorted(self.issue_depends_on.items())),
            "last_event_id": self.last_event_id,
            "counts": dict(sorted(self.counts.items())),
        }
        # Preserve historical digest bytes when the log predates containment.
        if self.containments:
            canon["containments"] = {
                f"{xid}:{generation}": [
                    view.workspace_key, view.state.value, view.prepared,
                    view.established, view.unconfirmed, view.released,
                ]
                for (xid, generation), view in sorted(self.containments.items())
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
    deps = ev.payload.get("depends_on") or []
    if deps:
        p.issue_depends_on[iid] = list(deps)
    p.issue_meta[iid] = {
        "title": ev.payload.get("title", ""),
        "body": ev.payload.get("body", ""),
        "acceptance_criteria": ev.payload.get("acceptance_criteria") or [],
    }


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
    if ev.type is EventType.ISSUE_ACTIVATED:
        bc = ev.payload.get("base_commit")
        if bc:
            p.issue_base_commit[iid] = bc


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
    p.executions[xid] = ExecutionView(
        xid, iid, ExecutionState.EXECUTING,
        base_commit=p.issue_base_commit.get(iid),
        pre_execution_untracked=list(ev.payload.get("pre_execution_untracked") or []),
    )
    p.issue_executions.setdefault(iid, []).append(xid)


def _containment_execution(p: StateProjection, ev: Event) -> ExecutionView:
    xid, iid = _need(ev, "execution_id"), _need(ev, "issue_id")
    view = p.executions.get(xid)
    if view is None:
        raise TransitionError(
            f"{ev.type.value} for unknown execution {xid} (event {ev.event_id})")
    if view.issue_id != iid:
        raise TransitionError(
            f"{ev.type.value} issue mismatch for {xid} (event {ev.event_id})")
    if view.state is not ExecutionState.EXECUTING:
        raise TransitionError(
            f"{ev.type.value} illegal in {view.state.value} for {xid} "
            f"(event {ev.event_id})")
    return view


def _field(payload: dict, name: str, ev: Event) -> object:
    if name not in payload:
        raise TransitionError(
            f"{ev.type.value} missing payload.{name} (event {ev.event_id})")
    return payload[name]


def _string(payload: dict, name: str, ev: Event) -> str:
    value = _field(payload, name, ev)
    if not isinstance(value, str) or not value:
        raise TransitionError(
            f"{ev.type.value} invalid payload.{name} (event {ev.event_id})")
    return value


def _mapping(payload: dict, name: str, ev: Event) -> dict:
    value = _field(payload, name, ev)
    if not isinstance(value, dict):
        raise TransitionError(
            f"{ev.type.value} invalid payload.{name} (event {ev.event_id})")
    return value


def _nonempty_mapping(payload: dict, name: str, ev: Event) -> dict:
    value = _mapping(payload, name, ev)
    if not value:
        raise TransitionError(
            f"{ev.type.value} empty payload.{name} (event {ev.event_id})")
    return value


def _positive_int(payload: dict, name: str, ev: Event) -> int:
    value = _field(payload, name, ev)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise TransitionError(
            f"{ev.type.value} invalid payload.{name} (event {ev.event_id})")
    return value


def _containment_key(ev: Event) -> tuple[str, str, str]:
    xid = _need(ev, "execution_id")
    workspace_key = _string(ev.payload, "workspace_key", ev)
    generation = _string(ev.payload, "containment_generation", ev)
    return xid, workspace_key, generation


def _required_identity(payload: dict, name: str, ev: Event) -> dict:
    identity = _mapping(payload, name, ev)
    _positive_int(identity, "pid", ev)
    _string(identity, "creation_time", ev)
    return identity


def _containment_prepared(p: StateProjection, ev: Event) -> None:
    _containment_execution(p, ev)
    xid, workspace_key, generation = _containment_key(ev)
    key = (xid, generation)
    if key in p.containments:
        raise TransitionError(
            f"duplicate ExecutionContainmentPrepared for {xid}/{generation} "
            f"(event {ev.event_id})")
    if any(existing.execution_id == xid
           and existing.state is not ContainmentState.RELEASED
           for existing in p.containments.values()):
        raise TransitionError(
            f"ExecutionContainmentPrepared for {xid} while a containment "
            f"generation is unreleased (event {ev.event_id})")
    _string(ev.payload, "protocol_version", ev)
    _string(ev.payload, "launch_mode", ev)
    _required_identity(ev.payload, "controller", ev)
    lease = _mapping(ev.payload, "lease", ev)
    _string(lease, "scope", ev)
    _string(lease, "version", ev)
    p.containments[key] = ContainmentView(
        execution_id=xid,
        workspace_key=workspace_key,
        generation=generation,
        state=ContainmentState.PREPARED,
        prepared=dict(ev.payload),
    )


def _matching_containment(
    p: StateProjection, ev: Event,
) -> ContainmentView:
    _containment_execution(p, ev)
    xid, workspace_key, generation = _containment_key(ev)
    view = p.containments.get((xid, generation))
    if view is None:
        raise TransitionError(
            f"{ev.type.value} without matching Prepared for {xid}/{generation} "
            f"(event {ev.event_id})")
    if view.workspace_key != workspace_key:
        raise TransitionError(
            f"{ev.type.value} workspace mismatch for {xid}/{generation} "
            f"(event {ev.event_id})")
    return view


def _containment_established(p: StateProjection, ev: Event) -> None:
    view = _matching_containment(p, ev)
    if view.state is not ContainmentState.PREPARED:
        raise TransitionError(
            f"ExecutionContainmentEstablished illegal after {view.state.value} "
            f"for {view.execution_id}/{view.generation} (event {ev.event_id})")
    root_suspended = _field(ev.payload, "root_suspended", ev)
    if root_suspended is not True:
        raise TransitionError(
            f"ExecutionContainmentEstablished requires root_suspended=true "
            f"(event {ev.event_id})")
    _required_identity(ev.payload, "root", ev)
    job = _mapping(ev.payload, "job", ev)
    if (job.get("kill_on_job_close") is not True
            or job.get("breakaway_ok") is not False
            or job.get("silent_breakaway_ok") is not False):
        raise TransitionError(
            f"ExecutionContainmentEstablished has invalid job witness "
            f"(event {ev.event_id})")
    membership = _mapping(ev.payload, "membership", ev)
    if membership.get("root_member") is not True:
        raise TransitionError(
            f"ExecutionContainmentEstablished requires root membership witness "
            f"(event {ev.event_id})")
    _positive_int(membership, "member_count", ev)
    view.state = ContainmentState.ESTABLISHED
    view.established = dict(ev.payload)


def _termination_unconfirmed(p: StateProjection, ev: Event) -> None:
    view = _matching_containment(p, ev)
    if view.state is not ContainmentState.ESTABLISHED:
        raise TransitionError(
            f"ExecutionTerminationUnconfirmed illegal after {view.state.value} "
            f"for {view.execution_id}/{view.generation} (event {ev.event_id})")
    _string(ev.payload, "stage", ev)
    _string(ev.payload, "category", ev)
    _nonempty_mapping(ev.payload, "diagnostic", ev)
    view.state = ContainmentState.UNCONFIRMED
    view.unconfirmed = dict(ev.payload)


def _containment_released(p: StateProjection, ev: Event) -> None:
    view = _matching_containment(p, ev)
    if view.state is ContainmentState.RELEASED:
        raise TransitionError(
            f"duplicate ExecutionContainmentReleased for "
            f"{view.execution_id}/{view.generation} (event {ev.event_id})")
    _string(ev.payload, "proof_kind", ev)
    _nonempty_mapping(ev.payload, "proof", ev)
    _string(ev.payload, "proof_ts", ev)
    view.state = ContainmentState.RELEASED
    view.released = dict(ev.payload)


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
    if ev.type is EventType.EXECUTION_FINISHED:
        view.end_commit = ev.payload.get("end_commit")
        if ev.payload.get("outcome") == "REJECTED":
            view.taxonomy_category = ev.payload.get("taxonomy_category")
    elif ev.type is EventType.EXECUTION_CRASHED:
        view.taxonomy_category = ev.payload.get("last_known_state") or "crashed"
    elif ev.type is EventType.VALIDATION_PASSED:
        view.validated_commit = ev.payload.get("validated_commit")
    elif ev.type is EventType.VALIDATION_FAILED:
        view.taxonomy_category = ev.payload.get("taxonomy_category")
    elif ev.type is EventType.REVIEW_APPROVED:
        view.reviewed_commit = ev.payload.get("reviewed_commit")
    elif ev.type is EventType.REVIEW_REJECTED:
        view.taxonomy_category = ev.payload.get("taxonomy_category")
        view.feedback = list(ev.payload.get("feedback") or [])


def _commit_intent(p: StateProjection, ev: Event) -> None:
    view = _accepted_view(p, ev)
    if view.commit_intended:
        raise TransitionError(
            f"duplicate CommitIntent for {view.execution_id} (event {ev.event_id})")
    view.commit_intended = True
    view.intent_end_commit = ev.payload.get("end_commit")
    view.intent_target_branch = ev.payload.get("target_branch")


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
    EventType.EXECUTION_CONTAINMENT_PREPARED: _containment_prepared,
    EventType.EXECUTION_CONTAINMENT_ESTABLISHED: _containment_established,
    EventType.EXECUTION_TERMINATION_UNCONFIRMED: _termination_unconfirmed,
    EventType.EXECUTION_CONTAINMENT_RELEASED: _containment_released,
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
