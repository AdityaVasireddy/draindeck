"""Tolerant issue/execution projection (docs/19: unknown event types and
illegal or out-of-order transitions must degrade gracefully — a torn,
reordered, or replayed-across-generations observation must never crash
the issues/executions view).

Reuses doc 03's public state vocabulary and transition tables
(``runtime.state.model`` / ``runtime.state.transitions`` — pure enums and
dict lookups, no file/lock/subprocess access, the same shape ADR-26's
allowlist and docs/19 already require Dashboard to understand) so state
names never drift from the core runtime. This deliberately does NOT call
``runtime.events.projections.StateProjection.apply`` — that replay engine
raises on any illegal transition, which is correct for the core runtime
(a log that does not replay cleanly is corruption) but wrong for
Dashboard's tolerant, read-only observation of a log ADR-25 may hand back
torn or reordered. An illegal transition here is recorded as
``inconsistent`` on the entity, never raised.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from runtime.events.schema import EventType
from runtime.state.model import ExecutionState, IssueState
from runtime.state.transitions import EXECUTION_TRANSITIONS, ISSUE_TRANSITIONS

from .proxy_cost import validate_dollars, validate_tokens

_ISSUE_TRANSITION_TYPES = frozenset({
    EventType.ISSUE_ACTIVATED, EventType.ISSUE_COMPLETED, EventType.ISSUE_ESCALATED,
})
_EXECUTION_TRANSITION_TYPES = frozenset({
    EventType.EXECUTION_FINISHED, EventType.EXECUTION_CRASHED,
    EventType.VALIDATION_PASSED, EventType.VALIDATION_FAILED,
    EventType.REVIEW_APPROVED, EventType.REVIEW_REJECTED,
})

# ADR-25 hardcodes writerState UNKNOWN — every EXECUTING execution is
# "Pending reconciliation" in Part 2; Running is unreachable and Dashboard
# must never invent a liveness probe (docs/19).
PENDING_RECONCILIATION = "Pending reconciliation"


@dataclass
class IssueView:
    issue_id: str
    state: str
    title: str = ""
    last_event_id: Optional[int] = None
    inconsistent: bool = False


@dataclass
class ExecutionView:
    execution_id: str
    issue_id: Optional[str]
    state: str
    last_event_id: Optional[int] = None
    inconsistent: bool = False
    run_id: Optional[str] = None
    # Proxy cost/tokens captured at the single ACCEPTED ExecutionFinished
    # transition (spec §2.1). None/False mean "unknown", never zero. A metered
    # valid zero is proxy_micro_usd=0, cost_valid=True. Cost and token coverage
    # are independent (spec §2.3).
    proxy_micro_usd: Optional[int] = None
    cost_valid: bool = False
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    tokens_valid: bool = False


# Dashboard's own message for a run_id with no matching RunStarted evidence
# (docs/19 "Run lifecycle compatibility"). Availability is decided ONLY by
# whether a RunStarted was actually observed for this run_id -- never by the
# run_id's string shape (legacy timestamp-only vs. the new UUID4-suffixed
# format) -- so a legacy run_id is never treated as collision-safe just
# because it parses as one shape or the other.
RUN_METADATA_UNAVAILABLE = "run metadata unavailable (legacy/ambiguous)"

# A RunStarted with no matching RunFinished anywhere later in the log is a
# permanent, honest record (doc 03 amendment) -- ADR-25's boundary gives
# Dashboard no liveness signal, so this must never be rendered as "Running"
# (a claim about current process state Dashboard cannot make).
RUN_NO_CONTROLLED_FINISH_OBSERVED = "no controlled finish observed"


@dataclass
class RunView:
    """Doc 03 amendment run-level provenance, tolerant of malformed or
    partial RunStarted/RunFinished payloads -- an unparseable field is
    recorded as None/inconsistent, never raised (this module never raises)."""

    run_id: str
    engine_provider: Optional[str] = None
    engine_model: Optional[str] = None
    reviewer_provider: Optional[str] = None
    reviewer_model: Optional[str] = None
    budget: dict = field(default_factory=dict)
    config_digest: Optional[str] = None
    outcome: Optional[str] = None
    last_event_id: Optional[int] = None
    inconsistent: bool = False
    # Tracks whether ANY RunFinished (valid or malformed) has already been
    # observed for this run -- a second one is a duplicate regardless of
    # whether the first was itself valid, and must never silently overwrite
    # the first outcome.
    finished_seen: bool = False
    # Tracks whether the CURRENTLY STORED fields came from a structurally
    # valid RunStarted/RunFinished -- distinct from `inconsistent` (any
    # anomaly ever observed, including the mere fact of a duplicate).
    # Without this, a malformed record observed first would permanently
    # hide a fully valid record observed second: "duplicate -> flag and
    # return" alone discards real, recoverable signal instead of just
    # flagging the anomaly (adversarial-review finding, 2026-08-21).
    started_valid: bool = False
    finished_valid: bool = False
    # The evidence event's own `ts` at first observation -- distinct from
    # whether the RunStarted/RunFinished payload itself parsed cleanly.
    # Never recomputed on a later recovery (see _apply_run_started): the
    # first event is honestly when the run was observed to start/finish,
    # regardless of whether that record's other fields were malformed.
    observed_started_at: Optional[str] = None
    observed_finished_at: Optional[str] = None


_CONTAINMENT_EVENT_TYPES = frozenset({
    EventType.EXECUTION_CONTAINMENT_PREPARED, EventType.EXECUTION_CONTAINMENT_ESTABLISHED,
    EventType.EXECUTION_TERMINATION_UNCONFIRMED, EventType.EXECUTION_CONTAINMENT_RELEASED,
})

# Exact states PREPARED|ESTABLISHED|UNCONFIRMED|RELEASED (docs/27 SS8.2, doc
# 03 amendment "execution containment protocol"). Released is reachable
# directly from Prepared or Established -- the amendment requires only "a
# matching unreleased generation", not that Unconfirmed be observed first.
_CONTAINMENT_TRANSITIONS: dict[tuple[str, EventType], str] = {
    ("PREPARED", EventType.EXECUTION_CONTAINMENT_ESTABLISHED): "ESTABLISHED",
    ("ESTABLISHED", EventType.EXECUTION_TERMINATION_UNCONFIRMED): "UNCONFIRMED",
    ("PREPARED", EventType.EXECUTION_CONTAINMENT_RELEASED): "RELEASED",
    ("ESTABLISHED", EventType.EXECUTION_CONTAINMENT_RELEASED): "RELEASED",
    ("UNCONFIRMED", EventType.EXECUTION_CONTAINMENT_RELEASED): "RELEASED",
}


@dataclass
class ContainmentGenView:
    """One (execution_id, containment_generation) containment row --
    orthogonal to execution lifecycle state (doc 03 amendment)."""

    execution_id: str
    containment_generation: str
    workspace_key: Optional[str]
    state: str
    last_event_id: Optional[int] = None
    inconsistent: bool = False


@dataclass
class ProjectionResult:
    issues: dict = field(default_factory=dict)
    executions: dict = field(default_factory=dict)
    runs: dict = field(default_factory=dict)
    containments: dict = field(default_factory=dict)
    unknown_event_type_count: int = 0


def _try_event_type(raw: Optional[str]) -> Optional[EventType]:
    if raw is None:
        return None
    try:
        return EventType(raw)
    except ValueError:
        return None  # unknown event type: evidence, not projected, not a crash


def fetch_ok_evidence_rows(conn: sqlite3.Connection, repo_id: int, identity_generation_id: int,
                           *, issue_id: Optional[str] = None, execution_id: Optional[str] = None,
                           run_id: Optional[str] = None) -> list:
    """OK evidence rows for one identity generation, optionally scoped to a
    single issue/execution/run id (read_models.py's entity-scoped
    incremental recompute uses this to replay only one entity's own
    history instead of the whole generation)."""
    clauses = ["repository_id = ?", "identity_generation_id = ?", "integrity = 'OK'"]
    params: list = [repo_id, identity_generation_id]
    if issue_id is not None:
        clauses.append("issue_id = ?")
        params.append(issue_id)
    if execution_id is not None:
        clauses.append("execution_id = ?")
        params.append(execution_id)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    sql = (
        "SELECT event_id, event_type, issue_id, execution_id, run_id, payload_json, event_ts "
        "FROM evidence WHERE " + " AND ".join(clauses) + " ORDER BY event_id"
    )
    return conn.execute(sql, params).fetchall()


def apply_ok_evidence_rows(rows: list) -> ProjectionResult:
    """The pure reducer's dispatch loop, decoupled from SQL fetching so it
    can run over either a full generation (build_projection) or one
    entity's own scoped row set (read_models.py)."""
    result = ProjectionResult()
    for event_id, event_type_str, issue_id, execution_id, run_id, payload_json, event_ts in rows:
        etype = _try_event_type(event_type_str)
        if etype is None:
            result.unknown_event_type_count += 1
            continue

        if etype is EventType.ISSUE_CREATED:
            _apply_issue_created(result, issue_id, payload_json, event_id)
        elif etype in _ISSUE_TRANSITION_TYPES:
            _apply_issue_transition(result, etype, issue_id, payload_json, event_id)
        elif etype is EventType.EXECUTION_SPAWNED:
            _apply_execution_spawned(result, execution_id, issue_id, run_id, event_id)
        elif etype in _EXECUTION_TRANSITION_TYPES:
            _apply_execution_transition(result, etype, execution_id, payload_json, event_id)
        elif etype in _CONTAINMENT_EVENT_TYPES:
            _apply_containment_event(result, etype, execution_id, payload_json, event_id)
        elif etype is EventType.RUN_STARTED:
            _apply_run_started(result, run_id, payload_json, event_id, event_ts)
        elif etype is EventType.RUN_FINISHED:
            _apply_run_finished(result, run_id, payload_json, event_id, event_ts)
        # CommitIntent/CommitCreated/HumanIntervention/GuidelinePromoted:
        # not modeled in Part 2's issues/executions summary view.

    for view in result.executions.values():
        if not view.inconsistent and view.state == ExecutionState.EXECUTING.value:
            view.state = PENDING_RECONCILIATION

    return result


