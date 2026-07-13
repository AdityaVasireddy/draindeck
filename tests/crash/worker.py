"""Stub workload for the kill-9 harness — GIT-WORLD edition (docs/11 §3).

Drives the REAL log, projection, transition tables, recovery, AND a REAL
temp git repository through doc 03 §5's happy path. The filesystem "world"
of the previous version is gone; every world effect is now a git operation
through GitCliAdapter, and recovery runs the production seam bindings
(bind_reconciler) — checks 2 and 3 are no longer SKIPPED.

Per-execution git lifecycle (on the persistent ``work`` branch):
  engine  → reset_hard(base); edit issues/<issue>.txt + an untracked
            scratch file; snapshot_commit → end_commit; set_attempt_ref
  commit  → merge_to(trunk, end_commit)  (object-DB merge, §1.3)

The dispatcher is a pure function of the replayed projection — that IS
deterministic resume. Recovery (check 1) crashes orphaned executions,
never resumes them; check 2 backfills an unwitnessed merge; check 3
archives+resets a dirty workspace. The retry policy spawns fresh.

pid discipline (I-h) is unchanged: Spawned/Finished record os.getpid().

Crash injection: RUNTIME_CRASH_POINT=<name>[:<nth>] self-terminates at the
nth hit. Points are worker-level (after_append:*, engine:*) and adapter-
internal (git:* via HarnessAdapter._checkpoint).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _hard_kill_self() -> None:
    """Terminate THIS process uncatchably (SIGKILL / TerminateProcess)."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.c_void_p(-1), ctypes.c_uint(137)
        )
    else:
        import signal
        os.kill(os.getpid(), signal.SIGKILL)

from runtime.events.log import EventLog                       # noqa: E402
from runtime.events.projections import StateProjection        # noqa: E402
from runtime.events.schema import Event, EventType            # noqa: E402
from runtime.recovery.bindings import bind_reconciler         # noqa: E402
from runtime.recovery.reconciler import recover               # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter            # noqa: E402
from runtime.state.model import ExecutionState, IssueState    # noqa: E402

ISSUES = ["042", "043", "044", "045"]
CAP = 8            # generous: injected crashes may burn several attempts
# Per-issue cap override (Session 6): 045 is capped at 2 so that two scripted
# validation failures exhaust it and the spawn guard escalates it to
# NEEDS_HUMAN — the deterministic source of the after_append:IssueEscalated
# crash window. Default stays CAP for every other issue.
CAP_BY_ISSUE = {"045": 2}
RUN_ID = "run-harness"
TRUNK = "trunk"    # deliberately not 'main' — proves nothing hardcodes it
WORK = "work"

# Scripted deterministic rejections (Session 5): the reject path must be
# crash-durable too. 043 fails VALIDATION on attempt 1, 044 fails REVIEW on
# attempt 1; each passes on attempt 2, so those issues still reach DONE (I-c
# holds) while exercising the after_append:ValidationFailed /
# after_append:ReviewRejected crash windows and check 3's post-reject reset.
# Session 6: 045 fails VALIDATION on attempts 1 AND 2 → capped at 2 → escalates
# to NEEDS_HUMAN (never DONE, never committed). Values are sets of attempt nos.
VAL_FAIL = {"043": frozenset({1}), "045": frozenset({1, 2})}
REV_REJECT = {"044": 1}


def _cap(issue: str) -> int:
    return CAP_BY_ISSUE.get(issue, CAP)


# The terminal state each issue is scripted to reach. 042/043/044 ship (DONE);
# 045 is capped-out and escalates (NEEDS_HUMAN). "Complete" = every issue at its
# expected terminal, NOT every issue DONE — a run that leaves 045 escalated is a
# clean exit (0), not an error, so restart_until_done accepts it.
EXPECTED_TERMINAL = {
    "042": IssueState.DONE,
    "043": IssueState.DONE,
    "044": IssueState.DONE,
    "045": IssueState.NEEDS_HUMAN,
}
_TERMINAL_STATES = (
    IssueState.DONE, IssueState.NEEDS_HUMAN, IssueState.NEEDS_DECOMPOSITION,
)


