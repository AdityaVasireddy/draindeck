"""Phase 3 acceptance: bounded catch-up, terminal OVERSIZED handling
(never spins on hasMore), global concurrency four, and OFFLINE/
NOT_INITIALIZED backoff schedule (docs/19 "Registration and polling")."""
from __future__ import annotations

import asyncio
import inspect
import threading
import time

from draindeck_dashboard import poller


def _page(records, *, has_more, next_cursor, availability="AVAILABLE"):
    return {
        "records": records,
        "hasMore": has_more,
        "nextCursor": next_cursor,
        "metadata": {"availability": availability},
    }


def _record(integrity="OK"):
    return {"integrity": integrity, "eventId": 1, "eventType": "IssueCreated"}


def test_stops_at_a_caught_up_page(monkeypatch):
    calls = []

    def fake_invoke(executable, log_path, *, after, limit):
        calls.append(after)
        return _page([_record()], has_more=False, next_cursor=None)

    monkeypatch.setattr(poller, "invoke_observer_events", fake_invoke)
    result = asyncio.run(poller.poll_repository_once("exe", "log", None))

    assert result.pages_fetched == 1
    assert len(calls) == 1
    assert result.halted_oversized is False
    assert result.next_cursor is None


def test_never_exceeds_four_pages_per_tick_even_with_hasmore_true(monkeypatch):
    calls = []

    def fake_invoke(executable, log_path, *, after, limit):
        calls.append(after)
        return _page([_record()], has_more=True, next_cursor=f"cursor-{len(calls)}")

    monkeypatch.setattr(poller, "invoke_observer_events", fake_invoke)
    result = asyncio.run(poller.poll_repository_once("exe", "log", None))

    assert result.pages_fetched == poller.MAX_PAGES_PER_TICK
    assert len(calls) == poller.MAX_PAGES_PER_TICK


def test_oversized_record_halts_immediately_without_chasing_hasmore(monkeypatch):
    calls = []

    def fake_invoke(executable, log_path, *, after, limit):
        calls.append(after)
        if len(calls) == 1:
            return _page([_record()], has_more=True, next_cursor="c1")
        # ADR-25: observe.py can honestly report hasMore=True at an
        # OVERSIZED tail (bytes exist past it) -- the poller must still
        # treat this as terminal, never chase further pages.
        return _page([_record(integrity="OVERSIZED")], has_more=True, next_cursor="c2")

    monkeypatch.setattr(poller, "invoke_observer_events", fake_invoke)
    result = asyncio.run(poller.poll_repository_once("exe", "log", None))

    assert result.halted_oversized is True
    assert result.pages_fetched == 2
    assert len(calls) == 2  # never called a third time chasing hasMore


def test_observer_error_stops_the_tick_and_is_surfaced(monkeypatch):
    from draindeck_dashboard.observer_client import ObserverError

    def fake_invoke(executable, log_path, *, after, limit):
        raise ObserverError("OBSERVER_TIMEOUT", "timed out")

    monkeypatch.setattr(poller, "invoke_observer_events", fake_invoke)
    result = asyncio.run(poller.poll_repository_once("exe", "log", None))

    assert result.error is not None
    assert result.error.code == "OBSERVER_TIMEOUT"
    assert result.pages_fetched == 0


def test_global_concurrency_never_exceeds_four(monkeypatch):
    lock = threading.Lock()
    state = {"current": 0, "max": 0}

    def fake_invoke(executable, log_path, *, after, limit):
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return _page([], has_more=False, next_cursor=None, availability="EMPTY")

    monkeypatch.setattr(poller, "invoke_observer_events", fake_invoke)

    async def run():
        tasks = [poller.poll_repository_once("exe", f"log{i}", None) for i in range(8)]
        return await asyncio.gather(*tasks)

    asyncio.run(run())
    assert state["max"] <= 4


def test_backoff_starts_at_two_and_caps_at_sixty():
    b = poller.next_backoff_seconds(None)
    assert b == 2
    b = poller.next_backoff_seconds(b)
    assert b == 4
    b = poller.next_backoff_seconds(b)
    assert b == 8
    for _ in range(10):
        b = poller.next_backoff_seconds(b)
    assert b == poller.BACKOFF_MAX_SECONDS == 60


def test_availability_is_read_only_from_events_metadata_never_status():
    source = inspect.getsource(poller)
    assert "invoke_observer_status" not in source


def test_poller_never_opens_the_log_file_directly():
    source = inspect.getsource(poller)
    assert "open(" not in source
