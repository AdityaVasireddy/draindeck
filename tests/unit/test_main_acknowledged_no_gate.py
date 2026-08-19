"""ADR-24 (doc 08 Sec5f) main.py wiring tests: check-config reporting for
an acknowledged-empty validation config, and both production Validator
construction sites (baseline check + orchestrator) receiving
acknowledged_no_gate explicitly rather than relying on the default.

New file, mirroring the one-file-per-mechanism convention used elsewhere
in tests/unit/.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config, load_config  # noqa: E402


def _write_config(path: Path, command: str | None = "exit 0",
                   acknowledged_no_gate: bool | None = None) -> None:
    commands_line = "commands: []" if command is None else f"commands: ['{command}']"
    ack_line = (f"    acknowledged_no_gate: {str(acknowledged_no_gate).lower()}\n"
                if acknowledged_no_gate is not None else "")
    path.write_text(f"""project:
  name: example
  repository: C:\\target
  branch: main
  validation:
    {commands_line}
{ack_line}engine:
  provider: claude-headless
  auth_mode: subscription
reviewer:
  provider: qwen
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


# ── cmd_check_config ────────────────────────────────────────────────────

def test_check_config_rejects_unacknowledged_empty(tmp_path, capsys):
    from runtime import main as main_mod

    path = tmp_path / "config.yaml"
    _write_config(path, command=None)
    exit_code = main_mod.cmd_check_config(SimpleNamespace(config=str(path)))
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "CONFIG INVALID" in captured.err
    assert "acknowledged_no_gate" in captured.err


def test_check_config_accepts_acknowledged_empty_with_note(tmp_path, capsys):
    from runtime import main as main_mod

    path = tmp_path / "config.yaml"
    _write_config(path, command=None, acknowledged_no_gate=True)
    with mock.patch.object(main_mod, "validate_environment", return_value=[]):
        exit_code = main_mod.cmd_check_config(SimpleNamespace(config=str(path)))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "OK: structure and environment valid" in captured.out
    assert "NOTE" in captured.out
    assert "acknowledged_no_gate" in captured.out


def test_check_config_normal_config_output_unchanged(tmp_path, capsys):
    from runtime import main as main_mod

    path = tmp_path / "config.yaml"
    _write_config(path, command="exit 0")
    with mock.patch.object(main_mod, "validate_environment", return_value=[]):
        exit_code = main_mod.cmd_check_config(SimpleNamespace(config=str(path)))
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "OK: structure and environment valid\n"


# ── cmd_run wiring (Validator construction sites + baseline reporting) ──

def _cfg(repo: Path, *, commands: list[str], acknowledged_no_gate: bool) -> Config:
    return Config.model_validate({
        "project": {"name": "T", "repository": str(repo), "branch": "agent-work",
                    "issues_file": "Issues.md",
                    "validation": {"commands": commands,
                                   "acknowledged_no_gate": acknowledged_no_gate}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription"},
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": "http://x", "model": "q"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })


def _drive(cfg: Config, *, skip_baseline: bool, replayed_events: int,
           validator_cls):
    """Run cmd_run with every collaborator mocked except Validator
    construction/invocation, which the caller supplies (real or spy)."""
    from runtime import main as main_mod

    args = SimpleNamespace(config="unused.yaml", skip_baseline=skip_baseline)

    adapter = mock.MagicMock(name="adapter")
    orch = mock.MagicMock(name="orch")
    orch.run.side_effect = lambda: "queue drained"
    orch.budget.metrics.return_value = SimpleNamespace(
        executions_this_run=0, proxy_dollars_this_run=0.0)
    lease = mock.MagicMock(name="lease", acquired=True, workspace_key="ws-test")
    lease.state.value = "ACQUIRED"
    lease.detail = "acquired"

    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod, "EventLog"), \
         mock.patch.object(main_mod, "Validator", validator_cls), \
         mock.patch.object(main_mod.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main_mod, "resolve_startup_containment",
                           return_value=mock.MagicMock()), \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine",
                            return_value=mock.MagicMock(reap_orphans=lambda: [])), \
         mock.patch.object(main_mod, "GitCliAdapter", return_value=adapter), \
         mock.patch.object(main_mod, "bind_reconciler", return_value={}), \
         mock.patch.object(main_mod, "recover",
                            return_value=(mock.MagicMock(is_workspace_blocked=mock.Mock(return_value=False)),
                                          SimpleNamespace(orphans_crashed=[],
                                                          workspace_repairs=[],
                                                          replayed_events=replayed_events))), \
         mock.patch.object(main_mod, "_reviewer_reachable", return_value=(True, "ok")), \
         mock.patch.object(main_mod, "_ingest_issues", return_value=0), \
         mock.patch.object(main_mod, "Orchestrator", return_value=orch):
        exit_code = main_mod.cmd_run(args)

    return exit_code


def test_both_validator_call_sites_receive_acknowledged_no_gate_explicitly(tmp_path):
    """Baseline-check Validator AND the orchestrator's own Validator must
    both be constructed with acknowledged_no_gate=cfg...— not relying on
    the parameter's default."""
    cfg = _cfg(tmp_path, commands=[], acknowledged_no_gate=True)
    calls = []

    class SpyValidator:
        def __init__(self, commands, **kwargs):
            calls.append(kwargs)

        def validate(self, *a, **kw):
            return SimpleNamespace(passed=True, gate_results=lambda: [])

    exit_code = _drive(cfg, skip_baseline=False, replayed_events=0,
                        validator_cls=SpyValidator)
    assert exit_code == 0
    assert len(calls) == 2  # baseline site + orchestrator site
    for kwargs in calls:
        assert kwargs["acknowledged_no_gate"] is True


def test_baseline_acknowledged_empty_prints_vacuous_green_and_spawns_nothing(
    tmp_path, capsys, monkeypatch,
):
    from runtime.validation import runner as runner_module

    spawn_calls = []
    monkeypatch.setattr(runner_module.subprocess, "run",
                        lambda *a, **kw: spawn_calls.append((a, kw)))

    cfg = _cfg(tmp_path, commands=[], acknowledged_no_gate=True)
    from runtime.validation.runner import Validator as RealValidator

    exit_code = _drive(cfg, skip_baseline=False, replayed_events=0,
                        validator_cls=RealValidator)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert spawn_calls == []
    assert ("[health] baseline green (no validation gate configured — "
            "commands=[], acknowledged_no_gate=true)") in captured.out
    assert captured.out.count("[health] baseline green\n") == 0


def test_baseline_normal_config_message_unchanged(tmp_path, capsys, monkeypatch):
    from runtime.validation import runner as runner_module

    monkeypatch.setattr(runner_module.subprocess, "run",
                        lambda *a, **kw: SimpleNamespace(returncode=0))

    cfg = _cfg(tmp_path, commands=["exit 0"], acknowledged_no_gate=False)
    from runtime.validation.runner import Validator as RealValidator

    exit_code = _drive(cfg, skip_baseline=False, replayed_events=0,
                        validator_cls=RealValidator)
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[health] baseline green\n" in captured.out
    assert "no validation gate configured" not in captured.out
