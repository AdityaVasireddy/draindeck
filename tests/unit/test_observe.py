"""Read-only external observer contract (ADR-25, docs/08 §5g; SPEC.md;
ADR-25 remediation amendment, same section).

Covers: missing/empty/healthy logs, malformed and unknown-type/schema
records, torn tails, cursor pagination, stable exact-byte hashing,
structured input errors, non-mutation of the log / `.draindeck` / Git,
content-lineage and file-generation identity, cursor rejection on log
replacement/truncation, strict per-page limit enforcement (including a
torn tail), oversized-record safety handling, and bounded (non
whole-file) reads.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.log import EventLog                     # noqa: E402
from runtime.events.schema import Event, EventType           # noqa: E402
import runtime.observe as observe                             # noqa: E402
from runtime.observe import (                                 # noqa: E402
    ObserverInputError,
    _encode_cursor,
    read_events_page,
    read_status,
    validate_limit,
    validate_log_path,
)


# ── input validation ─────────────────────────────────────────────────

def test_relative_log_path_is_rejected():
    with pytest.raises(ObserverInputError) as exc:
        validate_log_path("relative/events.jsonl")
    assert exc.value.code == "LOG_PATH_NOT_ABSOLUTE"
    resp = exc.value.to_response()
    assert resp == {
        "contractVersion": 1,
        "error": {"code": "LOG_PATH_NOT_ABSOLUTE", "message": exc.value.message},
    }


def test_directory_log_path_is_rejected(tmp_path):
    with pytest.raises(ObserverInputError) as exc:
        validate_log_path(str(tmp_path))
    assert exc.value.code == "LOG_PATH_NOT_REGULAR_FILE"


def test_missing_absolute_log_path_is_accepted_by_validation(tmp_path):
    # Non-existence is an observable state, not an input error.
    p = validate_log_path(str(tmp_path / "missing" / "events.jsonl"))
    assert p == tmp_path / "missing" / "events.jsonl"


@pytest.mark.parametrize("limit", [0, -1, 501, 10_000])
def test_out_of_range_limit_is_rejected(limit):
    with pytest.raises(ObserverInputError) as exc:
        validate_limit(limit)
    assert exc.value.code == "LIMIT_OUT_OF_RANGE"


@pytest.mark.parametrize("limit", [1, 100, 500])
def test_in_range_limit_is_accepted(limit):
    assert validate_limit(limit) == limit


# ── events: missing / empty / healthy ───────────────────────────────

def test_events_missing_log_is_not_initialized(tmp_path):
    page = read_events_page(tmp_path / "events.jsonl", after=None, limit=10)
    assert page["contractVersion"] == 1
    assert page["metadata"]["availability"] == "NOT_INITIALIZED"
    assert page["records"] == []
    assert page["nextCursor"] is None
    assert page["hasMore"] is False
    assert not (tmp_path / "events.jsonl").exists()


def test_events_empty_log_is_empty(tmp_path):
    path = tmp_path / "events.jsonl"
    path.touch()
    page = read_events_page(path, after=None, limit=10)
    assert page["metadata"]["availability"] == "EMPTY"
    assert page["records"] == []


def test_events_healthy_log_returns_all_records(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))

    page = read_events_page(path, after=None, limit=10)
    assert page["metadata"]["availability"] == "AVAILABLE"
    assert page["hasMore"] is False
    assert page["nextCursor"] is None
    assert [r["eventType"] for r in page["records"]] == ["IssueCreated", "IssueActivated"]
    assert [r["eventId"] for r in page["records"]] == [1, 2]
    assert [r["schemaVersion"] for r in page["records"]] == [1, 1]
    assert all(r["integrity"] == "OK" for r in page["records"])


def test_records_never_expose_a_raw_byte_offset(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 2
    for rec in page["records"]:
        assert "offsetBytes" not in rec


# ── malformed / unknown-type / torn evidence ────────────────────────

def test_malformed_complete_record_is_evidence_not_a_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    with open(path, "ab") as fh:
        fh.write(b"not json at all\n")

    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 2
    good, bad = page["records"]
    assert good["integrity"] == "OK"
    assert bad["integrity"] == "MALFORMED"
    assert bad["eventId"] is None
    assert bad["eventType"] is None
    assert bad["schemaVersion"] is None
    assert base64.b64decode(bad["recordBytesBase64"]) == b"not json at all\n"
    # cursor advances past a malformed-but-terminated record
    assert page["hasMore"] is False
    assert page["nextCursor"] is None


def test_unknown_type_and_schema_version_are_retained_as_ok_evidence(tmp_path):
    path = tmp_path / "events.jsonl"
    unknown = {
        "event_id": 1, "schema_version": 99, "ts": "2026-08-19T00:00:00Z",
        "run_id": None, "type": "SomeFutureEventType", "issue_id": None,
        "execution_id": None, "payload": {},
    }
    path.write_bytes((json.dumps(unknown, sort_keys=True) + "\n").encode())

    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 1
    rec = page["records"][0]
    assert rec["integrity"] == "OK"
    assert rec["eventType"] == "SomeFutureEventType"
    assert rec["schemaVersion"] == 99
    assert rec["eventId"] == 1


def test_torn_final_record_is_reported_without_blocking_earlier_records(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    torn = b'{"event_id":2,"schema_version":1,"type":"IssueActivated"'
    with open(path, "ab") as fh:
        fh.write(torn)

    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 2
    complete, tail = page["records"]
    assert complete["integrity"] == "OK"
    assert tail["integrity"] == "TORN"
    assert base64.b64decode(tail["recordBytesBase64"]) == torn
    # the cursor is pinned at the torn record's start, not past it
    assert page["hasMore"] is False
    assert page["nextCursor"] == tail["cursor"]

    # a second read at that cursor sees the same torn evidence again
    # (append-only growth would complete it; nothing here mutates it)
    page2 = read_events_page(path, after=page["nextCursor"], limit=10)
    assert len(page2["records"]) == 1
    assert page2["records"][0]["integrity"] == "TORN"


# ── strict pagination correctness (records.length <= limit, always) ──

def test_cursor_pagination_walks_the_full_log_in_pages(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        for i in range(5):
            log.append(Event(EventType.ISSUE_CREATED, issue_id=f"{i:03d}"))

    seen: list[int] = []
    cursor = None
    for _ in range(10):
        page = read_events_page(path, after=cursor, limit=2)
        assert len(page["records"]) <= 2
        seen.extend(r["eventId"] for r in page["records"])
        if not page["hasMore"]:
            assert page["nextCursor"] is None
            break
        cursor = page["nextCursor"]
    assert seen == [1, 2, 3, 4, 5]


def test_limit_one_walks_complete_records_then_torn_tail_without_exceeding_limit(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
    torn = b'{"event_id":3,"schema_version":1,"type":"IssueEscalated"'
    with open(path, "ab") as fh:
        fh.write(torn)

    seen_integrities = []
    cursor = None
    for _ in range(10):
        page = read_events_page(path, after=cursor, limit=1)
        assert len(page["records"]) <= 1
        seen_integrities.extend(r["integrity"] for r in page["records"])
        if not page["hasMore"]:
            break
        cursor = page["nextCursor"]
    assert seen_integrities == ["OK", "OK", "TORN"]


def test_invalid_cursor_is_a_structured_input_error(tmp_path):
    path = tmp_path / "events.jsonl"
    path.touch()
    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after="not-a-real-cursor!!", limit=10)
    assert exc.value.code == "CURSOR_INVALID"


# ── content lineage / file generation identity ──────────────────────

def test_metadata_reports_content_lineage_and_file_generation(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))

    page = read_events_page(path, after=None, limit=10)
    meta = page["metadata"]
    first_raw = base64.b64decode(page["records"][0]["recordBytesBase64"])
    assert meta["contentLineage"] == hashlib.sha256(first_raw).hexdigest()

    st = path.stat()
    gen = meta["fileGeneration"]
    assert gen["available"] is True
    assert gen["fileIndex"] == st.st_ino
    assert gen["device"] == st.st_dev

    # deterministic and stable across repeated reads of an unchanged file
    page2 = read_events_page(path, after=None, limit=10)
    assert page2["metadata"]["contentLineage"] == meta["contentLineage"]
    assert page2["metadata"]["fileGeneration"] == gen


def test_lineage_and_generation_are_explicitly_unavailable_when_unobservable(tmp_path):
    path = tmp_path / "events.jsonl"

    page = read_events_page(path, after=None, limit=10)  # NOT_INITIALIZED
    assert page["metadata"]["contentLineage"] is None
    assert page["metadata"]["fileGeneration"] == {
        "device": None, "fileIndex": None, "available": False,
    }

    path.touch()  # EMPTY: the file exists, so generation IS observable
    page = read_events_page(path, after=None, limit=10)
    assert page["metadata"]["contentLineage"] is None
    assert page["metadata"]["fileGeneration"]["available"] is True


# ── cursor rejection on log replacement / truncation ────────────────

def test_cursor_rejected_after_log_replaced_with_different_content(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
    page = read_events_page(path, after=None, limit=1)
    assert page["hasMore"] is True
    cursor = page["nextCursor"]

    path.unlink()
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="999"))  # different first record

    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after=cursor, limit=10)
    assert exc.value.code == "CURSOR_LOG_REPLACED"


def test_cursor_rejected_after_log_truncated_even_with_the_same_first_record(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        for i in range(5):
            log.append(Event(EventType.ISSUE_CREATED, issue_id=f"{i:03d}"))
    page = read_events_page(path, after=None, limit=2)
    assert page["hasMore"] is True
    cursor = page["nextCursor"]

    first_len = len(base64.b64decode(page["records"][0]["recordBytesBase64"]))
    original = path.read_bytes()
    path.write_bytes(original[:first_len])  # keep record 1's bytes; drop the rest

    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after=cursor, limit=10)
    assert exc.value.code == "CURSOR_LOG_REPLACED"


def test_cursor_rejected_when_embedded_generation_does_not_match(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    page = read_events_page(path, after=None, limit=10)
    lineage = page["metadata"]["contentLineage"]
    forged = _encode_cursor(0, lineage, (999_999, 999_999))

    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after=forged, limit=10)
    assert exc.value.code == "CURSOR_LOG_REPLACED"


def test_cursor_rejected_when_log_disappears_between_calls(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
    page = read_events_page(path, after=None, limit=1)
    cursor = page["nextCursor"]
    path.unlink()

    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after=cursor, limit=10)
    assert exc.value.code == "CURSOR_LOG_REPLACED"


def test_cursor_replacement_detection_is_bounded_not_a_full_prefix_guarantee(tmp_path):
    """Documents a known, accepted limitation (ADR-25 Amendment 1's
    honesty correction): identity is (fileGeneration, contentLineage of
    the FIRST record only). An in-place truncate-and-rewrite that keeps
    the same underlying file (same fileGeneration) and byte-for-byte
    preserves the first record (same contentLineage) is indistinguishable
    from ordinary append-only growth by this bounded reader — detecting
    it would require hashing the full prefix up to the cursor's offset,
    persistent state, or writer cooperation, none of which this observer
    does. This is NOT a bug to fix; it is the documented boundary of what
    a stat + first-record fingerprint can promise."""
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_CREATED, issue_id="002"))
    page = read_events_page(path, after=None, limit=1)
    cursor = page["nextCursor"]

    original = path.read_bytes()
    first_record_len = len(base64.b64decode(page["records"][0]["recordBytesBase64"]))
    # Truncate-and-rewrite in place (same path, same open-for-write call):
    # keep record 1 byte-for-byte, replace everything after it with
    # DIFFERENT content of the SAME total length the cursor expects.
    replacement_tail = (b'{"event_id":2,"schema_version":1,"ts":"x","run_id":null,'
                         b'"type":"REPLACED","issue_id":null,"execution_id":null,'
                         b'"payload":{}}\n')
    replacement_tail += b" " * (len(original) - first_record_len - len(replacement_tail))
    assert len(replacement_tail) == len(original) - first_record_len  # same total size
    path.write_bytes(original[:first_record_len] + replacement_tail)

    # Accepted, not rejected: fileGeneration and contentLineage both still
    # match, so this in-place rewrite is honestly outside what this
    # observer can detect.
    page2 = read_events_page(path, after=cursor, limit=10)
    assert len(page2["records"]) >= 1
    assert page2["records"][0]["eventType"] == "REPLACED"


# ── stable exact-byte hashing ────────────────────────────────────────

def test_record_hash_is_sha256_of_exactly_the_encoded_bytes(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))

    page = read_events_page(path, after=None, limit=10)
    rec = page["records"][0]
    raw = base64.b64decode(rec["recordBytesBase64"])
    assert rec["recordHash"] == hashlib.sha256(raw).hexdigest()
    assert raw == path.read_bytes()  # single-record file: whole file is the record

    # deterministic across repeated reads
    page_again = read_events_page(path, after=None, limit=10)
    assert page_again["records"][0]["recordHash"] == rec["recordHash"]


# ── oversized-record safety handling ────────────────────────────────

def test_oversized_record_is_capped_hashed_and_flagged_not_silently_truncated(tmp_path, monkeypatch):
    # Cap chosen strictly between the small first record's length and the
    # huge second record's length, so the cap genuinely discriminates
    # between them rather than catching both (or neither).
    monkeypatch.setattr(observe, "MAX_RECORD_BYTES", 40)
    path = tmp_path / "events.jsonl"
    small = b'{"a":1}\n'          # 8 bytes: well within the 40-byte cap
    huge = b"x" * 200             # far past the cap; no newline anywhere
    path.write_bytes(small + huge)

    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 2
    good, oversized = page["records"]
    assert good["integrity"] == "OK"
    assert oversized["integrity"] == "OVERSIZED"
    # not silently truncated-and-presented-as-complete: bytes/hash of the
    # (unknown, possibly larger) true record are explicitly withheld...
    assert oversized["recordBytesBase64"] is None
    assert oversized["recordHash"] is None
    # ...replaced by an honest, exact hash of only the scanned prefix
    assert oversized["truncatedPrefixBytes"] == 40
    assert oversized["truncatedPrefixHash"] == hashlib.sha256(huge[:40]).hexdigest()
    # the file has real bytes beyond the capped prefix — said so, not silent
    assert page["hasMore"] is True


def test_oversized_record_reports_no_more_data_when_the_cap_lands_exactly_at_eof(tmp_path, monkeypatch):
    monkeypatch.setattr(observe, "MAX_RECORD_BYTES", 16)
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"x" * 16)  # exactly the cap, no newline, nothing after it

    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 1
    assert page["records"][0]["integrity"] == "OVERSIZED"
    assert page["hasMore"] is False


def test_newline_past_the_cap_does_not_make_the_record_valid(tmp_path, monkeypatch):
    """Regression for the ADR-25 remediation follow-up: a single read()
    can pull an entire small file into the buffer in one shot, including
    a \\n that sits past MAX_RECORD_BYTES. That \\n must never be treated
    as a valid terminator — only a \\n within the cap counts, for both
    record streaming and contentLineage discovery."""
    monkeypatch.setattr(observe, "MAX_RECORD_BYTES", 50)
    path = tmp_path / "events.jsonl"

    exactly_at_cap = b"x" * 49 + b"\n"        # total length 50 == cap: valid
    path.write_bytes(exactly_at_cap)
    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 1
    assert page["records"][0]["integrity"] != "OVERSIZED"  # terminated (content is non-JSON -> MALFORMED)
    assert page["records"][0]["integrity"] == "MALFORMED"
    assert page["metadata"]["contentLineage"] == hashlib.sha256(exactly_at_cap).hexdigest()

    one_byte_past_cap = b"x" * 50 + b"\n"     # total length 51 == cap+1: must be OVERSIZED
    path.write_bytes(one_byte_past_cap)
    page2 = read_events_page(path, after=None, limit=10)
    assert len(page2["records"]) == 1
    assert page2["records"][0]["integrity"] == "OVERSIZED"
    assert page2["records"][0]["truncatedPrefixBytes"] == 50
    assert page2["records"][0]["truncatedPrefixHash"] == hashlib.sha256(one_byte_past_cap[:50]).hexdigest()
    # no complete record exists within the cap, so lineage is unavailable
    assert page2["metadata"]["contentLineage"] is None


# ── bounded ingestion (Part 3) ──────────────────────────────────────

def test_observe_never_calls_path_read_bytes(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))

    def forbidden(self, *a, **kw):
        raise AssertionError("observe.py must not call Path.read_bytes()")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    page = read_events_page(path, after=None, limit=10)
    assert len(page["records"]) == 2
    read_status(path)


def test_bounded_reads_do_not_load_the_whole_file_for_a_small_limit(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        for i in range(20_000):
            log.append(Event(EventType.ISSUE_CREATED, issue_id=f"{i:05d}"))
    full_size = path.stat().st_size
    assert full_size > 2_000_000  # sanity: this fixture is genuinely large

    real_open = open
    counters: list[dict] = []

    class _CountingFile:
        def __init__(self, fh):
            self._fh = fh
            self.read_bytes = 0

        def read(self, n=-1):
            data = self._fh.read(n)
            self.read_bytes += len(data)
            return data

        def seek(self, *a, **kw):
            return self._fh.seek(*a, **kw)

        def fileno(self):
            return self._fh.fileno()

        def close(self):
            return self._fh.close()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._fh.close()

    def counting_open(file, mode="r", *a, **kw):
        fh = real_open(file, mode, *a, **kw)
        if Path(file) == path and "b" in mode:
            wrapper = _CountingFile(fh)
            counters.append(wrapper)
            return wrapper
        return fh

    monkeypatch.setattr("builtins.open", counting_open)
    page = read_events_page(path, after=None, limit=5)
    assert len(page["records"]) == 5
    assert page["hasMore"] is True

    total_read = sum(c.read_bytes for c in counters)
    assert total_read < 200_000  # a small bounded slice, nowhere near full_size


# ── status ───────────────────────────────────────────────────────────

def test_status_not_initialized(tmp_path):
    status = read_status(tmp_path / "events.jsonl")
    assert status == {
        "contractVersion": 1,
        "log": str(tmp_path / "events.jsonl"),
        "availability": "NOT_INITIALIZED",
        "writerState": "UNKNOWN",
    }


def test_status_empty(tmp_path):
    path = tmp_path / "events.jsonl"
    path.touch()
    assert read_status(path)["availability"] == "EMPTY"


def test_status_available(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    status = read_status(path)
    assert status["availability"] == "AVAILABLE"
    assert status["writerState"] == "UNKNOWN"


def test_status_offline_on_stat_failure(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.touch()
    real_stat = Path.stat

    def failing_stat(self, *a, **kw):
        if self == path:
            raise PermissionError("denied")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", failing_stat)
    assert read_status(path)["availability"] == "OFFLINE"


def test_events_offline_when_open_fails(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.touch()
    real_open = open

    def failing_open(file, mode="r", *a, **kw):
        if Path(file) == path and "b" in mode:
            raise PermissionError("denied")
        return real_open(file, mode, *a, **kw)

    monkeypatch.setattr("builtins.open", failing_open)
    page = read_events_page(path, after=None, limit=10)
    assert page["metadata"]["availability"] == "OFFLINE"
    assert page["records"] == []
    assert page["metadata"]["contentLineage"] is None
    assert page["metadata"]["fileGeneration"]["available"] is False


# ── non-mutation ─────────────────────────────────────────────────────

def test_observe_module_never_imports_writer_lock_or_git_types():
    tree = ast.parse(inspect.getsource(observe))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
    forbidden = {"EventLog", "ReadOnlyEventLog", "WorkspaceLease",
                 "subprocess", "WindowsMutexApi"}
    assert imported & forbidden == set()


def test_reads_never_mutate_the_log_bytes_or_create_sidecars(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    with open(path, "ab") as fh:
        fh.write(b'{"event_id":2,"schema_version":1,"type":"IssueActivated"')  # torn

    before_bytes = path.read_bytes()
    before_listing = sorted(p.name for p in tmp_path.iterdir())

    for _ in range(3):
        read_events_page(path, after=None, limit=1)
        read_status(path)

    assert path.read_bytes() == before_bytes
    assert sorted(p.name for p in tmp_path.iterdir()) == before_listing
    assert not (tmp_path / ".draindeck").exists()
    assert not list(tmp_path.glob("*.torn.*"))


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                        cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"git {args} failed: {p.stderr}")
    return p.stdout


def test_reads_never_touch_git_state(tmp_path):
    _git(tmp_path, "init", "-b", "trunk")
    _git(tmp_path, "config", "core.autocrlf", "false")
    path = tmp_path / "state" / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "seed")
    before_status = _git(tmp_path, "status", "--porcelain")

    read_events_page(path, after=None, limit=10)
    read_status(path)

    assert _git(tmp_path, "status", "--porcelain") == before_status


# ── CLI command wiring ──────────────────────────────────────────────

def test_cmd_observe_events_rejects_relative_path(capsys):
    from runtime import main

    rc = main.cmd_observe_events(
        SimpleNamespace(log="relative.jsonl", after=None, limit=10))
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "LOG_PATH_NOT_ABSOLUTE"


def test_cmd_observe_events_rejects_bad_limit(tmp_path, capsys):
    from runtime import main

    rc = main.cmd_observe_events(
        SimpleNamespace(log=str(tmp_path / "e.jsonl"), after=None, limit=0))
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "LIMIT_OUT_OF_RANGE"


def test_cmd_observe_events_reports_cursor_log_replaced(tmp_path, capsys):
    from runtime import main

    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="001"))
    page = read_events_page(path, after=None, limit=1)
    cursor = page["nextCursor"]
    path.unlink()
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="999"))

    rc = main.cmd_observe_events(
        SimpleNamespace(log=str(path), after=cursor, limit=10))
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "CURSOR_LOG_REPLACED"


def test_cmd_observe_events_success_prints_json_page(tmp_path, capsys):
    from runtime import main

    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))

    rc = main.cmd_observe_events(
        SimpleNamespace(log=str(path), after=None, limit=10))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["metadata"]["availability"] == "AVAILABLE"
    assert len(out["records"]) == 1


def test_cmd_observe_status_success_prints_json(tmp_path, capsys):
    from runtime import main

    rc = main.cmd_observe_status(SimpleNamespace(log=str(tmp_path / "e.jsonl")))
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["availability"] == "NOT_INITIALIZED"
    assert out["writerState"] == "UNKNOWN"


def test_cmd_observe_status_rejects_directory(tmp_path, capsys):
    from runtime import main

    rc = main.cmd_observe_status(SimpleNamespace(log=str(tmp_path)))
    assert rc == 1
    err = json.loads(capsys.readouterr().err)
    assert err["error"]["code"] == "LOG_PATH_NOT_REGULAR_FILE"


def test_main_dispatches_observe_events_and_status(tmp_path, capsys):
    from runtime.main import main as entrypoint

    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="001"))

    rc = entrypoint(["observe", "events", "--log", str(path), "--format", "json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["records"]) == 1

    rc = entrypoint(["observe", "status", "--log", str(path), "--format", "json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["availability"] == "AVAILABLE"


def test_main_rejects_unsupported_format(tmp_path):
    from runtime.main import main as entrypoint

    with pytest.raises(SystemExit):
        entrypoint(["observe", "status", "--log", str(tmp_path / "e.jsonl"),
                    "--format", "xml"])
