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

from runtime.config import EngineCfg                       # noqa: E402
from runtime.engine.claude_headless import (               # noqa: E402
    _DENY_TOOLS,
    ClaudeHeadlessEngine,
    EngineEnvError,
    _pid_image,
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


def test_is_execution_alive_false_after_stale_pid_reused(tmp_path):
    """A pidfile recording a pid that has since exited (and whose image no
    longer matches, simulating reuse by an unrelated process) must read as
    dead, and the stale pidfile must be cleaned up by the check itself."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait(timeout=10)
    eng._xdir("042-e1").mkdir(parents=True)
    eng._write_pidfile(eng._pidfile("042-e1"), finished.pid)
    assert eng.is_execution_alive("042-e1") is False
    assert not eng._pidfile("042-e1").exists()


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


# ── recovery integration (unit-level M3 proof) ───────────────────────
def test_reap_orphans_kills_survivor(tmp_path):
    """A real survivor with a production-written pidfile is detected as alive,
    then reaped: killed, reported, and its pidfile removed (gut reap_orphans =>
    survivor alive + empty repairs => red)."""
    eng = _DummyEngine(_cfg("subscription"), tmp_path / "art", "import sys")
    sleeper = subprocess.Popen([sys.executable, "-c", _SLEEP])
    try:
        eng._xdir("042-e1").mkdir(parents=True)
        eng._write_pidfile(eng._pidfile("042-e1"), sleeper.pid)
        assert eng.is_execution_alive("042-e1") is True

        repairs = eng.reap_orphans()
        assert any("042-e1" in r for r in repairs), repairs
        sleeper.wait(timeout=10)
        assert sleeper.returncode is not None, "survivor not killed"
        assert eng.is_execution_alive("042-e1") is False
        assert not eng._pidfile("042-e1").exists()
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait(timeout=10)
