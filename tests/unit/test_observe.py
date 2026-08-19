"""Read-only external observer contract (ADR-25, docs/08 §5g; SPEC.md).

Covers: missing/empty/healthy logs, malformed and unknown-type/schema
records, torn tails, cursor pagination, stable exact-byte hashing,
structured input errors, and non-mutation of the log / `.draindeck` / Git.
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


# ── cursor pagination ────────────────────────────────────────────────

def test_cursor_pagination_walks_the_full_log_in_pages(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        for i in range(5):
            log.append(Event(EventType.ISSUE_CREATED, issue_id=f"{i:03d}"))

    seen: list[int] = []
    cursor = None
    for _ in range(10):
        page = read_events_page(path, after=cursor, limit=2)
        seen.extend(r["eventId"] for r in page["records"])
        if not page["hasMore"]:
            assert page["nextCursor"] is None
            break
        cursor = page["nextCursor"]
    assert seen == [1, 2, 3, 4, 5]


def test_invalid_cursor_is_a_structured_input_error(tmp_path):
    path = tmp_path / "events.jsonl"
    path.touch()
    with pytest.raises(ObserverInputError) as exc:
        read_events_page(path, after="not-a-real-cursor!!", limit=10)
    assert exc.value.code == "CURSOR_INVALID"


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


def test_events_offline_on_stat_failure(tmp_path, monkeypatch):
    path = tmp_path / "events.jsonl"
    path.touch()
    real_stat = Path.stat

    def failing_stat(self, *a, **kw):
        if self == path:
            raise PermissionError("denied")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", failing_stat)
    page = read_events_page(path, after=None, limit=10)
    assert page["metadata"]["availability"] == "OFFLINE"
    assert page["records"] == []


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
