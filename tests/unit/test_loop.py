"""Orchestrator loop dispatcher tests (doc 03 §5 rows) against in-memory fakes —
no real git, no `claude`, no Ollama. The fake adapter simulates just enough git
(monotonic commits, branches, attempt refs, object-DB merges) for the loop to
drive an issue through EXECUTING → VALIDATING → REVIEWING → ACCEPTED → committed,
and through every rejection/escalation branch.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.budget.manager import BudgetManager                     # noqa: E402
from runtime.config import Config                                    # noqa: E402
from runtime.engine.claude_headless import EngineResult             # noqa: E402
from runtime.events.log import EventLog                              # noqa: E402
from runtime.events.projections import StateProjection              # noqa: E402
from runtime.events.schema import Event, EventType                  # noqa: E402
from runtime.loop import Orchestrator, OrchestratorHalt             # noqa: E402
from runtime.reviewer.base import (                                  # noqa: E402
    ReviewerUnavailableError, ReviewVerdict,
)
from runtime.state.model import ExecutionState, IssueState          # noqa: E402


# ── fakes ────────────────────────────────────────────────────────────
class FakeAdapter:
    def __init__(self, base="c0"):
        self._c = itertools.count(1)
        self._head = base
        self._branches = {"agent-work": base}
        self._commits = {base}
        self._refs: dict[str, str] = {}
        self._merged: dict[str, str] = {}
        self._added_files: dict[tuple, list] = {}

    def _new(self, tag="c"):
        sha = f"{tag}{next(self._c)}"
        self._commits.add(sha)
        return sha

    def head_of(self, branch): return self._branches.get(branch)
    def current_commit(self): return self._head

    def checkout_branch(self, branch, *, create_from=None):
        self._head = create_from if create_from is not None else self._branches.get(branch, self._head)
        self._branches[branch] = self._head

    def snapshot_commit(self, message):
        sha = self._new("w")  # every execution "dirties" the tree → a real commit
        self._head = sha
        return sha

    def set_attempt_ref(self, issue, xid, commit):
        ref = f"refs/attempts/{issue}/{xid}"
        self._refs[ref] = commit
        return ref

    def reset_hard(self, commit): self._head = commit
    def diff(self, base, head): return f"diff {base}..{head}\n"
    def added_files(self, base, head): return self._added_files.get((base, head), [])
    def commit_exists(self, sha): return sha in self._commits
    def is_ancestor(self, a, target): return a in self._merged
    def find_merge_commit(self, target, end): return self._merged.get(end)

    def merge_to(self, target, end, message):
        mc = self._new("m")
        self._branches[target] = mc
        self._merged[end] = mc
        return mc

    def list_attempt_refs(self, issue=None):
        if issue is None:
            return dict(self._refs)
        return {r: s for r, s in self._refs.items() if f"/{issue}/" in r}

    def delete_attempt_ref(self, issue, xid):
        ref = f"refs/attempts/{issue}/{xid}"
        return self._refs.pop(ref, None) is not None


class FakeEngine:
    def __init__(self, result_fn=None, artifacts_dir="."):
        self.result_fn = result_fn or (lambda xid: _ok_result())
        self.artifacts_dir = Path(artifacts_dir)

    def run(self, xid, prompt_file, workspace):
        return self.result_fn(xid)


class FakeValidator:
    def __init__(self, passed_fn=None):
        self.passed_fn = passed_fn or (lambda xid: True)

    def validate(self, workspace, validated_commit, execution_id, extra_commands=None):
        from runtime.validation.runner import ValidationResult
        ok = self.passed_fn(execution_id)
        return ValidationResult(
            passed=ok, validated_commit=validated_commit,
            per_command=[{"name": "test", "passed": ok, "duration_s": 0.0,
                          "log_path": "x"}],
            taxonomy_category=None if ok else "validation-test",
        )


class FakeReviewer:
    name = "fake"

    def __init__(self, verdict_fn=None):
        self.verdict_fn = verdict_fn or (lambda pack: _approve(pack))

    def review(self, pack):
        return self.verdict_fn(pack)


def _ok_result(num_turns=2, timed_out=False, exit_status=0):
    return EngineResult(
        exit_status=exit_status, timed_out=timed_out, duration_s=1.0,
        usage={"dollars": 0.01}, num_turns=num_turns,
        transcript_path=Path("t.jsonl"), stderr_tail="",
    )


def _approve(pack):
    return ReviewVerdict(execution_id=pack.execution_id,
                         reviewed_commit=pack.reviewed_commit,
                         provider="fake", verdict="APPROVE")


def _reject(pack, category):
    return ReviewVerdict(execution_id=pack.execution_id,
                         reviewed_commit=pack.reviewed_commit,
                         provider="fake", verdict="REJECT",
                         feedback=[{"category": category, "message": "no"}])


# ── harness builder ──────────────────────────────────────────────────
def _config(max_attempts=3):
    return Config.model_validate({
        "project": {"name": "T", "repository": ".", "branch": "agent-work",
                    "validation": {"commands": ["exit 0"]}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription"},
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": "http://x", "model": "q"}},
        "budget": {"max_attempts_per_issue": max_attempts,
                   "max_executions_per_run": 50,
                   "hard_stop_proxy_cost_per_run_usd": 100.0},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })


def _build(tmp_path, *, issues, engine=None, validator=None, reviewer=None,
           max_attempts=3, budget=None):
    cfg = _config(max_attempts)
    log = EventLog(tmp_path / "events.jsonl")
    proj = StateProjection()
    for iid, deps in issues:
        ev = Event(EventType.ISSUE_CREATED, issue_id=iid,
                   payload={"title": f"Issue {iid}", "body": "b", "depends_on": deps})
        eid = log.append(ev)
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                         event_id=eid))
    orch = Orchestrator(
        cfg=cfg, log=log, proj=proj, adapter=FakeAdapter(),
        engine=engine or FakeEngine(artifacts_dir=tmp_path / "art"),
        validator=validator or FakeValidator(),
        reviewer=reviewer or FakeReviewer(),
        budget=budget or BudgetManager(50, 100.0),
        artifacts_dir=tmp_path / "art", run_id="run-test",
    )
    return orch


# ── scenarios ────────────────────────────────────────────────────────
def test_happy_path_ships_one_issue(tmp_path):
    orch = _build(tmp_path, issues=[("001", [])])
    orch.run()
    assert orch.proj.issues["001"] is IssueState.DONE
    assert orch.proj.counts.get("CommitCreated") == 1        # I-d: no double commit
    ex = orch.proj.latest_execution("001")
    assert ex.state is ExecutionState.ACCEPTED and ex.commit_created
    assert orch.proj.attempts("001") == 1                    # attempt-1 success


def test_validation_fail_then_retry_succeeds(tmp_path):
    passed = {"001-e1": False, "001-e2": True}
    orch = _build(tmp_path, issues=[("001", [])],
                  validator=FakeValidator(lambda xid: passed.get(xid, True)))
    orch.run()
    assert orch.proj.issues["001"] is IssueState.DONE
    assert orch.proj.attempts("001") == 2
    assert orch.proj.counts.get("ValidationFailed") == 1
    assert orch.proj.counts.get("CommitCreated") == 1


def test_review_reject_then_retry_succeeds(tmp_path):
    def verdict(pack):
        return _reject(pack, "review-correctness") if pack.execution_id == "001-e1" \
            else _approve(pack)
    orch = _build(tmp_path, issues=[("001", [])], reviewer=FakeReviewer(verdict))
    orch.run()
    assert orch.proj.issues["001"] is IssueState.DONE
    assert orch.proj.attempts("001") == 2
    assert orch.proj.counts.get("ReviewRejected") == 1


def test_duplicate_feedback_escalates_needs_human(tmp_path):
    # same reviewer category twice → the loop cannot converge → escalate
    orch = _build(tmp_path, issues=[("001", [])],
                  reviewer=FakeReviewer(lambda p: _reject(p, "review-correctness")))
    orch.run()
    assert orch.proj.issues["001"] is IssueState.NEEDS_HUMAN
    esc = _last_payload(orch, EventType.ISSUE_ESCALATED)
    assert esc["reason"] == "duplicate-feedback"


def test_cap_hit_escalates_needs_human(tmp_path):
    # distinct categories each time so dedupe never fires; cap=2 ends it
    cats = itertools.count()
    orch = _build(tmp_path, issues=[("001", [])], max_attempts=2,
                  reviewer=FakeReviewer(lambda p: _reject(p, f"review-c{next(cats)}")))
    orch.run()
    assert orch.proj.issues["001"] is IssueState.NEEDS_HUMAN
    assert orch.proj.attempts("001") == 2
    esc = _last_payload(orch, EventType.ISSUE_ESCALATED)
    assert esc["reason"] == "cap-hit"


def test_turn_budget_escalates_needs_decomposition(tmp_path):
    orch = _build(tmp_path, issues=[("001", [])],
                  engine=FakeEngine(lambda xid: _ok_result(num_turns=999),
                                    artifacts_dir=tmp_path / "art"))
    orch.run()
    assert orch.proj.issues["001"] is IssueState.NEEDS_DECOMPOSITION
    ex = orch.proj.latest_execution("001")
    assert ex.state is ExecutionState.REJECTED
    assert ex.taxonomy_category == "needs-decomposition"


def test_timeout_rejects_and_retries(tmp_path):
    seen = {"n": 0}

    def eng(xid):
        seen["n"] += 1
        return _ok_result(timed_out=True) if xid == "001-e1" else _ok_result()
    orch = _build(tmp_path, issues=[("001", [])],
                  engine=FakeEngine(eng, artifacts_dir=tmp_path / "art"))
    orch.run()
    # e1 timed out (REJECTED/timeout), e2 shipped
    assert orch.proj.issues["001"] is IssueState.DONE
    assert orch.proj.executions["001-e1"].taxonomy_category == "timeout"
    assert orch.proj.attempts("001") == 2


def test_budget_hard_stop_ends_run(tmp_path):
    orch = _build(tmp_path, issues=[("001", [])], budget=BudgetManager(0, 100.0))
    reason = orch.run()
    assert "budget" in reason.lower()
    assert orch.proj.issues["001"] is IssueState.ACTIVE       # activated, never spawned
    assert orch.proj.latest_execution("001") is None


def test_reviewer_unavailable_halts_without_verdict(tmp_path):
    def boom(pack):
        raise ReviewerUnavailableError("ollama down")
    orch = _build(tmp_path, issues=[("001", [])], reviewer=FakeReviewer(boom))
    with pytest.raises(ReviewerUnavailableError):
        orch.run()
    # execution parked in REVIEWING; NO review verdict event emitted
    assert orch.proj.latest_execution("001").state is ExecutionState.REVIEWING
    assert orch.proj.counts.get("ReviewApproved") is None
    assert orch.proj.counts.get("ReviewRejected") is None


def test_pin_gate_break_halts(tmp_path):
    """A tampered ACCEPTED view (validated != end) must halt, never commit."""
    orch = _build(tmp_path, issues=[("001", [])])
    # hand-build an ACCEPTED execution whose pin is inconsistent
    from runtime.events.projections import ExecutionView
    orch.proj.issues["001"] = IssueState.ACTIVE
    orch.proj.executions["001-e1"] = ExecutionView(
        "001-e1", "001", ExecutionState.ACCEPTED, end_commit="w1",
        validated_commit="w1", reviewed_commit="DIFFERENT", base_commit="c0")
    orch.proj.issue_executions["001"] = ["001-e1"]
    with pytest.raises(OrchestratorHalt):
        orch.step("001")


def test_dependency_gates_activation(tmp_path):
    """002 depends on 001; the loop ships 001 first, then 002 — never activates
    002 while its dep is unmet."""
    orch = _build(tmp_path, issues=[("001", []), ("002", ["001"])])
    orch.run()
    assert orch.proj.issues["001"] is IssueState.DONE
    assert orch.proj.issues["002"] is IssueState.DONE
    assert orch.proj.counts.get("CommitCreated") == 2


def _last_payload(orch, etype):
    last = None
    for ev in orch.log.replay():
        if ev.type is etype:
            last = ev.payload
    return last
