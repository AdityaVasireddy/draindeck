"""ADR-24 (doc 08 Sec5f) unit tests -- Validator's explicit
acknowledged_no_gate parameter and the acknowledged-empty vacuous-pass
behavior it authorizes.

New file (mirrors the existing one-file-per-mechanism convention:
test_validation_env_adr23.py, test_validation_extra_commands_gap2.py).

Validator has no injected subprocess seam (unlike init/command.py's
confirm_and_run_install, which takes run_fn) -- _run_once calls
subprocess.run directly. The smallest correct test seam for proving zero
subprocess execution is a monkeypatch on the module-level
runtime.validation.runner.subprocess.run symbol, used below rather than
redesigning the runner for injectability.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.validation import runner as runner_module  # noqa: E402
from runtime.validation.runner import Validator  # noqa: E402


def test_empty_commands_unacknowledged_still_raises(tmp_path):
    """Regression guard: current behavior (before ADR-24) is unchanged
    when acknowledged_no_gate is omitted or False."""
    with pytest.raises(ValueError, match="at least one command"):
        Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art")
    with pytest.raises(ValueError, match="at least one command"):
        Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=False)


def test_empty_commands_acknowledged_constructs(tmp_path):
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    assert v.commands == []


def test_acknowledged_empty_validate_passes_with_empty_gate_results(tmp_path):
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    result = v.validate(tmp_path, "deadbeef", "x1")
    assert result.passed is True
    assert result.gate_results() == []
    assert result.validated_commit == "deadbeef"


def test_acknowledged_empty_validate_spawns_zero_subprocesses(tmp_path, monkeypatch):
    calls = []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("subprocess.run must not be called")

    monkeypatch.setattr(runner_module.subprocess, "run", spy)
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    result = v.validate(tmp_path, "deadbeef", "x2")
    assert calls == []
    assert result.passed is True


def test_acknowledged_empty_with_extra_commands_still_runs_and_can_pass(tmp_path):
    """Gap-2 remains active: acknowledged_no_gate covers only the
    config-sourced baseline (self.commands), never extra_commands."""
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    result = v.validate(tmp_path, "deadbeef", "x3", extra_commands=["exit 0"])
    assert result.passed is True
    assert [g["gate"] for g in result.gate_results()] == ["exit 0"]


def test_acknowledged_empty_with_failing_extra_command_fails_validation(tmp_path):
    """Gap-2 extras can still fail validation even when the configured
    baseline is acknowledged-empty -- the no-gate acknowledgement is not a
    bypass for child-authored new test files."""
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    result = v.validate(tmp_path, "deadbeef", "x4", extra_commands=["exit 1"])
    assert result.passed is False
    assert result.taxonomy_category == "validation-test"


def test_acknowledged_empty_with_extra_commands_actually_invokes_subprocess(
    tmp_path, monkeypatch,
):
    """Direct proof the extra command is really spawned (not silently
    skipped alongside the acknowledged-empty baseline)."""
    calls = []
    real_run = runner_module.subprocess.run

    def spy(*args, **kwargs):
        calls.append(args)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(runner_module.subprocess, "run", spy)
    v = Validator([], timeout_seconds=30, artifacts_dir=tmp_path / "art",
                   acknowledged_no_gate=True)
    v.validate(tmp_path, "deadbeef", "x5", extra_commands=["exit 0"])
    assert len(calls) == 1
