"""Runtime CLI.

  python -m runtime.main verify-log  [--log PATH]   replay, enforce contract
  python -m runtime.main show-state  [--log PATH]   print projection summary
  python -m runtime.main recover     [--log PATH]   run recovery, print report
  python -m runtime.main check-config CONFIG        structural + env validation
  python -m runtime.main run         --config CONFIG  the orchestrator loop

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
from pathlib import Path

from .budget.manager import BudgetManager
from .config import Config, ConfigError, load_config, validate_environment
from .context.pack import build_prompt  # noqa: F401  (re-exported convenience)
from .engine.claude_headless import ClaudeHeadlessEngine, EngineError
from .events.log import CorruptionError, EventLog
from .events.projections import StateProjection
from .events.schema import Event, EventType
from .loop import Orchestrator, OrchestratorHalt
from .queue.issues_md import IssuesParseError, parse as parse_issues
from .recovery.bindings import bind_reconciler
from .recovery.reconciler import recover
from .repo.adapter import RepoError
from .repo.git_adapter import GitCliAdapter
from .reviewer.base import ReviewerError, ReviewerProvider
from .reviewer.qwen_ollama import QwenOllamaReviewer
from .validation.runner import Validator


def _load(path: str) -> EventLog:
    return EventLog(Path(path))


def cmd_verify_log(args) -> int:
    try:
        log = _load(args.log)
        n = sum(1 for _ in log.replay())
    except CorruptionError as e:
        print(f"CORRUPT: {e}", file=sys.stderr)
        return 1
    print(f"OK: {n} events, last_event_id={log.last_event_id}")
    return 0


def cmd_show_state(args) -> int:
    log = _load(args.log)
    proj = StateProjection().rebuild(log.replay())
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


def cmd_recover(args) -> int:
    log = _load(args.log)
    proj, rep = recover(log)
    print(json.dumps({
        "replayed_events": rep.replayed_events,
        "orphans_crashed": rep.orphans_crashed,
        "emitted": rep.emitted,
        "checks_run": rep.checks_run,
        "checks_skipped": rep.checks_skipped,
        "digest": proj.digest(),
    }, indent=2))
    return 0


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
    return 0


# ── orchestrator ──────────────────────────────────────────────────────
def _make_reviewer(cfg: Config) -> ReviewerProvider:
    if cfg.reviewer.provider == "qwen":
        q = cfg.reviewer.qwen
        return QwenOllamaReviewer(q.endpoint, q.model)
    raise NotImplementedError(
        "reviewer.provider=claude (ClaudeReviewer) is deferred to Session 7; "
        "v1 ships the qwen provider only"
    )


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


def cmd_run(args) -> int:
    # 1. config (structural, no side effects)
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1
    # 2. environment (repo/git/branch, ADR-18 key posture)
    problems = validate_environment(cfg)
    if problems:
        print("ENVIRONMENT PROBLEMS (refusing to start):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    state_dir = Path(cfg.event_log.path).parent
    artifacts_dir = state_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_id = "run-" + datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")

    # 3. log
    log = EventLog(Path(cfg.event_log.path))
    # 4. engine (fails fast if `claude` not on PATH)
    try:
        engine = ClaudeHeadlessEngine(cfg.engine, artifacts_dir)
    except EngineError as e:
        print(f"ENGINE INIT FAILED: {e}", file=sys.stderr)
        return 1
    # 5. adapter
    adapter = GitCliAdapter(cfg.project.repository, cfg.attempts.ref_namespace)

    # 5b. enforce checked-out branch BEFORE recovery/baseline (ADR-20 amendment,
    # 2026-07-26): recovery binds its seams to cfg.project.branch and the baseline
    # health check validates the physical tree — both are meaningless if the wrong
    # branch is on disk. Reuses the existing adapter method (no create_from: we must
    # never force-reset the target repo's long-lived branch, only switch to it).
    try:
        adapter.checkout_branch(cfg.project.branch)
    except RepoError as e:
        print(f"CHECKOUT FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[startup] checked out {cfg.project.branch}")

    # 6. reap engine orphans BEFORE recovery (doc 12 §1.6)
    for r in engine.reap_orphans():
        print(f"[startup] {r}")
    # 7. recovery — the full production seam binding proven by harness f4
    proj, report = recover(
        log,
        is_execution_alive=engine.is_execution_alive,
        **bind_reconciler(adapter, cfg.project.branch),
    )
    if report.orphans_crashed:
        print(f"[recovery] crashed orphans: {report.orphans_crashed}")
    for r in report.workspace_repairs:
        print(f"[recovery] {r}")

    # 8. health checks
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
                              env=cfg.project.validation.env)  # ADR-23: same hygiene as the loop's validator
        head = adapter.head_of(cfg.project.branch) or adapter.current_commit()
        res = validator.validate(cfg.project.repository, head, "baseline")
        if not res.passed:
            print(f"[health] BASELINE RED on {cfg.project.branch} — refusing to "
                  f"start (ADR-20 requires baseline green). See "
                  f"{artifacts_dir / 'baseline' / 'validation'}", file=sys.stderr)
            return 1
        print("[health] baseline green")

    # 9. ingest issues (idempotent)
    try:
        n = _ingest_issues(cfg, log, proj, run_id)
    except (IssuesParseError, FileNotFoundError) as e:
        print(f"INGEST FAILED: {e}", file=sys.stderr)
        return 1
    print(f"[ingest] {n} new issue(s); {len(proj.issues)} total in queue")

    # 10. the loop
    orch = Orchestrator(
        cfg=cfg, log=log, proj=proj, adapter=adapter, engine=engine,
        validator=Validator(cfg.project.validation.commands,
                            timeout_seconds=cfg.project.validation.timeout_seconds,
                            artifacts_dir=artifacts_dir,
                            env=cfg.project.validation.env),  # ADR-23: same hygiene as the baseline check
        reviewer=_make_reviewer(cfg),
        budget=BudgetManager(cfg.budget.max_executions_per_run,
                            cfg.budget.hard_stop_proxy_cost_per_run_usd),
        artifacts_dir=artifacts_dir, run_id=run_id,
    )
    try:
        reason = orch.run()
    except (OrchestratorHalt, ReviewerError) as e:
        print(f"[halt] run stopped abnormally: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n[stop] interrupted — current step finished; recovery owns the rest")
        return 0
    m = orch.budget.metrics()
    print(f"[done] {reason}")
    print(f"[metrics] executions_this_run={m.executions_this_run} "
          f"proxy_dollars_this_run=${m.proxy_dollars_this_run:.4f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("verify-log", cmd_verify_log),
                     ("show-state", cmd_show_state),
                     ("recover", cmd_recover)]:
        s = sub.add_parser(name)
        s.add_argument("--log", default="state/events.jsonl")
        s.set_defaults(fn=fn)
    s = sub.add_parser("check-config")
    s.add_argument("config")
    s.set_defaults(fn=cmd_check_config)
    s = sub.add_parser("run")
    s.add_argument("--config", required=True)
    s.add_argument("--skip-baseline", action="store_true",
                   help="skip the first-run baseline-green health check")
    s.set_defaults(fn=cmd_run)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
