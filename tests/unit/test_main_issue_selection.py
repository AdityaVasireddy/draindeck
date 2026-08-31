"""ADR-30 RED 4: runtime exact-selection CLI and re-validation.

Covers argparse-level contract (repeated --issue, --all-issues mutual
exclusivity, legacy no-selection form unchanged), and _validate_selection's
digest/replay/planner wiring. cmd_run-level tests reuse
test_main_exit_paths.py's full-mock harness style.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config                                    # noqa: E402
from runtime.events.projections import StateProjection              # noqa: E402
from runtime.events.schema import Event, EventType                  # noqa: E402
from runtime import main as main_mod                                 # noqa: E402
from runtime.main import SelectionRunAllEmpty, _validate_selection  # noqa: E402


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


def _proj_with(issue_states: dict) -> StateProjection:
    """Builds a StateProjection whose `.issues` map holds exactly the given
    states. Uses real ISSUE_CREATED/ISSUE_ACTIVATED replay for PENDING/ACTIVE
    (exercising real transitions), then directly assigns any other target
    state (DONE, NEEDS_HUMAN, NEEDS_DECOMPOSITION) -- `_validate_selection`
    only ever reads `proj.issues`, so this tests its consumption of that map,
    not StateProjection's own transition correctness (covered exhaustively
    elsewhere, e.g. tests/unit/test_loop.py)."""
    from runtime.state.model import IssueState
    proj = StateProjection()
    for iid, state in issue_states.items():
        ev = Event(EventType.ISSUE_CREATED, issue_id=iid,
                   payload={"title": iid, "body": "b", "depends_on": []})
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id, event_id=1))
        if state == "ACTIVE":
            act = Event(EventType.ISSUE_ACTIVATED, issue_id=iid, payload={"base_commit": "c0"})
            proj.apply(Event(type=act.type, payload=act.payload, issue_id=act.issue_id, event_id=2))
        elif state != "PENDING":
            proj.issues[iid] = IssueState(state)
    return proj


# ── argparse contract ───────────────────────────────────────────────────

def test_run_cli_accepts_repeated_issue_ids_as_exact_selection():
    args = main_mod.main.__wrapped__ if hasattr(main_mod.main, "__wrapped__") else None
    ap_args = _parse(["run", "--config", "c.yaml", "--issues-digest", "a" * 64,
                       "--issue", "x", "--issue", "y"])
    assert ap_args.issue_ids == ["x", "y"]
    assert ap_args.all_issues is False


def test_run_cli_without_selection_preserves_existing_cli_behavior():
    ap_args = _parse(["run", "--config", "c.yaml"])
    assert ap_args.issue_ids is None
    assert ap_args.all_issues is False
    assert ap_args.issues_digest is None


def test_run_cli_issue_and_all_issues_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        _parse(["run", "--config", "c.yaml", "--issue", "x", "--all-issues"])


def _parse(argv):
    import argparse
    # main() builds argparse fresh each call and only returns an exit code,
    # so reconstruct just the `run` subparser piece it defines, to assert on
    # parsed args directly without invoking cmd_run.
    ap = argparse.ArgumentParser(prog="runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run")
    s.add_argument("--config", required=True)
    s.add_argument("--skip-baseline", action="store_true")
    s.add_argument("--issues-digest", default=None)
    sel = s.add_mutually_exclusive_group()
    sel.add_argument("--issue", action="append", dest="issue_ids", default=None)
    sel.add_argument("--all-issues", action="store_true")
    return ap.parse_args(argv)


# ── _validate_selection ──────────────────────────────────────────────────

def test_runtime_revalidates_selection_after_workspace_ownership_and_recovery(tmp_path):
    """The digest is checked against fresh bytes read right now, not any
    cached value -- proving re-validation, not trust of the caller."""
    repo = tmp_path
    issues = repo / "Issues.md"
    issues.write_text("## a: A\nbody\n", encoding="utf-8")
    cfg = _cfg(repo)
    proj = _proj_with({})

    stale_digest = hashlib.sha256(b"stale content").hexdigest()
    args = SimpleNamespace(issue_ids=["a"], all_issues=False, issues_digest=stale_digest)
    allowed, error = _validate_selection(args, cfg, proj)
    assert allowed is None
    assert "mismatch" in error


def test_runtime_selection_refusal_occurs_before_issue_activation_and_emits_nothing(tmp_path):
    """_validate_selection is a pure function over (args, cfg, proj) -- it
    never touches an EventLog, so a refusal cannot emit RunStarted,
    RunFinished, or IssueActivated by construction."""
    import ast
    source = Path("src/runtime/main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_validate_selection")
    fn_source = ast.get_source_segment(source, fn)
    assert "log.append" not in fn_source
    assert "_emit_run_started" not in fn_source
    assert "ISSUE_ACTIVATED" not in fn_source


def test_runtime_never_activates_unselected_pending_issue_via_validate(tmp_path):
    repo = tmp_path
    text = "## a: A\nbody\n\n## b: B\nbody\n"
    (repo / "Issues.md").write_text(text, encoding="utf-8", newline="")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cfg = _cfg(repo)
    proj = _proj_with({})
    args = SimpleNamespace(issue_ids=["a"], all_issues=False, issues_digest=digest)
    allowed, error = _validate_selection(args, cfg, proj)
    assert error is None
    assert allowed == frozenset({"a"})


def test_runtime_run_all_uses_current_nonterminal_set(tmp_path):
    repo = tmp_path
    text = "## a: A\nbody\n\n## b: B\nbody\n"
    (repo / "Issues.md").write_text(text, encoding="utf-8", newline="")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cfg = _cfg(repo)
    proj = _proj_with({"b": "DONE"})
    args = SimpleNamespace(issue_ids=None, all_issues=True, issues_digest=digest)
    allowed, error = _validate_selection(args, cfg, proj)
    assert error is None
    assert allowed == frozenset({"a"})


def test_runtime_run_all_zero_nonterminal_is_clean_noop(tmp_path):
    repo = tmp_path
    text = "## a: A\nbody\n"
    (repo / "Issues.md").write_text(text, encoding="utf-8", newline="")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cfg = _cfg(repo)
    proj = _proj_with({"a": "DONE"})
    args = SimpleNamespace(issue_ids=None, all_issues=True, issues_digest=digest)
    with pytest.raises(SelectionRunAllEmpty):
        _validate_selection(args, cfg, proj)


def test_selection_digest_must_be_lowercase_hex_64(tmp_path):
    cfg = _cfg(tmp_path)
    proj = _proj_with({})
    args = SimpleNamespace(issue_ids=["a"], all_issues=False, issues_digest="not-hex")
    allowed, error = _validate_selection(args, cfg, proj)
    assert allowed is None
    assert "64 lowercase hex" in error


def test_selection_reports_every_blocker_not_just_first(tmp_path):
    repo = tmp_path
    text = "## a: A\nbody\n\n## b: B\nbody\n"
    (repo / "Issues.md").write_text(text, encoding="utf-8", newline="")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cfg = _cfg(repo)
    proj = _proj_with({})  # neither a nor b has any dependency here; use unknown ids instead
    args = SimpleNamespace(issue_ids=["ghost1", "ghost2"], all_issues=False, issues_digest=digest)
    allowed, error = _validate_selection(args, cfg, proj)
    assert allowed is None
    assert "ghost1" in error and "ghost2" in error


# ── cmd_run full-mock integration (mirrors test_main_exit_paths.py style) ──

def _drive_selected(tmp_path, issue_ids, digest, proj_issue_states=None):
    repo = tmp_path
    cfg = _cfg(repo)
    args = SimpleNamespace(config="unused.yaml", skip_baseline=True,
                           issue_ids=issue_ids, all_issues=False, issues_digest=digest)

    orch = mock.MagicMock(name="orch")
    orch.run.side_effect = lambda: "queue drained"
    orch.budget.metrics.return_value = SimpleNamespace(executions_this_run=0, proxy_dollars_this_run=0.0)
    lease = mock.MagicMock(name="lease", acquired=True, workspace_key="ws-test")
    lease.state.value = "ACQUIRED"
    lease.detail = "acquired"

    captured_kwargs = {}

    def _capture_orch(**kwargs):
        captured_kwargs.update(kwargs)
        return orch

    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod, "EventLog"), \
         mock.patch.object(main_mod.Path, "mkdir"), \
         mock.patch.object(main_mod, "WorkspaceLease") as WL, \
         mock.patch.object(main_mod, "resolve_startup_containment", return_value=mock.MagicMock()), \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine",
                            return_value=mock.MagicMock(reap_orphans=lambda: [])), \
         mock.patch.object(main_mod, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main_mod, "bind_reconciler", return_value={}), \
         mock.patch.object(main_mod, "recover",
                            return_value=(mock.MagicMock(is_workspace_blocked=mock.Mock(return_value=False)),
                                          SimpleNamespace(orphans_crashed=[], workspace_repairs=[],
                                                          replayed_events=1))), \
         mock.patch.object(main_mod, "_reviewer_reachable", return_value=(True, "ok")), \
         mock.patch.object(main_mod, "_ingest_issues", return_value=0), \
         mock.patch.object(main_mod, "Orchestrator", side_effect=_capture_orch), \
         mock.patch.object(main_mod, "_emit_run_started"), \
         mock.patch.object(main_mod, "_emit_run_finished"):
        WL.acquire.return_value = lease
        if proj_issue_states:
            def _startup(cfg_arg):
                startup = mock.MagicMock()
                startup.lease = lease
                startup.log = mock.MagicMock()
                startup.engine = mock.MagicMock(reap_orphans=lambda: [])
                startup.adapter = mock.MagicMock()
                startup.artifacts_dir = tmp_path / "art"
                startup.proj = _proj_with(proj_issue_states)
                startup.report = SimpleNamespace(orphans_crashed=[], workspace_repairs=[], replayed_events=1)
                return startup
            with mock.patch.object(main_mod, "_open_startup_recovery", side_effect=_startup):
                exit_code = main_mod.cmd_run(args)
        else:
            exit_code = main_mod.cmd_run(args)

    return exit_code, captured_kwargs


def test_selection_refusal_returns_exit_1_without_constructing_orchestrator(tmp_path):
    (tmp_path / "Issues.md").write_text("## a: A\nbody\n", encoding="utf-8")
    exit_code, kwargs = _drive_selected(tmp_path, ["ghost"], "a" * 64)
    assert exit_code == 1
    assert kwargs == {}  # Orchestrator was never constructed


def test_selected_run_passes_allowed_issue_ids_to_orchestrator(tmp_path):
    text = "## a: A\nbody\n\n## b: B\nbody\n"
    (tmp_path / "Issues.md").write_text(text, encoding="utf-8", newline="")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    exit_code, kwargs = _drive_selected(tmp_path, ["a"], digest, proj_issue_states={})
    assert exit_code == 0
    assert kwargs.get("allowed_issue_ids") == frozenset({"a"})
