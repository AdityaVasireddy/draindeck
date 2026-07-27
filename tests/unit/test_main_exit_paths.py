"""cmd_run exit-path coverage for the branch-restore fix (NEXT.md item 8):
every exit out of the orch.run() try/except (clean drain, OrchestratorHalt,
ReviewerError, KeyboardInterrupt) must restore cfg.project.branch via the
finally block, and a restore failure must never supersede the primary
exit_code/exception already in flight."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config                                    # noqa: E402
from runtime.loop import OrchestratorHalt                            # noqa: E402
from runtime.repo.adapter import RepoError                           # noqa: E402
from runtime.reviewer.base import ReviewerError                      # noqa: E402


def _cfg(repo: Path) -> Config:
    return Config.model_validate({
        "project": {"name": "T", "repository": str(repo), "branch": "agent-work",
                    "issues_file": "Issues.md",
                    "validation": {"commands": ["exit 0"]}},
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


def _drive(tmp_path, run_side_effect, checkout_side_effect=None):
    """Run cmd_run with every collaborator mocked except the try/except/finally
    under test. Returns (exit_code, adapter_mock, capsys_text_placeholder)."""
    from runtime import main as main_mod

    cfg = _cfg(tmp_path)
    args = SimpleNamespace(config="unused.yaml", skip_baseline=True)

    adapter = mock.MagicMock(name="adapter")
    if checkout_side_effect is not None:
        adapter.checkout_branch.side_effect = checkout_side_effect

    orch = mock.MagicMock(name="orch")
    orch.run.side_effect = run_side_effect
    orch.budget.metrics.return_value = SimpleNamespace(
        executions_this_run=0, proxy_dollars_this_run=0.0)

    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod, "EventLog"), \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine",
                            return_value=mock.MagicMock(reap_orphans=lambda: [])), \
         mock.patch.object(main_mod, "GitCliAdapter", return_value=adapter), \
         mock.patch.object(main_mod, "bind_reconciler", return_value={}), \
         mock.patch.object(main_mod, "recover",
                            return_value=(mock.MagicMock(),
                                          SimpleNamespace(orphans_crashed=[],
                                                          workspace_repairs=[],
                                                          replayed_events=1))), \
         mock.patch.object(main_mod, "_reviewer_reachable", return_value=(True, "ok")), \
         mock.patch.object(main_mod, "_ingest_issues", return_value=0), \
         mock.patch.object(main_mod, "Orchestrator", return_value=orch):
        exit_code = main_mod.cmd_run(args)

    return exit_code, adapter


def test_clean_drain_restores_branch(tmp_path):
    exit_code, adapter = _drive(tmp_path, run_side_effect=lambda: "queue drained")
    assert exit_code == 0
    calls = [c.args for c in adapter.checkout_branch.call_args_list]
    assert calls[-1] == ("agent-work",)  # shutdown restore is the LAST call
    assert calls.count(("agent-work",)) == 2  # startup (5b) + shutdown (finally)


def test_orchestrator_halt_restores_branch_and_exit_code_2(tmp_path):
    exit_code, adapter = _drive(
        tmp_path, run_side_effect=OrchestratorHalt("tamper detected"))
    assert exit_code == 2
    assert adapter.checkout_branch.call_args_list[-1].args == ("agent-work",)


def test_reviewer_error_restores_branch_and_exit_code_2(tmp_path):
    exit_code, adapter = _drive(
        tmp_path, run_side_effect=ReviewerError("reviewer unreachable"))
    assert exit_code == 2
    assert adapter.checkout_branch.call_args_list[-1].args == ("agent-work",)


def test_keyboard_interrupt_restores_branch_and_exit_code_0(tmp_path):
    exit_code, adapter = _drive(tmp_path, run_side_effect=KeyboardInterrupt())
    assert exit_code == 0
    assert adapter.checkout_branch.call_args_list[-1].args == ("agent-work",)


def test_restore_failure_does_not_supersede_inflight_halt(tmp_path, capsys):
    """The inner except RepoError in the finally must log-and-continue, not
    re-raise — a shutdown git failure must never mask a real OrchestratorHalt
    exit code."""
    exit_code, adapter = _drive(
        tmp_path,
        run_side_effect=OrchestratorHalt("tamper detected"),
        checkout_side_effect=[None, RepoError("simulated shutdown checkout failure")],
    )
    assert exit_code == 2  # halt's exit code survives the failed restore
    err = capsys.readouterr().err
    assert "WARNING: failed to restore agent-work" in err
    assert "halt] run stopped abnormally: tamper detected" in err
