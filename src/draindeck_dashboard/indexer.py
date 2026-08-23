"""Evidence, identity, checkpoint, and projections (docs/19 "SQLite, lease,
and identity generations" / "Cursor, idempotency, and integrity").

`ingest_repository_tick` is the one entry point that turns a poller tick
into durable state: one SQLite transaction per fetched page, idempotent
evidence upsert, same-eventId OK-only corruption detection, and the
CURSOR_LOG_REPLACED confirm-before-rollover protocol.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, TypeVar

T = TypeVar("T")
Persist = Callable[[Callable[[sqlite3.Connection], T]], Awaitable[T]]

from .observer_client import ObserverError, invoke_observer_events
from .poller import poll_pages
from .read_models import (
    apply_changed_entities_locked,
    mark_preparing,
    mark_rebuilding,
)
from .sse import prune_changes

_HALTED_DETAIL = "OVERSIZED tail — operator remediation required"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TickOutcome:
    status: str  # "halted" | "ok" | "cursor_replaced_retained" | "cursor_replaced_rolled" | "error"
    pages_ingested: int = 0
    records_ingested: int = 0
    detail: Optional[str] = None


def _current_checkpoint(conn: sqlite3.Connection, repo_id: int):
    return conn.execute(
        "SELECT identity_generation_id, last_record_cursor, last_record_hash, "
        "halted_oversized, reduced_confidence FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()


def _current_generation(conn: sqlite3.Connection, generation_id: int):
    return conn.execute(
        "SELECT id, generation_number, content_lineage, file_generation_device, "
        "file_generation_file_index, file_generation_available "
        "FROM identity_generations WHERE id = ?",
        (generation_id,),
    ).fetchone()


def _identity_matches(generation_row, metadata: dict) -> bool:
    _id, _num, content_lineage, device, file_index, _available = generation_row
    fg = metadata["fileGeneration"]
    return (content_lineage == metadata["contentLineage"]
            and device == fg["device"] and file_index == fg["fileIndex"])


def _open_new_generation(conn: sqlite3.Connection, repo_id: int, metadata: dict) -> int:
    next_number = conn.execute(
        "SELECT COALESCE(MAX(generation_number), 0) + 1 FROM identity_generations "
        "WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()[0]
    fg = metadata["fileGeneration"]
    cur = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (repo_id, next_number, metadata["contentLineage"], fg["device"], fg["fileIndex"],
         int(fg["available"]), _now()),
    )
    return cur.lastrowid


def _set_checkpoint(conn: sqlite3.Connection, repo_id: int, *, identity_generation_id: int,
                    last_record_cursor: Optional[str], last_record_hash: Optional[str],
                    halted_oversized: bool, reduced_confidence: bool,
                    availability: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id) DO UPDATE SET "
        "identity_generation_id=excluded.identity_generation_id, "
        "last_record_cursor=excluded.last_record_cursor, "
        "last_record_hash=excluded.last_record_hash, "
        "halted_oversized=excluded.halted_oversized, "
        "reduced_confidence=excluded.reduced_confidence, "
        "availability=excluded.availability, "
        "updated_at=excluded.updated_at",
        (repo_id, identity_generation_id, last_record_cursor, last_record_hash,
         int(halted_oversized), int(reduced_confidence), availability, _now()),
    )


def _record_change(conn: sqlite3.Connection, repo_id: int, entity_type: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (repo_id, entity_type, entity_id, _now()),
    )


def _decode_ok_payload(rec: dict) -> tuple:
    """(issue_id, execution_id, run_id, event_ts, payload_json) for an
    integrity="OK" record, or all-None if decoding fails. This is
    Dashboard's OWN additional parsing beyond what observe.py already
    validated (event_id/type/schema_version only) — it degrades to
    "unavailable" on any failure rather than raising."""
    raw_b64 = rec.get("recordBytesBase64")
    if raw_b64 is None:
        return (None, None, None, None, None)
    try:
        raw = base64.b64decode(raw_b64)
        body = raw[:-1] if raw.endswith(b"\n") else raw
        obj = json.loads(body)
    except Exception:
        return (None, None, None, None, None)
    if not isinstance(obj, dict):
        return (None, None, None, None, None)
    issue_id = obj.get("issue_id")
    execution_id = obj.get("execution_id")
    run_id = obj.get("run_id")
    ts = obj.get("ts")
    payload = obj.get("payload")
    return (
        issue_id if isinstance(issue_id, str) else None,
        execution_id if isinstance(execution_id, str) else None,
        run_id if isinstance(run_id, str) else None,
        ts if isinstance(ts, str) else None,
        json.dumps(payload) if isinstance(payload, dict) else None,
    )


def _upsert_evidence_and_detect_corrupt(conn: sqlite3.Connection, repo_id: int,
                                        identity_generation_id: int, records: list) -> dict:
    """Returns the sets of issue/execution/run ids named by an OK record
    whose stored content actually changed this call (a brand-new row or a
    TORN/MALFORMED->OK tail repair) -- read_models.apply_changed_entities'
    entity-scoped incremental recompute input. Never includes ids from a
    boundary-redelivered no-op re-upsert of already-identical content."""
    changed_issue_ids: set = set()
    changed_execution_ids: set = set()
    changed_run_ids: set = set()
    unsafe_mutation = False

    for rec in records:
        cursor = rec["cursor"]
        integrity = rec["integrity"]
        event_id = rec.get("eventId")
        event_type = rec.get("eventType")
        schema_version = rec.get("schemaVersion")
        record_hash = (rec.get("truncatedPrefixHash") if integrity == "OVERSIZED"
                       else rec.get("recordHash"))
        length_bytes = rec.get("lengthBytes")
        issue_id = execution_id = run_id = event_ts = payload_json = None
        if integrity == "OK":
            issue_id, execution_id, run_id, event_ts, payload_json = _decode_ok_payload(rec)

        # CORRUPT: two OK records sharing the same non-null integer eventId
        # with a different recordHash, scoped to this identity generation.
        # TORN/MALFORMED/OVERSIZED never reach this branch (event_id is
        # always None for them per observe.py's own _classify).
        if integrity == "OK" and event_id is not None:
            conflicting = conn.execute(
                "SELECT record_cursor, record_hash FROM evidence WHERE repository_id = ? "
                "AND identity_generation_id = ? AND integrity = 'OK' AND event_id = ? "
                "AND record_hash != ?",
                (repo_id, identity_generation_id, event_id, record_hash),
            ).fetchone()
            if conflicting is not None:
                conn.execute(
                    "INSERT INTO corruptions (repository_id, identity_generation_id, event_id, "
                    "cursor_a, hash_a, cursor_b, hash_b, detected_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (repo_id, identity_generation_id, event_id,
                     conflicting[0], conflicting[1], cursor, record_hash, _now()),
                )
                _record_change(conn, repo_id, "corruption", str(event_id))

        # A single record caught up exactly at EOF is intentionally
        # re-delivered on every subsequent tick (docs/19; see
        # ingest_repository_tick's checkpoint-fallback comment) -- harmless
        # for THIS idempotent upsert, but the `changes` table backs the SSE
        # feed, so recording a "change" on every no-op re-delivery would
        # make change_sequence grow forever and the UI refresh on every
        # single tick even though nothing new happened. Only record a
        # change when the row is new or its content actually differs.
        existing = conn.execute(
            "SELECT integrity, record_hash FROM evidence WHERE repository_id = ? "
            "AND identity_generation_id = ? AND record_cursor = ?",
            (repo_id, identity_generation_id, cursor),
        ).fetchone()
        content_changed = existing is None or existing != (integrity, record_hash)
        # docs/27 SS8.4: "a previously OK row changing hash, event ID,
        # decoded content or integrity ... schedules an off-thread scoped
        # rebuild" -- distinct from a brand-new row (existing is None) or a
        # TORN/MALFORMED->OK tail repair (existing[0] != 'OK'), neither of
        # which is an "unsafe" mutation; the incremental apply below
        # already handles both of those correctly by construction.
        if existing is not None and existing[0] == "OK" and content_changed:
            unsafe_mutation = True

        conn.execute(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
            "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
            "event_ts, payload_json, record_hash, length_bytes, stored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(repository_id, identity_generation_id, record_cursor) DO UPDATE SET "
            "integrity=excluded.integrity, event_id=excluded.event_id, "
            "event_type=excluded.event_type, schema_version=excluded.schema_version, "
            "issue_id=excluded.issue_id, execution_id=excluded.execution_id, "
            "run_id=excluded.run_id, event_ts=excluded.event_ts, "
            "payload_json=excluded.payload_json, record_hash=excluded.record_hash, "
            "length_bytes=excluded.length_bytes, stored_at=excluded.stored_at",
            (repo_id, identity_generation_id, cursor, integrity, event_id, event_type,
             schema_version, issue_id, execution_id, run_id, event_ts, payload_json,
             record_hash, length_bytes, _now()),
        )
        if content_changed:
            _record_change(conn, repo_id, "evidence", cursor)
            if integrity == "OK":
                if issue_id is not None:
                    changed_issue_ids.add(issue_id)
                if execution_id is not None:
                    changed_execution_ids.add(execution_id)
                if run_id is not None:
                    changed_run_ids.add(run_id)

    return {
        "issue_ids": changed_issue_ids,
        "execution_ids": changed_execution_ids,
        "run_ids": changed_run_ids,
        "unsafe_mutation": unsafe_mutation,
    }


async def _handle_cursor_log_replaced(conn: sqlite3.Connection, repo_id: int,
                                      executable: str, log_path: str, checkpoint,
                                      persist: Persist) -> TickOutcome:
    """CURSOR_LOG_REPLACED is not itself proof of replacement — a transient
    open failure uses the same error. Confirm with a fresh after=None probe
    before rolling generation; a same-identity or unavailable probe retains
    the checkpoint (docs/19). ``persist`` (see ingest_repository_tick) runs
    the actual write -- inline against ``conn`` by default, or off-thread
    via the read-model worker in production."""
    try:
        probe = await asyncio.to_thread(
            invoke_observer_events, executable, log_path, after=None, limit=1,
        )
    except ObserverError:
        return TickOutcome(status="cursor_replaced_retained",
                           detail="probe unavailable; checkpoint retained, backing off")

    availability = probe["metadata"]["availability"]
    if availability not in ("AVAILABLE", "EMPTY"):
        return TickOutcome(status="cursor_replaced_retained",
                           detail=f"probe availability={availability}; checkpoint retained")

    # Read-only, so it stays on the caller's own connection (`conn`) even
    # in production -- SQLite/WAL gives a consistent snapshot regardless
    # of which connection performs the read.
    generation_row = _current_generation(conn, checkpoint[0]) if checkpoint is not None else None
    if generation_row is not None and _identity_matches(generation_row, probe["metadata"]):
        return TickOutcome(status="cursor_replaced_retained",
                           detail="probe identity unchanged; checkpoint retained")

    def _open_generation_and_checkpoint(c: sqlite3.Connection) -> int:
        c.execute("BEGIN IMMEDIATE")
        try:
            new_generation_id = _open_new_generation(c, repo_id, probe["metadata"])
            mark_preparing(c, repo_id, new_generation_id)
            _set_checkpoint(
                c, repo_id, identity_generation_id=new_generation_id,
                last_record_cursor=None, last_record_hash=None, halted_oversized=False,
                reduced_confidence=not probe["metadata"]["fileGeneration"]["available"],
                availability=probe["metadata"]["availability"],
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return new_generation_id

    new_generation_id = await persist(_open_generation_and_checkpoint)
    # Old-generation view rows are deliberately NOT pruned here. The new
    # generation is only PREPARING at this point -- pruning now would
    # destroy the one complete snapshot a reader could otherwise still be
    # served (docs/27 SS8.4; this session's merge-blocker review).
    # Pruning happens later, atomically together with the new generation's
    # own successful publication, inside rebuild_read_models itself.
    return TickOutcome(status="cursor_replaced_rolled",
                       detail=f"identity replaced; generation {new_generation_id} opened")


def _persist_page(c: sqlite3.Connection, repo_id: int, identity_generation_id: Optional[int],
                  page: dict, last_cursor: Optional[str], last_hash: Optional[str]) -> tuple:
    """One page's whole SQL transaction: open-generation-if-needed,
    evidence upsert, entity-scoped read-model apply, checkpoint, changes
    pruning. Pure function of (c, ...) -> the updated (identity_generation_id,
    last_cursor, last_hash, halted) the caller threads into the next page/
    the final TickOutcome -- no reliance on outer-scope mutable state, so
    it runs identically whether ``c`` is the caller's own connection or
    the read-model worker's dedicated one."""
    c.execute("BEGIN IMMEDIATE")
    try:
        metadata = page["metadata"]
        if identity_generation_id is None:
            identity_generation_id = _open_new_generation(c, repo_id, metadata)
            mark_preparing(c, repo_id, identity_generation_id)

        records = page["records"]
        changed = _upsert_evidence_and_detect_corrupt(c, repo_id, identity_generation_id, records)
        if changed["issue_ids"] or changed["execution_ids"] or changed["run_ids"]:
            apply_changed_entities_locked(
                c, repo_id, identity_generation_id,
                issue_ids=changed["issue_ids"], execution_ids=changed["execution_ids"],
                run_ids=changed["run_ids"],
            )
        if changed["unsafe_mutation"]:
            mark_rebuilding(c, repo_id)

        # Prefer the page's own nextCursor when the observer gave one: for
        # a normal advancing page it is EXCLUSIVE (past every record just
        # durably stored, so a later tick never re-scans records already
        # consumed), and at a TORN/OVERSIZED tail it is already pinned to
        # that record's own start offset. The one case with no page-level
        # cursor at all is catching up to EOF with a COMPLETE last record —
        # there, nextCursor is null, so the fallback below to that record's
        # own INCLUSIVE cursor is the only resumable position the public
        # contract exposes; it is intentionally re-delivered (idempotent
        # upsert) until new data arrives.
        if page["nextCursor"] is not None:
            last_cursor = page["nextCursor"]
        elif records:
            last_cursor = records[-1]["cursor"]
        if records:
            last_record = records[-1]
            last_hash = (last_record.get("truncatedPrefixHash")
                        if last_record["integrity"] == "OVERSIZED"
                        else last_record.get("recordHash"))
        # An empty caught-up page (no records, nextCursor null) deliberately
        # leaves last_cursor/last_hash unchanged — the durable checkpoint
        # must never regress to offset zero just because nothing new arrived.

        halted = any(r["integrity"] == "OVERSIZED" for r in records)
        reduced_confidence = not metadata["fileGeneration"]["available"]

        _set_checkpoint(
            c, repo_id, identity_generation_id=identity_generation_id,
            last_record_cursor=last_cursor, last_record_hash=last_hash,
            halted_oversized=halted, reduced_confidence=reduced_confidence,
            availability=metadata["availability"],
        )
        prune_changes(c)  # retain only the latest 10,000 (docs/19)
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    return identity_generation_id, last_cursor, last_hash, halted


