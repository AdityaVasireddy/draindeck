"""ClaudeHeadlessEngine unit tests — ADR-18 env hygiene and the timeout/kill/
reap path, exercised with a Python dummy child (no real `claude` CLI: slow,
non-deterministic, and it would bill real usage). The dummy is substituted via
the ``_command`` test seam; construction bypasses the PATH resolution so these
run anywhere. See the Session-4 plan §5(a). Mutation M4 (drop the ANTHROPIC_API_KEY
strip) turns ``test_subscription_strips_api_key`` red; a unit-level M3 (gut
``reap_orphans``) turns ``test_reap_orphans_kills_survivor`` red.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from runtime.engine import claude_headless as engine_module  # noqa: E402

from runtime.config import EngineCfg                       # noqa: E402
from runtime.engine.claude_headless import (               # noqa: E402
    _DENY_TOOLS,
    ClaudeHeadlessEngine,
    ContainmentExecutionContext,
    EngineContainmentError,
    EngineEnvError,
    _pid_image,
)
from runtime.engine.windows_job import (                    # noqa: E402
    EmptyMembershipResult,
    EmptyMembershipStatus,
    MembershipObservation,
    TerminationRequestError,
    WindowsJobError,
)

_SLEEP = "import time; time.sleep(300)"


class _DummyEngine(ClaudeHeadlessEngine):
    """Runs a Python dummy child instead of ``claude``. Bypasses __init__'s
    PATH resolution — the dummy argv comes from the overridden ``_command``, so
    ``self._claude_exe`` is never used to build the command."""

    def __init__(self, cfg, artifacts_dir, dummy_src):
        self.cfg = cfg
        self.artifacts_dir = Path(artifacts_dir)
        self._claude_exe = sys.executable  # unused; _command overrides argv
        self._dummy_src = dummy_src

    def _command(self, prompt_file):
        return [sys.executable, "-c", self._dummy_src]

    def run(self, execution_id, prompt_file, workspace, *, containment=None):
        if containment is None and engine_module._IS_WINDOWS:
            self.containment_events = []
            containment = ContainmentExecutionContext(
                issue_id="042", workspace_key="unit-workspace",
                containment_generation="g1",
                controller={"pid": 1, "creation_time": "unit-controller"},
                lease={"scope": "Global", "version": "v1"},
                append_event=self.containment_events.append,
            )
        return super().run(execution_id, prompt_file, workspace, containment=containment)


def _cfg(auth_mode: str = "subscription", timeout_seconds: int = 30) -> EngineCfg:
    return EngineCfg(
        provider="claude-headless", auth_mode=auth_mode,
        timeout_seconds=timeout_seconds,
    )


def _prompt(tmp_path: Path, text: str = "do the thing") -> Path:
    p = tmp_path / "prompt.txt"
    p.write_text(text, encoding="utf-8")
    return p


# ── ADR-18 env hygiene ───────────────────────────────────────────────
def test_subscription_strips_api_key(tmp_path, monkeypatch):
    """Subscription mode must strip every billing/routing var from the child
    env even when the parent shell exports them (mutation M4 kills this)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-should-be-stripped")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://evil")
    dummy = (
        "import os,sys;"
        "sys.stdout.write('KEY='+repr(os.environ.get('ANTHROPIC_API_KEY'))+'\\n');"
        "sys.stdout.write('TOK='+repr(os.environ.get('ANTHROPIC_AUTH_TOKEN'))+'\\n');"
        "sys.stdout.write('URL='+repr(os.environ.get('ANTHROPIC_BASE_URL'))+'\\n')"
    )
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    body = res.transcript_path.read_text(encoding="utf-8")
    assert "KEY=None" in body, body
    assert "TOK=None" in body, body
    assert "URL=None" in body, body
    assert res.timed_out is False