def _attempt_no(execution_id: str) -> int:
    return int(execution_id.rsplit("-e", 1)[1])

# ── crash injection ──────────────────────────────────────────────
_spec = os.environ.get("RUNTIME_CRASH_POINT", "")
_CRASH_POINT, _CRASH_NTH = _spec, 1
if ":" in _spec:
    head, tail = _spec.rsplit(":", 1)
    if tail.isdigit():  # point names contain ':', parse nth from the right
        _CRASH_POINT, _CRASH_NTH = head, int(tail)
_hits = 0


def crash_point(name: str) -> None:
    global _hits
    if _CRASH_POINT and name == _CRASH_POINT:
        _hits += 1
        if _hits >= _CRASH_NTH:
            _hard_kill_self()


class HarnessAdapter(GitCliAdapter):
    """Routes the adapter's internal instrumentation seam to crash_point,
    so kills can land between git's own steps (mid-snapshot, mid-merge)."""
    def _checkpoint(self, name: str) -> None:
        crash_point(f"git:{name}")


def emit(log: EventLog, ev: Event) -> None:
    log.append(ev)
    crash_point(f"after_append:{ev.type.value}")


# ── the dispatcher: one deterministic step from projection state ─
def step(log: EventLog, proj: StateProjection, adapter: GitCliAdapter,
         issue: str) -> None:
    istate = proj.issues.get(issue)

    if istate is None:
        emit(log, Event(EventType.ISSUE_CREATED, issue_id=issue, run_id=RUN_ID,
                        payload={"source": "stub", "title": f"issue {issue}"}))
        return
    if istate is IssueState.PENDING:
        # base_commit = trunk's head at activation (pinned clean base)
        base = adapter.head_of(TRUNK)
        emit(log, Event(EventType.ISSUE_ACTIVATED, issue_id=issue, run_id=RUN_ID,
                        payload={"base_commit": base}))
        return

    ex = proj.latest_execution(issue)

    if ex is None or ex.state in (ExecutionState.REJECTED, ExecutionState.CRASHED):
        if proj.attempts(issue) >= _cap(issue):
            emit(log, Event(EventType.ISSUE_ESCALATED, issue_id=issue, run_id=RUN_ID,
                            payload={"reason": "cap", "taxonomy_category": "cap-hit"}))
            return
        reason = "initial" if ex is None else "retry"
        emit(log, Event(EventType.EXECUTION_SPAWNED, issue_id=issue,
                        execution_id=f"{issue}-e{proj.attempts(issue) + 1}",
                        run_id=RUN_ID,
                        payload={"spawn_reason": reason, "engine": "stub",
                                 "pid": os.getpid()}))
        return

    if ex.state is ExecutionState.EXECUTING:
        base = proj.issue_base_commit[issue]
        adapter.reset_hard(base)                    # clean slate (incl. clean -fd)
        (adapter.repo_path / "issues").mkdir(exist_ok=True)
        (adapter.repo_path / "issues" / f"{issue}.txt").write_text(
            f"{ex.execution_id}\n")                  # tracked work
        (adapter.repo_path / f"scratch-{ex.execution_id}.tmp").write_text(
            "engine byproduct\n")                    # untracked; snapshot captures it
        crash_point("engine:post-edit")
        end = adapter.snapshot_commit(f"work {ex.execution_id}")
        crash_point("engine:post-snapshot")          # b5
        adapter.set_attempt_ref(issue, ex.execution_id, end)
        crash_point("engine:post-attempt-ref")       # b6
        emit(log, Event(EventType.EXECUTION_FINISHED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"start_commit": base, "end_commit": end,
                                 "exit_status": 0, "pid": os.getpid()}))
        return

    if ex.state is ExecutionState.VALIDATING:
        # Validation writes a cache byproduct, then cleans it up. A kill at
        # validate:post-artifact leaves the tree dirty (untracked valcache) with
        # the execution still VALIDATING. In PRODUCTION this crash relies on
        # recovery check 3 (_expected_commit returns end_commit for VALIDATING) to
        # reset the tree before _validate re-runs. This HARNESS worker, however,
        # blanket-resets at every EXECUTING entry and re-unlinks the valcache
        # here, so the point proves loop-level survival to the correct terminal —
        # it does NOT isolate check-3's reset (doc 14 §1.3-1.5, deferred item R1).
        # No ExecutionCrashed is emitted (resumable, not orphaned), so this point
        # is deliberately NOT in the harness RESIDUE_POINTS.
        valcache = adapter.repo_path / f"valcache-{ex.execution_id}.tmp"
        valcache.write_text("validation byproduct\n")
        crash_point("validate:post-artifact")
        valcache.unlink()
        if _attempt_no(ex.execution_id) in VAL_FAIL.get(issue, frozenset()):
            emit(log, Event(EventType.VALIDATION_FAILED, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"validated_commit": ex.end_commit,
                                     "gate_results": [],
                                     "taxonomy_category": "validation-test"}))
            # crash between the reject fact and this reset leaves head at
            # end_commit while the log says REJECTED (expects base) → check 3.
            adapter.reset_hard(proj.issue_base_commit[issue])
            return
        emit(log, Event(EventType.VALIDATION_PASSED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"validated_commit": ex.end_commit,
                                 "gate_results": []}))
        return

    if ex.state is ExecutionState.REVIEWING:
        if REV_REJECT.get(issue) == _attempt_no(ex.execution_id):
            emit(log, Event(EventType.REVIEW_REJECTED, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"reviewed_commit": ex.end_commit,
                                     "reviewer_provider": "stub",
                                     "verdict": "REJECT", "severity": "blocking",
                                     "taxonomy_category": "review-correctness",
                                     "feedback": [{"category": "review-correctness",
                                                   "message": "stub reject"}]}))
            adapter.reset_hard(proj.issue_base_commit[issue])
            return
        emit(log, Event(EventType.REVIEW_APPROVED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"reviewed_commit": ex.end_commit,
                                 "reviewer_provider": "stub",
                                 "verdict": "APPROVE"}))
        return

    if ex.state is ExecutionState.ACCEPTED:
        if not ex.commit_intended:
            emit(log, Event(EventType.COMMIT_INTENT, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"end_commit": ex.end_commit,
                                     "target_branch": TRUNK}))
            return
        if not ex.commit_created:
            end = ex.intent_end_commit or ex.end_commit
            # check-then-act (ADR-13): if a crash already advanced trunk,
            # backfill; otherwise perform the object-DB merge.
            if adapter.is_ancestor(end, TRUNK):
                mc = adapter.find_merge_commit(TRUNK, end)
                backfilled = True
            else:
                mc = adapter.merge_to(TRUNK, end, f"merge {issue}")
                backfilled = False
            emit(log, Event(EventType.COMMIT_CREATED, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"merge_commit": mc, "target_branch": TRUNK,
                                     "backfilled": backfilled}))
            return
        emit(log, Event(EventType.ISSUE_COMPLETED, issue_id=issue, run_id=RUN_ID,
                        payload={"reason": "accepted"}))
        return

    raise AssertionError(f"dispatcher has no move for {issue} / {ex}")


def main() -> int:
    base = Path(sys.argv[1])
    repo = base / "repo"                             # created by the harness
    adapter = HarnessAdapter(repo)

    log = EventLog(base / "events.jsonl")
    # Recovery is unconditional at startup — the production path, with all
    # three seams bound to the real repo (checks 2 & 3 no longer SKIPPED).
    proj, _report = recover(log, **bind_reconciler(adapter, TRUNK))

    for issue in ISSUES:
        while proj.issues.get(issue) not in _TERMINAL_STATES:
            step(log, proj, adapter, issue)
            # Re-derive from the log each step (replay, not memory-trust):
            # deliberately expensive-honest for the harness.
            proj = StateProjection().rebuild(log.replay())

    ok = all(proj.issues.get(i) is EXPECTED_TERMINAL[i] for i in ISSUES)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
