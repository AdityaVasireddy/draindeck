"""Runtime CLI.

  python -m runtime.main verify-log  [--log PATH]   replay, enforce contract
  python -m runtime.main show-state  [--log PATH]   print projection summary
  python -m runtime.main recover     --config CONFIG  run configured recovery
  python -m runtime.main check-config CONFIG        structural + env validation
  python -m runtime.main run         --config CONFIG  the orchestrator loop
  python -m runtime.main init        REPO_PATH [--branch NAME] [--yes] [--force]
                                                     onboard a target repo (doc 16)

``run`` is the Session-5 orchestrator: startup order (config → log → engine →
adapter → reap_orphans → recover → health → ingest) then the doc 09 §8.2 loop.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .budget.manager import BudgetManager
from .config import Config, ConfigError, load_config, validate_environment
from .context.pack import build_prompt  # noqa: F401  (re-exported convenience)
from .engine.claude_headless import ClaudeHeadlessEngine, EngineError
from .events.log import (
    CorruptionError,
    EventLog,
    EventLogUnavailable,
    IncompleteLogError,
    ReadOnlyEventLog,
)
from .events.projections import StateProjection
from .events.schema import Event, EventType
from .init.command import cmd_init
from .loop import Orchestrator, OrchestratorHalt
from .queue.issues_md import IssuesParseError, parse as parse_issues
from .recovery.bindings import bind_reconciler
from .recovery.containment import WorkspaceContainmentBlocked, resolve_startup_containment
from .recovery.reconciler import recover
from .repo.adapter import RepoError
from .repo.git_adapter import GitCliAdapter
from .reviewer.base import ReviewerError, ReviewerProvider
from .reviewer.qwen_ollama import QwenOllamaReviewer
from .validation.runner import Validator
from .workspace_lease import WorkspaceLease, probe_controller_identity


def cmd_verify_log(args) -> int:
    try:
        with ReadOnlyEventLog(Path(args.log)) as log:
            events = list(log.replay())
    except FileNotFoundError:
        print(f"LOG MISSING: {args.log} (not created)", file=sys.stderr)
        return 1
    except IncompleteLogError as e:
        print(f"LOG INCOMPLETE: {e} (not repaired)", file=sys.stderr)
        return 1
    except CorruptionError as e:
        print(f"CORRUPT: {e}", file=sys.stderr)
        return 1
    last_event_id = events[-1].event_id if events else 0
    print(f"OK: {len(events)} events, last_event_id={last_event_id}")
    return 0


def cmd_show_state(args) -> int:
    try:
        with ReadOnlyEventLog(Path(args.log)) as log:
            proj = StateProjection().rebuild(log.replay())
    except FileNotFoundError:
        print(f"LOG MISSING: {args.log} (not created)", file=sys.stderr)
        return 1
    except IncompleteLogError as e:
        print(f"LOG INCOMPLETE: {e} (not repaired)", file=sys.stderr)
        return 1
    except CorruptionError as e:
        print(f"CORRUPT: {e}", file=sys.stderr)
        return 1
    out = {
        "last_event_id": proj.last_event_id,
        "digest": proj.digest(),
        "issues": {k: v.value for k, v in sorted(proj.issues.items())},
        "executions": {
            k: {"issue": v.issue_id, "state": v.state.value,
                "commit_intended": v.commit_intended,
                "commit_created": v.commit_created}
            for k, v in sorted(proj.executions.items())
        },
        "event_counts": dict(sorted(proj.counts.items())),
    }
    print(json.dumps(out, indent=2))
    return 0


class WorkspaceOwnershipUnavailable(RuntimeError):
    """Configured recovery/run could not become the workspace owner."""


@dataclass
class _StartupRecovery:
    """Owned safety-critical startup boundary shared by run and recover."""

    lease: WorkspaceLease
    log: EventLog
    engine: ClaudeHeadlessEngine
    adapter: GitCliAdapter
    artifacts_dir: Path
    proj: StateProjection
    report: object

    def close(self) -> None:
        """Release authoritative-log ownership before workspace ownership."""
        try:
            self.log.close()
        finally:
            self.lease.release_and_close()


def _load_runtime_config(config_path: str) -> Config | None:
    """Load configuration and fail before workspace/log ownership on error."""
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return None
    problems = validate_environment(cfg)
    if problems:
        print("ENVIRONMENT PROBLEMS (refusing to start):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return None
    return cfg


def _open_startup_recovery(cfg: Config) -> _StartupRecovery:
    """Perform the ownership-to-bound-recovery startup boundary exactly once."""
    lease = WorkspaceLease.acquire(cfg.project.repository)
    if not lease.acquired:
        raise WorkspaceOwnershipUnavailable(
            f"{lease.state.value}: {lease.detail}")

    log: EventLog | None = None
    try:
        # Writer ownership covers repair and replay before any containment or
        # workspace recovery action.  Workspace ownership is deliberately
        # separate: it protects the wider B4/runtime boundary.
        log = EventLog(Path(cfg.event_log.path))
        resolve_startup_containment(
            log, lease.workspace_key, controller_probe=probe_controller_identity)

        artifacts_dir = Path(cfg.event_log.path).parent / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        engine = ClaudeHeadlessEngine(cfg.engine, artifacts_dir)
        adapter = GitCliAdapter(cfg.project.repository, cfg.attempts.ref_namespace)
        for repair in engine.reap_orphans():
            print(f"[startup] {repair}")
        proj, report = recover(
            log,
            is_execution_alive=engine.is_execution_alive,
            workspace_key=lease.workspace_key,
            **bind_reconciler(adapter, cfg.project.branch),
        )
        return _StartupRecovery(lease, log, engine, adapter, artifacts_dir, proj, report)
    except Exception:
        try:
            if log is not None:
                try:
                    log.close()
                except Exception:
                    # Preserve the startup failure; the lease cleanup below
                    # must still run even if writer cleanup itself fails.
                    pass
        finally:
            lease.release_and_close()
        raise


def cmd_recover(args) -> int:
    cfg = _load_runtime_config(args.config)
    if cfg is None:
        return 1
    try:
        startup = _open_startup_recovery(cfg)
    except WorkspaceOwnershipUnavailable as e:
        print(f"WORKSPACE OWNERSHIP UNAVAILABLE: {e}", file=sys.stderr)
        return 1
    except EventLogUnavailable as e:
        print(f"AUTHORITATIVE LOG WRITER UNAVAILABLE: {e}", file=sys.stderr)
        return 1
    except WorkspaceContainmentBlocked as e:
        print(f"CONTAINMENT BLOCKED: {e}", file=sys.stderr)
        return 1
    except EngineError as e:
        print(f"ENGINE INIT FAILED: {e}", file=sys.stderr)
        return 1
    try:
        report = startup.report
        print(json.dumps({
            "replayed_events": report.replayed_events,
            "orphans_crashed": report.orphans_crashed,
            "emitted": report.emitted,
            "checks_run": report.checks_run,
            "checks_skipped": report.checks_skipped,
            "digest": startup.proj.digest(),
        }, indent=2))
        return 0
    finally:
        startup.close()


def cmd_check_config(args) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1
    problems = validate_environment(cfg)
    if problems:
        print("STRUCTURE OK; ENVIRONMENT PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: structure and environment valid")
    if cfg.project.validation.acknowledged_no_gate:
        print("NOTE: no validation gate configured (acknowledged_no_gate=true) "
              "— issues will be accepted without an automated check.")
    return 0


# ── orchestrator ──────────────────────────────────────────────────────
def _make_qwen_reviewer(cfg: Config) -> ReviewerProvider:
    q = cfg.reviewer.qwen
    return QwenOllamaReviewer(q.endpoint, q.model)


# Provider abstraction: config.py's KNOWN_REVIEWER_PROVIDERS gates what
# reaches here at all; a new provider is added by registering a factory
# below, not by editing this function's control flow.
_REVIEWER_FACTORIES: dict[str, Callable[[Config], ReviewerProvider]] = {
    "qwen": _make_qwen_reviewer,
}


def _make_reviewer(cfg: Config) -> ReviewerProvider:
    try:
        factory = _REVIEWER_FACTORIES[cfg.reviewer.provider]
    except KeyError:
        raise NotImplementedError(
            f"no reviewer factory registered for provider {cfg.reviewer.provider!r}"
        ) from None
    return factory(cfg)


def _reviewer_reachable(cfg: Config) -> tuple[bool, str]:
    if cfg.reviewer.provider != "qwen":
        return True, "skipped (non-qwen provider)"
    endpoint = cfg.reviewer.qwen.endpoint
    try:
        with urllib.request.urlopen(endpoint, timeout=5) as resp:
            resp.read(64)
        return True, f"reachable at {endpoint}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"unreachable at {endpoint}: {e}"


def _ingest_issues(cfg: Config, log: EventLog, proj: StateProjection,
                   run_id: str) -> int:
    """Read the target repo's Issues.md, emit IssueCreated for ids not already
    in the log (idempotent). Returns the count emitted. Aborts on a malformed
    file (fail-loud, matching the config loader)."""
    issues_path = Path(cfg.project.repository) / cfg.project.issues_file
    if not issues_path.exists():
        raise FileNotFoundError(f"issues file not found: {issues_path}")
    specs = parse_issues(issues_path.read_text(encoding="utf-8"))
    emitted = 0
    for spec in specs:
        if spec.id in proj.issues:
            continue  # already created in a prior run
        ev = Event(EventType.ISSUE_CREATED, issue_id=spec.id, run_id=run_id,
                   payload={"source": cfg.project.issues_file, "title": spec.title,
                            "body": spec.body, "acceptance_criteria": spec.acceptance_criteria,
                            "depends_on": spec.depends_on})
        eid = log.append(ev)
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                         run_id=ev.run_id, event_id=eid))
        emitted += 1
    return emitted


def _run_after_startup(args, cfg: Config, startup: _StartupRecovery) -> int:
    """Continue normal run work after the shared safety-critical boundary."""
    lease = startup.lease
    log = startup.log
    engine = startup.engine
    adapter = startup.adapter
    artifacts_dir = startup.artifacts_dir
    proj = startup.proj
    report = startup.report
    run_id = "run-" + datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")
    if report.orphans_crashed:
        print(f"[recovery] crashed orphans: {report.orphans_crashed}")
    for repair in report.workspace_repairs:
        print(f"[recovery] {repair}")

    # Recovery intentionally precedes checkout: its bound seams repair the
    # current crash residue before checkout's dirty-workspace guard runs.
    try:
        adapter.checkout_branch(cfg.project.branch)
    except RepoError as e:
        print(f"CHECKOUT FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[startup] checked out {cfg.project.branch}")

    ok, detail = _reviewer_reachable(cfg)
    print(f"[health] reviewer: {detail}")
    if not ok:
        print("[health] reviewer endpoint unreachable — refusing to start "
              "(the first review would halt the run)", file=sys.stderr)
        return 1
    if report.replayed_events == 0 and not args.skip_baseline:
        validator = Validator(cfg.project.validation.commands,
                              timeout_seconds=cfg.project.validation.timeout_seconds,
                              artifacts_dir=artifacts_dir,
                              env=cfg.project.validation.env,
                              acknowledged_no_gate=cfg.project.validation.acknowledged_no_gate)
        head = adapter.head_of(cfg.project.branch) or adapter.current_commit()
        result = validator.validate(cfg.project.repository, head, "baseline")
        if not result.passed:
            print(f"[health] BASELINE RED on {cfg.project.branch} — refusing to "
                  f"start (ADR-20 requires baseline green). See "
                  f"{artifacts_dir / 'baseline' / 'validation'}", file=sys.stderr)
            return 1
        if result.gate_results():
            print("[health] baseline green")
        else:
            # ADR-24 (doc 08 Sec5f): a vacuously-green baseline (no
            # configured validation command) must remain operator-visible,
            # not indistinguishable from a real passing gate.
            print("[health] baseline green (no validation gate configured — "
                  "commands=[], acknowledged_no_gate=true)")

    try:
        ingested = _ingest_issues(cfg, log, proj, run_id)
    except (IssuesParseError, FileNotFoundError) as e:
        print(f"INGEST FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[ingest] {ingested} new issue(s); {len(proj.issues)} total in queue")

    orch = Orchestrator(
        cfg=cfg, log=log, proj=proj, adapter=adapter, engine=engine,
        validator=Validator(cfg.project.validation.commands,
                            timeout_seconds=cfg.project.validation.timeout_seconds,
                            artifacts_dir=artifacts_dir,
                            env=cfg.project.validation.env,
                            acknowledged_no_gate=cfg.project.validation.acknowledged_no_gate),
        reviewer=_make_reviewer(cfg),
        budget=BudgetManager(cfg.budget.max_executions_per_run,
                             cfg.budget.hard_stop_proxy_cost_per_run_usd),
        artifacts_dir=artifacts_dir, run_id=run_id,
    )
    exit_code = 0
    try:
        reason = orch.run()
        metrics = orch.budget.metrics()
        print(f"[done] {reason}")
        print(f"[metrics] executions_this_run={metrics.executions_this_run} "
              f"proxy_dollars_this_run=${metrics.proxy_dollars_this_run:.4f}")
    except (OrchestratorHalt, ReviewerError) as e:
        print(f"[halt] run stopped abnormally: {e}", file=sys.stderr)
        exit_code = 2
    except KeyboardInterrupt:
        print("\n[stop] interrupted — current step finished; recovery owns the rest")
    finally:
        if proj.is_workspace_blocked(lease.workspace_key):
            print("[shutdown] containment remains unreleased; no branch restore attempted",
                  file=sys.stderr)
        else:
            try:
                adapter.checkout_branch(cfg.project.branch)
                print(f"[shutdown] restored {cfg.project.branch}")
            except RepoError as e:
                print(f"[shutdown] WARNING: failed to restore {cfg.project.branch}: {e}",
                      file=sys.stderr)
    return exit_code


def cmd_run(args) -> int:
    cfg = _load_runtime_config(args.config)
    if cfg is None:
        return 1

    # Workspace authority comes before anything which could inspect, repair, or
    # launch work in that workspace.  The mutex is exclusion only; containment
    # is separately replayed and resolved below.
    try:
        startup = _open_startup_recovery(cfg)
    except WorkspaceOwnershipUnavailable as e:
        print(f"WORKSPACE OWNERSHIP UNAVAILABLE: {e}", file=sys.stderr)
        return 1
    except EventLogUnavailable as e:
        print(f"AUTHORITATIVE LOG WRITER UNAVAILABLE: {e}", file=sys.stderr)
        return 1
    except WorkspaceContainmentBlocked as e:
        print(f"CONTAINMENT BLOCKED: {e}", file=sys.stderr)
        return 1
    except EngineError as e:
        print(f"ENGINE INIT FAILED: {e}", file=sys.stderr)
        return 1

    try:
        return _run_after_startup(args, cfg, startup)
    finally:
        startup.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("verify-log", cmd_verify_log),
                     ("show-state", cmd_show_state)]:
        s = sub.add_parser(name)
        s.add_argument("--log", default="state/events.jsonl")
        s.set_defaults(fn=fn)
    s = sub.add_parser("recover")
    s.add_argument("--config", required=True)
    s.set_defaults(fn=cmd_recover)
    s = sub.add_parser("check-config")
    s.add_argument("config")
    s.set_defaults(fn=cmd_check_config)
    s = sub.add_parser("run")
    s.add_argument("--config", required=True)
    s.add_argument("--skip-baseline", action="store_true",
                   help="skip the first-run baseline-green health check")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("init")
    s.add_argument("repo_path")
    s.add_argument("--branch", default="agent-work")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-validation", action="store_true")
    s.add_argument("--yes-no-validation", action="store_true")
    s.set_defaults(fn=cmd_init)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
