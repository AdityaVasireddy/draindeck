"""ADR-30 RED 4: runtime exact allowlist, Orchestrator level.

Reuses test_loop.py's in-memory fakes and `_build` harness, extended with
`allowed_issue_ids`. See
docs/plans/dashboard-issue-run-control-failing-tests.md RED 4.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_loop import (  # noqa: E402
    FakeAdapter, FakeEngine, FakeReviewer, FakeValidator, _config,
)

from runtime.budget.manager import BudgetManager                     # noqa: E402
from runtime.events.log import EventLog                              # noqa: E402
from runtime.events.projections import StateProjection              # noqa: E402
from runtime.events.schema import Event, EventType                  # noqa: E402
from runtime.loop import Orchestrator                                # noqa: E402
from runtime.state.model import IssueState                          # noqa: E402


def _build(tmp_path, *, issues, allowed_issue_ids=None, engine=None, validator=None,
           reviewer=None, max_attempts=3, budget=None, cfg=None, active_ids=()):
    cfg = cfg or _config(max_attempts)
    log = EventLog(tmp_path / "events.jsonl")
    proj = StateProjection()
    for iid, deps in issues:
        ev = Event(EventType.ISSUE_CREATED, issue_id=iid,
                   payload={"title": f"Issue {iid}", "body": "b", "depends_on": deps})
        eid = log.append(ev)
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                         event_id=eid))
    for iid in active_ids:
        ev = Event(EventType.ISSUE_ACTIVATED, issue_id=iid, payload={"base_commit": "c0"})
        eid = log.append(ev)
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                         event_id=eid))
    orch = Orchestrator(
        cfg=cfg, log=log, proj=proj, adapter=FakeAdapter(),
        engine=engine or FakeEngine(artifacts_dir=tmp_path / "art"),
        validator=validator or FakeValidator(),
        reviewer=reviewer or FakeReviewer(),
        budget=budget or BudgetManager(50, 100.0),
        artifacts_dir=tmp_path / "art", run_id="run-test",
        allowed_issue_ids=allowed_issue_ids,
    )
    return orch


def test_runtime_never_activates_unselected_pending_issue(tmp_path):
    orch = _build(tmp_path, issues=[("a", []), ("b", [])], allowed_issue_ids=frozenset({"a"}))
    orch.run()
    assert orch.proj.issues["a"] is IssueState.DONE
    assert orch.proj.issues["b"] is IssueState.PENDING  # never touched
    assert orch.proj.counts.get("IssueActivated") == 1


def test_runtime_selected_queue_drained_ignores_unselected_actionable_issues(tmp_path):
    orch = _build(tmp_path, issues=[("a", []), ("b", [])], allowed_issue_ids=frozenset({"a"}))
    reason = orch.run()
    assert "drained" in reason
    assert orch.proj.issues["b"] is IssueState.PENDING


def test_runtime_resumes_selected_active_issue_before_later_selected_issue(tmp_path):
    orch = _build(tmp_path, issues=[("a", []), ("b", [])], active_ids=["a"],
                 allowed_issue_ids=frozenset({"a", "b"}))
    order: list[str] = []
    real_step = orch.step

    def spy_step(issue):
        order.append(issue)
        return real_step(issue)
    orch.step = spy_step
    orch.run()
    assert order[0] == "a"  # ACTIVE always wins over a later PENDING, allowlist or not


def test_runtime_refuses_when_active_issue_is_outside_allowlist():
    from runtime.queue.issues_md import IssueSpec
    from runtime.queue.selection import plan_selected
    specs = [IssueSpec(id="a", title="A"), IssueSpec(id="b", title="B")]
    result = plan_selected(specs, {"a": "ACTIVE"}, ["b"])
    assert result.ok is False
    assert result.omitted_active_ids == ("a",)


def test_runtime_independent_selected_issues_use_file_order(tmp_path):
    orch = _build(tmp_path, issues=[("z", []), ("a", []), ("m", [])],
                 allowed_issue_ids=frozenset({"z", "a", "m"}))
    order: list[str] = []
    real_step = orch.step

    def spy_step(issue):
        if issue not in order:
            order.append(issue)
        return real_step(issue)
    orch.step = spy_step
    orch.run()
    assert order == ["z", "a", "m"]  # proj.issues preserves IssueCreated/file order


def test_allowed_issue_ids_none_preserves_existing_unfiltered_behavior(tmp_path):
    """Every pre-existing direct-CLI call site passes no allowed_issue_ids at
    all; the default None must behave byte-identically to before this ADR."""
    orch = _build(tmp_path, issues=[("a", []), ("b", [])])  # allowed_issue_ids=None
    orch.run()
    assert orch.proj.issues["a"] is IssueState.DONE
    assert orch.proj.issues["b"] is IssueState.DONE
