"""Containment-event replay contract; no engine or Win32 execution."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.projections import ContainmentState, StateProjection
from runtime.events.schema import Event, EventType
from runtime.state.model import IssueState
from runtime.state.transitions import TransitionError


def _event(event_id: int, etype: EventType, payload: dict, *, xid="042-e1") -> Event:
    return Event(etype, event_id=event_id, issue_id="042", execution_id=xid,
                 payload=payload)


def _prefix(xid="042-e1") -> list[Event]:
    return [
        Event(EventType.ISSUE_CREATED, event_id=1, issue_id="042"),
        Event(EventType.ISSUE_ACTIVATED, event_id=2, issue_id="042",
              payload={"base_commit": "c0"}),
        Event(EventType.EXECUTION_SPAWNED, event_id=3, issue_id="042",
              execution_id=xid, payload={"spawn_reason": "initial"}),
    ]


def _prepared(workspace_key="ws-a", generation="g1") -> dict:
    return {
        "workspace_key": workspace_key,
        "containment_generation": generation,
        "protocol_version": "windows-job-v1",
        "launch_mode": "windows-job-list-at-create",
        "controller": {"pid": 101, "creation_time": "ct-controller"},
        "lease": {"scope": "Global", "version": "v1"},
    }


def _established(workspace_key="ws-a", generation="g1") -> dict:
    return {
        "workspace_key": workspace_key,
        "containment_generation": generation,
        "root_suspended": True,
        "root": {"pid": 202, "creation_time": "ct-root"},
        "job": {"kill_on_job_close": True, "breakaway_ok": False,
                "silent_breakaway_ok": False},
        "membership": {"root_member": True, "member_count": 1},
    }


def _unconfirmed(workspace_key="ws-a", generation="g1") -> dict:
    return {
        "workspace_key": workspace_key,
        "containment_generation": generation,
        "stage": "termination-confirmation",
        "category": "deadline-expired",
        "diagnostic": {"artifact": "artifacts/042-e1/containment.json"},
    }


def _released(workspace_key="ws-a", generation="g1") -> dict:
    return {
        "workspace_key": workspace_key,
        "containment_generation": generation,
        "proof_kind": "job-member-count-zero",
        "proof": {"member_count": 0},
        "proof_ts": "2026-08-15T00:00:00Z",
    }


def _project(events: list[Event]) -> StateProjection:
    return StateProjection().rebuild(iter(events))


def test_prepared_projects_unreleased_workspace_blocker():
    p = _project(_prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
    ])
    view = p.containments[("042-e1", "g1")]
    assert view.state is ContainmentState.PREPARED
    assert p.is_workspace_blocked("ws-a")
    assert p.unreleased_containments("ws-a") == [view]


def test_containment_event_schema_roundtrip_and_kinds():
    prepared = _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared())
    established = _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established())
    assert Event.from_line(prepared.to_line()).kind.value == "intent"
    assert Event.from_line(established.to_line()).kind.value == "fact"


def test_established_and_unconfirmed_remain_blocked():
    p = _project(_prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
        _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
        _event(6, EventType.EXECUTION_TERMINATION_UNCONFIRMED, _unconfirmed()),
    ])
    assert p.containments[("042-e1", "g1")].state is ContainmentState.UNCONFIRMED
    assert p.is_workspace_blocked("ws-a")


def test_released_removes_only_matching_generation_blocker():
    p = _project(_prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
        _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
        _event(6, EventType.EXECUTION_CONTAINMENT_RELEASED, _released()),
    ])
    assert p.containments[("042-e1", "g1")].state is ContainmentState.RELEASED
    assert not p.is_workspace_blocked("ws-a")


def test_workspaces_project_independently():
    p = _project(_prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared("ws-a", "g1")),
        _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established("ws-a", "g1")),
        _event(6, EventType.EXECUTION_CONTAINMENT_RELEASED, _released("ws-a", "g1")),
        _event(7, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared("ws-b", "g2")),
    ])
    assert not p.is_workspace_blocked("ws-a")
    assert p.is_workspace_blocked("ws-b")


def test_release_generation_mismatch_does_not_clear_blocker():
    events = _prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared("ws-a", "g1")),
        _event(5, EventType.EXECUTION_CONTAINMENT_RELEASED, _released("ws-a", "g2")),
    ]
    with pytest.raises(TransitionError):
        _project(events)


@pytest.mark.parametrize(
    ("etype", "payload"),
    [
        (EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
        (EventType.EXECUTION_TERMINATION_UNCONFIRMED, _unconfirmed()),
    ],
)
def test_established_or_unconfirmed_without_required_predecessor_is_illegal(etype, payload):
    with pytest.raises(TransitionError):
        _project(_prefix() + [_event(4, etype, payload)])


def test_duplicate_containment_facts_are_illegal():
    events = _prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
        _event(5, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
    ]
    with pytest.raises(TransitionError):
        _project(events)


def test_duplicate_release_and_malformed_prepared_are_illegal():
    events = _prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
        _event(5, EventType.EXECUTION_CONTAINMENT_RELEASED, _released()),
        _event(6, EventType.EXECUTION_CONTAINMENT_RELEASED, _released()),
    ]
    with pytest.raises(TransitionError):
        _project(events)

    malformed = _prepared()
    del malformed["controller"]
    with pytest.raises(TransitionError):
        _project(_prefix() + [
            _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, malformed),
        ])

    empty_proof = _released()
    empty_proof["proof"] = {}
    with pytest.raises(TransitionError):
        _project(_prefix() + [
            _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
            _event(5, EventType.EXECUTION_CONTAINMENT_RELEASED, empty_proof),
        ])

    events = _prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
        _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
        _event(6, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
    ]
    with pytest.raises(TransitionError):
        _project(events)


def test_sequential_generations_do_not_release_one_another():
    p = _project(_prefix() + [
        _event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared("ws-a", "g1")),
        _event(5, EventType.EXECUTION_CONTAINMENT_RELEASED, _released("ws-a", "g1")),
        _event(6, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared("ws-a", "g2")),
    ])
    assert p.containments[("042-e1", "g1")].state is ContainmentState.RELEASED
    assert p.containments[("042-e1", "g2")].state is ContainmentState.PREPARED
    assert p.is_workspace_blocked("ws-a")


def test_historical_events_without_containment_replay_unchanged():
    p = _project(_prefix())
    baseline = StateProjection().rebuild(iter(_prefix()))
    assert p.containments == {}
    assert p.issues["042"] is IssueState.ACTIVE
    assert not p.is_workspace_blocked("ws-a")
    assert p.digest() == baseline.digest()
