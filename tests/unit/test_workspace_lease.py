"""Lease, controller-proof, and containment-first startup tests; no Win32 calls."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.projections import StateProjection
from runtime.events.schema import Event, EventType
from runtime.recovery.containment import (  # noqa: E402
    WorkspaceContainmentBlocked,
    resolve_startup_containment,
)
from runtime.recovery.reconciler import recover
from runtime.workspace_lease import (  # noqa: E402
    ControllerIdentityState,
    LeaseState,
    WAIT_ABANDONED,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    WorkspaceLease,
    mutex_name_for_workspace,
    probe_controller_identity,
    workspace_key,
)


class FakeMutexApi:
    def __init__(self, wait=WAIT_OBJECT_0, inheritable=False, create_handle=41):
        self.wait = wait
        self.inheritable = inheritable
        self.create_handle = create_handle
        self.calls: list[str] = []

    def create_mutex(self, name):
        self.calls.append("create")
        return self.create_handle, 0

    def clear_inherit(self, handle):
        self.calls.append("clear")
        self.inheritable = False
        return True, 0

    def is_inheritable(self, handle):
        self.calls.append("verify")
        return self.inheritable, 0

    def wait_zero(self, handle):
        self.calls.append("wait")
        return self.wait, 0

    def release_mutex(self, handle):
        self.calls.append("release")
        return True, 0

    def close_handle(self, handle):
        self.calls.append("close")
        return True, 0


class FakeProcessApi:
    def __init__(self, result): self.result = result
    def probe(self, pid): return self.result


_WORKSPACE = Path("C:/draindeck-unit-workspace")


def test_workspace_identity_and_mutex_name_are_deterministic_and_distinct():
    same = _WORKSPACE / "work"
    assert workspace_key(same) == workspace_key(str(same))
    assert mutex_name_for_workspace(same) == mutex_name_for_workspace(same)
    assert mutex_name_for_workspace(same) != mutex_name_for_workspace(_WORKSPACE / "other")
    assert mutex_name_for_workspace(same).startswith("Global\\draindeck-workspace-v1-")


def test_lease_acquisition_states_and_balanced_close():
    api = FakeMutexApi()
    lease = WorkspaceLease.acquire(_WORKSPACE, api=api)
    assert lease.state is LeaseState.ACQUIRED
    assert lease.acquired
    assert api.calls[:4] == ["create", "clear", "verify", "wait"]
    lease.release_and_close()
    assert api.calls[-2:] == ["release", "close"]
    lease.release_and_close()
    assert api.calls.count("release") == 1

    owner = WorkspaceLease.acquire(_WORKSPACE / "same-process", api=FakeMutexApi())
    duplicate = WorkspaceLease.acquire(_WORKSPACE / "same-process", api=FakeMutexApi())
    assert duplicate.state is LeaseState.ERROR
    owner.release_and_close()

    assert WorkspaceLease.acquire(_WORKSPACE, api=FakeMutexApi(wait=WAIT_TIMEOUT)).state is LeaseState.UNAVAILABLE
    assert WorkspaceLease.acquire(_WORKSPACE, api=FakeMutexApi(wait=WAIT_ABANDONED)).state is LeaseState.ABANDONED_ACQUIRED


def test_lease_inheritance_or_wait_error_fails_closed():
    class BadInherit(FakeMutexApi):
        def clear_inherit(self, handle):
            self.calls.append("clear")
            return False, 5
    lease = WorkspaceLease.acquire(_WORKSPACE, api=BadInherit())
    assert lease.state is LeaseState.ERROR
    assert not lease.acquired


@pytest.mark.parametrize(("probe", "expected"), [
    (("live", "same", 0), ControllerIdentityState.LIVE_MATCH),
    (("dead", None, 87), ControllerIdentityState.DEAD),
    (("live", "different", 0), ControllerIdentityState.PID_REUSED),
    (("unknown", None, 5), ControllerIdentityState.UNKNOWN),
])
def test_controller_identity_classification(probe, expected):
    result = probe_controller_identity({"pid": 7, "creation_time": "same"}, api=FakeProcessApi(probe))
    assert result.state is expected


def _event(event_id, kind, payload, *, xid="42-e1"):
    return Event(kind, event_id=event_id, issue_id="42", execution_id=xid, payload=payload)


def _prepared(ws="ws", generation="g"):
    return {"workspace_key": ws, "containment_generation": generation,
            "protocol_version": "windows-job-v1", "launch_mode": "windows-job-list-at-create",
            "controller": {"pid": 7, "creation_time": "ct"},
            "lease": {"scope": "Global", "version": "v1"}}


def _established(ws="ws", generation="g"):
    return {"workspace_key": ws, "containment_generation": generation, "root_suspended": True,
            "root": {"pid": 8, "creation_time": "root"},
            "job": {"kill_on_job_close": True, "breakaway_ok": False, "silent_breakaway_ok": False},
            "membership": {"root_member": True, "member_count": 1}}


def _unconfirmed(ws="ws", generation="g"):
    return {"workspace_key": ws, "containment_generation": generation,
            "stage": "termination", "category": "unknown", "diagnostic": {"id": "x"}}


class MemoryLog:
    def __init__(self, events): self.events = list(events)
    def replay(self): return iter(self.events)
    def append(self, event):
        eid = len(self.events) + 1
        self.events.append(Event(event.type, payload=event.payload, issue_id=event.issue_id,
                                 execution_id=event.execution_id, run_id=event.run_id,
                                 ts=event.ts, event_id=eid))
        return eid


def _prefix():
    return [Event(EventType.ISSUE_CREATED, event_id=1, issue_id="42"),
            Event(EventType.ISSUE_ACTIVATED, event_id=2, issue_id="42", payload={"base_commit": "a"}),
            Event(EventType.EXECUTION_SPAWNED, event_id=3, issue_id="42", execution_id="42-e1", payload={})]


def _probe(state):
    return lambda _identity: SimpleNamespace(state=state, detail=state.value)


@pytest.mark.parametrize("owner_state", [ControllerIdentityState.DEAD, ControllerIdentityState.PID_REUSED])
def test_restart_release_requires_qualified_dead_or_reused_and_is_scoped(owner_state):
    log = MemoryLog(_prefix() + [_event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared()),
                                 _event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established())])
    result = resolve_startup_containment(log, "ws", controller_probe=_probe(owner_state),
                                         now=lambda: datetime.datetime(2026, 8, 15, tzinfo=datetime.timezone.utc))
    assert result.released == ("42-e1/g",)
    assert not result.projection.is_workspace_blocked("ws")
    assert log.events[-1].type is EventType.EXECUTION_CONTAINMENT_RELEASED
    assert log.events[-1].payload["proof"]["controller_identity_state"] == owner_state.value


@pytest.mark.parametrize("state", [ControllerIdentityState.LIVE_MATCH, ControllerIdentityState.UNKNOWN])
def test_unreleased_prepared_established_or_unconfirmed_blocks_for_live_or_unknown(state):
    for boundary in ([], [_event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established())],
                     [_event(5, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, _established()),
                      _event(6, EventType.EXECUTION_TERMINATION_UNCONFIRMED, _unconfirmed())]):
        log = MemoryLog(_prefix() + [_event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared())] + boundary)
        with pytest.raises(WorkspaceContainmentBlocked):
            resolve_startup_containment(log, "ws", controller_probe=_probe(state))


def test_malformed_or_non_atomic_containment_evidence_fails_closed():
    prepared = _prepared()
    prepared["launch_mode"] = "legacy-create-process"
    log = MemoryLog(_prefix() + [_event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, prepared)])
    with pytest.raises(WorkspaceContainmentBlocked):
        resolve_startup_containment(log, "ws", controller_probe=_probe(ControllerIdentityState.DEAD))


def test_historical_log_without_containment_is_permitted():
    result = resolve_startup_containment(MemoryLog(_prefix()), "ws", controller_probe=_probe(ControllerIdentityState.UNKNOWN))
    assert result.released == ()
    assert not result.projection.is_workspace_blocked("ws")


def test_recovery_guard_prevents_all_workspace_seams_before_mutation():
    log = MemoryLog(_prefix() + [_event(4, EventType.EXECUTION_CONTAINMENT_PREPARED, _prepared())])
    called = []
    with pytest.raises(WorkspaceContainmentBlocked):
        recover(log, workspace_key="ws", recover_workspace=lambda: called.append("mutated"))
    assert called == []


def test_main_ownership_and_containment_gate_precedes_engine_and_recovery():
    from runtime import main as main_mod
    cfg = mock.MagicMock(project=mock.MagicMock(repository=str(_WORKSPACE), branch="main", validation=mock.MagicMock()),
                         event_log=mock.MagicMock(path="C:/draindeck-unit-state/events.jsonl"),
                         engine=mock.MagicMock(provider="claude-headless", model="default",
                                               max_turns=30, timeout_seconds=1800),
                         reviewer=mock.MagicMock(provider="qwen",
                                                 qwen=mock.MagicMock(model="qwen2.5-coder")),
                         budget=mock.MagicMock(max_attempts_per_issue=3, max_executions_per_run=10,
                                               hard_stop_proxy_cost_per_run_usd=15.0,
                                               proxy_pricing="api_list_rates"),
                         attempts=mock.MagicMock(ref_namespace="refs/a"))
    args = SimpleNamespace(config="x", skip_baseline=True)
    calls = []
    lease = mock.MagicMock(acquired=True, workspace_key="ws", state=SimpleNamespace(value="ACQUIRED"), detail="ok")
    engine = mock.MagicMock()
    engine.reap_orphans.side_effect = lambda: calls.append("reap") or []
    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod.WorkspaceLease, "acquire", side_effect=lambda _w: calls.append("lease") or lease), \
         mock.patch.object(main_mod.Path, "mkdir"), \
         mock.patch.object(main_mod, "EventLog"), \
         mock.patch.object(main_mod, "resolve_startup_containment", side_effect=lambda *_a, **_k: calls.append("containment") or mock.MagicMock()), \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine", return_value=engine), \
         mock.patch.object(main_mod, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main_mod, "bind_reconciler", return_value={}), \
         mock.patch.object(main_mod, "recover", side_effect=lambda *_a, **_k: (calls.append("recover") or (mock.MagicMock(), SimpleNamespace(orphans_crashed=[], workspace_repairs=[], replayed_events=1)))), \
         mock.patch.object(main_mod, "_reviewer_reachable", return_value=(False, "stop")):
        assert main_mod.cmd_run(args) == 1
    assert calls[:4] == ["lease", "containment", "reap", "recover"]


def test_lease_contention_prevents_log_engine_and_recovery():
    from runtime import main as main_mod
    cfg = mock.MagicMock(project=mock.MagicMock(repository=str(_WORKSPACE)), event_log=mock.MagicMock())
    lease = mock.MagicMock(acquired=False, state=SimpleNamespace(value="UNAVAILABLE"), detail="owned")
    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main_mod, "EventLog") as log, \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine") as engine, \
         mock.patch.object(main_mod, "recover") as recovery:
        assert main_mod.cmd_run(SimpleNamespace(config="x", skip_baseline=True)) == 1
    assert not log.called and not engine.called and not recovery.called
