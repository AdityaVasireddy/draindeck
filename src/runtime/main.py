"""Runtime CLI.

  python -m runtime.main verify-log  [--log PATH]   replay, enforce contract
  python -m runtime.main show-state  [--log PATH]   print projection summary
  python -m runtime.main recover     --config CONFIG  run configured recovery
  python -m runtime.main check-config CONFIG        structural + env validation
  python -m runtime.main run         --config CONFIG  the orchestrator loop
  python -m runtime.main init        REPO_PATH [--branch NAME] [--yes] [--force]
                                                     onboard a target repo (doc 16)
  python -m runtime.main observe events --log PATH [--after CURSOR]
                                         [--limit N] --format json
                                                     read-only event evidence (ADR-25)
  python -m runtime.main observe status --log PATH --format json
                                                     read-only availability (ADR-25)

Installed as the ``draindeck`` console script (pyproject.toml
[project.scripts]) for the same argv shape.

``run`` is the Session-5 orchestrator: startup order (config → log → engine →
adapter → reap_orphans → recover → health → ingest) then the doc 09 §8.2 loop.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .budget.manager import BudgetManager
from .config import (
    Config,
    ConfigError,
    load_config,
    resolve_event_log_path,
    validate_environment,
)
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
from .observe import (
    DEFAULT_LIMIT,
    ObserverInputError,
    read_events_page,
    read_status,
    validate_limit,
    validate_log_path,
)
from .queue.issues_md import IssuesParseError, parse as parse_issues
from .queue.selection import Blocker, TerminalExclusion, plan_run_all, plan_selected
from .recovery.bindings import bind_reconciler
from .recovery.containment import WorkspaceContainmentBlocked, resolve_startup_containment
from .recovery.reconciler import recover
from .repo.adapter import RepoError
from .repo.git_adapter import GitCliAdapter
from .reviewer.base import ReviewerError, ReviewerProvider
from .reviewer.qwen_ollama import QwenOllamaReviewer
from .state.transitions import TransitionError
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


def cmd_observe_events(args) -> int:
    try:
        log_path = validate_log_path(args.log)
        limit = validate_limit(args.limit)
        page = read_events_page(log_path, after=args.after, limit=limit)
    except ObserverInputError as e:
        print(json.dumps(e.to_response()), file=sys.stderr)
        return 1
    print(json.dumps(page))
    return 0


def cmd_observe_status(args) -> int:
    try:
        log_path = validate_log_path(args.log)
    except ObserverInputError as e:
        print(json.dumps(e.to_response()), file=sys.stderr)
        return 1
    print(json.dumps(read_status(log_path)))
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
        log_path = resolve_event_log_path(cfg)
        log = EventLog(log_path)
        resolve_startup_containment(
            log, lease.workspace_key, controller_probe=probe_controller_identity)

        artifacts_dir = log_path.parent / "artifacts"
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


# Reviewer-model resolution for RunStarted/config_digest (doc 03 amendment).
# Mirrors _REVIEWER_FACTORIES's registry-not-Literal-widening pattern: a new
# provider gets a resolver registered here, never a control-flow branch.
# "Null only when the selected provider's own config subsection has no
# model field at all" (doc 03 amendment) -- no registered provider today
# lacks one; an unregistered future provider resolves to None.
_REVIEWER_MODEL_RESOLVERS: dict[str, Callable[[Config], Optional[str]]] = {
    "qwen": lambda cfg: cfg.reviewer.qwen.model,
}


def _resolve_reviewer_model(cfg: Config) -> Optional[str]:
    resolver = _REVIEWER_MODEL_RESOLVERS.get(cfg.reviewer.provider)
    return resolver(cfg) if resolver else None


def _config_digest(cfg: Config, reviewer_model: Optional[str]) -> str:
    """SHA-256 over canonical JSON of exactly the doc 03 amendment's
    10-field allowlist -- built field-by-field, never from the full
    Config object, so an excluded field (secrets, paths, endpoints,
    commands, env, ...) can never reach the digest input by construction."""
    canon = {
        "budget": {
            "hard_stop_proxy_cost_per_run_usd": cfg.budget.hard_stop_proxy_cost_per_run_usd,
            "max_attempts_per_issue": cfg.budget.max_attempts_per_issue,
            "max_executions_per_run": cfg.budget.max_executions_per_run,
            "proxy_pricing": cfg.budget.proxy_pricing,
        },
        "engine": {
            "max_turns": cfg.engine.max_turns,
            "model": cfg.engine.model,
            "provider": cfg.engine.provider,
            "timeout_seconds": cfg.engine.timeout_seconds,
        },
        "reviewer": {
            "model": reviewer_model,
            "provider": cfg.reviewer.provider,
        },
    }
    raw = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _run_started_payload(cfg: Config, reviewer_model: Optional[str], digest: str) -> dict:
    return {
        "engine": {"provider": cfg.engine.provider, "model": cfg.engine.model},
        "reviewer": {"provider": cfg.reviewer.provider, "model": reviewer_model},
        "budget": {
            "max_attempts_per_issue": cfg.budget.max_attempts_per_issue,
            "max_executions_per_run": cfg.budget.max_executions_per_run,
            "hard_stop_proxy_cost_per_run_usd": cfg.budget.hard_stop_proxy_cost_per_run_usd,
            "proxy_pricing": cfg.budget.proxy_pricing,
        },
        "config_digest": digest,
    }


def _new_run_id() -> str:
    # run-<UTC-second>-<uuid4> (doc 03 amendment, "Run ID format"). The
    # UUID4 suffix — never the timestamp alone — is what prevents two runs
    # starting in the same UTC second from colliding.
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4()}"


class LifecycleEventInvalid(RuntimeError):
    """A constructed RunStarted/RunFinished failed the same canonical
    validation StateProjection.apply() uses at replay time -- e.g. an
    empty resolved model, or a malformed run_id. Config-layer guards
    (config.py) close the known gaps; this is the structural, defense-in-
    depth backstop that guarantees a violation is caught before durable
    append regardless of what config.py's own rules do or don't catch
    (review requirement: "a validation failure must occur before durable
    append"). Reuses runtime.events.projections' own _HANDLERS rather than
    re-implementing the doc 03 closed-schema rules a second time."""


def _validate_lifecycle_event(ev: Event) -> None:
    try:
        StateProjection().apply(ev)
    except TransitionError as e:
        raise LifecycleEventInvalid(str(e)) from e


def _emit_run_started(log: EventLog, proj: StateProjection, cfg: Config, run_id: str) -> None:
    reviewer_model = _resolve_reviewer_model(cfg)
    digest = _config_digest(cfg, reviewer_model)
    payload = _run_started_payload(cfg, reviewer_model, digest)
    candidate = Event(EventType.RUN_STARTED, run_id=run_id, payload=payload)
    _validate_lifecycle_event(candidate)
    eid = log.append(candidate)
    proj.apply(Event(type=EventType.RUN_STARTED, run_id=run_id, payload=payload, event_id=eid))
    # ADR-30 review finding 6 / spec "Frozen event schema": a bounded,
    # machine-readable stdout line immediately after the fsynced RunStarted
    # above, so a launcher can correlate a spawned process with its run. It
    # is only a hint -- adds no event, schema, or payload field, and a
    # consumer must independently confirm run_id through the normal
    # observer/indexed evidence before trusting it for anything.
    print(f"DRAINDECK_RUN_ID={run_id}")


def _emit_run_finished(log: EventLog, proj: StateProjection, run_id: str, outcome: str) -> None:
    # detail is always null (doc 03 amendment's binding safety rule) --
    # never str(exception) or any other dynamically-derived value.
    payload = {"outcome": outcome, "detail": None}
    candidate = Event(EventType.RUN_FINISHED, run_id=run_id, payload=payload)
    _validate_lifecycle_event(candidate)
    eid = log.append(candidate)
    proj.apply(Event(type=EventType.RUN_FINISHED, run_id=run_id, payload=payload, event_id=eid))


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


def _resolve_issues_file_path(cfg: Config) -> Path:
    return Path(cfg.project.repository) / cfg.project.issues_file


def _format_plan_refusal(result) -> str:
    """ADR-30: names every refusal reason -- never just the first one found."""
    parts: list[str] = []
    if result.empty_selection:
        parts.append("selection is empty")
    if result.unknown_ids:
        parts.append(f"unknown issue id(s): {', '.join(result.unknown_ids)}")
    if result.duplicate_ids:
        parts.append(f"duplicate issue id(s): {', '.join(result.duplicate_ids)}")
    if result.terminal_selected:
        parts.append("terminal issue(s) selected: " + ", ".join(
            f"{t.issue_id} ({t.state})" for t in result.terminal_selected))
    if result.blockers:
        parts.append("unfinished dependencies: " + "; ".join(
            f"{b.issue_id} needs {b.missing_dependency_id} ({b.dependency_state})"
            for b in result.blockers))
    if result.cycle_members:
        parts.append(f"dependency cycle among: {', '.join(result.cycle_members)}")
    if result.omitted_active_ids:
        parts.append(f"active issue(s) omitted from selection: {', '.join(result.omitted_active_ids)}")
    return "; ".join(parts) if parts else "selection refused"


@dataclass(frozen=True)
class SelectionPlan:
    """ADR-30 review finding 2: carries the validated topological order and
    a current-configured-file dependency map (built from the freshly
    re-read/re-parsed issue file, at this same validation call) through into
    the Orchestrator, so historical IssueCreated ordering/dependency
    metadata can never override a freshly validated selection or run-all
    batch. `dependencies` covers every issue in the freshly parsed file, not
    only the selected/run-all subset, since a dependency can reference an
    issue outside the batch."""

    allowed_ids: "frozenset[str]"
    ordered_ids: "tuple[str, ...]"
    dependencies: "dict[str, tuple[str, ...]]"


class SelectionRunAllEmpty(Exception):
    """Raised by _validate_selection for the one successful-but-early-exit
    case: a valid --all-issues batch with zero non-terminal issues remaining.
    ADR-30 sec2: "a valid zero-item run-all is a successful no-op and emits
    no empty run lifecycle" -- distinct from a refusal, so it is not folded
    into the (allowed_ids, error) return shape below."""


def _validate_selection(args, cfg: Config, proj: StateProjection) -> tuple[Optional[SelectionPlan], Optional[str]]:
    """ADR-30 sec2: re-reads the configured issue file fresh (never the
    Dashboard's cached copy), verifies the issues-digest against those exact
    bytes, replays authoritative state from `proj` (already fully recovered
    at this call site, before RunStarted), and re-validates the complete
    batch through the same pure planner the Dashboard API uses. Returns
    (None, None) for the legacy no-selection CLI form (unchanged behavior).
    Raises SelectionRunAllEmpty for a valid, empty --all-issues result."""
    issue_ids = getattr(args, "issue_ids", None)
    all_issues = getattr(args, "all_issues", False)
    if not all_issues and not issue_ids:
        return None, None

    digest = getattr(args, "issues_digest", None)
    if not digest or len(digest) != 64 or digest != digest.lower() or not all(c in "0123456789abcdef" for c in digest):
        return None, "--issues-digest must be exactly 64 lowercase hex characters"

    issues_path = _resolve_issues_file_path(cfg)
    if not issues_path.exists():
        return None, f"issues file not found: {issues_path}"
    raw = issues_path.read_bytes()
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != digest:
        return None, f"issues-digest mismatch: expected {digest}, file is now {actual_digest}"

    try:
        specs = parse_issues(raw.decode("utf-8"))
    except (UnicodeDecodeError, IssuesParseError) as e:
        return None, f"issues file could not be parsed: {e}"

    states = {iid: st.value for iid, st in proj.issues.items()}

    if all_issues:
        result = plan_run_all(specs, states)
    else:
        result = plan_selected(specs, states, issue_ids)

    if not result.ok:
        return None, _format_plan_refusal(result)
    if all_issues and not result.ordered_ids:
        raise SelectionRunAllEmpty()
    dependencies = {s.id: tuple(s.depends_on) for s in specs}
    plan = SelectionPlan(
        allowed_ids=frozenset(result.ordered_ids),
        ordered_ids=tuple(result.ordered_ids),
        dependencies=dependencies,
    )
    return plan, None


def _ingest_issues(cfg: Config, log: EventLog, proj: StateProjection,
                   run_id: str) -> int:
    """Read the target repo's Issues.md, emit IssueCreated for ids not already
    in the log (idempotent). Returns the count emitted. Aborts on a malformed
    file (fail-loud, matching the config loader)."""
    issues_path = _resolve_issues_file_path(cfg)
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

    # ADR-30: selection re-validation happens after ownership/recovery (proj
    # already reflects fully-replayed authoritative state) but strictly
    # before RunStarted and before any issue activation. Legacy invocations
    # supplying neither --issue nor --all-issues get (None, None) and are
    # completely unaffected.
    try:
        selection_plan, selection_error = _validate_selection(args, cfg, proj)
    except SelectionRunAllEmpty:
        print("[run-all] no non-terminal issues remain — successful no-op, "
              "no run started")
        return 0
    if selection_error is not None:
        print(f"SELECTION REJECTED: {selection_error}", file=sys.stderr)
        return 1

    # RunStarted is the run's first action after entering normal run work --
    # before checkout, reviewer health, baseline validation, and ingestion
    # (doc 03 amendment, "Ordering and pre-normal-run failures"). Everything
    # before this call (config load, workspace/log ownership, recovery) is
    # pre-normal-run and deliberately emits neither RunStarted nor
    # RunFinished.
    run_id = _new_run_id()
    try:
        _emit_run_started(log, proj, cfg, run_id)
    except LifecycleEventInvalid as e:
        # Caught before log.append ran (_validate_lifecycle_event runs
        # first) -- nothing was durably written for this run.
        print(f"CONFIG CANNOT PRODUCE A VALID RunStarted: {e}", file=sys.stderr)
        return 1

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
        _emit_run_finished(log, proj, run_id, "CHECKOUT_FAILED")
        return 1
    print(f"[startup] checked out {cfg.project.branch}")

    ok, detail = _reviewer_reachable(cfg)
    print(f"[health] reviewer: {detail}")
    if not ok:
        print("[health] reviewer endpoint unreachable — refusing to start "
              "(the first review would halt the run)", file=sys.stderr)
        _emit_run_finished(log, proj, run_id, "REVIEWER_UNREACHABLE")
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
            _emit_run_finished(log, proj, run_id, "BASELINE_FAILED")
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
        _emit_run_finished(log, proj, run_id, "INGEST_FAILED")
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
        allowed_issue_ids=selection_plan.allowed_ids if selection_plan else None,
        selection_order=selection_plan.ordered_ids if selection_plan else None,
        selection_dependencies=selection_plan.dependencies if selection_plan else None,
    )
    # COMPLETED and INTERRUPTED both leave exit_code at 0 today (an existing,
    # unchanged property of this loop) -- outcome is therefore decided by
    # which except/try branch actually executed, never by exit_code (doc 03
    # amendment, INTERRUPTED row: "the process's own exit code does not
    # distinguish this from COMPLETED").
    exit_code = 0
    try:
        reason = orch.run()
        metrics = orch.budget.metrics()
        print(f"[done] {reason}")
        print(f"[metrics] executions_this_run={metrics.executions_this_run} "
              f"proxy_dollars_this_run=${metrics.proxy_dollars_this_run:.4f}")
        _emit_run_finished(log, proj, run_id, "COMPLETED")
    except (OrchestratorHalt, ReviewerError) as e:
        print(f"[halt] run stopped abnormally: {e}", file=sys.stderr)
        exit_code = 2
        _emit_run_finished(log, proj, run_id, "HALTED")
    except KeyboardInterrupt:
        print("\n[stop] interrupted — current step finished; recovery owns the rest")
        _emit_run_finished(log, proj, run_id, "INTERRUPTED")
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
    s.add_argument("--issues-digest", default=None,
                   help="SHA-256 (64 lowercase hex) of the issue file presented during "
                        "planning; required with --issue/--all-issues (ADR-30)")
    sel = s.add_mutually_exclusive_group()
    sel.add_argument("--issue", action="append", dest="issue_ids", default=None,
                     help="exact issue id to run; repeatable (ADR-30)")
    sel.add_argument("--all-issues", action="store_true",
                     help="run every current non-terminal configured issue (ADR-30)")
    s.set_defaults(fn=cmd_run)
    s = sub.add_parser("observe")
    observe_sub = s.add_subparsers(dest="observe_cmd", required=True)
    ev = observe_sub.add_parser("events")
    ev.add_argument("--log", required=True)
    ev.add_argument("--after", default=None)
    ev.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ev.add_argument("--format", required=True, choices=["json"])
    ev.set_defaults(fn=cmd_observe_events)
    st = observe_sub.add_parser("status")
    st.add_argument("--log", required=True)
    st.add_argument("--format", required=True, choices=["json"])
    st.set_defaults(fn=cmd_observe_status)
    s = sub.add_parser("init")
    s.add_argument("repo_path")
    s.add_argument("--branch", default="agent-work")
    s.add_argument("--yes", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument("--no-validation", action="store_true")
    s.add_argument("--yes-no-validation", action="store_true")
    s.add_argument("--config-out", default=None)
    s.set_defaults(fn=cmd_init)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
