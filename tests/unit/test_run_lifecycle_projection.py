"""RunStarted/RunFinished strict replay validation (doc 03 amendment,
"Strict replay validation"). Validation-only: these must never touch
issues/executions/issue_executions/issue_base_commit/issue_depends_on."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.projections import StateProjection
from runtime.events.schema import Event, EventType, KIND_OF, Kind, RESOLUTION_OF
from runtime.state.transitions import TransitionError

VALID_RUN_ID = "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _run_started_payload(**overrides) -> dict:
    payload = {
        "engine": {"provider": "claude-headless", "model": "default"},
        "reviewer": {"provider": "qwen", "model": "qwen2.5-coder"},
        "budget": {
            "max_attempts_per_issue": 3,
            "max_executions_per_run": 10,
            "hard_stop_proxy_cost_per_run_usd": 15.0,
            "proxy_pricing": "api_list_rates",
        },
        "config_digest": "a" * 64,
    }
    payload.update(overrides)
    return payload


def _run_finished_payload(**overrides) -> dict:
    payload = {"outcome": "COMPLETED", "detail": None}
    payload.update(overrides)
    return payload


def _started(event_id=1, run_id=VALID_RUN_ID, issue_id=None, execution_id=None,
            payload=None) -> Event:
    return Event(EventType.RUN_STARTED, event_id=event_id, run_id=run_id,
                issue_id=issue_id, execution_id=execution_id,
                payload=payload if payload is not None else _run_started_payload())


def _finished(event_id=1, run_id=VALID_RUN_ID, issue_id=None, execution_id=None,
             payload=None) -> Event:
    return Event(EventType.RUN_FINISHED, event_id=event_id, run_id=run_id,
                issue_id=issue_id, execution_id=execution_id,
                payload=payload if payload is not None else _run_finished_payload())


def _apply(ev: Event) -> StateProjection:
    p = StateProjection()
    p.apply(ev)
    return p


def _assert_no_state_mutation(exc_info_call):
    p = StateProjection()
    with pytest.raises(TransitionError):
        exc_info_call(p)
    assert p.issues == {}
    assert p.executions == {}
    assert p.issue_executions == {}
    assert p.issue_base_commit == {}
    assert p.issue_depends_on == {}


# ── schema vocabulary (schema.py) ──────────────────────────────────
def test_run_started_is_intent_kind():
    assert KIND_OF[EventType.RUN_STARTED] is Kind.INTENT


def test_run_finished_is_fact_kind():
    assert KIND_OF[EventType.RUN_FINISHED] is Kind.FACT


def test_run_started_not_in_resolution_of():
    assert EventType.RUN_STARTED not in RESOLUTION_OF


# ── positive cases ───────────────────────────────────────────────
def test_valid_run_started_applies_cleanly():
    p = _apply(_started())
    assert p.last_event_id == 1
    assert p.counts["RunStarted"] == 1
    assert p.issues == {} and p.executions == {}


def test_valid_run_finished_applies_cleanly():
    p = _apply(_finished())
    assert p.counts["RunFinished"] == 1
    assert p.issues == {} and p.executions == {}


def test_reviewer_model_null_is_accepted():
    payload = _run_started_payload(reviewer={"provider": "qwen", "model": None})
    p = _apply(_started(payload=payload))
    assert p.counts["RunStarted"] == 1


def test_every_controlled_outcome_is_accepted():
    for outcome in ["CHECKOUT_FAILED", "REVIEWER_UNREACHABLE", "BASELINE_FAILED",
                    "INGEST_FAILED", "COMPLETED", "HALTED", "INTERRUPTED"]:
        p = _apply(_finished(payload=_run_finished_payload(outcome=outcome)))
        assert p.counts["RunFinished"] == 1


# ── envelope negative cases ─────────────────────────────────────
def test_null_run_id_rejected():
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=None)))


_MALFORMED_RUN_ID_VALUES = pytest.mark.parametrize("bad_run_id", [
    12345,           # integer
    True,            # boolean
    ["a"],           # list
    {"a": 1},        # object/dict
    "",              # empty string
    None,            # null
], ids=["integer", "boolean", "list", "object", "empty-string", "null"])


@_MALFORMED_RUN_ID_VALUES
def test_run_started_malformed_run_id_type_raises_transition_error_not_type_error(bad_run_id):
    """re.fullmatch on a non-string raises TypeError, not TransitionError --
    isinstance must be checked first. Every malformed run_id, regardless of
    its JSON type, must raise TransitionError and leave no partial state."""
    p = StateProjection()
    with pytest.raises(TransitionError):
        p.apply(_started(run_id=bad_run_id))
    assert p.issues == {} and p.executions == {}


@_MALFORMED_RUN_ID_VALUES
def test_run_finished_malformed_run_id_type_raises_transition_error_not_type_error(bad_run_id):
    p = StateProjection()
    with pytest.raises(TransitionError):
        p.apply(_finished(run_id=bad_run_id))
    assert p.issues == {} and p.executions == {}


def test_run_id_trailing_characters_rejected():
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=VALID_RUN_ID + "x")))


def test_run_id_wrong_uuid_version_nibble_rejected():
    bad = VALID_RUN_ID.replace("-4562-", "-1562-")
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=bad)))


def test_run_id_wrong_uuid_variant_nibble_rejected():
    bad = VALID_RUN_ID.replace("-b3fc-", "-c3fc-")
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=bad)))


def test_run_id_uppercase_uuid_rejected():
    bad = VALID_RUN_ID.upper().replace("RUN-", "run-")
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=bad)))


def test_run_id_invalid_calendar_timestamp_rejected():
    bad = VALID_RUN_ID.replace("20260821T060512Z", "20261332T060512Z")  # month 13
    _assert_no_state_mutation(lambda p: p.apply(_started(run_id=bad)))


def test_run_id_legacy_format_without_uuid_rejected():
    _assert_no_state_mutation(
        lambda p: p.apply(_started(run_id="run-20260821T060512Z")))


def test_run_started_issue_id_must_be_null():
    _assert_no_state_mutation(lambda p: p.apply(_started(issue_id="042")))


def test_run_started_execution_id_must_be_null():
    _assert_no_state_mutation(lambda p: p.apply(_started(execution_id="042-e1")))


def test_run_finished_null_run_id_rejected():
    _assert_no_state_mutation(lambda p: p.apply(_finished(run_id=None)))


# ── RunStarted payload negative cases ───────────────────────────
def test_run_started_missing_engine_rejected():
    payload = _run_started_payload()
    del payload["engine"]
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_unexpected_top_level_key_rejected():
    payload = _run_started_payload(extra="nope")
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_engine_missing_provider_rejected():
    payload = _run_started_payload(engine={"model": "default"})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_engine_empty_provider_rejected():
    payload = _run_started_payload(engine={"provider": "", "model": "default"})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_engine_unexpected_key_rejected():
    payload = _run_started_payload(
        engine={"provider": "claude-headless", "model": "default", "extra": 1})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_engine_model_null_rejected():
    payload = _run_started_payload(engine={"provider": "claude-headless", "model": None})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_reviewer_missing_model_key_rejected():
    payload = _run_started_payload(reviewer={"provider": "qwen"})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_reviewer_empty_string_model_rejected():
    payload = _run_started_payload(reviewer={"provider": "qwen", "model": ""})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_reviewer_unexpected_key_rejected():
    payload = _run_started_payload(
        reviewer={"provider": "qwen", "model": "q", "extra": 1})
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_missing_key_rejected():
    budget = _run_started_payload()["budget"]
    del budget["proxy_pricing"]
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_unexpected_key_rejected():
    budget = dict(_run_started_payload()["budget"], extra=1)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_max_attempts_bool_rejected():
    budget = dict(_run_started_payload()["budget"], max_attempts_per_issue=True)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_max_attempts_zero_rejected():
    budget = dict(_run_started_payload()["budget"], max_attempts_per_issue=0)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_max_executions_negative_rejected():
    budget = dict(_run_started_payload()["budget"], max_executions_per_run=-1)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_cost_bool_rejected():
    budget = dict(_run_started_payload()["budget"],
                  hard_stop_proxy_cost_per_run_usd=True)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_cost_nan_rejected():
    budget = dict(_run_started_payload()["budget"],
                  hard_stop_proxy_cost_per_run_usd=math.nan)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_cost_infinity_rejected():
    budget = dict(_run_started_payload()["budget"],
                  hard_stop_proxy_cost_per_run_usd=math.inf)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_cost_zero_rejected():
    budget = dict(_run_started_payload()["budget"],
                  hard_stop_proxy_cost_per_run_usd=0)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_cost_negative_rejected():
    budget = dict(_run_started_payload()["budget"],
                  hard_stop_proxy_cost_per_run_usd=-5.0)
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_budget_unknown_proxy_pricing_rejected():
    budget = dict(_run_started_payload()["budget"], proxy_pricing="flat_rate")
    payload = _run_started_payload(budget=budget)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_config_digest_wrong_length_rejected():
    payload = _run_started_payload(config_digest="a" * 63)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


def test_run_started_config_digest_uppercase_rejected():
    payload = _run_started_payload(config_digest="A" * 64)
    _assert_no_state_mutation(lambda p: p.apply(_started(payload=payload)))


# ── RunFinished payload negative cases ──────────────────────────
def test_run_finished_unknown_outcome_rejected():
    payload = _run_finished_payload(outcome="SOMETHING_ELSE")
    _assert_no_state_mutation(lambda p: p.apply(_finished(payload=payload)))


def test_run_finished_missing_detail_key_rejected():
    payload = {"outcome": "COMPLETED"}
    _assert_no_state_mutation(lambda p: p.apply(_finished(payload=payload)))


def test_run_finished_nonnull_detail_rejected():
    payload = _run_finished_payload(detail="some exception text")
    _assert_no_state_mutation(lambda p: p.apply(_finished(payload=payload)))


def test_run_finished_unexpected_key_rejected():
    payload = _run_finished_payload(extra="nope")
    _assert_no_state_mutation(lambda p: p.apply(_finished(payload=payload)))