def build_projection(conn: sqlite3.Connection, repo_id: int,
                     identity_generation_id: int) -> ProjectionResult:
    return apply_ok_evidence_rows(
        fetch_ok_evidence_rows(conn, repo_id, identity_generation_id))


def _load_payload(payload_json: Optional[str]) -> dict:
    if not payload_json:
        return {}
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_issue_created(result: ProjectionResult, issue_id: Optional[str],
                         payload_json: Optional[str], event_id: int) -> None:
    if issue_id is None:
        return
    if issue_id in result.issues:
        result.issues[issue_id].inconsistent = True
        return
    payload = _load_payload(payload_json)
    result.issues[issue_id] = IssueView(
        issue_id, IssueState.PENDING.value,
        title=payload.get("title", "") if isinstance(payload.get("title"), str) else "",
        last_event_id=event_id,
    )


def _apply_issue_transition(result: ProjectionResult, etype: EventType,
                            issue_id: Optional[str], payload_json: Optional[str],
                            event_id: int) -> None:
    if issue_id is None:
        return
    view = result.issues.get(issue_id)
    if view is None or view.inconsistent:
        return
    try:
        cur_state = IssueState(view.state)
    except ValueError:
        view.inconsistent = True
        return
    fn = ISSUE_TRANSITIONS.get((cur_state, etype))
    if fn is None:
        view.inconsistent = True
        return
    try:
        view.state = fn(_load_payload(payload_json)).value
    except Exception:
        view.inconsistent = True
        return
    view.last_event_id = event_id