def test_api_key_mode_fails_fast(tmp_path, monkeypatch):
    """api_key mode with no key must raise BEFORE any spawn side effect."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    eng = _DummyEngine(_cfg("api_key"), tmp_path / "art", "import sys")
    with pytest.raises(EngineEnvError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert not (tmp_path / "art" / "042-e1").exists()  # no artifacts written


def test_apikeysource_leak_raises(tmp_path):
    """In-band ADR-18 witness: a non-'none' apiKeySource in subscription mode
    (a credential leaked past the strip) is a hard EngineEnvError."""
    init_line = json.dumps({
        "type": "system", "subtype": "init", "apiKeySource": "ANTHROPIC_API_KEY",
    })
    dummy = "import sys;" + f"sys.stdout.write({init_line!r}+'\\n')"
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    with pytest.raises(EngineEnvError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path)


# ── timeout / kill / reap ────────────────────────────────────────────
def test_timeout_kills_process_tree(tmp_path):
    """A wall-clock timeout tree-kills: the grandchild (a descendant of the
    engine child) must be dead, and the pidfile cleaned up."""
    dummy = (
        "import subprocess,sys,time;"
        "g=subprocess.Popen([sys.executable,'-c','import time;time.sleep(300)']);"
        "sys.stdout.write('GRANDCHILD='+str(g.pid)+'\\n');sys.stdout.flush();"
        "time.sleep(300)"
    )
    eng = _DummyEngine(_cfg("subscription", timeout_seconds=2), tmp_path / "art", dummy)
    t0 = time.monotonic()
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    elapsed = time.monotonic() - t0
    assert res.timed_out is True
    assert elapsed < 60, f"timeout took {elapsed:.1f}s"

    gpid = None
    for line in res.transcript_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GRANDCHILD="):
            gpid = int(line.split("=", 1)[1])
    assert gpid is not None
    for _ in range(100):                       # allow the OS a moment to reap
        if _pid_image(gpid) is None:
            break
        time.sleep(0.1)
    assert _pid_image(gpid) is None, f"grandchild {gpid} survived tree-kill"
    assert not (tmp_path / "art" / "042-e1" / "pid").exists()
    if engine_module._IS_WINDOWS:
        assert [event.type.value for event in eng.containment_events] == [
            "ExecutionContainmentPrepared",
            "ExecutionContainmentEstablished",
            "ExecutionContainmentReleased",
        ]


def test_timeout_arms_when_child_never_reads_stdin(tmp_path):
    """The FIX-1 guarantee: a large prompt to a child that never drains stdin
    must NOT block the parent before the timeout arms (communicate covers the
    stdin write + wait + timeout as one operation)."""
    big = _prompt(tmp_path, "x" * 500_000)     # past the OS pipe buffer
    eng = _DummyEngine(_cfg("subscription", timeout_seconds=2), tmp_path / "art", _SLEEP)
    t0 = time.monotonic()
    res = eng.run("042-e1", big, tmp_path)
    elapsed = time.monotonic() - t0
    assert res.timed_out is True
    assert elapsed < 60, f"stdin write blocked the timeout: {elapsed:.1f}s"
    if engine_module._IS_WINDOWS:
        assert eng.containment_events[-1].type.value == "ExecutionContainmentReleased"


def test_transcript_survives_kill(tmp_path):
    """A mid-run kill leaves a valid PARTIAL JSONL (line-oriented output), not
    one truncated blob — each flushed line still parses."""
    dummy = (
        "import sys,time;"
        "sys.stdout.write('{\"type\":\"system\",\"subtype\":\"init\"}\\n');"
        "sys.stdout.write('{\"type\":\"assistant\"}\\n');"
        "sys.stdout.flush();time.sleep(300)"
    )
    eng = _DummyEngine(_cfg("subscription", timeout_seconds=2), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.timed_out is True
    lines = [
        ln for ln in res.transcript_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) >= 2
    for ln in lines:
        json.loads(ln)  # valid JSON despite the mid-run kill


def _engine_batch_fixture(tmp_path, *, hold_seconds: float) -> Path:
    launcher_dir = tmp_path / "engine batch launcher"
    launcher_dir.mkdir()
    (launcher_dir / "child.py").write_text(
        "import json, os, sys, time\n"
        "print(json.dumps({'type':'system','subtype':'init','apiKeySource':'none'}), flush=True)\n"
        "time.sleep(float(os.environ['T7_ENGINE_BATCH_HOLD']))\n",
        encoding="utf-8",
    )
    batch = launcher_dir / "engine synthetic.CMD"
    batch.write_text(
        "@echo off\r\n"
        "\"%T7_ENGINE_BATCH_PYTHON%\" \"%~dp0child.py\"\r\n",
        encoding="utf-8",
    )
    return batch


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_engine_batch_launcher_preserves_containment_event_order(tmp_path):
    batch = _engine_batch_fixture(tmp_path, hold_seconds=.05)
    cfg = EngineCfg(
        provider="claude-headless", auth_mode="subscription", timeout_seconds=2,
        child_env={"T7_ENGINE_BATCH_PYTHON": sys.executable,
                   "T7_ENGINE_BATCH_HOLD": ".05"},
    )
    eng = _DummyEngine(cfg, tmp_path / "art", "unused")
    eng._command = lambda _prompt: [str(batch)]
    result = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert result.timed_out is False
    assert [event.type.value for event in eng.containment_events] == [
        "ExecutionContainmentPrepared",
        "ExecutionContainmentEstablished",
        "ExecutionContainmentReleased",
    ]


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_engine_batch_launcher_timeout_releases_only_after_job_empty_proof(tmp_path):
    batch = _engine_batch_fixture(tmp_path, hold_seconds=10)
    cfg = EngineCfg(
        provider="claude-headless", auth_mode="subscription", timeout_seconds=1,
        child_env={"T7_ENGINE_BATCH_PYTHON": sys.executable,
                   "T7_ENGINE_BATCH_HOLD": "10"},
    )
    eng = _DummyEngine(cfg, tmp_path / "art", "unused")
    eng._command = lambda _prompt: [str(batch)]
    result = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert result.timed_out is True
    assert [event.type.value for event in eng.containment_events] == [
        "ExecutionContainmentPrepared",
        "ExecutionContainmentEstablished",
        "ExecutionContainmentReleased",
    ]


def test_kill_tree_reports_windows_nonzero_result(monkeypatch):
    """The T5 orphan-reaper diagnostic retains taskkill result detail."""
    completed = subprocess.CompletedProcess(
        ["taskkill"], 5, stdout="not found", stderr="access denied",
    )
    monkeypatch.setattr(engine_module, "_IS_WINDOWS", True)
    monkeypatch.setattr(
        engine_module.subprocess, "run", lambda *args, **kwargs: completed,
    )
    detail = engine_module._kill_tree(123)
    assert detail == (
        "taskkill rc=5 for pid 123; stdout='not found'; stderr='access denied'"
    )


# -- Windows containment ordering / fail-closed contract -------------------
class _FakePrepared:
    def __init__(self, *, root_status="SIGNALED", empty=None, resume_error=None,
                 terminate_error=None):
        self.pid = 321
        self.initial_membership = MembershipObservation((321,))
        self.root_status = root_status
        self.empty = empty or EmptyMembershipResult(
            EmptyMembershipStatus.EMPTY_CONFIRMED, MembershipObservation(()))
        self.resume_error = resume_error
        self.terminate_error = terminate_error
        self.resumed = False
        self.closed = False

    def diagnostic_identity(self):
        return {"pid": self.pid, "creation_time": "fake-root"}

    def resume(self):
        if self.resume_error:
            raise self.resume_error
        self.resumed = True

    def root_wait_status(self):
        return self.root_status

    def exit_status(self):
        return 0

    def terminate_job(self):
        if self.terminate_error:
            raise self.terminate_error

    def wait_until_empty(self, _deadline):
        return self.empty

    def close(self):
        self.closed = True


class _FakeJobController:
    prepared = None
    create_error = None
    root_error = None
    instances = []

    def __init__(self):
        self.closed = False
        self.create_calls = 0
        type(self).instances.append(self)

    @classmethod
    def reset(cls, prepared=None, create_error=None, root_error=None):
        cls.prepared = prepared or _FakePrepared()
        cls.create_error = create_error
        cls.root_error = root_error
        cls.instances = []

    @classmethod
    def create(cls):
        if cls.create_error:
            raise cls.create_error
        return cls()

    def create_suspended_root(self, *_args, **_kwargs):
        self.create_calls += 1
        if type(self).root_error:
            raise type(self).root_error
        return type(self).prepared

    def close(self):
        self.closed = True


def _contained_context(events, *, fail_on=None):
    def append(event):
        if event.type is fail_on:
            raise OSError(f"append failed for {event.type.value}")
        events.append(event)
    return ContainmentExecutionContext(
        issue_id="042", workspace_key="unit-workspace", containment_generation="g1",
        controller={"pid": 1, "creation_time": "unit-controller"},
        lease={"scope": "Global", "version": "v1"}, append_event=append,
    )


def _fake_contained_engine(tmp_path, monkeypatch, prepared=None, *,
                           create_error=None, root_error=None, timeout=1):
    _FakeJobController.reset(prepared, create_error, root_error)
    monkeypatch.setattr(engine_module, "WindowsJobController", _FakeJobController)
    return _DummyEngine(_cfg("subscription", timeout), tmp_path / "art", "import sys")


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_prepared_append_failure_creates_no_root(tmp_path, monkeypatch):
    eng = _fake_contained_engine(tmp_path, monkeypatch)
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path,
                containment=_contained_context(events, fail_on=engine_module.EventType.EXECUTION_CONTAINMENT_PREPARED))
    assert events == []
    assert _FakeJobController.instances == []


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_root_creation_failure_leaves_only_prepared_blocker(tmp_path, monkeypatch):
    eng = _fake_contained_engine(tmp_path, monkeypatch,
                                 root_error=WindowsJobError("synthetic root failure"))
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path,
                containment=_contained_context(events))
    assert [event.type for event in events] == [engine_module.EventType.EXECUTION_CONTAINMENT_PREPARED]
    assert _FakeJobController.instances[0].create_calls == 1


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_established_append_failure_never_resumes_root(tmp_path, monkeypatch):
    prepared = _FakePrepared()
    eng = _fake_contained_engine(tmp_path, monkeypatch, prepared)
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path,
                containment=_contained_context(events, fail_on=engine_module.EventType.EXECUTION_CONTAINMENT_ESTABLISHED))
    assert prepared.resumed is False
    assert [event.type for event in events] == [engine_module.EventType.EXECUTION_CONTAINMENT_PREPARED]


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_resume_failure_latches_unconfirmed_without_release(tmp_path, monkeypatch):
    prepared = _FakePrepared(resume_error=WindowsJobError("synthetic resume failure"))
    eng = _fake_contained_engine(tmp_path, monkeypatch, prepared)
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path, containment=_contained_context(events))
    assert [event.type for event in events] == [
        engine_module.EventType.EXECUTION_CONTAINMENT_PREPARED,
        engine_module.EventType.EXECUTION_CONTAINMENT_ESTABLISHED,
        engine_module.EventType.EXECUTION_TERMINATION_UNCONFIRMED,
    ]


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
@pytest.mark.parametrize("result", [
    EmptyMembershipResult(EmptyMembershipStatus.STILL_NONEMPTY, MembershipObservation((321,))),
    EmptyMembershipResult(EmptyMembershipStatus.QUERY_UNKNOWN, None,
                          WindowsJobError("synthetic query failure")),
])
def test_normal_completion_without_positive_empty_latches_unconfirmed(tmp_path, monkeypatch, result):
    eng = _fake_contained_engine(tmp_path, monkeypatch, _FakePrepared(empty=result))
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path, containment=_contained_context(events))
    assert events[-1].type is engine_module.EventType.EXECUTION_TERMINATION_UNCONFIRMED
    assert all(event.type is not engine_module.EventType.EXECUTION_CONTAINMENT_RELEASED for event in events)


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_timeout_termination_failure_latches_unconfirmed(tmp_path, monkeypatch):
    prepared = _FakePrepared(root_status="RUNNING",
                              terminate_error=TerminationRequestError("synthetic terminate failure"))
    eng = _fake_contained_engine(tmp_path, monkeypatch, prepared, timeout=1)
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path, containment=_contained_context(events))
    assert events[-1].type is engine_module.EventType.EXECUTION_TERMINATION_UNCONFIRMED


@pytest.mark.skipif(not engine_module._IS_WINDOWS, reason="Windows containment path")
def test_released_append_failure_never_returns_ordinary_result(tmp_path, monkeypatch):
    eng = _fake_contained_engine(tmp_path, monkeypatch)
    events = []
    with pytest.raises(EngineContainmentError):
        eng.run("042-e1", _prompt(tmp_path), tmp_path,
                containment=_contained_context(events, fail_on=engine_module.EventType.EXECUTION_CONTAINMENT_RELEASED))
    assert events[-1].type is engine_module.EventType.EXECUTION_TERMINATION_UNCONFIRMED


# ── advisory result parsing ──────────────────────────────────────────
def test_result_line_parsed_advisory(tmp_path):
    """num_turns (max_turns enforcement input) and usage/dollars are parsed
    from the result line; apiKeySource='none' does not raise."""
    result_line = json.dumps({
        "type": "result", "subtype": "success", "num_turns": 7,
        "total_cost_usd": 0.42,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    })
    init_line = json.dumps({
        "type": "system", "subtype": "init", "apiKeySource": "none",
    })
    dummy = (
        "import sys;"
        f"sys.stdout.write({init_line!r}+'\\n');"
        f"sys.stdout.write({result_line!r}+'\\n')"
    )
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.num_turns == 7
    assert res.usage["dollars"] == 0.42
    assert res.usage["input_tokens"] == 100
    assert res.usage["output_tokens"] == 20
    assert res.timed_out is False


# ── parsing edge cases (advisory extraction must never raise) ───────
def test_empty_transcript_yields_empty_advisory(tmp_path):
    """A child that writes nothing (e.g. immediate crash) must not make
    EngineResult construction raise — advisory fields fall back to empty/None."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys; sys.exit(1)")
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.usage == {}
    assert res.num_turns is None
    assert res.exit_status == 1
    assert res.timed_out is False


