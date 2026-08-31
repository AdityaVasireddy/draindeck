"""ADR-30 pure selection and dependency planner (RED 3).

Shared, framework-free, side-effect-free planner used by BOTH Dashboard API
admission and runtime re-validation (spec/dashboard-issue-run-control.md
"Pure selection and dependency planner"). Pure inputs only: the parsed
`IssueSpec` list (file order, from `runtime.queue.issues_md.parse`) plus an
authoritative map of issue_id -> state string (absent id = no event evidence
yet, i.e. NOT_INGESTED). No filesystem, subprocess, SQLite, or browser access
-- and this module never reads `IssueSpec.body`, so source text can never
influence a state decision (doc 31: "source status text never sets runtime
state").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from .issues_md import IssueSpec

TERMINAL_STATES = frozenset({"DONE", "NEEDS_HUMAN", "NEEDS_DECOMPOSITION"})
_SATISFYING_STATE = "DONE"
_ACTIVE_STATE = "ACTIVE"


@dataclass(frozen=True)
class Blocker:
    issue_id: str
    missing_dependency_id: str
    dependency_state: str  # a real IssueState value, "NOT_INGESTED", or "UNKNOWN"


@dataclass(frozen=True)
class TerminalExclusion:
    issue_id: str
    state: str


@dataclass(frozen=True)
class PlanResult:
    ok: bool
    ordered_ids: tuple[str, ...] = ()
    unknown_ids: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    terminal_selected: tuple[TerminalExclusion, ...] = ()
    blockers: tuple[Blocker, ...] = ()
    cycle_members: tuple[str, ...] = ()
    omitted_active_ids: tuple[str, ...] = ()
    excluded: tuple[TerminalExclusion, ...] = ()  # run-all only
    empty_selection: bool = False


def _state_of(issue_id: str, states: Mapping[str, str]) -> Optional[str]:
    return states.get(issue_id)


def _is_terminal(issue_id: str, states: Mapping[str, str]) -> bool:
    return _state_of(issue_id, states) in TERMINAL_STATES


def _dependency_state_label(dep_id: str, spec_by_id: Mapping[str, IssueSpec],
                            states: Mapping[str, str]) -> str:
    state = _state_of(dep_id, states)
    if state is not None:
        return state
    return "NOT_INGESTED" if dep_id in spec_by_id else "UNKNOWN"


def _is_satisfied(dep_id: str, states: Mapping[str, str]) -> bool:
    return _state_of(dep_id, states) == _SATISFYING_STATE


def _topological_order(ids_in_file_order: Sequence[str],
                       spec_by_id: Mapping[str, IssueSpec]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Kahn's algorithm restricted to edges within `ids_in_file_order`,
    always picking the earliest-file-order zero-indegree node so ties break
    deterministically by configured file order. Returns (ordered, leftover);
    a non-empty leftover means a cycle among exactly those members."""
    id_set = set(ids_in_file_order)
    indegree = {iid: 0 for iid in ids_in_file_order}
    dependents: dict[str, list[str]] = {iid: [] for iid in ids_in_file_order}
    for iid in ids_in_file_order:
        for dep in spec_by_id[iid].depends_on:
            if dep in id_set:
                indegree[iid] += 1
                dependents[dep].append(iid)

    remaining = list(ids_in_file_order)
    ordered: list[str] = []
    while remaining:
        ready = next((iid for iid in remaining if indegree[iid] == 0), None)
        if ready is None:
            return tuple(ordered), tuple(remaining)
        remaining.remove(ready)
        ordered.append(ready)
        for dependent in dependents[ready]:
            indegree[dependent] -= 1
    return tuple(ordered), ()


def plan_selected(specs: Sequence[IssueSpec], states: Mapping[str, str],
                  selected_ids: Sequence[str]) -> PlanResult:
    if not selected_ids:
        return PlanResult(ok=False, empty_selection=True)

    spec_by_id = {s.id: s for s in specs}

    seen: set[str] = set()
    duplicate_ids: list[str] = []
    for iid in selected_ids:
        if iid in seen and iid not in duplicate_ids:
            duplicate_ids.append(iid)
        seen.add(iid)

    unknown_ids = [iid for iid in dict.fromkeys(selected_ids) if iid not in spec_by_id]
    known_selected = [iid for iid in dict.fromkeys(selected_ids) if iid in spec_by_id]
    # Keep known_selected in configured file order (not request order) so
    # every downstream computation (terminal check, blockers, topological
    # sort) uses one single deterministic ordering.
    known_selected_set = set(known_selected)
    known_selected = [s.id for s in specs if s.id in known_selected_set]

    terminal_selected = tuple(
        TerminalExclusion(iid, states[iid])
        for iid in known_selected if _is_terminal(iid, states)
    )

    blockers: list[Blocker] = []
    for iid in known_selected:
        for dep in spec_by_id[iid].depends_on:
            if dep in known_selected_set:
                continue  # ordered together below
            if _is_satisfied(dep, states):
                continue
            blockers.append(Blocker(iid, dep, _dependency_state_label(dep, spec_by_id, states)))

    all_active_ids = [iid for iid, st in states.items() if st == _ACTIVE_STATE]
    omitted_active_ids = tuple(sorted(iid for iid in all_active_ids if iid not in known_selected_set))

    ordered, leftover = _topological_order(known_selected, spec_by_id)
    cycle_members = leftover

    ok = not (unknown_ids or duplicate_ids or terminal_selected or blockers
              or omitted_active_ids or cycle_members)
    return PlanResult(
        ok=ok,
        ordered_ids=ordered if ok else (),
        unknown_ids=tuple(unknown_ids),
        duplicate_ids=tuple(duplicate_ids),
        terminal_selected=terminal_selected,
        blockers=tuple(blockers),
        cycle_members=cycle_members,
        omitted_active_ids=omitted_active_ids,
    )


def plan_run_all(specs: Sequence[IssueSpec], states: Mapping[str, str]) -> PlanResult:
    spec_by_id = {s.id: s for s in specs}
    non_terminal_ids = [s.id for s in specs if not _is_terminal(s.id, states)]
    non_terminal_set = set(non_terminal_ids)
    excluded = tuple(
        TerminalExclusion(s.id, states[s.id]) for s in specs if _is_terminal(s.id, states)
    )

    # ADR-30 review finding 8: an authoritative ACTIVE issue absent from the
    # current file is never silently dropped from a run-all batch -- Run
    # All is defined as "every current non-terminal configured issue", but
    # an ACTIVE issue not in specs at all can never appear in non_terminal_ids
    # (it has no IssueSpec to iterate), so without this check it would be
    # silently ignored rather than blocking the whole batch the way
    # plan_selected's own omitted_active_ids check already does.
    all_active_ids = [iid for iid, st in states.items() if st == _ACTIVE_STATE]
    omitted_active_ids = tuple(sorted(iid for iid in all_active_ids if iid not in spec_by_id))

    blockers: list[Blocker] = []
    for iid in non_terminal_ids:
        for dep in spec_by_id[iid].depends_on:
            if dep in non_terminal_set:
                continue
            if _is_satisfied(dep, states):
                continue
            blockers.append(Blocker(iid, dep, _dependency_state_label(dep, spec_by_id, states)))

    ordered, leftover = _topological_order(non_terminal_ids, spec_by_id)

    ok = not (blockers or leftover or omitted_active_ids)
    return PlanResult(
        ok=ok,
        ordered_ids=ordered if ok else (),
        blockers=tuple(blockers),
        cycle_members=leftover,
        omitted_active_ids=omitted_active_ids,
        excluded=excluded,
    )
