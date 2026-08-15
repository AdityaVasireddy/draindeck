"""ADR-23 rule 3 unit tests — validation child-env hygiene (doc 08 §5d).

Covers ``Validator._child_env()``: the config overlay
(``project.validation.env``) is applied to a fresh snapshot of the parent
environment in a SINGLE pass over its items, mutating the base — a ``None``
value UNSETS its key (popped FROM THE BASE, so an *inherited* variable is
genuinely absent, not merely empty), any other value sets/overrides it.

Discipline (mirrors the ADR-22 ``_hygienic_env`` tests in
``test_engine_adr22.py``): assert on the RETURNED dict's shape, never on
``subprocess.run``'s call args; assert membership/absence/value on the SPECIFIC
keys under test, never full-dict equality against the whole inherited
environment (which would couple the test to the machine). The one exception is
the deliberate backward-compat test, whose entire point is that an empty overlay
returns something EQUAL to ``dict(os.environ)``.

The load-bearing test is ``test_inherited_key_nulled_is_absent_from_child``: it
is written so that reverting the implementation to pop-from-overlay turns it RED
(membership-absence is the only assertion that discriminates — ``.get(...) is
None`` would pass on the broken two-pass version too). That discrimination is
the test's whole reason to exist.

New file (Session 15): existing tests are deliberately untouched.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.validation.runner import Validator  # noqa: E402


def _validator(env, tmp_path) -> Validator:
    return Validator(
        ["exit 0"], timeout_seconds=30, artifacts_dir=tmp_path / "art", env=env
    )


def test_inherited_key_nulled_is_absent_from_child(tmp_path, monkeypatch):
    """THE discriminating test: a variable present in the parent env and set to
    None in the overlay must be ABSENT (membership) from the built dict — not
    empty, not None-valued. Reverting to pop-from-overlay leaves the inherited
    copy in place and turns this red; that is exactly what it guards."""
    monkeypatch.setenv("VIRTUAL_ENV", "C:/Projects/issue-runtime/.venv")
    built = _validator({"VIRTUAL_ENV": None}, tmp_path)._child_env()
    assert "VIRTUAL_ENV" in os.environ            # precondition: it WAS inherited
    assert "VIRTUAL_ENV" not in built             # the only assertion that discriminates


def test_new_key_set_is_present_with_value(tmp_path, monkeypatch):
    """A key absent from the parent env, non-null in the overlay, is present in
    the built dict with that value."""
    monkeypatch.delenv("ADR23_NEW_KEY", raising=False)
    built = _validator({"ADR23_NEW_KEY": "pinned"}, tmp_path)._child_env()
    assert built["ADR23_NEW_KEY"] == "pinned"


def test_unrelated_inherited_key_untouched(tmp_path, monkeypatch):
    """A parent-env key not mentioned in the overlay survives unchanged (the
    unenumerated tail ADR-23 explicitly does NOT close)."""
    monkeypatch.setenv("ADR23_UNRELATED", "untouched")
    built = _validator({"SOMETHING_ELSE": "x"}, tmp_path)._child_env()
    assert built["ADR23_UNRELATED"] == "untouched"


def test_overlay_overrides_inherited_key(tmp_path, monkeypatch):
    """A key present in the parent env AND non-null in the overlay is overridden
    to the overlay value (e.g. pinning PATH to an absolute toolchain)."""
    monkeypatch.setenv("PATH", "C:/inherited/path")
    built = _validator({"PATH": "C:/Python314;C:/Windows/system32"}, tmp_path)._child_env()
    assert built["PATH"] == "C:/Python314;C:/Windows/system32"


def test_null_on_absent_key_does_not_raise(tmp_path, monkeypatch):
    """Unsetting a key that isn't in the parent env is a no-op, not an error —
    locks in the ``None`` default on ``built.pop(key, None)`` (load-bearing but
    otherwise untested)."""
    monkeypatch.delenv("ADR23_NEVER_SET", raising=False)
    built = _validator({"ADR23_NEVER_SET": None}, tmp_path)._child_env()  # must not raise
    assert "ADR23_NEVER_SET" not in built


def test_empty_overlay_equals_parent_env(tmp_path, monkeypatch):
    """Backward compat, first-class: an empty overlay returns something EQUAL to
    dict(os.environ) — existing callers (test_seams, test_loop_real_git,
    config.yaml today) are byte-unmoved, so any suite movement is attributable
    to something other than this mechanism. This is the one place full-dict
    equality is the correct assertion, because equality-to-inherited IS the
    claim under test."""
    monkeypatch.setenv("ADR23_SENTINEL", "present")
    built = _validator({}, tmp_path)._child_env()
    assert built == dict(os.environ)
    assert built["ADR23_SENTINEL"] == "present"  # the seeded key rode through


def test_validation_command_uses_explicit_powershell(tmp_path):
    completed = Mock(returncode=0)
    validator = _validator({}, tmp_path)
    with patch("runtime.validation.runner.subprocess.run", return_value=completed) as run:
        result = validator.validate(tmp_path, "deadbeef", "powershell")
    assert result.passed is True
    assert run.call_args.args[0] == [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "exit 0"
    ]
    assert run.call_args.kwargs["shell"] is False


def test_extra_command_with_powershell_variable_is_rejected(tmp_path):
    validator = _validator({}, tmp_path)
    with pytest.raises(ValueError, match="must use a .ps1"):
        validator.validate(tmp_path, "deadbeef", "variables", extra_commands=["Write-Output $env:PATH"])
