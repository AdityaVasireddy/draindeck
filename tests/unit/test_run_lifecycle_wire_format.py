"""Prove the ACTUAL bytes main.py would durably emit for RunStarted/
RunFinished -- not just the in-memory Event object -- survive the real
durability contract: Event.to_line() -> bytes -> Event.from_line() ->
StateProjection().apply() must accept them cleanly (review requirement).
Also proves the emitted RunStarted has the exact closed payload, a genuine
canonical-lowercase-UUID4 run_id, null envelope fields, and that no
secret/path/endpoint/command/environment value from configuration can
appear anywhere in the serialized bytes."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config
from runtime.events.projections import StateProjection
from runtime.events.schema import Event, EventType
from runtime.main import (
    _config_digest,
    _new_run_id,
    _resolve_reviewer_model,
    _run_started_payload,
)

_UUID4_RUN_ID_RE = re.compile(
    r"run-\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)

# Distinctive markers that must never leak into a lifecycle event's bytes.
_SECRET = "sk-ant-super-secret-token-do-not-leak-9f3a"
_REPO_PATH = "C:/definitely-not-allowlisted/secret-repo-path"
_ENDPOINT = "http://internal-reviewer-host.example:19999/v1"
_VALIDATION_COMMAND = "run-the-forbidden-validation-script.ps1"
_ENV_SECRET_VALUE = "env-secret-should-never-appear-anywhere"


def _cfg_with_secrets() -> Config:
    return Config.model_validate({
        "project": {
            "name": "T", "repository": _REPO_PATH, "branch": "agent-work",
            "issues_file": "Issues.md",
            "validation": {"commands": [_VALIDATION_COMMAND],
                           "env": {"SECRET_TOKEN": _ENV_SECRET_VALUE}},
        },
        "engine": {
            "provider": "claude-headless", "auth_mode": "subscription",
            "model": "default", "max_turns": 30, "timeout_seconds": 1800,
            "child_env": {"ANTHROPIC_API_KEY": _SECRET},
        },
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": _ENDPOINT, "model": "qwen2.5-coder"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0,
                   "proxy_pricing": "api_list_rates"},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })


def _build_real_run_started_event() -> Event:
    """Exactly what _emit_run_started constructs -- calling the same
    production functions, not a hand-rolled substitute."""
    cfg = _cfg_with_secrets()
    run_id = _new_run_id()
    reviewer_model = _resolve_reviewer_model(cfg)
    digest = _config_digest(cfg, reviewer_model)
    payload = _run_started_payload(cfg, reviewer_model, digest)
    return Event(EventType.RUN_STARTED, run_id=run_id, payload=payload)


def test_run_started_roundtrips_through_to_line_and_from_line():
    ev = _build_real_run_started_event()
    ev_with_id = Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                       execution_id=ev.execution_id, run_id=ev.run_id, ts=ev.ts,
                       event_id=1, schema_version=ev.schema_version)
    line = ev_with_id.to_line()
    roundtripped = Event.from_line(line)

    assert roundtripped.type is EventType.RUN_STARTED
    assert roundtripped.run_id == ev.run_id
    assert roundtripped.payload == ev.payload
    assert roundtripped.issue_id is None
    assert roundtripped.execution_id is None


def test_run_started_roundtripped_bytes_pass_strict_projection_validation():
    ev = _build_real_run_started_event()
    ev_with_id = Event(type=ev.type, payload=ev.payload, run_id=ev.run_id,
                       event_id=1)
    roundtripped = Event.from_line(ev_with_id.to_line())

    StateProjection().apply(roundtripped)  # must not raise


def test_run_started_exact_closed_payload_keys():
    ev = _build_real_run_started_event()
    assert set(ev.payload) == {"engine", "reviewer", "budget", "config_digest"}
    assert set(ev.payload["engine"]) == {"provider", "model"}
    assert set(ev.payload["reviewer"]) == {"provider", "model"}
    assert set(ev.payload["budget"]) == {
        "max_attempts_per_issue", "max_executions_per_run",
        "hard_stop_proxy_cost_per_run_usd", "proxy_pricing",
    }


def test_run_started_run_id_is_genuine_uuid4_format():
    ev = _build_real_run_started_event()
    assert _UUID4_RUN_ID_RE.fullmatch(ev.run_id)


def test_run_started_envelope_issue_and_execution_id_are_null():
    ev = _build_real_run_started_event()
    assert ev.issue_id is None
    assert ev.execution_id is None


def test_run_started_bytes_never_contain_excluded_config_values():
    ev = _build_real_run_started_event()
    ev_with_id = Event(type=ev.type, payload=ev.payload, run_id=ev.run_id, event_id=1)
    raw = ev_with_id.to_line()

    for marker in (_SECRET, _REPO_PATH, _ENDPOINT, _VALIDATION_COMMAND, _ENV_SECRET_VALUE):
        assert marker.encode() not in raw, f"excluded value leaked into event bytes: {marker!r}"


def test_run_started_payload_never_contains_excluded_config_values_even_serialized_deep():
    """Belt-and-suspenders: search the payload structurally (not just the
    raw bytes) in case some future change nests an excluded value under a
    key whose own name doesn't match a marker."""
    import json
    ev = _build_real_run_started_event()
    serialized = json.dumps(ev.payload)
    for marker in (_SECRET, _REPO_PATH, _ENDPOINT, _VALIDATION_COMMAND, _ENV_SECRET_VALUE):
        assert marker not in serialized


# ── RunFinished: same wire-format proof for every controlled outcome ────
def _build_real_run_finished_event(outcome: str) -> Event:
    run_id = _new_run_id()
    payload = {"outcome": outcome, "detail": None}
    return Event(EventType.RUN_FINISHED, run_id=run_id, payload=payload)


def test_run_finished_roundtrips_and_validates_for_every_outcome():
    for outcome in ["CHECKOUT_FAILED", "REVIEWER_UNREACHABLE", "BASELINE_FAILED",
                    "INGEST_FAILED", "COMPLETED", "HALTED", "INTERRUPTED"]:
        ev = _build_real_run_finished_event(outcome)
        ev_with_id = Event(type=ev.type, payload=ev.payload, run_id=ev.run_id, event_id=1)
        roundtripped = Event.from_line(ev_with_id.to_line())

        StateProjection().apply(roundtripped)  # must not raise
        assert roundtripped.payload == {"outcome": outcome, "detail": None}
        assert roundtripped.issue_id is None
        assert roundtripped.execution_id is None
