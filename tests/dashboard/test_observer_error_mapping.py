"""observer_client's error mapping (docs/19 "Observer output is untrusted
and schema-validated"): exit-1 JSON errors, exit-2 argparse text, timeout,
missing executable, non-UTF8, and non-JSON output all become
``{"error": {"code", "message", "details?"}}`` without exposing raw stderr
or the child environment. Built alongside the Phase 2 subprocess wrapper;
Phase 3 wires this into the polling loop."""
from __future__ import annotations

import subprocess

import pytest

from draindeck_dashboard.observer_client import ObserverError, invoke_observer_status


def _run(monkeypatch, fake_run):
    monkeypatch.setattr("draindeck_dashboard.observer_client.subprocess.run", fake_run)
    return invoke_observer_status("C:/x/draindeck.exe", "C:/x/events.jsonl")


def test_exit1_json_error_is_passed_through_by_code(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b'{"error": {"code": "CURSOR_LOG_REPLACED", "message": "replaced"}}'

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.code == "CURSOR_LOG_REPLACED"


def test_exit1_without_error_object_still_maps_cleanly(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b"{}"

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.code == "OBSERVER_ERROR"


def test_exit2_argparse_text_never_leaks_raw_stderr(monkeypatch):
    class FakeCompleted:
        returncode = 2
        stdout = b"usage: draindeck observe status ...\n"

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.code == "OBSERVER_INVOCATION_FAILED"
    response = exc_info.value.to_response()
    assert "usage:" not in response["error"]["message"]


def test_timeout_maps_to_observer_timeout(monkeypatch):
    def fake_run(argv, **kw):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kw.get("timeout", 10))

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, fake_run)
    assert exc_info.value.code == "OBSERVER_TIMEOUT"


def test_missing_executable_maps_cleanly(monkeypatch):
    def fake_run(argv, **kw):
        raise FileNotFoundError()

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, fake_run)
    assert exc_info.value.code == "OBSERVER_EXECUTABLE_NOT_FOUND"


def test_non_utf8_output_maps_cleanly(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = b"\xff\xfe not utf-8"

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.code == "OBSERVER_OUTPUT_NOT_UTF8"


def test_non_json_stdout_on_success_maps_cleanly(monkeypatch):
    class FakeCompleted:
        returncode = 0
        stdout = b"not json"

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.code == "OBSERVER_OUTPUT_NOT_JSON"


def test_to_response_shape(monkeypatch):
    class FakeCompleted:
        returncode = 1
        stdout = b'{"error": {"code": "LIMIT_OUT_OF_RANGE", "message": "bad", "details": {"limit": 999}}}'

    with pytest.raises(ObserverError) as exc_info:
        _run(monkeypatch, lambda argv, **kw: FakeCompleted())
    assert exc_info.value.to_response() == {
        "error": {"code": "LIMIT_OUT_OF_RANGE", "message": "bad", "details": {"limit": 999}}
    }