def test_malformed_lines_skipped_valid_result_still_parsed(tmp_path):
    """A garbled line interleaved with valid ones (e.g. a partial write torn by
    a kill) must be skipped, not abort parsing of the rest of the transcript."""
    result_line = json.dumps({
        "type": "result", "num_turns": 3, "total_cost_usd": 0.01,
        "usage": {"input_tokens": 5, "output_tokens": 1},
    })
    dummy = (
        "import sys;"
        "sys.stdout.write('{not json\\n');"
        f"sys.stdout.write({result_line!r}+'\\n')"
    )
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.num_turns == 3
    assert res.usage["dollars"] == 0.01


def test_missing_usage_fields_yield_none(tmp_path):
    """A result line with a partial/absent usage object must not raise — every
    field degrades to None rather than a KeyError."""
    result_line = json.dumps({"type": "result", "num_turns": 1})
    dummy = f"import sys; sys.stdout.write({result_line!r}+'\\n')"
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.usage["input_tokens"] is None
    assert res.usage["output_tokens"] is None
    assert res.usage["dollars"] is None
    assert res.num_turns == 1


def test_stderr_tail_captures_recent_output(tmp_path):
    """stderr is archived to a file and the tail is surfaced on EngineResult
    for diagnostics — never load-bearing, just visible."""
    dummy = "import sys; sys.stderr.write('boom: something went wrong\\n')"
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", dummy)
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert "boom: something went wrong" in res.stderr_tail


