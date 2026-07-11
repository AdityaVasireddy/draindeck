"""Crash recovery — RECONCILED against doc 03.

Runs unconditionally at every startup. Ordering law: a crash may only
leave a missing FACT, which the reconciler backfills.

Check 1 (log-complete here): an EXECUTING view with no live engine
process is an orphan. Doc 03 is explicit: EXECUTING is **abandonable,
never resumed** — residue is preserved to an attempt ref, then
ExecutionCrashed is emitted, then the workspace is reset. There is no
"witness as finished" path: an unwitnessed engine exit cannot be
distinguished from a partial run, so it is always CRASHED and the retry
policy spawns a fresh execution.

Checks 2 (unwitnessed commit → CommitCreated(backfilled=true)) and 3
(dirty workspace) need the RepositoryAdapter and are injectable seams;
None ⇒ the check is SKIPPED and reported as such — recovery never
silently claims a check it did not run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..events.log import EventLog
from ..events.projections import StateProjection
from ..events.schema import Event, EventType

# Seam signatures (bound to RepositoryAdapter in a later session):
#   is_execution_alive(execution_id) -> bool
#   preserve_residue(execution_id) -> str | None
#       Commit workspace residue to refs/attempts/<issue>/<execution>,
#       return the ref (None = nothing to preserve). Runs BEFORE the
#       ExecutionCrashed fact, matching residue→ref→event ordering.
#   check_unwitnessed_commit(projection) -> list[Event]   (check 2)
#   check_dirty_workspace(projection) -> list[Event]      (check 3)


@dataclass
class RecoveryReport:
    replayed_events: int = 0
    orphans_crashed: list[str] = field(default_factory=list)
    emitted: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    checks_skipped: list[str] = field(default_factory=list)


def recover(
    log: EventLog,
    *,
    is_execution_alive: Callable[[str], bool] = lambda _xid: False,
    preserve_residue: Optional[Callable[[str], Optional[str]]] = None,
    check_unwitnessed_commit=None,
    check_dirty_workspace=None,
) -> tuple[StateProjection, RecoveryReport]:
    """Replay, reconcile, return a projection consistent with the world.

    Crash-safe and idempotent: repairs go through the same durable
    append path as all other events; a crash mid-recovery leaves the
    already-durable repairs for the next startup to replay, and repairs
    move executions to terminal states so a second pass finds nothing.
    """
    report = RecoveryReport()
    proj = StateProjection()
    for ev in log.replay():
        proj.apply(ev)
        report.replayed_events += 1

    # ── check 1: orphaned executions ─────────────────────────────
    report.checks_run.append("orphaned_execution")
    for view in proj.open_executions():
        if is_execution_alive(view.execution_id):
            continue  # legitimately still running
        residue_ref = preserve_residue(view.execution_id) if preserve_residue else None
        ev = Event(
            type=EventType.EXECUTION_CRASHED,
            issue_id=view.issue_id,
            execution_id=view.execution_id,
            payload={"residue_ref": residue_ref,
                     "last_known_state": view.state.value},
        )
        _emit(log, proj, ev)
        report.orphans_crashed.append(view.execution_id)
        report.emitted.append(ev.type.value)

    # ── checks 2 & 3: repo-dependent, injectable ─────────────────
    for name, fn in (
        ("unwitnessed_commit", check_unwitnessed_commit),
        ("dirty_workspace", check_dirty_workspace),
    ):
        if fn is None:
            report.checks_skipped.append(name)
            continue
        report.checks_run.append(name)
        for ev in fn(proj):
            _emit(log, proj, ev)
            report.emitted.append(ev.type.value)

    return proj, report


def _emit(log: EventLog, proj: StateProjection, ev: Event) -> Event:
    eid = log.append(ev)
    persisted = Event(
        type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
        execution_id=ev.execution_id, run_id=ev.run_id,
        ts=ev.ts, event_id=eid,
    )
    proj.apply(persisted)
    return persisted
