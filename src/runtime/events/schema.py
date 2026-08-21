"""Event schema — RECONCILED against doc 03 (frozen v1.0, 2026-07-05).

Envelope (doc 03 §3): event_id (monotonic int, single writer — assigned
by the log on append), schema_version, ts, run_id, type, issue_id,
execution_id, payload. ``kind`` (intent/fact) is schema knowledge held
here in code, NOT a serialized field. Type strings are CamelCase per the
contract. Events are never edited or deleted; new needs mean a new type
or a bumped schema_version.

Ordering law (I5/I6): intent events before the effect, fact events
after; a crash may therefore only leave a missing FACT, which the
reconciler backfills.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

SCHEMA_VERSION = 1


class Kind(str, Enum):
    INTENT = "intent"  # fsync'd BEFORE the action it announces
    FACT = "fact"      # appended AFTER the effect is observed


class EventType(str, Enum):
    # doc 03 §3, verbatim type strings
    ISSUE_CREATED = "IssueCreated"
    ISSUE_ACTIVATED = "IssueActivated"
    EXECUTION_SPAWNED = "ExecutionSpawned"          # intent
    EXECUTION_CONTAINMENT_PREPARED = "ExecutionContainmentPrepared"  # intent
    EXECUTION_CONTAINMENT_ESTABLISHED = "ExecutionContainmentEstablished"
    EXECUTION_TERMINATION_UNCONFIRMED = "ExecutionTerminationUnconfirmed"
    EXECUTION_CONTAINMENT_RELEASED = "ExecutionContainmentReleased"
    EXECUTION_FINISHED = "ExecutionFinished"
    EXECUTION_CRASHED = "ExecutionCrashed"          # reconciler-assigned
    VALIDATION_PASSED = "ValidationPassed"
    VALIDATION_FAILED = "ValidationFailed"
    REVIEW_APPROVED = "ReviewApproved"
    REVIEW_REJECTED = "ReviewRejected"
    COMMIT_INTENT = "CommitIntent"                  # intent
    COMMIT_CREATED = "CommitCreated"
    ISSUE_COMPLETED = "IssueCompleted"
    ISSUE_ESCALATED = "IssueEscalated"
    HUMAN_INTERVENTION = "HumanIntervention"
    GUIDELINE_PROMOTED = "GuidelinePromoted"
    RUN_STARTED = "RunStarted"                      # intent — doc 03 amendment 2026-08-21
    RUN_FINISHED = "RunFinished"                     # doc 03 amendment 2026-08-21


KIND_OF: dict[EventType, Kind] = {
    t: Kind.FACT for t in EventType
}
KIND_OF[EventType.EXECUTION_SPAWNED] = Kind.INTENT
KIND_OF[EventType.EXECUTION_CONTAINMENT_PREPARED] = Kind.INTENT
KIND_OF[EventType.COMMIT_INTENT] = Kind.INTENT
# RUN_STARTED is Kind.INTENT for write-ordering purposes only (fsync'd
# before the normal-run work it announces) — deliberately NOT added to
# RESOLUTION_OF below. The reconciler must never attempt to resolve, heal,
# or backfill a RunFinished for an orphaned RunStarted; an unresolved
# RunStarted after abrupt death is a permanent, honest record, not a gap
# the reconciler is expected to close (doc 03 amendment, "Event vocabulary
# addition").
KIND_OF[EventType.RUN_STARTED] = Kind.INTENT

# Intents and the facts that resolve them (recovery + harness use this).
RESOLUTION_OF: dict[EventType, frozenset[EventType]] = {
    EventType.EXECUTION_SPAWNED: frozenset(
        {EventType.EXECUTION_FINISHED, EventType.EXECUTION_CRASHED}
    ),
    EventType.EXECUTION_CONTAINMENT_PREPARED: frozenset(
        {EventType.EXECUTION_CONTAINMENT_ESTABLISHED,
         EventType.EXECUTION_CONTAINMENT_RELEASED}
    ),
    EventType.COMMIT_INTENT: frozenset({EventType.COMMIT_CREATED}),
}


class SchemaError(ValueError):
    """An event violates the envelope contract."""


def _utcnow() -> str:
    # doc 03 shows seconds precision with Z suffix; ordering comes from
    # event_id, not timestamps.
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    """Immutable envelope. event_id is assigned by the log on append
    (0 = unassigned); events read from disk always carry theirs."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    issue_id: Optional[str] = None
    execution_id: Optional[str] = None
    run_id: Optional[str] = None
    ts: str = field(default_factory=_utcnow)
    event_id: int = 0
    schema_version: int = SCHEMA_VERSION

    @property
    def kind(self) -> Kind:
        return KIND_OF[self.type]

    def to_line(self) -> bytes:
        obj = {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "ts": self.ts,
            "run_id": self.run_id,
            "type": self.type.value,
            "issue_id": self.issue_id,
            "execution_id": self.execution_id,
            "payload": self.payload,
        }
        # sort_keys + compact separators ⇒ canonical bytes ⇒ deterministic
        # replay digests. Key order on disk is not contract-bearing.
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"

    @classmethod
    def from_line(cls, raw: bytes) -> "Event":
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise SchemaError(f"unparseable event line: {e}") from e
        try:
            etype = EventType(obj["type"])
        except (KeyError, ValueError) as e:
            raise SchemaError(f"unknown event type: {obj.get('type')!r}") from e
        sv = obj.get("schema_version")
        if sv != SCHEMA_VERSION:
            raise SchemaError(f"unsupported schema_version {sv!r}")
        eid = obj.get("event_id")
        if not isinstance(eid, int) or eid < 1:
            raise SchemaError(f"invalid event_id {eid!r}")
        if not isinstance(obj.get("payload"), dict):
            raise SchemaError("payload must be an object")
        return cls(
            type=etype, payload=obj["payload"],
            issue_id=obj.get("issue_id"), execution_id=obj.get("execution_id"),
            run_id=obj.get("run_id"), ts=obj["ts"],
            event_id=eid, schema_version=sv,
        )