def test_exit_status_nonzero_preserved(tmp_path):
    """A clean-but-failing child (nonzero exit, no timeout) must surface its
    real exit_status — never gate on it, but never lose it either."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys; sys.exit(7)")
    res = eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert res.exit_status == 7
    assert res.timed_out is False


# ── pidfile lifecycle ────────────────────────────────────────────────
def test_pidfile_removed_on_clean_return(tmp_path):
    """A normal (non-timeout) run must leave no pidfile behind."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    eng.run("042-e1", _prompt(tmp_path), tmp_path)
    assert not eng._pidfile("042-e1").exists()


def test_is_execution_alive_false_for_unknown_execution(tmp_path):
    """No pidfile at all (never spawned, or already cleaned up) => False, and
    this must not raise even though the execution directory doesn't exist."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    assert eng.is_execution_alive("never-spawned") is False


def _identity(pid, image="worker.exe", created="2026-08-14T10:00:00Z"):
    return {"pid": pid, "image": image, "creation_time": created}


def _resolved_record(shim_pid=10, worker_pid=20):
    shim = _identity(shim_pid, "claude.cmd")
    worker = _identity(worker_pid)
    return {
        "version": 2,
        "state": "resolved",
        "shim": shim,
        "worker": worker,
        "ancestry": {"chain": [shim, worker]},
    }


def _write_record(eng, record):
    pidfile = eng._pidfile("042-e1")
    engine_module._write_identity_record(pidfile, record)
    return pidfile


def test_is_execution_alive_when_shim_is_dead_and_worker_is_alive(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    _write_record(eng, _resolved_record())
    monkeypatch.setattr(engine_module, "_identity_liveness", lambda identity: "alive")
    assert eng.is_execution_alive("042-e1") is True


def test_is_execution_alive_false_after_worker_death(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    monkeypatch.setattr(engine_module, "_identity_liveness", lambda identity: "dead")
    assert eng.is_execution_alive("042-e1") is False
    assert not pidfile.exists()


def test_is_execution_alive_false_after_stale_pid_reused(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    monkeypatch.setattr(engine_module, "_pid_image", lambda pid: "worker.exe")
    monkeypatch.setattr(
        engine_module, "_pid_creation_time", lambda pid: "2026-08-14T10:01:00Z",
    )
    assert eng.is_execution_alive("042-e1") is False
    assert not pidfile.exists()


def test_is_execution_alive_rejects_worker_image_mismatch(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    monkeypatch.setattr(engine_module, "_pid_image", lambda pid: "other.exe")
    assert eng.is_execution_alive("042-e1") is False
    assert not pidfile.exists()


def test_probe_failure_is_unknown_and_never_reaped(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    killed = []
    monkeypatch.setattr(engine_module, "_identity_liveness", lambda identity: "unknown")
    monkeypatch.setattr(engine_module, "_kill_tree", killed.append)
    assert eng.is_execution_alive("042-e1") is False
    assert eng.reap_orphans() == []
    assert pidfile.exists()
    assert killed == []


def test_unresolved_and_malformed_records_are_unknown_and_preserved(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    unresolved = _write_record(eng, {"version": 2, "state": "resolving", "shim": _identity(10)})
    killed = []
    monkeypatch.setattr(engine_module, "_kill_tree", killed.append)
    assert eng.is_execution_alive("042-e1") is False
    assert eng.reap_orphans() == []
    assert unresolved.exists()

    malformed = eng._pidfile("bad")
    engine_module._write_identity_record(malformed, {"version": 2, "state": "resolved"})
    assert eng.is_execution_alive("bad") is False
    assert malformed.exists()

    assert killed == []


def test_live_legacy_record_is_unknown_but_stale_legacy_record_is_removed(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    live_legacy = eng._pidfile("legacy-live")
    engine_module._write_identity_record(live_legacy, {"pid": 10, "image": "claude.cmd"})
    monkeypatch.setattr(engine_module, "_pid_image", lambda pid: "claude.cmd")
    assert eng.is_execution_alive("legacy-live") is False
    assert live_legacy.exists()

    stale_legacy = eng._pidfile("legacy-stale")
    engine_module._write_identity_record(stale_legacy, {"pid": 11, "image": "claude.cmd"})
    monkeypatch.setattr(engine_module, "_pid_image", lambda pid: None)
    monkeypatch.setattr(engine_module, "_pid_exists", lambda pid: False)
    assert eng.is_execution_alive("legacy-stale") is False
    assert not stale_legacy.exists()


def test_reap_orphans_kills_only_owned_resolved_worker(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    killed = []
    monkeypatch.setattr(engine_module, "_identity_liveness", lambda identity: "alive")
    monkeypatch.setattr(engine_module, "_kill_tree", killed.append)
    repairs = eng.reap_orphans()
    assert killed == [20]
    assert any("042-e1" in repair for repair in repairs)
    assert not pidfile.exists()


def test_reap_orphans_never_kills_pid_reuse_or_image_mismatch(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = _write_record(eng, _resolved_record())
    killed = []
    monkeypatch.setattr(engine_module, "_identity_liveness", lambda identity: "dead")
    monkeypatch.setattr(engine_module, "_kill_tree", killed.append)
    assert eng.reap_orphans() == []
    assert killed == []
    assert not pidfile.exists()


def test_atomic_identity_record_replacement_keeps_old_record_and_cleans_temp_on_failure(tmp_path, monkeypatch):
    pidfile = tmp_path / "art" / "042-e1" / "pid"
    old_record = {"version": 2, "state": "resolving", "shim": _identity(10)}
    engine_module._write_identity_record(pidfile, old_record)
    monkeypatch.setattr(engine_module.os, "replace", lambda source, target: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        engine_module._write_identity_record(pidfile, _resolved_record())
    assert json.loads(pidfile.read_text(encoding="utf-8")) == old_record
    assert list(pidfile.parent.glob(".pid.*.tmp")) == []


def test_worker_identity_is_atomically_upgraded_after_resolution(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = eng._pidfile("042-e1")
    identities = {10: _identity(10, "claude.cmd"), 20: _identity(20)}
    monkeypatch.setattr(engine_module, "_pid_identity", lambda pid, **kwargs: identities.get(pid))
    monkeypatch.setattr(engine_module, "_resolve_leaf_worker", lambda pid, **kwargs: ([20], 20, [], None))
    monkeypatch.setattr(engine_module, "_ancestry_chain", lambda root, worker, **kwargs: [10, 20])
    eng._write_pidfile(pidfile, 10)
    assert json.loads(pidfile.read_text(encoding="utf-8"))["state"] == "resolving"
    eng._resolve_and_persist_worker(pidfile, 10)
    resolved = json.loads(pidfile.read_text(encoding="utf-8"))
    assert {key: value for key, value in resolved.items() if key != "started_at"} == _resolved_record()
    assert isinstance(resolved["started_at"], str)


def test_worker_resolution_failure_leaves_resolving_record(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    pidfile = eng._pidfile("042-e1")
    monkeypatch.setattr(engine_module, "_pid_identity", lambda pid: _identity(pid, "claude.cmd"))
    monkeypatch.setattr(engine_module, "_resolve_leaf_worker", lambda pid, **kwargs: ([], None, [], "root exited"))
    eng._write_pidfile(pidfile, 10)
    eng._resolve_and_persist_worker(pidfile, 10)
    assert json.loads(pidfile.read_text(encoding="utf-8"))["state"] == "resolving"


def test_worker_resolution_uses_only_the_remaining_execution_budget(tmp_path, monkeypatch):
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    captured = {}

    def resolve(pid, **kwargs):
        captured.update(kwargs)
        return [], None, [], "deadline exhausted"

    monkeypatch.setattr(engine_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(engine_module, "_resolve_leaf_worker", resolve)
    eng._resolve_and_persist_worker(eng._pidfile("042-e1"), 10, deadline=102.0)
    assert captured["max_seconds"] == 2.0


def test_worker_resolution_stops_when_popen_has_reaped_the_shim(monkeypatch):
    monkeypatch.setattr(engine_module, "_walk_descendants", lambda pid, **kwargs: ([], {}))
    descendants, worker, poll_log, reason = engine_module._resolve_leaf_worker(
        10, max_polls=20, max_seconds=10, poll_interval=1, root_alive=lambda: False,
    )
    assert descendants == []
    assert worker is None
    assert len(poll_log) == 1
    assert reason == "root exited before worker resolution"


# ── ADR-21 fence (the only working engine restriction) ───────────────
def test_command_carries_the_adr21_fence(tmp_path):
    """PROBE-VERIFIED: --allowedTools does NOT restrict in -p mode; only
    --disallowedTools fences. The real _command() must therefore carry the
    ADR-21 deny set. We call the CLASS method directly (the _DummyEngine
    override is bypassed) to exercise the production argv."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    eng._claude_exe = "claude"  # value irrelevant — not exercised by the fence
    eng.cfg = EngineCfg(
        provider="claude-headless", auth_mode="subscription", model="claude-x",
    )
    argv = ClaudeHeadlessEngine._command(eng, tmp_path / "p.txt")

    assert "--disallowedTools" in argv
    # the load-bearing denies ride in the fence (egress, git, destruction,
    # recursive-spawn, sub-agent escape)
    for tok in ("WebFetch", "WebSearch", "Task", "Bash(curl:*)",
                "Bash(git:*)", "Bash(rm:*)", "Bash(claude:*)"):
        assert tok in argv, f"{tok} missing from fence"
    # the fence is exactly _DENY_TOOLS, contiguous after the flag
    di = argv.index("--disallowedTools")
    assert argv[di + 1: di + 1 + len(_DENY_TOOLS)] == list(_DENY_TOOLS)
    # the variadic fence must precede --model so it does not swallow the value
    assert "--model" in argv and di < argv.index("--model")
    assert argv[argv.index("--model") + 1] == "claude-x"


