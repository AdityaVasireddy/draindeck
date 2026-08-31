"""ADR-30 RED 3: pure batch admission and deterministic ordering.

Pure inputs only (IssueSpec + an authoritative state map) -- no filesystem,
subprocess, SQLite, or browser. See
docs/plans/dashboard-issue-run-control-failing-tests.md RED 3 and
docs/31-dashboard-issue-run-control-outcome-matrix.md "Selection, terminal
handling, and dependency admission" / "Run-all admission".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.queue.issues_md import IssueSpec
from runtime.queue.selection import Blocker, plan_run_all, plan_selected


def _spec(id: str, *, depends_on: list[str] | None = None) -> IssueSpec:
    return IssueSpec(id=id, title=f"Title {id}", body=f"STATUS: DONE\nbody of {id}",
                     depends_on=depends_on or [])


def test_selected_empty_refuses_without_plan():
    result = plan_selected([_spec("a")], {}, [])
    assert result.ok is False
    assert result.empty_selection is True
    assert result.ordered_ids == ()


def test_selected_unknown_ids_are_all_reported():
    result = plan_selected([_spec("a")], {}, ["a", "ghost1", "ghost2"])
    assert result.ok is False
    assert set(result.unknown_ids) == {"ghost1", "ghost2"}


def test_selected_duplicate_ids_refuse_without_silent_dedupe():
    result = plan_selected([_spec("a")], {}, ["a", "a"])
    assert result.ok is False
    assert result.duplicate_ids == ("a",)


def test_selected_terminal_issues_are_all_reported_and_none_run():
    specs = [_spec("a"), _spec("b")]
    states = {"a": "DONE", "b": "NEEDS_HUMAN"}
    result = plan_selected(specs, states, ["a", "b"])
    assert result.ok is False
    assert {(t.issue_id, t.state) for t in result.terminal_selected} == {
        ("a", "DONE"), ("b", "NEEDS_HUMAN"),
    }
    assert result.ordered_ids == ()


def test_selected_done_dependency_need_not_be_selected():
    specs = [_spec("a", depends_on=["dep"])]
    states = {"dep": "DONE"}
    result = plan_selected(specs, states, ["a"])
    assert result.ok is True
    assert result.ordered_ids == ("a",)


def test_selected_unfinished_dependency_in_selection_is_allowed():
    specs = [_spec("a", depends_on=["dep"]), _spec("dep")]
    states = {"dep": "PENDING"}
    result = plan_selected(specs, states, ["a", "dep"])
    assert result.ok is True
    assert result.ordered_ids == ("dep", "a")


def test_selected_unfinished_dependency_outside_selection_refuses_whole_batch():
    specs = [_spec("a", depends_on=["dep"]), _spec("dep")]
    states = {"dep": "PENDING"}
    result = plan_selected(specs, states, ["a"])
    assert result.ok is False
    assert result.blockers == (Blocker("a", "dep", "PENDING"),)


def test_selected_reports_every_missing_dependency_for_every_issue():
    specs = [
        _spec("a", depends_on=["d1", "d2"]),
        _spec("b", depends_on=["d3"]),
    ]
    states = {}
    result = plan_selected(specs, states, ["a", "b"])
    assert result.ok is False
    reported = {(b.issue_id, b.missing_dependency_id) for b in result.blockers}
    assert reported == {("a", "d1"), ("a", "d2"), ("b", "d3")}


def test_unknown_dependency_is_unfinished_and_blocks():
    specs = [_spec("a", depends_on=["nowhere"])]
    result = plan_selected(specs, {}, ["a"])
    assert result.ok is False
    assert result.blockers[0].missing_dependency_id == "nowhere"
    assert result.blockers[0].dependency_state == "UNKNOWN"


def test_dependency_absent_from_file_but_done_in_events_is_satisfied():
    specs = [_spec("a", depends_on=["ghost-dep"])]
    states = {"ghost-dep": "DONE"}
    result = plan_selected(specs, states, ["a"])
    assert result.ok is True


def test_needs_human_or_decomposition_dependency_is_not_done():
    specs = [_spec("a", depends_on=["dep"])]
    for terminal_state in ("NEEDS_HUMAN", "NEEDS_DECOMPOSITION"):
        states = {"dep": terminal_state}
        result = plan_selected(specs, states, ["a"])
        assert result.ok is False
        assert result.blockers[0].dependency_state == terminal_state


def test_self_dependency_reports_cycle():
    specs = [_spec("a", depends_on=["a"])]
    result = plan_selected(specs, {}, ["a"])
    assert result.ok is False
    assert result.cycle_members == ("a",)


def test_multi_issue_dependency_cycle_reports_all_members():
    specs = [_spec("a", depends_on=["b"]), _spec("b", depends_on=["a"])]
    result = plan_selected(specs, {}, ["a", "b"])
    assert result.ok is False
    assert set(result.cycle_members) == {"a", "b"}


def test_selected_active_issue_is_included_once():
    specs = [_spec("a")]
    states = {"a": "ACTIVE"}
    result = plan_selected(specs, states, ["a"])
    assert result.ok is True
    assert result.ordered_ids == ("a",)


def test_omitted_active_issue_refuses_new_selection():
    specs = [_spec("a"), _spec("b")]
    states = {"a": "ACTIVE"}
    result = plan_selected(specs, states, ["b"])
    assert result.ok is False
    assert result.omitted_active_ids == ("a",)


def test_dependency_order_is_topological():
    specs = [_spec("a", depends_on=["b"]), _spec("b")]
    result = plan_selected(specs, {}, ["a", "b"])
    assert result.ok is True
    assert result.ordered_ids == ("b", "a")


def test_file_order_breaks_topological_ties_deterministically():
    specs = [_spec("z"), _spec("a"), _spec("m")]  # independent, file order z, a, m
    result = plan_selected(specs, {}, ["a", "m", "z"])
    assert result.ok is True
    assert result.ordered_ids == ("z", "a", "m")


def test_run_all_includes_every_nonterminal_issue():
    specs = [_spec("a"), _spec("b")]
    states = {"a": "PENDING", "b": "ACTIVE"}
    result = plan_run_all(specs, states)
    assert result.ok is True
    assert set(result.ordered_ids) == {"a", "b"}


def test_run_all_excludes_terminal_issues_with_state_counts():
    specs = [_spec("a"), _spec("b"), _spec("c")]
    states = {"a": "DONE", "b": "NEEDS_HUMAN", "c": "PENDING"}
    result = plan_run_all(specs, states)
    assert result.ok is True
    assert result.ordered_ids == ("c",)
    assert {(e.issue_id, e.state) for e in result.excluded} == {("a", "DONE"), ("b", "NEEDS_HUMAN")}


def test_run_all_all_terminal_is_successful_noop():
    specs = [_spec("a"), _spec("b")]
    states = {"a": "DONE", "b": "NEEDS_DECOMPOSITION"}
    result = plan_run_all(specs, states)
    assert result.ok is True
    assert result.ordered_ids == ()
    assert len(result.excluded) == 2


def test_run_all_empty_file_is_successful_noop():
    result = plan_run_all([], {})
    assert result.ok is True
    assert result.ordered_ids == ()
    assert result.excluded == ()


def test_run_all_includes_full_nonterminal_dependency_chain():
    specs = [_spec("a", depends_on=["b"]), _spec("b", depends_on=["c"]), _spec("c")]
    result = plan_run_all(specs, {})
    assert result.ok is True
    assert result.ordered_ids == ("c", "b", "a")


def test_run_all_refuses_unfinished_dependency_outside_result_set():
    specs = [_spec("a", depends_on=["outside"])]
    result = plan_run_all(specs, {})
    assert result.ok is False
    assert result.blockers[0].missing_dependency_id == "outside"


def test_admission_never_reads_status_text_for_state():
    """Every fixture spec's body contains 'STATUS: DONE', but no fixture
    ever puts the corresponding id in the states map -- if the planner read
    body text for state, every one of the tests above using _spec() with a
    non-DONE expectation would already be failing. This test additionally
    proves it structurally: the planner module never accesses `.body`."""
    import ast
    source = Path("src/runtime/queue/selection.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    body_accesses = [
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "body"
    ]
    assert body_accesses == []
