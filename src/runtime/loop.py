"""The orchestrator loop (doc 09 §8.2, wired to doc 03 §5's transition table).

ONE deterministic step per call, keyed on the replayed projection exactly like
``tests/crash/worker.py::step`` — that shape IS crash-safe resume: a restart
re-derives the same next move from the log. The orchestrator owns ALL git
contact (through the RepositoryAdapter) and ALL event emission; the engine emits
nothing and returns an advisory ``EngineResult`` whose only load-bearing fields
are ``timed_out``/``exit_status``/``num_turns`` — and those may ONLY select
which doc 03 §5 row fires, never whether the work "worked" (ADR-02/07).

Event ordering law (I5/I6): intent events are appended+fsync'd BEFORE their
action, fact events after. ``ExecutionSpawned`` (intent) is emitted in the spawn
step; the engine actually runs in the following EXECUTING step, so a crash
between them leaves an orphan that reconciler check 1 crashes. ``CommitIntent``
(intent) is emitted before the merge in the ACCEPTED sequence.

Two failures HALT the run rather than emit a verdict (doc 03 §2): a reviewer
transport/unavailability failure (execution parks in REVIEWING; recovery re-calls) and an
I3 pin-gate break (log/world tamper — fabricating a reject would violate the
honesty rule and doc 03 has no reject edge from ACCEPTED). A budget hard stop
ends the run cleanly. A reviewer parse failure receives its provider's bounded
parse retry; exhaustion escalates through IssueEscalated without fabricating a
reviewer verdict.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from .budget.manager import BudgetManager
from .config import Config
from .context.pack import build_prompt, prompt_hash
from .events.log import EventLog
from .events.projections import ExecutionView, StateProjection
from .events.schema import Event, EventType
from .engine.claude_headless import ClaudeHeadlessEngine
from .engine.claude_headless import ContainmentExecutionContext, EngineContainmentError
from .repo.adapter import RepositoryAdapter
from .reviewer.base import ReviewPack, ReviewParseError, ReviewerProvider
from .state.model import ExecutionState, IssueState
from .validation.runner import Validator
from .workspace_lease import current_process_identity, workspace_key

_TERMINAL_ISSUE = (
    IssueState.DONE, IssueState.NEEDS_HUMAN, IssueState.NEEDS_DECOMPOSITION,
)
_RETRYABLE_EXEC = (ExecutionState.REJECTED, ExecutionState.CRASHED)


class OrchestratorHalt(RuntimeError):
    """A condition the loop must not guess through (pin-gate tamper). Halts the
    run; the next startup replays and either heals or re-halts."""


class _BudgetExhausted(RuntimeError):
    """Internal control signal: a run-level hard stop was hit at a spawn."""


class Orchestrator:
    def __init__(
        self,
        *,
        cfg: Config,
        log: EventLog,
        proj: StateProjection,
        adapter: RepositoryAdapter,
        engine: ClaudeHeadlessEngine,
        validator: Validator,
        reviewer: ReviewerProvider,
        budget: BudgetManager,
        artifacts_dir: Path,
        run_id: str,
        allowed_issue_ids: "frozenset[str] | None" = None,
        selection_order: "tuple[str, ...] | None" = None,
        selection_dependencies: "dict[str, tuple[str, ...]] | None" = None,
    ) -> None:
        self.cfg = cfg
        self.log = log
        self.proj = proj
        self.adapter = adapter
        self.engine = engine
        self.validator = validator
        self.reviewer = reviewer
        self.budget = budget
        self.artifacts_dir = Path(artifacts_dir)
        self.run_id = run_id
        self.target = cfg.project.branch
        self.workspace = Path(cfg.project.repository)
        self.stop_reason = ""
        # ADR-30: None (the default, and every pre-existing direct-CLI call
        # site) preserves the original unfiltered scan exactly. When set, it
        # is an exact allowlist -- an issue outside it is never returned by
        # _next_actionable regardless of its state, so it can never be
        # activated, spawned, or otherwise touched by this run.
        self.allowed_issue_ids = allowed_issue_ids
        # ADR-30 review finding 2: when both are supplied (only
        # runtime.main's ADR-30 selection path does), these carry the
        # validated topological order and a current-configured-file
        # dependency map through from re-validation, so historical
        # IssueCreated order/depends_on can never override a freshly
        # validated selection or run-all batch. When either is None (every
        # pre-existing direct-CLI call site, and any allowed_issue_ids-only
        # construction), _next_actionable falls back to the original
        # unfiltered-except-for-allowlist scan using proj.issues' own
        # ingest order and event-sourced deps_met -- byte-identical to
        # this ADR's original behavior.
        self.selection_order = selection_order
        self.selection_dependencies = selection_dependencies

    # ── durable emit (reconciler._emit pattern: append+fsync, then apply) ──
    def _emit(self, ev: Event) -> None:
        eid = self.log.append(ev)  # flush+fsync before returning (I6)
        self.proj.apply(Event(
            type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
            execution_id=ev.execution_id, run_id=ev.run_id, ts=ev.ts, event_id=eid,
        ))

    def _event(self, etype: EventType, issue: str, payload: dict,
               execution_id: str | None = None) -> Event:
        return Event(type=etype, issue_id=issue, execution_id=execution_id,
                     run_id=self.run_id, payload=payload)

    # ── the run loop ──────────────────────────────────────────────────
    def run(self) -> str:
        """Drive the queue to quiescence. Returns the stop reason. Reviewer /
        tamper halts propagate as exceptions (the run stopped abnormally)."""
        while True:
            issue = self._next_actionable()
            if issue is None:
                self.stop_reason = "queue drained — no actionable issue"
                return self.stop_reason
            try:
                self.step(issue)
            except _BudgetExhausted as e:
                self.stop_reason = f"budget hard stop: {e}"
                return self.stop_reason

    def _next_actionable(self) -> str | None:
        """First issue in ingest order that has a legal next move: an ACTIVE
        issue (in flight — finish it before starting another, sequential per
        doc 01), or a PENDING issue whose deps are all DONE.

        When a validated selection order is present, delegates to
        `_next_actionable_selected` instead (ADR-30 review finding 2)."""
        if self.allowed_issue_ids is not None and self.selection_order is not None:
            return self._next_actionable_selected()
        for iid in self.proj.issues:  # dict preserves IssueCreated (file) order
            if self.allowed_issue_ids is not None and iid not in self.allowed_issue_ids:
                continue
            st = self.proj.issues[iid]
            if st is IssueState.ACTIVE:
                return iid
            if st is IssueState.PENDING and self.proj.deps_met(iid):
                return iid
        return None

    def _next_actionable_selected(self) -> str | None:
        """ADR-30 review finding 2: activation order and the dependency gate
        come from the freshly-validated plan (current configured-file order
        and dependencies), never `proj.issues`' historical ingest order or
        `deps_met`'s event-sourced `depends_on` -- so a dependency added, or
        the running order changed, in the file after ingestion is honored
        exactly, and a dependent is never activated ahead of a current
        dependency that has not reached DONE (including one that has
        already terminated some other way, e.g. NEEDS_HUMAN). An
        already-ACTIVE selected issue always resumes first, regardless of
        its own position in the validated order (sequential recovery
        safety) -- at most one issue is ever ACTIVE at a time in this
        engine, so a plain membership scan suffices."""
        for iid in self.proj.issues:
            if iid in self.allowed_issue_ids and self.proj.issues[iid] is IssueState.ACTIVE:
                return iid
        deps = self.selection_dependencies or {}
        for iid in self.selection_order:
            if self.proj.issues.get(iid) is not IssueState.PENDING:
                continue
            if all(self.proj.issues.get(dep) is IssueState.DONE for dep in deps.get(iid, ())):
                return iid
        return None

    # ── one deterministic step ────────────────────────────────────────
    def step(self, issue: str) -> None:
        st = self.proj.issues.get(issue)
        if st is IssueState.PENDING:
            return self._activate(issue)
        if st is not IssueState.ACTIVE:
            raise OrchestratorHalt(f"step() called on non-actionable issue {issue} ({st})")

        ex = self.proj.latest_execution(issue)
        # ex is None here heals the activate→spawn crash gap: a kill after
        # IssueActivated (durable) but before ExecutionSpawned leaves the issue
        # ACTIVE with zero executions, and this guard re-spawns e1 on restart
        # (spawn_reason "initial"). base_commit stays pinned — IssueActivated
        # runs once per issue (doc 03 §1 PENDING→ACTIVE, "Yes (replay)").
        if ex is None or ex.state in _RETRYABLE_EXEC:
            return self._spawn_or_escalate(issue, ex)
        if ex.state is ExecutionState.EXECUTING:
            return self._execute(issue, ex)
        if ex.state is ExecutionState.VALIDATING:
            return self._validate(issue, ex)
        if ex.state is ExecutionState.REVIEWING:
            return self._review(issue, ex)
        if ex.state is ExecutionState.ACCEPTED:
            return self._commit_sequence(issue, ex)
        raise OrchestratorHalt(f"no move for {issue} / {ex.execution_id} ({ex.state})")

    # ── row: idle → activate ──────────────────────────────────────────
    def _activate(self, issue: str) -> None:
        base = self.adapter.head_of(self.target)
        if base is None:
            raise OrchestratorHalt(f"target branch {self.target!r} has no head")
        self._emit(self._event(EventType.ISSUE_ACTIVATED, issue,
                               {"base_commit": base}))

    # ── row: spawn (with retry/escalate guard) ────────────────────────
    def _spawn_or_escalate(self, issue: str, prev: ExecutionView | None) -> None:
        attempts = self.proj.attempts(issue)
        if attempts >= self.cfg.budget.max_attempts_per_issue:
            return self._escalate(issue, "cap-hit", "needs-human")
        if _has_duplicate_feedback(self.proj.reviewer_feedback_categories(issue)):
            return self._escalate(issue, "duplicate-feedback", "needs-human")

        decision = self.budget.check()
        if not decision.allowed:
            raise _BudgetExhausted(decision.reason)

        xid = f"{issue}-e{attempts + 1}"
        prompt = build_prompt(self.proj, issue, self.cfg.project.validation.commands)
        prompt_file = self.artifacts_dir / xid / "prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt, encoding="utf-8")

        payload = {
            "parent_execution_id": prev.execution_id if prev else None,
            "spawn_reason": "initial" if prev is None else "retry",
            "engine": self.cfg.engine.provider,
            "prompt_hash": prompt_hash(prompt),
            "budget": {"wall_seconds": self.cfg.engine.timeout_seconds,
                       "max_turns": self.cfg.engine.max_turns},
            "pid": os.getpid(),  # I-h: must equal this execution's Finished pid
            # Untracked-file ownership baseline (resolve-item, 2026-08-18):
            # captured now, before the engine can touch anything, and
            # fsync'd with this intent event (I6) -- reconciler check 3
            # uses it to tell "this execution's own residue" apart from a
            # target repo's own pre-existing untracked files.
            "pre_execution_untracked": sorted(self.adapter.untracked_paths()),
        }
        # intent, fsync'd BEFORE any spawn side effect (the engine runs next step)
        self._emit(self._event(EventType.EXECUTION_SPAWNED, issue, payload,
                               execution_id=xid))
        self.budget.note_execution_started()

    def _escalate(self, issue: str, reason: str, taxonomy: str) -> None:
        evidence = sorted(self.adapter.list_attempt_refs(issue).keys())
        payload = {"reason": reason, "taxonomy_category": taxonomy,
                   "evidence_refs": evidence}
        self._emit(self._event(EventType.ISSUE_ESCALATED, issue, payload))

    # ── row: EXECUTING (do the work, then route the finish) ───────────
    def _execute(self, issue: str, ex: ExecutionView) -> None:
        base = ex.base_commit or self.proj.issue_base_commit.get(issue)
        if base is None:
            raise OrchestratorHalt(f"execution {ex.execution_id} has no base commit")
        # clean base on a per-issue branch (doc 02 §3). checkout -B force-resets
        # the branch tip to base; the worktree is clean here because the prior
        # reject/complete step ended clean.
        self.adapter.checkout_branch(f"issue/{issue}", create_from=base)

        prompt_file = self.artifacts_dir / ex.execution_id / "prompt.md"
        if not prompt_file.exists():  # crash between spawn and here — rebuild (pure)
            prompt = build_prompt(self.proj, issue, self.cfg.project.validation.commands)
            prompt_file.parent.mkdir(parents=True, exist_ok=True)
            prompt_file.write_text(prompt, encoding="utf-8")

        containment = None
        if os.name == "nt":
            containment = ContainmentExecutionContext(
                issue_id=issue,
                workspace_key=workspace_key(self.workspace),
                containment_generation="g1",
                controller=current_process_identity(),
                lease={"scope": "Global", "version": "v1"},
                append_event=self._emit,
            )
        try:
            result = self.engine.run(ex.execution_id, prompt_file, self.workspace,
                                     containment=containment)
        except EngineContainmentError as exc:
            # The containment facts are already durable (or the engine refused
            # before launch); no snapshot/reset/retry may follow this path.
            raise OrchestratorHalt(f"execution containment unresolved: {exc}") from exc

        # residue → attempt ref BEFORE the fact event (I-i: end_commit == ref)
        end = self.adapter.snapshot_commit(f"work {ex.execution_id}") \
            or self.adapter.current_commit()
        self.adapter.set_attempt_ref(issue, ex.execution_id, end)
        self.budget.record_usage(ex.execution_id, result.usage)

        common = {
            "start_commit": base, "end_commit": end,
            "exit_status": result.exit_status,
            "num_turns": result.num_turns,
            "usage": result.usage, "duration_s": result.duration_s,
            "transcript_path": str(result.transcript_path),
            "pid": os.getpid(),
        }
        # advisory routing (ADR-07): only timed_out / num_turns / exit_status,
        # and only to pick which frozen-vocabulary row fires.
        if result.timed_out:
            self._finish_rejected(issue, ex, common, "timeout", base)
        elif (result.num_turns is not None
              and result.num_turns >= self.cfg.engine.max_turns):
            # turn-budget → execution REJECTED, then issue NEEDS_DECOMPOSITION
            self._emit(self._event(EventType.EXECUTION_FINISHED, issue,
                                   {**common, "outcome": "REJECTED",
                                    "taxonomy_category": "needs-decomposition"},
                                   execution_id=ex.execution_id))
            self._emit(self._event(EventType.ISSUE_ESCALATED, issue,
                                   {"reason": "decompose",
                                    "taxonomy_category": "needs-decomposition",
                                    "evidence_refs": sorted(
                                        self.adapter.list_attempt_refs(issue).keys())}))
            self.adapter.reset_hard(base)
        elif result.exit_status != 0:
            self._finish_rejected(issue, ex, common, "crashed", base)
        else:
            # normal exit → VALIDATING (no outcome key)
            self._emit(self._event(EventType.EXECUTION_FINISHED, issue, common,
                                   execution_id=ex.execution_id))

    def _finish_rejected(self, issue: str, ex: ExecutionView, common: dict,
                         taxonomy: str, base: str) -> None:
        self._emit(self._event(
            EventType.EXECUTION_FINISHED, issue,
            {**common, "outcome": "REJECTED", "taxonomy_category": taxonomy},
            execution_id=ex.execution_id))
        self.adapter.reset_hard(base)  # residue already on the attempt ref

    # ── row: VALIDATING ───────────────────────────────────────────────
    def _new_test_commands(self, ex: ExecutionView) -> list[str]:
        """Gap-2 hook (doc 08 Amendment, Session 35): child-authored new test
        files, turned into their OWN explicit single-file commands (ADR-23
        rule 2 preserved -- never a bare glob/dir handed to pytest). Inert
        (returns []) unless config.project.validation.new_test_pattern AND
        new_test_command_prefix are BOTH set -- existing configs are
        unaffected until they opt in."""
        vcfg = self.cfg.project.validation
        if not vcfg.new_test_pattern or not vcfg.new_test_command_prefix:
            return []
        added = self.adapter.added_files(ex.base_commit, ex.end_commit)
        matched = [p for p in added if fnmatch.fnmatch(p, vcfg.new_test_pattern)]
        return [f"{vcfg.new_test_command_prefix} {p}" for p in matched]

    def _validate(self, issue: str, ex: ExecutionView) -> None:
        extra = self._new_test_commands(ex)
        result = self.validator.validate(self.workspace, ex.end_commit, ex.execution_id,
                                          extra_commands=extra)
        if result.passed:
            self._emit(self._event(EventType.VALIDATION_PASSED, issue,
                                   {"validated_commit": ex.end_commit,
                                    "gate_results": result.gate_results(),
                                    "flake_retries": result.flake_retries},
                                   execution_id=ex.execution_id))
            return
        self._emit(self._event(EventType.VALIDATION_FAILED, issue,
                               {"validated_commit": ex.end_commit,
                                "gate_results": result.gate_results(),
                                "flake_retries": result.flake_retries,
                                "taxonomy_category": result.taxonomy_category},
                               execution_id=ex.execution_id))
        self.adapter.reset_hard(ex.base_commit)

    # ── row: REVIEWING (transport halts; exhausted parse retry escalates) ──────
    def _review(self, issue: str, ex: ExecutionView) -> None:
        diff = self.adapter.diff(ex.base_commit, ex.end_commit)
        meta = self.proj.issue_meta.get(issue, {})
        pack = ReviewPack(
            execution_id=ex.execution_id, reviewed_commit=ex.end_commit,
            issue_text=f"{meta.get('title', '')}\n\n{meta.get('body', '')}".strip(),
            diff=diff,
        )
        try:
            verdict = self.reviewer.review(pack)
        except ReviewParseError as error:
            # The provider already performed its one bounded parse retry.
            # This is not model feedback, so never forge ReviewRejected.
            self._emit(self._event(EventType.ISSUE_ESCALATED, issue,
                                   {"reason": "reviewer-protocol-violation",
                                    "taxonomy_category": "needs-human",
                                    "evidence_refs": [f"review-parse-error:{type(error).__name__}"]},
                                   execution_id=ex.execution_id))
            return
        if verdict.approved:
            self._emit(self._event(EventType.REVIEW_APPROVED, issue,
                                   {"reviewed_commit": ex.end_commit,
                                    "reviewer_provider": verdict.provider,
                                    "verdict": "APPROVE"},
                                   execution_id=ex.execution_id))
            return
        self._emit(self._event(EventType.REVIEW_REJECTED, issue,
                               {"reviewed_commit": ex.end_commit,
                                "reviewer_provider": verdict.provider,
                                "verdict": "REJECT", "severity": verdict.severity,
                                "taxonomy_category": _review_taxonomy(verdict.feedback),
                                "feedback": verdict.feedback},
                               execution_id=ex.execution_id))
        self.adapter.reset_hard(ex.base_commit)

    # ── row: ACCEPTED (pin gate → intent → merge → complete → GC) ─────
    def _commit_sequence(self, issue: str, ex: ExecutionView) -> None:
        if not ex.commit_intended:
            # I3 pin gate: end == validated == reviewed, and the tree exists.
            if not (ex.end_commit and ex.end_commit == ex.validated_commit
                    == ex.reviewed_commit and self.adapter.commit_exists(ex.end_commit)):
                raise OrchestratorHalt(
                    f"I3 pin broken for {ex.execution_id}: end={ex.end_commit} "
                    f"validated={ex.validated_commit} reviewed={ex.reviewed_commit} "
                    f"— refusing to commit an unvalidated/unreviewed tree")
            self._emit(self._event(EventType.COMMIT_INTENT, issue,
                                   {"end_commit": ex.end_commit,
                                    "target_branch": self.target},
                                   execution_id=ex.execution_id))
            return
        if not ex.commit_created:
            end = ex.intent_end_commit or ex.end_commit
            if self.adapter.is_ancestor(end, self.target):
                mc = self.adapter.find_merge_commit(self.target, end)
                if mc is None:
                    raise OrchestratorHalt(
                        f"{end[:12]} is on {self.target} but no merge commit "
                        f"witnesses it — refusing to forge merge_commit")
                backfilled = True
            else:
                mc = self.adapter.merge_to(self.target, end, f"merge {issue}")
                backfilled = False
            self._emit(self._event(EventType.COMMIT_CREATED, issue,
                                   {"merge_commit": mc, "target_branch": self.target,
                                    "backfilled": backfilled},
                                   execution_id=ex.execution_id))
            return
        # both done → close the issue, then GC this execution's own attempt
        # ref (ADR-15 Amendment 1: scoped to the completing execution, not
        # the whole issue — its content is already reachable via the merge
        # above; a crashed sibling's residue ref must survive this GC)
        self._emit(self._event(EventType.ISSUE_COMPLETED, issue,
                               {"reason": "accepted",
                                "evidence_refs": [ex.end_commit]}))
        self.adapter.delete_attempt_ref(issue, ex.execution_id)  # idempotent


def _has_duplicate_feedback(categories: list[str]) -> bool:
    return len(categories) != len(set(categories))


def _review_taxonomy(feedback: list[dict]) -> str:
    """The rejection's taxonomy is the first reviewer feedback category (doc 02
    §6 review-*). Falls back to review-correctness if somehow absent (a valid
    REJECT always carries feedback, enforced by the reviewer parse contract)."""
    for fb in feedback:
        if isinstance(fb, dict) and fb.get("category"):
            return fb["category"]
    return "review-correctness"
