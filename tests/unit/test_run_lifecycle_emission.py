"""RunStarted/RunFinished emission from cmd_run (doc 03 amendment, "Core
emission"): exactly one RunStarted appended before checkout/reviewer
health/baseline/ingestion; exactly one RunFinished per controlled exit;
COMPLETED vs INTERRUPTED decided by control-flow path, never exit code;
detail always null; neither event for pre-normal-run failures; two runs
starting in the same UTC second get different run_ids."""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_NO_OVERRIDE = object()

from runtime.config import Config
from runtime.events.schema import EventType
from runtime.loop import OrchestratorHalt
from runtime.queue.issues_md import IssuesParseError
from runtime.repo.adapter import RepoError
from runtime.reviewer.base import ReviewerError
from runtime.validation.runner import ValidationResult


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


def _drive(*, skip_baseline=True, replayed_events=1, checkout_side_effect=None,
          reviewer_reachable=(True, "ok"), baseline_passed=True,
          ingest_side_effect=None, run_side_effect=None, reviewer_model_override=_NO_OVERRIDE):
    from runtime import main as main_mod

    cfg = _cfg(Path("C:/draindeck-unit-workspace"))
    args = SimpleNamespace(config="unused.yaml", skip_baseline=skip_baseline)

    adapter = mock.MagicMock(name="adapter")
    if checkout_side_effect is not None:
        adapter.checkout_branch.side_effect = checkout_side_effect
    adapter.head_of.return_value = "c0"

    orch = mock.MagicMock(name="orch")
    if run_side_effect is not None:
        orch.run.side_effect = run_side_effect
    else:
        orch.run.side_effect = lambda: "queue drained"
    orch.budget.metrics.return_value = SimpleNamespace(
        executions_this_run=0, proxy_dollars_this_run=0.0)
    lease = mock.MagicMock(name="lease", acquired=True, workspace_key="ws-test")
    lease.state.value = "ACQUIRED"
    lease.detail = "acquired"

    validator = mock.MagicMock(name="validator")
    validator.validate.return_value = ValidationResult(
        passed=baseline_passed, validated_commit="c0")

    reviewer_model_patch = (
        mock.patch.object(main_mod, "_resolve_reviewer_model", return_value=reviewer_model_override)
        if reviewer_model_override is not _NO_OVERRIDE else contextlib.nullcontext()
    )

    with reviewer_model_patch, \
         mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod, "EventLog") as event_log_cls, \
         mock.patch.object(main_mod.Path, "mkdir"), \
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
         mock.patch.object(main_mod, "_reviewer_reachable", return_value=reviewer_reachable), \
         mock.patch.object(main_mod, "Validator", return_value=validator), \
         mock.patch.object(main_mod, "_ingest_issues",
                           side_effect=ingest_side_effect if ingest_side_effect else (lambda *a, **k: 0)), \
         mock.patch.object(main_mod, "Orchestrator", return_value=orch):
        exit_code = main_mod.cmd_run(args)

    log_instance = event_log_cls.return_value
    appended = [c.args[0] for c in log_instance.append.call_args_list]
    return exit_code, appended


def _types(appended):
    return [ev.type for ev in appended]


def test_run_started_appended_first_and_before_checkout():
    from runtime import main as main_mod
    # checkout raises so we only observe the pre-checkout emission ordering
    exit_code, appended = _drive(checkout_side_effect=RepoError("boom"))
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload["outcome"] == "CHECKOUT_FAILED"
    assert appended[1].payload["detail"] is None


def test_pre_append_gate_blocks_invalid_constructed_run_started_before_any_append():
    """Defense-in-depth (review requirement): even if config.py's own
    guards were somehow bypassed -- simulated here via a monkeypatched
    reviewer-model resolver returning an empty string, which config.py's
    non-empty-model validators cannot see since it runs downstream of
    config loading -- the pre-append canonical-validation gate must
    independently refuse. Zero events may be durably appended."""
    exit_code, appended = _drive(reviewer_model_override="")
    assert appended == []
    assert exit_code == 1


def test_lifecycle_event_invalid_raised_directly_blocks_before_log_append():
    from runtime import main as main_mod
    from runtime.events.projections import StateProjection

    cfg = _cfg(Path("C:/draindeck-unit-workspace"))
    log = mock.MagicMock(name="log")
    proj = StateProjection()

    with mock.patch.object(main_mod, "_resolve_reviewer_model", return_value=""):
        with pytest.raises(main_mod.LifecycleEventInvalid):
            main_mod._emit_run_started(
                log, proj, cfg,
                "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6")

    assert not log.append.called


def test_reviewer_unreachable_emits_exactly_one_run_finished():
    exit_code, appended = _drive(reviewer_reachable=(False, "down"))
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "REVIEWER_UNREACHABLE", "detail": None}
    assert exit_code == 1


