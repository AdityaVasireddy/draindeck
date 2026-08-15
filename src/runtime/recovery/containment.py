"""Containment-first startup reconciliation; all evidence comes from events."""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Callable

from ..events.log import EventLog
from ..events.projections import ContainmentState, ContainmentView, StateProjection
from ..events.schema import Event, EventType
from ..workspace_lease import ControllerIdentityResult, ControllerIdentityState


class WorkspaceContainmentBlocked(RuntimeError):
    """An authoritative unreleased boundary prevents any workspace operation."""


@dataclass(frozen=True)
class ContainmentResolution:
    projection: StateProjection
    released: tuple[str, ...]


def resolve_startup_containment(
    log: EventLog,
    workspace_key: str,
    *,
    controller_probe: Callable[[object], ControllerIdentityResult],
    now: Callable[[], datetime.datetime] = lambda: datetime.datetime.now(datetime.timezone.utc),
) -> ContainmentResolution:
    """Release only exact, replay-valid prior-controller-death boundaries."""
    proj = StateProjection().rebuild(log.replay())
    released: list[str] = []
    for view in list(proj.unreleased_containments(workspace_key)):
        reason = _restart_release_reason(view, controller_probe)
        if reason is None:
            continue
        execution = proj.executions.get(view.execution_id)
        if execution is None:  # defensive: strict replay normally prevents this
            continue
        proof_ts = now().astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        event = Event(
            EventType.EXECUTION_CONTAINMENT_RELEASED,
            issue_id=execution.issue_id,
            execution_id=view.execution_id,
            payload={
                "workspace_key": workspace_key,
                "containment_generation": view.generation,
                "proof_kind": "restart-controller-death",
                "proof": reason,
                "proof_ts": proof_ts,
            },
        )
        eid = log.append(event)
        proj.apply(Event(event.type, payload=event.payload, issue_id=event.issue_id,
                         execution_id=event.execution_id, run_id=event.run_id,
                         ts=event.ts, event_id=eid))
        released.append(f"{view.execution_id}/{view.generation}")
    if proj.is_workspace_blocked(workspace_key):
        blocked = ", ".join(f"{v.execution_id}/{v.generation}" for v in proj.unreleased_containments(workspace_key))
        raise WorkspaceContainmentBlocked(f"unreleased execution containment: {blocked}")
    return ContainmentResolution(proj, tuple(released))


def _restart_release_reason(
    view: ContainmentView,
    controller_probe: Callable[[object], ControllerIdentityResult],
) -> dict | None:
    prepared = view.prepared
    # Prepared is the only durable assertion available before root creation;
    # it must identify the approved atomic-at-create protocol exactly.
    if prepared.get("protocol_version") != "windows-job-v1":
        return None
    if prepared.get("launch_mode") != "windows-job-list-at-create":
        return None
    lease = prepared.get("lease")
    if not isinstance(lease, dict) or lease.get("scope") != "Global" or lease.get("version") != "v1":
        return None
    if view.state in (ContainmentState.ESTABLISHED, ContainmentState.UNCONFIRMED):
        job = (view.established or {}).get("job")
        if not isinstance(job, dict) or job.get("kill_on_job_close") is not True or job.get("breakaway_ok") is not False or job.get("silent_breakaway_ok") is not False:
            return None
    result = controller_probe(prepared.get("controller"))
    if result.state not in (ControllerIdentityState.DEAD, ControllerIdentityState.PID_REUSED):
        return None
    return {
        "controller_identity_state": result.state.value,
        "controller_identity_detail": result.detail,
        "atomic_launch": prepared["launch_mode"],
        "protocol_version": prepared["protocol_version"],
        "lease": dict(lease),
    }
