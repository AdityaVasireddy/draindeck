"""ADR-22 unit tests — engine-child ambient-hook isolation (doc 08 §5c).

Covers the two accepted mechanism layers:
* A-empty — ``--setting-sources ""`` in the production argv, with the empty
  value preserved as its own argv element (the whole point: an empty value
  loads NO settings scopes; losing the token would silently re-enable the
  operator's user-scope hooks and the knowledge/ contamination of doc 14 §2.3).
* B — ``engine.child_env`` (config-driven) merged into the child env by
  ``_hygienic_env()``, with ADR-18 strip-list supremacy: the strip is applied
  after the merge and always wins, so config can never smuggle a billing/
  routing credential into the child.

New file (Session 8): existing tests are deliberately untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import EngineCfg                       # noqa: E402
from runtime.engine.claude_headless import (               # noqa: E402
    ClaudeHeadlessEngine,
)


class _BareEngine(ClaudeHeadlessEngine):
    """Bypasses __init__'s PATH resolution (same pattern as test_engine.py's
    _DummyEngine) so the production ``_command``/``_hygienic_env`` bodies can
    be exercised without a ``claude`` binary on PATH."""

    def __init__(self, cfg, artifacts_dir):
        self.cfg = cfg
        self.artifacts_dir = Path(artifacts_dir)
        self._claude_exe = "claude"  # value irrelevant to what's under test


def _cfg(**overrides) -> EngineCfg:
    kwargs = dict(provider="claude-headless", auth_mode="subscription")
    kwargs.update(overrides)
    return EngineCfg(**kwargs)


def test_command_carries_setting_sources_empty(tmp_path):
    """ADR-22 A-empty: the production argv must contain the EXACT adjacent
    pair ["--setting-sources", ""] — the empty string preserved as a distinct
    element, and placed before the variadic --disallowedTools so the fence
    cannot swallow it."""
    eng = _BareEngine(_cfg(), tmp_path / "art")
    argv = eng._command(tmp_path / "p.txt")

    i = argv.index("--setting-sources")
    assert argv[i + 1] == "", argv
    assert argv[i + 1 : i + 2] == [""]  # a real element, not a dropped token
    assert i < argv.index("--disallowedTools")


def test_child_env_merged_into_child_environment(tmp_path, monkeypatch):
    """ADR-22 B layer: a config-driven engine.child_env entry must appear in
    the built child env (machine-specific names live in config, src/ generic)."""
    monkeypatch.delenv("HISTORIAN_SWEEP_ACTIVE", raising=False)
    eng = _BareEngine(
        _cfg(child_env={"HISTORIAN_SWEEP_ACTIVE": "1"}), tmp_path / "art"
    )
    env = eng._hygienic_env()
    assert env["HISTORIAN_SWEEP_ACTIVE"] == "1"


def test_child_env_cannot_override_strip_list(tmp_path, monkeypatch):
    """ADR-18 strip supremacy over ADR-22 B: a child_env key that collides
    with a strip-list entry must end up STRIPPED, not present — config can
    never re-introduce a billing/routing credential into the child."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    eng = _BareEngine(
        _cfg(child_env={
            "ANTHROPIC_API_KEY": "sk-injected-via-config",
            "HISTORIAN_SWEEP_ACTIVE": "1",
        }),
        tmp_path / "art",
    )
    env = eng._hygienic_env()  # must not raise: strip runs after the merge
    assert "ANTHROPIC_API_KEY" not in env
    assert env["HISTORIAN_SWEEP_ACTIVE"] == "1"  # non-colliding keys survive