def _apply_execution_spawned(result: ProjectionResult, execution_id: Optional[str],
                             issue_id: Optional[str], run_id: Optional[str],
                             event_id: int) -> None:
    if execution_id is None:
        return
    if execution_id in result.executions:
        result.executions[execution_id].inconsistent = True
        return
    result.executions[execution_id] = ExecutionView(
        execution_id, issue_id, ExecutionState.EXECUTING.value, last_event_id=event_id,
        run_id=run_id,
    )


def _str_or_none(mapping: dict, key: str) -> Optional[str]:
    value = mapping.get(key)
    return value if isinstance(value, str) else None


def _has_nonempty_str(mapping: dict, key: str) -> bool:
    value = mapping.get(key)
    return isinstance(value, str) and bool(value)


def _has_nullable_str(mapping: dict, key: str) -> bool:
    """True iff `key` is present AND its value is either null or a
    non-empty string -- distinct from _str_or_none, which can't tell an
    explicitly-null value (valid for reviewer.model) apart from a
    missing key (invalid) since both resolve to None."""
    if key not in mapping:
        return False
    value = mapping[key]
    return value is None or (isinstance(value, str) and bool(value))


def _has_positive_int(mapping: dict, key: str) -> bool:
    """Doc 03: max_attempts_per_issue/max_executions_per_run are each an
    integer >= 1 -- bool excluded (isinstance(True, int) is True under
    Python's int/bool subtyping) and a float excluded too (the amendment
    specifies "an integer", not "a number equal to an integer", and this
    mirrors runtime.events.projections._positive_int's own int-only check)."""
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= 1


