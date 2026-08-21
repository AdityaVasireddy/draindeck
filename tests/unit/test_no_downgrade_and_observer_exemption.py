"""Doc 03 amendment, "No-downgrade policy": the strict writer/replay path
(EventLog, ReadOnlyEventLog) refuses on the first unrecognized event type
it reaches; ADR-25's `draindeck observe` (bytes-direct) is intentionally
exempt from that refusal. Also confirms RunStarted/RunFinished themselves
are now registered on the strict path (they were unrecognized before this
session's schema.py change)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.log import CorruptionError, EventLog, ReadOnlyEventLog
from runtime.events.schema import Event, EventType, SchemaError
from runtime.observe import read_events_page

_FICTIONAL_TYPE_LINE = (
    b'{"event_id":1,"schema_version":1,"ts":"2026-08-21T00:00:00Z","run_id":null,'
    b'"type":"SomeFutureEventTypeNotYetRegistered","issue_id":null,"execution_id":null,'
    b'"payload":{}}\n'
)


def test_from_line_rejects_a_genuinely_unrecognized_type():
    with pytest.raises(SchemaError):
        Event.from_line(_FICTIONAL_TYPE_LINE)


def test_event_log_refuses_to_open_a_log_with_an_unrecognized_type(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_bytes(_FICTIONAL_TYPE_LINE)
    with pytest.raises(CorruptionError):
        EventLog(p)


def test_readonly_event_log_refuses_to_replay_an_unrecognized_type(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_bytes(_FICTIONAL_TYPE_LINE)
    with pytest.raises(CorruptionError):
        list(ReadOnlyEventLog(p).replay())


def test_unrecognized_type_is_caught_regardless_of_position_in_the_log(tmp_path):
    """The scan reads in event_id order and refuses on the FIRST
    unrecognized type it reaches -- not only at the end of the log."""
    p = tmp_path / "events.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.ISSUE_CREATED, issue_id="1"))
    log.close()
    with open(p, "ab") as fh:
        fh.write(_FICTIONAL_TYPE_LINE.replace(b'"event_id":1', b'"event_id":2'))
    with pytest.raises(CorruptionError):
        EventLog(p)


def test_run_started_and_run_finished_are_now_registered_on_the_strict_path(tmp_path):
    """Regression guard: before this session, RunStarted/RunFinished were
    themselves unrecognized types and would have hit the same refusal
    above. They must now open/replay cleanly."""
    p = tmp_path / "events.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.RUN_STARTED, run_id="run-20260821T060512Z-"
                     "3fa85f64-5717-4562-b3fc-2c963f66afa6", payload={
        "engine": {"provider": "claude-headless", "model": "default"},
        "reviewer": {"provider": "qwen", "model": "q"},
        "budget": {"max_attempts_per_issue": 1, "max_executions_per_run": 1,
                   "hard_stop_proxy_cost_per_run_usd": 1.0, "proxy_pricing": "api_list_rates"},
        "config_digest": "a" * 64,
    }))
    log.append(Event(EventType.RUN_FINISHED, run_id="run-20260821T060512Z-"
                     "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                     payload={"outcome": "COMPLETED", "detail": None}))
    log.close()

    events = list(EventLog(p).replay())  # must not raise
    assert [ev.type for ev in events] == [EventType.RUN_STARTED, EventType.RUN_FINISHED]


# ── ADR-25 observer exemption ────────────────────────────────────────────
def test_observer_never_refuses_on_an_unrecognized_type(tmp_path):
    """The bytes-direct observer path is exempt from the strict-path
    refusal above -- it never resolves `type` through EventType at all, so
    it must read a log containing a genuinely unrecognized type without
    raising, unlike EventLog/ReadOnlyEventLog above."""
    p = tmp_path / "events.jsonl"
    p.write_bytes(_FICTIONAL_TYPE_LINE)

    page = read_events_page(p, after=None, limit=10)  # must not raise

    assert page["records"][0]["eventType"] == "SomeFutureEventTypeNotYetRegistered"
    assert page["records"][0]["integrity"] == "OK"


def test_observer_reads_run_started_and_run_finished_without_schema_dependency(tmp_path):
    p = tmp_path / "events.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.RUN_STARTED, run_id="run-20260821T060512Z-"
                     "3fa85f64-5717-4562-b3fc-2c963f66afa6", payload={"engine": {}}))
    log.close()

    page = read_events_page(p, after=None, limit=10)

    assert page["records"][0]["eventType"] == "RunStarted"
    assert page["records"][0]["integrity"] == "OK"
