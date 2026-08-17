"""Portable configuration and truthful reviewer selection regressions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import ConfigError, KNOWN_REVIEWER_PROVIDERS, load_config  # noqa: E402
from runtime.main import _REVIEWER_FACTORIES, _make_reviewer  # noqa: E402
from runtime.reviewer.qwen_ollama import QwenOllamaReviewer  # noqa: E402


def _write_config(path: Path, provider: str = "qwen", command: str = "exit 0",
                   validation_extra: str = "") -> None:
    commands_line = "commands: []" if command is None else f"commands: ['{command}']"
    path.write_text(f"""project:
  name: example
  repository: C:\\target
  branch: main
  validation:
    {commands_line}
{validation_extra}engine:
  provider: claude-headless
  auth_mode: subscription
reviewer:
  provider: {provider}
  qwen:
    endpoint: http://localhost:11434
    model: qwen
budget:
  max_attempts_per_issue: 1
  max_executions_per_run: 1
  hard_stop_proxy_cost_per_run_usd: 1
experiment:
  sample_size: 1
  attempt1_success_min: 0.5
  cost_per_shipped_issue_max_usd: 1
billing:
  posture: test
  headless_split_status: test
  verified_on: test
  reverify_at: test
""", encoding="utf-8")


def test_unsupported_reviewer_provider_is_rejected_during_load(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, provider="claude")
    with pytest.raises(ConfigError, match="provider"):
        load_config(path)


def test_validation_command_with_powershell_variable_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, command="Write-Output $env:PATH")
    with pytest.raises(ConfigError, match="may not contain"):
        load_config(path)


def test_make_reviewer_builds_qwen_provider_from_config(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, provider="qwen")
    cfg = load_config(path)
    reviewer = _make_reviewer(cfg)
    assert isinstance(reviewer, QwenOllamaReviewer)
    assert reviewer.endpoint == "http://localhost:11434"
    assert reviewer.model == "qwen"


def test_reviewer_factory_registry_matches_known_providers():
    """Every provider config.py will accept must have a main.py factory,
    and vice versa — otherwise a config-valid provider would blow up at
    reviewer construction instead of at load time."""
    assert set(_REVIEWER_FACTORIES) == KNOWN_REVIEWER_PROVIDERS


# ── ADR-24: explicit no-validation contract (acknowledged_no_gate) ────────

def test_empty_commands_without_acknowledgement_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, command=None)
    with pytest.raises(ConfigError, match="acknowledged_no_gate"):
        load_config(path)


def test_empty_commands_with_acknowledgement_false_is_rejected(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, command=None,
                   validation_extra="    acknowledged_no_gate: false\n")
    with pytest.raises(ConfigError, match="acknowledged_no_gate"):
        load_config(path)


def test_empty_commands_with_acknowledgement_true_is_accepted(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, command=None,
                   validation_extra="    acknowledged_no_gate: true\n")
    cfg = load_config(path)
    assert cfg.project.validation.commands == []
    assert cfg.project.validation.acknowledged_no_gate is True


def test_nonempty_commands_with_acknowledgement_false_is_accepted(tmp_path):
    path = tmp_path / "config.yaml"
    _write_config(path, command="exit 0")
    cfg = load_config(path)
    assert cfg.project.validation.commands == ["exit 0"]
    assert cfg.project.validation.acknowledged_no_gate is False


def test_nonempty_commands_with_acknowledgement_true_is_accepted(tmp_path):
    """ADR-24: no mutual exclusion -- a stale acknowledgement alongside
    real commands is accepted, not rejected (doc 17 Sec2a)."""
    path = tmp_path / "config.yaml"
    _write_config(path, command="exit 0",
                   validation_extra="    acknowledged_no_gate: true\n")
    cfg = load_config(path)
    assert cfg.project.validation.commands == ["exit 0"]
    assert cfg.project.validation.acknowledged_no_gate is True


def test_old_style_config_without_the_field_still_loads_and_defaults_false(tmp_path):
    """Compatibility regression guard (doc 17 Sec2i): a config written
    before acknowledged_no_gate existed still loads, with every other
    parsed value unchanged."""
    path = tmp_path / "config.yaml"
    _write_config(path, command="exit 0")
    cfg = load_config(path)
    assert cfg.project.validation.acknowledged_no_gate is False
    assert cfg.project.validation.commands == ["exit 0"]
    assert cfg.project.validation.timeout_seconds == 600


def test_powershell_safe_commands_check_still_active_with_new_validator(tmp_path):
    """Regression guard: adding the ValidationCfg model_validator must not
    disturb the existing field_validator's `$`-rejection."""
    path = tmp_path / "config.yaml"
    _write_config(path, command="Write-Output $env:PATH")
    with pytest.raises(ConfigError, match="may not contain"):
        load_config(path)
