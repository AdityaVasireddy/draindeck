"""Read-only external observer (ADR-25, docs/08 §5g; ADR-25 remediation
amendment, same section; SPEC.md).

A bytes-direct reader over the event log's on-disk file. It never
instantiates EventLog/ReadOnlyEventLog, never acquires the writer or
workspace mutex, never repairs or truncates the log, and never invokes
Git. It is a consumer of the log's physical newline-delimited framing,
not a participant in the writer/replay path — see docs/03's added
"Consumer note" for the boundary this module must never cross.

Unknown event types and schema versions are retained as exact raw
evidence (no dependency on ``events.schema.Event.from_line``'s strict
validation); a malformed or torn record is surfaced, not hidden.

Bounded ingestion: the file is opened once per call and streamed in
CHUNK_SIZE pieces — never ``Path.read_bytes()`` — so a small ``limit``
never loads the whole log into memory, however large the file is. A
single record is capped at MAX_RECORD_BYTES while scanning for its
terminating ``\\n``; a record that never terminates within that cap is
reported as ``OVERSIZED`` evidence (a hash of the scanned prefix, not a
claim about the true, unknown-length record) rather than silently
truncated and passed off as complete, and scanning stops there rather
than reading an unbounded distance looking for its real end.

Identity: every events response reports ``contentLineage`` (a hash of
the first complete record) and ``fileGeneration`` (device + file index,
i.e. Windows volume serial + NTFS file index, or the POSIX equivalent).
A cursor embeds both and is rejected, never silently honored, once they
no longer match the current log — no raw byte offset ever appears in
public output. This catches the log going missing, its on-disk identity
changing, its first record's bytes changing, or the cursor's position
landing past the current file's end: the realistic shapes of "this is
not the log the cursor came from." It is NOT a guarantee against every
possible replacement: an in-place truncate-and-rewrite that preserves
both the file's identity and the exact first-record bytes while changing
only the bytes between the first record and the cursor's position is
indistinguishable from ordinary append-only growth to a reader that
fingerprints only the first record. Closing that would need hashing the
full prefix on every call (unbounded, contradicting the module's own
boundedness guarantee above), persistent cross-invocation state (this
CLI has none), or writer cooperation — all out of scope. See
`_reject_if_cursor_identity_mismatch` and docs/08 §5g Amendment 1's
"Honest scope" note for the same limitation stated in full.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Optional

CONTRACT_VERSION = 1
MIN_LIMIT = 1
MAX_LIMIT = 500
DEFAULT_LIMIT = 100

# Streaming I/O bounds (Part 3 of the ADR-25 remediation). Real Draindeck
# event records are at most a few KB; both caps are sized to never bind on
# legitimate data and only ever engage on corruption/pathological input.
CHUNK_SIZE = 64 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024

# (device, fileIndex), or (None, None) when the filesystem can't expose a
# stable file index.
_Generation = tuple[Optional[int], Optional[int]]


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


# ── cursors: opaque, self-describing, lineage/generation-checked ──────
#
# The CLI is a fresh process per invocation with nothing to remember
# between calls, so a cursor must be self-contained. It carries the byte
# offset to resume at plus the (contentLineage, fileGeneration) identity
# of the log it was issued against; decode alone never trusts the offset
# — the caller must additionally compare identity against the log's
# *current* identity before honoring it (see read_events_page).

def _encode_cursor(offset: int, lineage: Optional[str], generation: _Generation) -> str:
    payload = {"o": offset, "cl": lineage, "fg": list(generation)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_cursor(cursor: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        offset = payload["o"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("bad offset")
        generation = tuple(payload.get("fg") or (None, None))
        if len(generation) != 2:
            raise ValueError("bad generation")
    except Exception as e:
        raise ObserverInputError(
            "CURSOR_INVALID",
            f"--after is not a cursor this observer issued: {cursor!r}",
        ) from e
    return {"offset": offset, "lineage": payload.get("cl"), "generation": generation}


def _reject_if_cursor_identity_mismatch(
    after: Optional[str], lineage: Optional[str], generation: _Generation, size: int,
) -> int:
    """Returns the validated start offset for `after`, or 0 if None.
    Raises CURSOR_LOG_REPLACED (never silently continues) the moment the
    log's identity no longer matches what the cursor was issued against,
    or the cursor now points past the end of a shorter file.

    Bounded, not exhaustive: this only ever compares (contentLineage of
    the first record, fileGeneration, size). An in-place rewrite that
    preserves both fingerprints while changing bytes between the first
    record and `after`'s offset is not detectable this way — see the
    module docstring's Identity section."""
    if after is None:
        return 0
    decoded = _decode_cursor(after)
    if (decoded["lineage"] != lineage
            or decoded["generation"] != generation
            or decoded["offset"] > size):
        raise ObserverInputError(
            "CURSOR_LOG_REPLACED",
            "--after belongs to a different log lineage/generation than the "
            "current log (it was replaced or truncated); restart with after=None",
        )
    return decoded["offset"]


