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

ISSUES = ["042", "043", "044"]
CAP = 8            # generous: injected crashes may burn several attempts
RUN_ID = "run-harness"
TRUNK = "trunk"    # deliberately not 'main' — proves nothing hardcodes it
WORK = "work"

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
        if proj.attempts(issue) >= CAP:
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
        emit(log, Event(EventType.VALIDATION_PASSED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"validated_commit": ex.end_commit,
                                 "gate_results": []}))
        return

    if ex.state is ExecutionState.REVIEWING:
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
        while proj.issues.get(issue) not in (
            IssueState.DONE, IssueState.NEEDS_HUMAN, IssueState.NEEDS_DECOMPOSITION
        ):
            step(log, proj, adapter, issue)
            # Re-derive from the log each step (replay, not memory-trust):
            # deliberately expensive-honest for the harness.
            proj = StateProjection().rebuild(log.replay())

    ok = all(proj.issues.get(i) is IssueState.DONE for i in ISSUES)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
