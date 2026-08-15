"""Gap 2 unit tests -- Validator.validate(extra_commands=...) (doc 08 Amendment,
Session 35, Design A).

Covers: an appended command is actually run and can fail the gate; a passing
appended command shows up in gate_results (the auditable trail loop.py's
event payload relies on); self.commands (the config-sourced baseline) is
never mutated by a call that passes extra_commands.

New file (Session 35): existing tests are deliberately untouched, mirroring
the test_validation_env_adr23.py convention of one new file per new
mechanism.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.validation.runner import Validator  # noqa: E402


def _validator(commands, tmp_path) -> Validator:
    return Validator(commands, timeout_seconds=30, artifacts_dir=tmp_path / "art")


def test_extra_commands_failure_fails_the_gate(tmp_path):
    """A new-file command appended via extra_commands that FAILS must flip
    ValidationResult.passed to False -- this is Gap 2's silent-ship fix:
    a child-authored new test file is no longer invisible to the gate."""
    v = _validator(["exit 0"], tmp_path)
    result = v.validate(tmp_path, "deadbeef", "x1", extra_commands=["exit 1"])
    assert result.passed is False
    assert result.taxonomy_category == "validation-test"


def test_extra_commands_passing_included_in_gate_results(tmp_path):
    """A passing appended command shows up in gate_results by its own command
    string -- the auditable trail: anyone reading VALIDATION_PASSED's payload
    sees exactly which auto-appended file ran, with no new event field."""
    v = _validator(["exit 0"], tmp_path)
    result = v.validate(tmp_path, "deadbeef", "x2",
                         extra_commands=["exit 0; # new-file-check"])
    assert result.passed is True
    names = [g["gate"] for g in result.gate_results()]
    assert names == ["exit 0", "exit 0; # new-file-check"]


def test_extra_commands_never_mutates_self_commands(tmp_path):
    """self.commands (the config-sourced, always-run baseline) must stay
    byte-identical across a call that passes extra_commands -- the
    auditability claim: the fixed list is never silently grown."""
    v = _validator(["exit 0"], tmp_path)
    v.validate(tmp_path, "deadbeef", "x3", extra_commands=["exit 0", "exit 0"])
    assert v.commands == ["exit 0"]


def test_no_extra_commands_is_backward_compatible(tmp_path):
    """Omitting extra_commands (existing callers, e.g. main.py's baseline
    Validator.validate() calls) behaves exactly as before this mechanism
    existed -- only self.commands runs."""
    v = _validator(["exit 0"], tmp_path)
    result = v.validate(tmp_path, "deadbeef", "x4")
    assert result.passed is True
    assert [g["gate"] for g in result.gate_results()] == ["exit 0"]