# ── file identity (Part 1: contentLineage / fileGeneration) ───────────

def _generation_token(stat_result: os.stat_result) -> _Generation:
    """(device, fileIndex), or (None, None) when the filesystem doesn't
    expose a stable file index (e.g. some non-NTFS Windows volumes) —
    Python's os.stat already surfaces the Windows volume serial number
    and NTFS file index via st_dev/st_ino; POSIX st_dev/st_ino are the
    same concept natively."""
    ino = stat_result.st_ino
    if not ino:
        return (None, None)
    return (stat_result.st_dev, ino)


def _generation_view(generation: _Generation) -> dict:
    device, file_index = generation
    return {
        "device": device,
        "fileIndex": file_index,
        "available": file_index is not None,
    }


def _read_head_and_lineage(fh: BinaryIO) -> tuple[Optional[str], bytes]:
    """(contentLineage, headBytes): contentLineage is the SHA-256 of the
    first complete (newline-terminated) record's exact raw bytes, or None
    when no complete record exists yet (empty log, or a first record that
    is itself torn/oversized). headBytes is everything read while looking
    for it, returned so a start_offset=0 caller can resume streaming from
    there without re-reading the same bytes — the file position is left
    at the end of headBytes. Bounded: reads at most MAX_RECORD_BYTES +
    CHUNK_SIZE bytes regardless of file size."""
    fh.seek(0)
    buf = b""
    while True:
        # Bounded to [0, MAX_RECORD_BYTES): a \n that only exists beyond
        # the cap must never be treated as terminating this record — see
        # the matching note in _stream_records.
        nl = buf.find(b"\n", 0, MAX_RECORD_BYTES)
        if nl != -1:
            return hashlib.sha256(buf[:nl + 1]).hexdigest(), buf
        if len(buf) >= MAX_RECORD_BYTES:
            return None, buf
        chunk = fh.read(CHUNK_SIZE)
        if not chunk:
            return None, buf
        buf += chunk


# ── bounded, streaming record iteration ────────────────────────────────

@dataclass(frozen=True)
class _RawRecord:
    offset: int
    raw: bytes                    # includes the trailing \n when terminated
    terminated: bool
    oversized: bool = False       # scan capped at MAX_RECORD_BYTES, no \n found
    file_continues: bool = False  # only meaningful if oversized


def _stream_records(fh: BinaryIO, start_offset: int, *, max_records: int,
                     preloaded: bytes = b""):
    """Yields up to `max_records` records starting at start_offset,
    reading the file in bounded CHUNK_SIZE pieces. Never buffers more
    than one in-progress record (capped at MAX_RECORD_BYTES) and never
    reads past producing max_records records — bounded time AND memory
    regardless of how large the underlying file is.

    `preloaded` lets a start_offset=0 caller hand in bytes it already
    read (e.g. while computing contentLineage) instead of paying for a
    second read of the same file head; the file position must already
    sit at the end of those bytes."""
    if start_offset == 0 and preloaded:
        pos, buf = 0, preloaded
    else:
        fh.seek(start_offset)
        pos, buf = start_offset, b""
    produced = 0
    while produced < max_records:
        # Bounded to [0, MAX_RECORD_BYTES): a single read() can overshoot
        # the cap (it may return up to CHUNK_SIZE bytes past whatever was
        # already in buf), so an unbounded `buf.find(b"\n")` here could
        # find a \n that only exists *past* the cap and wrongly accept an
        # oversized record as complete. Only a terminator within the cap
        # counts — this is what makes the cap authoritative rather than
        # advisory.
        nl = buf.find(b"\n", 0, MAX_RECORD_BYTES)
        if nl != -1:
            raw = buf[:nl + 1]
            yield _RawRecord(offset=pos, raw=raw, terminated=True)
            pos += len(raw)
            buf = buf[nl + 1:]
            produced += 1
            continue
        if len(buf) >= MAX_RECORD_BYTES:
            # Safety cap: stop scanning for this record's true end rather
            # than reading an unbounded distance looking for a \n that may
            # not exist. `buf` may hold up to one chunk more than the cap
            # (a single read() can overshoot it) — slice to the exact cap
            # so the reported prefix length is deterministic, and discard
            # the overshoot rather than treating it as consumed evidence.
            capped = buf[:MAX_RECORD_BYTES]
            file_size = os.fstat(fh.fileno()).st_size
            yield _RawRecord(
                offset=pos, raw=capped, terminated=False, oversized=True,
                file_continues=(pos + len(capped)) < file_size,
            )
            return
        chunk = fh.read(CHUNK_SIZE)
        if not chunk:
            if buf:
                yield _RawRecord(offset=pos, raw=buf, terminated=False)
            return
        buf += chunk


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