def _has_finite_positive_number(mapping: dict, key: str) -> bool:
    """Doc 03: hard_stop_proxy_cost_per_run_usd is an int or float (never
    bool), satisfying math.isfinite, and > 0."""
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and value > 0


# Doc 03: proxy_pricing is validated against a closed set matching
# BudgetCfg.proxy_pricing's own Literal type (config.py) -- today exactly
# {"api_list_rates"}, not "any non-empty string". Duplicated here (not
# imported from config.py) for the same reason _RUN_OUTCOMES is duplicated
# above -- see this file's own module docstring.
_KNOWN_PROXY_PRICING: frozenset[str] = frozenset({"api_list_rates"})


def _has_only_keys(mapping: dict, allowed: frozenset) -> bool:
    return set(mapping) <= allowed


# The 7 controlled outcomes (doc 03 amendment). Kept in sync by
# comment/convention with runtime.events.projections's _RUN_OUTCOMES --
# duplicated here because Dashboard deliberately never imports the core
# runtime's strict-replay module (see this file's own module docstring).
_RUN_OUTCOMES: frozenset[str] = frozenset({
    "CHECKOUT_FAILED", "REVIEWER_UNREACHABLE", "BASELINE_FAILED",
    "INGEST_FAILED", "COMPLETED", "HALTED", "INTERRUPTED",
})

