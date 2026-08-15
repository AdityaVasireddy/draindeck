"""Portable configuration and truthful reviewer selection regressions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import ConfigError, load_config  # noqa: E402


def _write_config(path: Path, provider: str = "qwen", command: str = "exit 0") -> None:
    path.write_text(f"""project:
  name: example
  repository: C:\\target
  branch: main
  validation:
    commands: ['{command}']
engine:
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