async def ingest_repository_tick(conn: sqlite3.Connection, repo_id: int,
                                 executable: str, log_path: str, *,
                                 persist: Optional[Persist] = None) -> TickOutcome:
    """``persist``: optional ``async def persist(fn) -> T`` that runs
    ``fn(some_connection)`` and returns its result. Defaults to running
    ``fn(conn)`` inline on the calling coroutine -- direct callers (every
    existing test, plus any other synchronous use) get identical behavior
    to before this parameter existed. In production, scheduler.py passes a
    persist that routes through ReadModelWorker so every SQL write for
    this tick's pages/rollover runs off the ASGI event loop on the
    worker's own dedicated connection -- while poll_pages' observer-
    subprocess I/O below stays on the event loop, so multiple repositories'
    ticks keep polling concurrently (only the SQL work serializes through
    the one lease-owned writer, not the whole tick)."""
    if persist is None:
        async def persist(fn):
            return fn(conn)

    checkpoint = _current_checkpoint(conn, repo_id)

    if checkpoint is not None and checkpoint[3]:  # halted_oversized
        return TickOutcome(status="halted", detail=_HALTED_DETAIL)

    after = checkpoint[1] if checkpoint is not None else None
    last_cursor = after
    last_hash = checkpoint[2] if checkpoint is not None else None
    identity_generation_id = checkpoint[0] if checkpoint is not None else None

    pages_ingested = 0
    records_ingested = 0
    try:
        async for page in poll_pages(executable, log_path, after):
            identity_generation_id, last_cursor, last_hash, halted = await persist(
                lambda c, _p=page, _gid=identity_generation_id, _lc=last_cursor, _lh=last_hash:
                    _persist_page(c, repo_id, _gid, _p, _lc, _lh)
            )

            pages_ingested += 1
            records_ingested += len(page["records"])
            if halted:
                return TickOutcome(status="halted", pages_ingested=pages_ingested,
                                   records_ingested=records_ingested, detail=_HALTED_DETAIL)
    except ObserverError as e:
        if e.code == "CURSOR_LOG_REPLACED":
            # Re-fetch rather than reuse the `checkpoint` captured at tick
            # start: an earlier page in THIS SAME tick may already have
            # opened a new generation and committed (each page is its own
            # committed transaction, so a fresh read here is durable, not
            # racy). Passing the stale start-of-tick value would make the
            # generation-identity comparison below compare against the
            # WRONG generation, opening a redundant one and orphaning the
            # evidence that earlier page already committed.
            current_checkpoint = _current_checkpoint(conn, repo_id)
            return await _handle_cursor_log_replaced(
                conn, repo_id, executable, log_path, current_checkpoint, persist)
        return TickOutcome(status="error", detail=e.code)

    return TickOutcome(status="ok", pages_ingested=pages_ingested, records_ingested=records_ingested)
