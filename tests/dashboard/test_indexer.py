"""Phase 4 acceptance: caught-up polling does not restart at offset zero;
torn completion; transient cursor error without rollover; confirmed
identity replacement; same-eventId OK-only corruption; reduced-confidence;
terminal OVERSIZED; one page is one transaction (docs/19 "Cursor,
idempotency, and integrity" / "SQLite, lease, and identity generations").

These tests drive the REAL `runtime.observe.read_events_page` logic
through a thin monkeypatched wrapper (instead of hand-fabricated fake
pages), so the cursor/hash/identity semantics under test are exactly what
the real observer produces. This does not violate "Dashboard consumes
only via the observe CLI" — that boundary constrains production code in
src/draindeck_dashboard, not test fixtures.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from draindeck_dashboard import indexer, poller
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.observer_client import ObserverError
from draindeck_dashboard.repositories import register_repository
from runtime.observe import read_events_page


def _observer_reader(executable, log_path, *, after, limit):
    return read_events_page(Path(log_path), after=after, limit=limit)


def _write_event_line(log_path: Path, event_id: int, payload: dict | None = None, *,
                      event_type: str = "IssueCreated", issue_id: str | None = None,
                      execution_id: str | None = None, run_id: str | None = None) -> None:
    line = json.dumps({
        "event_id": event_id, "schema_version": 1, "ts": "2026-08-20T00:00:00Z",
        "run_id": run_id, "type": event_type, "issue_id": issue_id,
        "execution_id": execution_id, "payload": payload or {},
    }, sort_keys=True, separators=(",", ":")) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def _register(conn, tmp_path, log_path):
    repo_dir = tmp_path / "repo"
    (repo_dir / ".git").mkdir(parents=True, exist_ok=True)
    return register_repository(conn, project_path=str(repo_dir), log_path=str(log_path))["id"]


def _seed_generation_and_checkpoint(conn, repo_id, *, lineage, device, file_index,
                                    cursor="stale-cursor", record_hash="stale-hash"):
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 1, ?, ?, ?, 1, '2026-08-20T00:00:00Z')",
        (repo_id, lineage, device, file_index),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, updated_at) "
        "VALUES (?, ?, ?, ?, 0, 0, '2026-08-20T00:00:00Z')",
        (repo_id, gen_id, cursor, record_hash),
    )
    return gen_id


# ── basic ingest + caught-up-does-not-reset ────────────────────────────

def test_basic_ingest_persists_evidence_and_advances_checkpoint(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)
    _write_event_line(log_path, 2)

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    assert outcome.status == "ok"
    assert outcome.records_ingested == 2
    rows = conn.execute(
        "SELECT integrity, event_id FROM evidence WHERE repository_id = ? ORDER BY id",
        (repo_id,),
    ).fetchall()
    assert [r[1] for r in rows] == [1, 2]
    checkpoint = conn.execute(
        "SELECT last_record_cursor FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert checkpoint[0] is not None


def test_caught_up_polling_does_not_restart_at_offset_zero(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    calls = []

    def spy(executable, log_path_arg, *, after, limit):
        calls.append(after)
        return _observer_reader(executable, log_path_arg, after=after, limit=limit)

    monkeypatch.setattr(poller, "invoke_observer_events", spy)
    repo_id = _register(conn, tmp_path, log_path)

    asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    checkpoint_after_first = conn.execute(
        "SELECT last_record_cursor FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert checkpoint_after_first is not None

    second = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    assert second.status == "ok"
    # the SECOND tick's call must resume from the persisted checkpoint,
    # never re-scan the whole log from offset zero (after=None)
    assert calls[-1] == checkpoint_after_first
    # a single record caught up exactly at EOF has no page-level nextCursor
    # to advance past it (observe.py's only cursor there is the record's
    # own inclusive one), so it is intentionally re-delivered every empty
    # tick — idempotent upsert means this stays exactly one evidence row,
    # not a growing duplicate.
    evidence_count = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert evidence_count == 1
    checkpoint_after_second = conn.execute(
        "SELECT last_record_cursor FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert checkpoint_after_second == checkpoint_after_first  # no regression


# ── torn tail: persists, then completes via re-delivery ────────────────

def test_torn_tail_persists_then_completes_on_redelivery(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(
            '{"event_id":2,"schema_version":1,"ts":"2026-08-20T00:00:01Z",'
            '"run_id":null,"type":"IssueCreated","issue_id":null,'
            '"execution_id":null,"payload":{}'
        )  # deliberately no trailing newline: a torn record

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    first = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert first.status == "ok"
    rows = conn.execute(
        "SELECT integrity, event_id FROM evidence WHERE repository_id = ? ORDER BY id",
        (repo_id,),
    ).fetchall()
    assert rows[0] == ("OK", 1)
    assert rows[1][0] == "TORN"
    assert rows[1][1] is None

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("}\n")  # complete the record

    second = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert second.status == "ok"
    rows_after = conn.execute(
        "SELECT integrity, event_id FROM evidence WHERE repository_id = ? ORDER BY id",
        (repo_id,),
    ).fetchall()
    assert rows_after[-1] == ("OK", 2)
    assert len(rows_after) == 2  # idempotent upsert: the torn row updated in place


# ── CORRUPT: same eventId, differing hash, OK-only ─────────────────────

def test_same_eventid_ok_only_corruption_is_detected(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, payload={"v": "first"})
    _write_event_line(log_path, 1, payload={"v": "second"})

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    corruptions = conn.execute(
        "SELECT event_id, hash_a, hash_b FROM corruptions WHERE repository_id = ?", (repo_id,)
    ).fetchall()
    assert len(corruptions) == 1
    assert corruptions[0][0] == 1
    assert corruptions[0][1] != corruptions[0][2]


def test_differing_integrity_at_same_cursor_never_triggers_corrupt(tmp_path, monkeypatch):
    # A torn-then-completed record changes hash at the SAME cursor but must
    # never be treated as CORRUPT (event_id is None while TORN). The FIRST
    # record must stay complete throughout -- contentLineage is derived
    # from it, so leaving IT torn-then-completed would itself look like a
    # log replacement (a different, legitimate case already covered by
    # test_torn_tail_persists_then_completes_on_redelivery).
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"event_id":2,"schema_version":1,"ts":"2026-08-20T00:00:00Z",'
                '"run_id":null,"type":"IssueCreated","issue_id":null,'
                '"execution_id":null,"payload":{}')

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)
    asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("}\n")
    asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    corruptions = conn.execute(
        "SELECT COUNT(*) FROM corruptions WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert corruptions == 0


# ── terminal OVERSIZED ──────────────────────────────────────────────────

def test_terminal_oversized_persists_then_halts_without_further_polling(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    with open(log_path, "wb") as f:
        f.write(b"x" * (8 * 1024 * 1024 + 100))  # exceeds MAX_RECORD_BYTES, no newline

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "halted"

    row = conn.execute(
        "SELECT integrity FROM evidence WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert row[0] == "OVERSIZED"
    checkpoint = conn.execute(
        "SELECT halted_oversized FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert checkpoint[0] == 1

    def must_not_be_called(*a, **kw):
        raise AssertionError("must never poll a halted repository again")

    monkeypatch.setattr(poller, "invoke_observer_events", must_not_be_called)
    second = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert second.status == "halted"


# ── CURSOR_LOG_REPLACED: confirm-before-rollover protocol ──────────────

def test_confirmed_identity_replacement_rolls_generation(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text("")
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path, log_path)
    old_gen_id = _seed_generation_and_checkpoint(
        conn, repo_id, lineage="old-lineage", device=1, file_index=1)

    def raises_replaced(executable, log_path_arg, *, after, limit):
        raise ObserverError("CURSOR_LOG_REPLACED", "replaced")

    def confirming_probe(executable, log_path_arg, *, after, limit):
        assert after is None
        return {"metadata": {"availability": "EMPTY", "contentLineage": None,
                             "fileGeneration": {"device": 2, "fileIndex": 2, "available": True}}}

    monkeypatch.setattr(poller, "invoke_observer_events", raises_replaced)
    monkeypatch.setattr(indexer, "invoke_observer_events", confirming_probe)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    assert outcome.status == "cursor_replaced_rolled"
    generation_numbers = [g[0] for g in conn.execute(
        "SELECT generation_number FROM identity_generations WHERE repository_id = ? "
        "ORDER BY generation_number", (repo_id,))]
    assert generation_numbers == [1, 2]
    checkpoint = conn.execute(
        "SELECT identity_generation_id, last_record_cursor FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    assert checkpoint[0] != old_gen_id
    assert checkpoint[1] is None


def test_transient_probe_failure_retains_checkpoint_and_backs_off(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text("")
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path, log_path)
    old_gen_id = _seed_generation_and_checkpoint(
        conn, repo_id, lineage="old-lineage", device=1, file_index=1)

    def raises_replaced(executable, log_path_arg, *, after, limit):
        raise ObserverError("CURSOR_LOG_REPLACED", "replaced")

    def failing_probe(executable, log_path_arg, *, after, limit):
        raise ObserverError("OBSERVER_TIMEOUT", "timed out")

    monkeypatch.setattr(poller, "invoke_observer_events", raises_replaced)
    monkeypatch.setattr(indexer, "invoke_observer_events", failing_probe)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    assert outcome.status == "cursor_replaced_retained"
    count = conn.execute(
        "SELECT COUNT(*) FROM identity_generations WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert count == 1  # no new generation opened
    checkpoint = conn.execute(
        "SELECT identity_generation_id, last_record_cursor FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    assert checkpoint == (old_gen_id, "stale-cursor")


def test_probe_confirming_same_identity_retains_checkpoint(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    log_path.write_text("")
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    repo_id = _register(conn, tmp_path, log_path)
    old_gen_id = _seed_generation_and_checkpoint(
        conn, repo_id, lineage="old-lineage", device=1, file_index=1)

    def raises_replaced(executable, log_path_arg, *, after, limit):
        raise ObserverError("CURSOR_LOG_REPLACED", "replaced")

    def same_identity_probe(executable, log_path_arg, *, after, limit):
        return {"metadata": {"availability": "AVAILABLE", "contentLineage": "old-lineage",
                             "fileGeneration": {"device": 1, "fileIndex": 1, "available": True}}}

    monkeypatch.setattr(poller, "invoke_observer_events", raises_replaced)
    monkeypatch.setattr(indexer, "invoke_observer_events", same_identity_probe)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    assert outcome.status == "cursor_replaced_retained"
    count = conn.execute(
        "SELECT COUNT(*) FROM identity_generations WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert count == 1
    checkpoint = conn.execute(
        "SELECT identity_generation_id FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert checkpoint[0] == old_gen_id


# ── reduced confidence ──────────────────────────────────────────────────

def test_reduced_confidence_when_file_generation_unavailable(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)

    import runtime.observe as observe_module
    monkeypatch.setattr(observe_module, "_generation_token", lambda stat_result: (None, None))

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    checkpoint = conn.execute(
        "SELECT reduced_confidence FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert checkpoint[0] == 1


# ── one page is one transaction ─────────────────────────────────────────

def test_one_page_is_one_transaction_atomic_rollback_on_failure(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    def boom(*a, **kw):
        raise RuntimeError("simulated failure mid-transaction")

    monkeypatch.setattr(indexer, "_set_checkpoint", boom)

    with pytest.raises(RuntimeError):
        asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))

    # rolled back together: the evidence insert from the SAME page must
    # not have survived either.
    evidence_count = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert evidence_count == 0
    checkpoint = conn.execute(
        "SELECT 1 FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert checkpoint is None


# ── payload decoding + availability (Phase 5 groundwork) ───────────────

def test_ok_record_payload_is_decoded_and_persisted(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1, payload={"title": "fix the bug"},
                      event_type="IssueCreated", issue_id="42", run_id="run-1")

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    row = conn.execute(
        "SELECT issue_id, execution_id, run_id, event_ts, payload_json "
        "FROM evidence WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    assert row[0] == "42"
    assert row[1] is None
    assert row[2] == "run-1"
    assert row[3] == "2026-08-20T00:00:00Z"
    assert json.loads(row[4]) == {"title": "fix the bug"}


def test_non_ok_record_never_gets_decoded_payload_fields(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write('{"event_id":1,"schema_version":1,"ts":"2026-08-20T00:00:00Z",'
                '"run_id":null,"type":"IssueCreated","issue_id":"42",'
                '"execution_id":null,"payload":{}')  # torn: no trailing newline

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    row = conn.execute(
        "SELECT integrity, issue_id, payload_json FROM evidence WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    assert row[0] == "TORN"
    assert row[1] is None
    assert row[2] is None


def test_checkpoint_stores_last_observed_availability(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    _write_event_line(log_path, 1)

    conn = connect_and_init(tmp_path / "dash.sqlite3")
    monkeypatch.setattr(poller, "invoke_observer_events", _observer_reader)
    repo_id = _register(conn, tmp_path, log_path)

    outcome = asyncio.run(indexer.ingest_repository_tick(conn, repo_id, "exe", str(log_path)))
    assert outcome.status == "ok"

    availability = conn.execute(
        "SELECT availability FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()[0]
    assert availability == "AVAILABLE"
