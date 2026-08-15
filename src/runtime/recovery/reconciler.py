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
from ..events.projections import ExecutionView, StateProjection
from ..events.schema import Event, EventType
from .containment import WorkspaceContainmentBlocked

# Seam signatures (bound to RepositoryAdapter via recovery/bindings.py):
#   is_execution_alive(execution_id) -> bool
#   preserve_residue(view: ExecutionView) -> str | None
#       Commit workspace residue to refs/attempts/<issue>/<execution>,
#       return the ref (None = nothing to preserve). Runs BEFORE the
#       ExecutionCrashed fact, matching residue→ref→event ordering. Takes
#       the whole view (needs issue_id for the ref, base_commit to detect
#       "nothing happened") — parsing issue ids out of execution ids would
#       be a hidden format coupling.
#   recover_workspace() -> list[str]
#       Clear stale git locks / in-progress merge state left by a killed
#       process (§1.2); runs ONCE before check 1. None ⇒ skipped.
#   check_unwitnessed_commit(projection) -> list[Event]   (check 2)
#   check_dirty_workspace(projection) -> list[Event]      (check 3)


@dataclass
class RecoveryReport:
    replayed_events: int = 0
    orphans_crashed: list[str] = field(default_factory=list)
    emitted: list[str] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    checks_skipped: list[str] = field(default_factory=list)
    # Check 3 (dirty workspace) has no event in doc 03's frozen vocabulary
    # (inventing one would be an ADR); its evidence trail is the attempt ref
    # plus these repair strings, so recovery still never silently claims work.
    workspace_repairs: list[str] = field(default_factory=list)


def recover(
    log: EventLog,
    *,
    is_execution_alive: Callable[[str], bool] = lambda _xid: False,
    preserve_residue: Optional[Callable[[ExecutionView], Optional[str]]] = None,
    recover_workspace: Optional[Callable[[], list[str]]] = None,
    check_unwitnessed_commit=None,
    check_dirty_workspace=None,
    workspace_key: Optional[str] = None,
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

    # This is the recovery-side defense in depth.  ``cmd_run`` resolves
    # qualifying prior-controller death first; any remaining boundary is an
    # authoritative stop before *any* injected repository seam can mutate.
    if workspace_key is not None and proj.is_workspace_blocked(workspace_key):
        raise WorkspaceContainmentBlocked(
            f"workspace {workspace_key} has unreleased execution containment")

    # ── workspace repair: clear killed-git debris before any git op ──
    if recover_workspace is not None:
        report.workspace_repairs.extend(recover_workspace())

    # ── check 1: orphaned executions ─────────────────────────────
    report.checks_run.append("orphaned_execution")
    for view in proj.open_executions():
        if is_execution_alive(view.execution_id):
            continue  # legitimately still running
        residue_ref = preserve_residue(view) if preserve_residue else None
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
        # A repo check with no doc-03 event (check 3) reports its work via a
        # ``repairs`` attribute instead — harvest it so recovery still never
        # silently claims work it did (see recovery/bindings.py).
        repairs = getattr(fn, "repairs", None)
        if repairs:
            report.workspace_repairs.extend(repairs)

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
