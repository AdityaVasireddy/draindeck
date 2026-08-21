"""Evidence, identity, checkpoint, and projections (docs/19 "SQLite, lease,
and identity generations" / "Cursor, idempotency, and integrity").

`ingest_repository_tick` is the one entry point that turns a poller tick
into durable state: one SQLite transaction per fetched page, idempotent
evidence upsert, same-eventId OK-only corruption detection, and the
CURSOR_LOG_REPLACED confirm-before-rollover protocol.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .observer_client import ObserverError, invoke_observer_events
from .poller import poll_pages

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
                    halted_oversized: bool, reduced_confidence: bool) -> None:
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(repository_id) DO UPDATE SET "
        "identity_generation_id=excluded.identity_generation_id, "
        "last_record_cursor=excluded.last_record_cursor, "
        "last_record_hash=excluded.last_record_hash, "
        "halted_oversized=excluded.halted_oversized, "
        "reduced_confidence=excluded.reduced_confidence, "
        "updated_at=excluded.updated_at",
        (repo_id, identity_generation_id, last_record_cursor, last_record_hash,
         int(halted_oversized), int(reduced_confidence), _now()),
    )


def _record_change(conn: sqlite3.Connection, repo_id: int, entity_type: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
        "VALUES (?, ?, ?, ?)",
        (repo_id, entity_type, entity_id, _now()),
    )


def _upsert_evidence_and_detect_corrupt(conn: sqlite3.Connection, repo_id: int,
                                        identity_generation_id: int, records: list) -> None:
    for rec in records:
        cursor = rec["cursor"]
        integrity = rec["integrity"]
        event_id = rec.get("eventId")
        event_type = rec.get("eventType")
        schema_version = rec.get("schemaVersion")
        record_hash = (rec.get("truncatedPrefixHash") if integrity == "OVERSIZED"
                       else rec.get("recordHash"))
        length_bytes = rec.get("lengthBytes")

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

        conn.execute(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
            "integrity, event_id, event_type, schema_version, record_hash, length_bytes, stored_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(repository_id, identity_generation_id, record_cursor) DO UPDATE SET "
            "integrity=excluded.integrity, event_id=excluded.event_id, "
            "event_type=excluded.event_type, schema_version=excluded.schema_version, "
            "record_hash=excluded.record_hash, length_bytes=excluded.length_bytes, "
            "stored_at=excluded.stored_at",
            (repo_id, identity_generation_id, cursor, integrity, event_id, event_type,
             schema_version, record_hash, length_bytes, _now()),
        )
        _record_change(conn, repo_id, "evidence", cursor)


async def _handle_cursor_log_replaced(conn: sqlite3.Connection, repo_id: int,
                                      executable: str, log_path: str, checkpoint) -> TickOutcome:
    """CURSOR_LOG_REPLACED is not itself proof of replacement — a transient
    open failure uses the same error. Confirm with a fresh after=None probe
    before rolling generation; a same-identity or unavailable probe retains
    the checkpoint (docs/19)."""
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

    generation_row = _current_generation(conn, checkpoint[0]) if checkpoint is not None else None
    if generation_row is not None and _identity_matches(generation_row, probe["metadata"]):
        return TickOutcome(status="cursor_replaced_retained",
                           detail="probe identity unchanged; checkpoint retained")

    conn.execute("BEGIN IMMEDIATE")
    try:
        new_generation_id = _open_new_generation(conn, repo_id, probe["metadata"])
        _set_checkpoint(
            conn, repo_id, identity_generation_id=new_generation_id,
            last_record_cursor=None, last_record_hash=None, halted_oversized=False,
            reduced_confidence=not probe["metadata"]["fileGeneration"]["available"],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return TickOutcome(status="cursor_replaced_rolled",
                       detail=f"identity replaced; generation {new_generation_id} opened")


async def ingest_repository_tick(conn: sqlite3.Connection, repo_id: int,
                                 executable: str, log_path: str) -> TickOutcome:
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
            conn.execute("BEGIN IMMEDIATE")
            try:
                metadata = page["metadata"]
                if identity_generation_id is None:
                    identity_generation_id = _open_new_generation(conn, repo_id, metadata)

                records = page["records"]
                _upsert_evidence_and_detect_corrupt(conn, repo_id, identity_generation_id, records)

                # Prefer the page's own nextCursor when the observer gave
                # one: for a normal advancing page it is EXCLUSIVE (past
                # every record just durably stored, so a later tick never
                # re-scans records already consumed), and at a TORN/
                # OVERSIZED tail it is already pinned to that record's own
                # start offset. The one case with no page-level cursor at
                # all is catching up to EOF with a COMPLETE last record —
                # there, nextCursor is null, so the fallback below to that
                # record's own INCLUSIVE cursor is the only resumable
                # position the public contract exposes; it is intentionally
                # re-delivered (idempotent upsert) until new data arrives.
                if page["nextCursor"] is not None:
                    last_cursor = page["nextCursor"]
                elif records:
                    last_cursor = records[-1]["cursor"]
                if records:
                    last_record = records[-1]
                    last_hash = (last_record.get("truncatedPrefixHash")
                                if last_record["integrity"] == "OVERSIZED"
                                else last_record.get("recordHash"))
                # An empty caught-up page (no records, nextCursor null)
                # deliberately leaves last_cursor/last_hash unchanged — the
                # durable checkpoint must never regress to offset zero just
                # because nothing new arrived.

                halted = any(r["integrity"] == "OVERSIZED" for r in records)
                reduced_confidence = not metadata["fileGeneration"]["available"]

                _set_checkpoint(
                    conn, repo_id, identity_generation_id=identity_generation_id,
                    last_record_cursor=last_cursor, last_record_hash=last_hash,
                    halted_oversized=halted, reduced_confidence=reduced_confidence,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

            pages_ingested += 1
            records_ingested += len(page["records"])
            if halted:
                return TickOutcome(status="halted", pages_ingested=pages_ingested,
                                   records_ingested=records_ingested, detail=_HALTED_DETAIL)
    except ObserverError as e:
        if e.code == "CURSOR_LOG_REPLACED":
            return await _handle_cursor_log_replaced(conn, repo_id, executable, log_path, checkpoint)
        return TickOutcome(status="error", detail=e.code)

    return TickOutcome(status="ok", pages_ingested=pages_ingested, records_ingested=records_ingested)