def test_baseline_failed_emits_exactly_one_run_finished():
    exit_code, appended = _drive(skip_baseline=False, replayed_events=0,
                                 baseline_passed=False)
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "BASELINE_FAILED", "detail": None}
    assert exit_code == 1


def test_ingest_failed_emits_exactly_one_run_finished():
    exit_code, appended = _drive(
        ingest_side_effect=IssuesParseError("bad issues file"))
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "INGEST_FAILED", "detail": None}
    assert exit_code == 1


def test_completed_emits_exactly_one_run_finished():
    exit_code, appended = _drive(run_side_effect=lambda: "queue drained")
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "COMPLETED", "detail": None}
    assert exit_code == 0


def test_halted_emits_exactly_one_run_finished():
    exit_code, appended = _drive(run_side_effect=OrchestratorHalt("tamper"))
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "HALTED", "detail": None}
    assert exit_code == 2


def test_reviewer_error_during_loop_is_halted_not_reviewer_unreachable():
    exit_code, appended = _drive(run_side_effect=ReviewerError("mid-loop failure"))
    assert appended[1].payload["outcome"] == "HALTED"
    assert exit_code == 2


def test_interrupted_emits_exactly_one_run_finished():
    exit_code, appended = _drive(run_side_effect=KeyboardInterrupt())
    assert _types(appended) == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert appended[1].payload == {"outcome": "INTERRUPTED", "detail": None}
    assert exit_code == 0


def test_completed_and_interrupted_share_exit_code_but_differ_in_outcome():
    """Exit code alone cannot distinguish them (doc 03 amendment) -- only the
    RunFinished outcome, decided by control-flow path, can."""
    completed_exit, completed_events = _drive(run_side_effect=lambda: "queue drained")
    interrupted_exit, interrupted_events = _drive(run_side_effect=KeyboardInterrupt())
    assert completed_exit == interrupted_exit == 0
    assert completed_events[1].payload["outcome"] == "COMPLETED"
    assert interrupted_events[1].payload["outcome"] == "INTERRUPTED"


def test_config_load_failure_emits_neither_event():
    from runtime import main as main_mod
    from runtime.config import ConfigError

    with mock.patch.object(main_mod, "load_config", side_effect=ConfigError("bad config")), \
         mock.patch.object(main_mod, "EventLog") as event_log_cls:
        exit_code = main_mod.cmd_run(SimpleNamespace(config="x", skip_baseline=True))
    assert exit_code == 1
    assert not event_log_cls.called


def _drive_pre_normal_run_failure(exc):
    """Every pre-normal-run failure path shares one shape: cmd_run's own
    except block around _open_startup_recovery() catches it and returns 1
    before _run_after_startup -- and therefore _emit_run_started -- is ever
    called. EventLog must never even be constructed."""
    from runtime import main as main_mod

    cfg = _cfg(Path("C:/draindeck-unit-workspace"))
    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod, "_open_startup_recovery", side_effect=exc), \
         mock.patch.object(main_mod, "EventLog") as event_log_cls:
        exit_code = main_mod.cmd_run(SimpleNamespace(config="x", skip_baseline=True))
    return exit_code, event_log_cls


def test_workspace_ownership_unavailable_emits_neither_event():
    from runtime import main as main_mod

    exit_code, event_log_cls = _drive_pre_normal_run_failure(
        main_mod.WorkspaceOwnershipUnavailable("lease held by another process"))
    assert exit_code == 1
    assert not event_log_cls.called


def test_event_log_unavailable_emits_neither_event():
    from runtime.events.log import EventLogUnavailable

    exit_code, event_log_cls = _drive_pre_normal_run_failure(
        EventLogUnavailable("authoritative writer unavailable"))
    assert exit_code == 1
    assert not event_log_cls.called


def test_workspace_containment_blocked_emits_neither_event():
    from runtime.recovery.containment import WorkspaceContainmentBlocked

    exit_code, event_log_cls = _drive_pre_normal_run_failure(
        WorkspaceContainmentBlocked("containment blocked"))
    assert exit_code == 1
    assert not event_log_cls.called


def test_engine_init_failed_emits_neither_event():
    from runtime.engine.claude_headless import EngineError

    exit_code, event_log_cls = _drive_pre_normal_run_failure(
        EngineError("engine init failed"))
    assert exit_code == 1
    assert not event_log_cls.called


def test_two_runs_in_the_same_second_get_different_run_ids():
    from runtime import main as main_mod

    ids = {main_mod._new_run_id() for _ in range(50)}
    assert len(ids) == 50  # UUID4 suffix prevents same-second collision