def _record_view(rec: _RawRecord, lineage: Optional[str], generation: _Generation) -> dict:
    view = {
        "cursor": _encode_cursor(rec.offset, lineage, generation),
        "lengthBytes": len(rec.raw),
        "recordBytesBase64": None,
        "recordHash": None,
        "integrity": None,
        "eventId": None,
        "eventType": None,
        "schemaVersion": None,
        # Only populated for integrity="OVERSIZED": a hash/length of the
        # scanned prefix, explicitly NOT a claim about the true (unknown,
        # possibly larger) record — see module docstring.
        "truncatedPrefixHash": None,
        "truncatedPrefixBytes": None,
    }
    if rec.oversized:
        view["integrity"] = "OVERSIZED"
        view["truncatedPrefixHash"] = hashlib.sha256(rec.raw).hexdigest()
        view["truncatedPrefixBytes"] = len(rec.raw)
        return view
    if rec.terminated:
        integrity, event_id, event_type, schema_version = _classify(rec.raw)
    else:
        integrity, event_id, event_type, schema_version = "TORN", None, None, None
    view.update({
        "recordBytesBase64": base64.b64encode(rec.raw).decode("ascii"),
        "recordHash": hashlib.sha256(rec.raw).hexdigest(),
        "integrity": integrity,
        "eventId": event_id,
        "eventType": event_type,
        "schemaVersion": schema_version,
    })
    return view


def _availability(log_path: Path) -> tuple[str, int]:
    """(availability, sizeBytes). Distinguishes genuine absence
    (NOT_INITIALIZED) from a real access failure (OFFLINE) — Path.exists()
    alone cannot, since it swallows every stat() error as False. Used by
    read_status, which never needs to open/read log content."""
    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        return "NOT_INITIALIZED", 0
    except OSError:
        return "OFFLINE", 0
    return ("EMPTY" if size == 0 else "AVAILABLE"), size


def _empty_events_page(log_path: Path, availability: str, *, after: Optional[str]) -> dict:
    """Only reached for NOT_INITIALIZED/OFFLINE (the file couldn't even
    be opened). A cursor can only ever have been issued while the log was
    AVAILABLE or EMPTY (see read_events_page — those go through the main
    body below, not here), so any `after` presented to a log that can't
    be opened at all necessarily refers to a log state that no longer
    exists. Reject rather than silently returning an empty page as if the
    cursor were simply exhausted."""
    if after is not None:
        _decode_cursor(after)  # CURSOR_INVALID first, if the encoding itself is bad
        raise ObserverInputError(
            "CURSOR_LOG_REPLACED",
            "--after belongs to a different log lineage/generation than the "
            "current log (it was replaced or truncated); restart with after=None",
        )
    return {
        "contractVersion": CONTRACT_VERSION,
        "log": str(log_path),
        "metadata": {
            "availability": availability,
            "logSizeBytes": 0,
            "contentLineage": None,
            "fileGeneration": _generation_view((None, None)),
        },
        "records": [],
        "nextCursor": None,
        "hasMore": False,
    }


def read_events_page(log_path: Path, *, after: Optional[str], limit: int) -> dict:
    try:
        fh = open(log_path, "rb")
    except FileNotFoundError:
        return _empty_events_page(log_path, "NOT_INITIALIZED", after=after)
    except OSError:
        return _empty_events_page(log_path, "OFFLINE", after=after)

    try:
        stat_result = os.fstat(fh.fileno())
        size = stat_result.st_size
        generation = _generation_token(stat_result)
        lineage, head_buf = _read_head_and_lineage(fh)
        availability = "EMPTY" if size == 0 else "AVAILABLE"

        start_offset = _reject_if_cursor_identity_mismatch(after, lineage, generation, size)

        records: list[dict] = []
        next_cursor: Optional[str] = None
        has_more = False
        stream = _stream_records(fh, start_offset, max_records=limit + 1,
                                  preloaded=head_buf)
        for rec in stream:
            if len(records) >= limit:
                next_cursor = _encode_cursor(rec.offset, lineage, generation)
                has_more = True
                break
            records.append(_record_view(rec, lineage, generation))
            if not rec.terminated:
                # Torn/oversized tail: always the last record a stream can
                # produce. The cursor stays pinned at its own start so a
                # later, completed write is re-observed in full rather
                # than treated as already consumed.
                next_cursor = _encode_cursor(rec.offset, lineage, generation)
                has_more = bool(rec.oversized and rec.file_continues)
                break
    finally:
        fh.close()

    return {
        "contractVersion": CONTRACT_VERSION,
        "log": str(log_path),
        "metadata": {
            "availability": availability,
            "logSizeBytes": size,
            "contentLineage": lineage,
            "fileGeneration": _generation_view(generation),
        },
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