_RUN_STARTED_TOP_KEYS = frozenset({"engine", "reviewer", "budget", "config_digest"})
_RUN_STARTED_ENGINE_KEYS = frozenset({"provider", "model"})
_RUN_STARTED_REVIEWER_KEYS = frozenset({"provider", "model"})
_RUN_STARTED_BUDGET_KEYS = frozenset({
    "max_attempts_per_issue", "max_executions_per_run",
    "hard_stop_proxy_cost_per_run_usd", "proxy_pricing",
})
_RUN_FINISHED_TOP_KEYS = frozenset({"outcome", "detail"})
_CONFIG_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _run_started_fields(payload: dict) -> tuple[dict, bool]:
    """Extract RunView's engine/reviewer/budget/digest fields from a
    RunStarted payload, plus whether the payload is structurally complete
    (closed schema, every required field present and well-typed)."""
    engine = payload.get("engine") if isinstance(payload.get("engine"), dict) else {}
    reviewer = payload.get("reviewer") if isinstance(payload.get("reviewer"), dict) else {}
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    digest = _str_or_none(payload, "config_digest")
    fields = {
        "engine_provider": _str_or_none(engine, "provider"),
        "engine_model": _str_or_none(engine, "model"),
        "reviewer_provider": _str_or_none(reviewer, "provider"),
        "reviewer_model": _str_or_none(reviewer, "model"),
        "budget": dict(budget),
        "config_digest": digest,
    }
    # Field-level completeness AND closed-schema, not whole-subdict
    # truthiness: an engine object present but missing just `model` (e.g.
    # {"provider": "..."}), an unexpected extra key anywhere, or a
    # config_digest that isn't 64 lowercase hex characters must all be
    # flagged -- not silently accepted because the containing dict is
    # merely non-empty.
    complete = (
        _has_only_keys(payload, _RUN_STARTED_TOP_KEYS)
        and _has_only_keys(engine, _RUN_STARTED_ENGINE_KEYS)
        and _has_only_keys(reviewer, _RUN_STARTED_REVIEWER_KEYS)
        and _has_only_keys(budget, _RUN_STARTED_BUDGET_KEYS)
        and _has_nonempty_str(engine, "provider") and _has_nonempty_str(engine, "model")
        and _has_nonempty_str(reviewer, "provider") and _has_nullable_str(reviewer, "model")
        and _has_positive_int(budget, "max_attempts_per_issue")
        and _has_positive_int(budget, "max_executions_per_run")
        and _has_finite_positive_number(budget, "hard_stop_proxy_cost_per_run_usd")
        and budget.get("proxy_pricing") in _KNOWN_PROXY_PRICING
        and digest is not None and bool(_CONFIG_DIGEST_RE.fullmatch(digest))
    )
    return fields, complete


def _apply_run_started(result: ProjectionResult, run_id: Optional[str],
                       payload_json: Optional[str], event_id: int,
                       event_ts: Optional[str] = None) -> None:
    if run_id is None:
        return  # no run_id to key metadata on -- evidence not modeled here
    payload = _load_payload(payload_json)
    fields, complete = _run_started_fields(payload)

    existing = result.runs.get(run_id)
    if existing is not None:
        # A second RunStarted is always anomalous -- flag it. But "first
        # observed wins" must not mean "first observed is trusted forever
        # even if it was garbage": if the stored fields came from a
        # malformed record and this one is structurally valid, the valid
        # data replaces it rather than staying permanently hidden behind
        # an earlier defect (adversarial-review finding, 2026-08-21).
        # Two equally-valid (or equally-invalid) RunStarted keep the first.
        existing.inconsistent = True
        if complete and not existing.started_valid:
            for name, value in fields.items():
                setattr(existing, name, value)
            existing.last_event_id = event_id
            existing.started_valid = True
        return

    view = RunView(run_id, last_event_id=event_id, started_valid=complete,
                   observed_started_at=event_ts, **fields)
    # Availability (has_run_metadata) still comes from THIS entry's mere
    # presence, per the amendment's rule that availability is decided by
    # RunStarted's existence, not by whether every field parsed.
    if not complete:
        view.inconsistent = True
    result.runs[run_id] = view


def _apply_run_finished(result: ProjectionResult, run_id: Optional[str],
                        payload_json: Optional[str], event_id: int,
                        event_ts: Optional[str] = None) -> None:
    if run_id is None:
        return
    view = result.runs.get(run_id)
    if view is None:
        return  # no RunStarted observed for this run_id -- nothing to attach to

    payload = _load_payload(payload_json)
    outcome = payload.get("outcome")
    valid = (
        _has_only_keys(payload, _RUN_FINISHED_TOP_KEYS)
        and isinstance(outcome, str) and outcome in _RUN_OUTCOMES
        and "detail" in payload and payload["detail"] is None
    )

    if view.finished_seen:
        # A second RunFinished is always anomalous -- flag it. As with
        # RunStarted above, a valid record must still be allowed to
        # recover the outcome an earlier malformed one couldn't establish;
        # it must never overwrite an outcome already validly recorded.
        view.inconsistent = True
        if valid and not view.finished_valid:
            view.outcome = outcome
            view.last_event_id = event_id
            view.finished_valid = True
        return

    view.finished_seen = True
    view.observed_finished_at = event_ts
    if valid:
        view.outcome = outcome
        view.last_event_id = event_id
        view.finished_valid = True
    else:
        view.inconsistent = True


