"""Read-only external observer (ADR-25, docs/08 §5g; SPEC.md).

A bytes-direct reader over the event log's on-disk file. It never
instantiates EventLog/ReadOnlyEventLog, never acquires the writer or
workspace mutex, never repairs or truncates the log, and never invokes
Git. It is a consumer of the log's physical newline-delimited framing,
not a participant in the writer/replay path — see docs/03's added
"Consumer note" for the boundary this module must never cross.

Unknown event types and schema versions are retained as exact raw
evidence (no dependency on ``events.schema.Event.from_line``'s strict
validation); a malformed or torn record is surfaced, not hidden.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CONTRACT_VERSION = 1
MIN_LIMIT = 1
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


class ObserverInputError(ValueError):
    """A caller-supplied argument fails the observer's input contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> dict:
        return {
            "contractVersion": CONTRACT_VERSION,
            "error": {"code": self.code, "message": self.message},
        }


def validate_log_path(raw: str) -> Path:
    """Accept only an absolute path; an existing non-regular-file path
    (e.g. a directory) is rejected. Non-existence is NOT an error here —
    it is an observable state, reported by read_status/read_events_page
    as NOT_INITIALIZED rather than refused at the input layer."""
    path = Path(raw)
    if not path.is_absolute():
        raise ObserverInputError(
            "LOG_PATH_NOT_ABSOLUTE",
            f"--log must be an absolute path, got {raw!r}",
        )
    if path.exists() and not path.is_file():
        raise ObserverInputError(
            "LOG_PATH_NOT_REGULAR_FILE",
            f"--log must name a regular file, got {raw!r}",
        )
    return path


def validate_limit(limit: int) -> int:
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ObserverInputError(
            "LIMIT_OUT_OF_RANGE",
            f"--limit must be between {MIN_LIMIT} and {MAX_LIMIT}, got {limit}",
        )
    return limit


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str) -> int:
    try:
        offset = int(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii"))
    except Exception as e:
        raise ObserverInputError(
            "CURSOR_INVALID",
            f"--after is not a cursor this observer issued: {cursor!r}",
        ) from e
    if offset < 0:
        raise ObserverInputError(
            "CURSOR_INVALID",
            f"--after is not a cursor this observer issued: {cursor!r}",
        )
    return offset


@dataclass(frozen=True)
class _RawRecord:
    offset: int
    raw: bytes          # includes the trailing \n when terminated
    terminated: bool


def _iter_raw_records(data: bytes, start_offset: int):
    pos, n = start_offset, len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        if nl == -1:
            yield _RawRecord(offset=pos, raw=data[pos:], terminated=False)
            return
        yield _RawRecord(offset=pos, raw=data[pos:nl + 1], terminated=True)
        pos = nl + 1


def _classify(raw_line: bytes) -> tuple[str, Optional[int], Optional[str], Optional[int]]:
    """(integrity, eventId, eventType, schemaVersion) for one terminated
    record's raw bytes (trailing newline included). Field extraction is
    best-effort and does not validate against EventType/SCHEMA_VERSION —
    an unrecognized type or schema version is still OK evidence."""
    body = raw_line[:-1] if raw_line.endswith(b"\n") else raw_line
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return "MALFORMED", None, None, None
    if not isinstance(obj, dict):
        return "MALFORMED", None, None, None
    event_id = obj.get("event_id")
    event_type = obj.get("type")
    schema_version = obj.get("schema_version")
    return (
        "OK",
        event_id if isinstance(event_id, int) else None,
        event_type if isinstance(event_type, str) else None,
        schema_version if isinstance(schema_version, int) else None,
    )


def _record_view(rec: _RawRecord) -> dict:
    if rec.terminated:
        integrity, event_id, event_type, schema_version = _classify(rec.raw)
    else:
        integrity, event_id, event_type, schema_version = "TORN", None, None, None
    return {
        "cursor": _encode_cursor(rec.offset),
        "offsetBytes": rec.offset,
        "lengthBytes": len(rec.raw),
        "recordBytesBase64": base64.b64encode(rec.raw).decode("ascii"),
        "recordHash": hashlib.sha256(rec.raw).hexdigest(),
        "integrity": integrity,
        "eventId": event_id,
        "eventType": event_type,
        "schemaVersion": schema_version,
    }


def _availability(log_path: Path) -> tuple[str, int]:
    """(availability, sizeBytes). Distinguishes genuine absence
    (NOT_INITIALIZED) from a real access failure (OFFLINE) — Path.exists()
    alone cannot, since it swallows every stat() error as False."""
    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        return "NOT_INITIALIZED", 0
    except OSError:
        return "OFFLINE", 0
    return ("EMPTY" if size == 0 else "AVAILABLE"), size


def read_events_page(log_path: Path, *, after: Optional[str], limit: int) -> dict:
    start_offset = _decode_cursor(after) if after is not None else 0
    availability, size = _availability(log_path)
    empty_page = {
        "contractVersion": CONTRACT_VERSION,
        "log": str(log_path),
        "metadata": {"availability": availability, "logSizeBytes": size},
        "records": [],
        "nextCursor": None,
        "hasMore": False,
    }
    if availability in ("NOT_INITIALIZED", "EMPTY", "OFFLINE"):
        return empty_page

    try:
        data = log_path.read_bytes()
    except OSError:
        empty_page["metadata"]["availability"] = "OFFLINE"
        return empty_page

    records: list[dict] = []
    next_cursor: Optional[str] = None
    has_more = False
    for rec in _iter_raw_records(data, start_offset):
        if not rec.terminated:
            # Torn tail: surfaced as evidence; the cursor stays pinned at
            # its start so a later, completed write is re-read in full.
            records.append(_record_view(rec))
            next_cursor = _encode_cursor(rec.offset)
            break
        if len(records) >= limit:
            next_cursor = _encode_cursor(rec.offset)
            has_more = True
            break
        records.append(_record_view(rec))

    return {
        "contractVersion": CONTRACT_VERSION,
        "log": str(log_path),
        "metadata": {"availability": availability, "logSizeBytes": len(data)},
        "records": records,
        "nextCursor": next_cursor,
        "hasMore": has_more,
    }


def read_status(log_path: Path) -> dict:
    availability, _size = _availability(log_path)
    return {
        "contractVersion": CONTRACT_VERSION,
        "log": str(log_path),
        "availability": availability,
        # MVP: never acquire the writer/workspace mutex to determine this
        # (ADR-25) — UNKNOWN is an honest answer; a guessed ACTIVE/IDLE is not.
        "writerState": "UNKNOWN",
    }