def test_command_fence_present_without_model(tmp_path):
    """model='default' emits no --model; the fence is still present and is the
    argv tail (nothing after it to be swallowed)."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    eng._claude_exe = "claude"
    eng.cfg = EngineCfg(provider="claude-headless", auth_mode="subscription")
    argv = ClaudeHeadlessEngine._command(eng, tmp_path / "p.txt")
    assert "--model" not in argv
    di = argv.index("--disallowedTools")
    assert argv[di + 1:] == list(_DENY_TOOLS)


def test_command_permission_mode_is_bypass_permissions(tmp_path):
    """Gap 1 (doc 08 §5b Amendment 2, Session 35): under acceptEdits/default
    a headless -p child cannot self-verify -- every Bash tool_use, even a
    single non-chained pytest command, is auto-denied
    (non_execution_kind="user-rejected"), VERIFIED live this session.
    bypassPermissions is the only mode that lets a non-denied Bash command
    run, while the denylist (asserted unchanged above) keeps denying
    curl/rm/git identically (non_execution_kind="permission-rule").
    This pins the argv so a future edit cannot silently regress to a mode
    that reintroduces the self-verification deadlock."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    eng._claude_exe = "claude"
    eng.cfg = EngineCfg(provider="claude-headless", auth_mode="subscription")
    argv = ClaudeHeadlessEngine._command(eng, tmp_path / "p.txt")
    pi = argv.index("--permission-mode")
    assert argv[pi + 1] == "bypassPermissions"


# ── recovery integration (unit-level M3 proof) ───────────────────────
def test_reap_orphans_retains_production_resolving_record(tmp_path, monkeypatch):
    """A crash before worker resolution is never reaped from a shim PID."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    monkeypatch.setattr(engine_module, "_pid_identity", lambda pid: _identity(pid, "claude.cmd"))
    eng._write_pidfile(eng._pidfile("042-e1"), 10)
    assert eng.is_execution_alive("042-e1") is False
    assert eng.reap_orphans() == []
    assert eng._pidfile("042-e1").exists()