def has_run_metadata(result: ProjectionResult, run_id: Optional[str]) -> bool:
    """Availability is decided ONLY by whether a RunStarted was observed for
    this run_id (docs/19) -- never by the run_id's string shape. A run_id of
    None (no ExecutionSpawned run_id at all -- always true for pre-amendment
    logs) is unavailable by construction, the same as an unrecognized one."""
    return run_id is not None and run_id in result.runs


def _apply_execution_transition(result: ProjectionResult, etype: EventType,
                                execution_id: Optional[str], payload_json: Optional[str],
                                event_id: int) -> None:
    if execution_id is None:
        return
    view = result.executions.get(execution_id)
    if view is None or view.inconsistent:
        return
    try:
        cur_state = ExecutionState(view.state)
    except ValueError:
        view.inconsistent = True
        return
    fn = EXECUTION_TRANSITIONS.get((cur_state, etype))
    if fn is None:
        view.inconsistent = True
        return
    payload = _load_payload(payload_json)
    try:
        view.state = fn(payload).value
    except Exception:
        view.inconsistent = True
        return
    view.last_event_id = event_id
    # Capture proxy cost/tokens ONLY at the single accepted ExecutionFinished
    # transition (spec §2.1) -- a duplicate/out-of-order second finish never
    # reaches here (its (state, EXECUTION_FINISHED) has no transition fn, so it
    # is flagged inconsistent and returns above), so cost is never
    # double-counted or overwritten.
    if etype is EventType.EXECUTION_FINISHED:
        _capture_usage(view, payload)


def _capture_usage(view: ExecutionView, payload: dict) -> None:
    """Populate the ExecutionView's proxy cost/token fields from an accepted
    ExecutionFinished payload's ``usage`` object. Cost and token validity are
    independent (spec §2.3); a missing/malformed ``usage`` leaves both unknown."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return
    micro = validate_dollars(usage.get("dollars"))
    if micro is not None:
        view.proxy_micro_usd = micro
        view.cost_valid = True
    input_tokens = validate_tokens(usage.get("input_tokens"))
    output_tokens = validate_tokens(usage.get("output_tokens"))
    if input_tokens is not None and output_tokens is not None:
        view.input_tokens = input_tokens
        view.output_tokens = output_tokens
        view.tokens_valid = True


def _apply_containment_event(result: ProjectionResult, etype: EventType,
                             execution_id: Optional[str], payload_json: Optional[str],
                             event_id: int) -> None:
    if execution_id is None:
        return
    payload = _load_payload(payload_json)
    workspace_key = _str_or_none(payload, "workspace_key")
    generation = _str_or_none(payload, "containment_generation")
    if generation is None:
        return  # no generation to key on -- evidence not modeled here

    key = (execution_id, generation)

    if etype is EventType.EXECUTION_CONTAINMENT_PREPARED:
        if key in result.containments:
            result.containments[key].inconsistent = True
            return
        result.containments[key] = ContainmentGenView(
            execution_id=execution_id, containment_generation=generation,
            workspace_key=workspace_key, state="PREPARED", last_event_id=event_id,
        )
        return

    view = result.containments.get(key)
    if view is None or view.inconsistent:
        return
    if workspace_key is not None and view.workspace_key != workspace_key:
        view.inconsistent = True
        return
    next_state = _CONTAINMENT_TRANSITIONS.get((view.state, etype))
    if next_state is None:
        view.inconsistent = True
        return
    view.state = next_state
    view.last_event_id = event_id
