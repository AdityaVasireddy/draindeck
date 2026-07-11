"""Stub workload for the kill-9 harness — RECONCILED against doc 03.

Drives the REAL log, projection, transition tables, and recovery through
doc 03 §5's happy path, with LLM/git stages as filesystem "world"
actions:

  engine stage  → world/engine-<execution>.done   (tmp + os.replace)
  commit stage  → world/commit-<issue>.done       (tmp + os.replace)

Happy-path event sequence (I5/I6 ordering, intents before effects):
  IssueCreated → IssueActivated → ExecutionSpawned → [engine action] →
  ExecutionFinished → ValidationPassed → ReviewApproved → CommitIntent →
  [commit action] → CommitCreated → IssueCompleted

The dispatcher is a pure function of the replayed projection — that IS
deterministic resume. Every world action is check-then-act. Recovery
(check 1) crashes orphaned executions — never resumes them (doc 03:
EXECUTING is abandonable) — and the retry policy spawns fresh. A
pre-existing commit artifact without its fact is healed check-then-act
with CommitCreated(backfilled=true), doc 03 check-2 semantics.

pid discipline: ExecutionSpawned and ExecutionFinished record os.getpid();
the harness asserts they match per execution — proof that no execution
is ever finished by a process other than the one that spawned it (the
"never replayed" rule made observable).

Crash injection: RUNTIME_CRASH_POINT=<name>[:<nth>] → uncatchable self-
termination (SIGKILL on POSIX, TerminateProcess on Windows) at the nth
hit of the named point. See _hard_kill_self.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def _hard_kill_self() -> None:
    """Terminate THIS process uncatchably — no atexit, no finally, no
    buffer flush — the SIGKILL guarantee, on either platform.

    POSIX: SIGKILL cannot be caught or ignored.
    Windows: TerminateProcess on our own handle is the closest analog —
    the process stops immediately with no Python cleanup. We use a
    distinctive exit code (137 = 128 + 9, the shell's convention for
    'killed by SIGKILL') so the harness can positively distinguish a
    kill from a clean exit (0) or an unhandled exception (1)."""
    if os.name == "nt":
        import ctypes
        # -1 (0xFFFFFFFF) is the pseudo-handle for the current process.
        ctypes.windll.kernel32.TerminateProcess(
            ctypes.c_void_p(-1), ctypes.c_uint(137)
        )
    else:
        import signal
        os.kill(os.getpid(), signal.SIGKILL)

from runtime.events.log import EventLog                      # noqa: E402
from runtime.events.projections import StateProjection       # noqa: E402
from runtime.events.schema import Event, EventType           # noqa: E402
from runtime.recovery.reconciler import recover              # noqa: E402
from runtime.state.model import ExecutionState, IssueState   # noqa: E402

ISSUES = ["042", "043", "044"]
CAP = 8  # generous: injected crashes may burn several attempts
RUN_ID = "run-harness"

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


# ── durable world actions (check-then-act) ───────────────────────
def world_action(world: Path, stage: str, key: str) -> None:
    artifact = world / f"{stage}-{key}.done"
    if artifact.exists():
        return
    crash_point(f"before_world:{stage}")
    tmp = world / f"tmp-{stage}-{key}"
    tmp.write_text(f"{stage}:{key}\n")
    crash_point(f"mid_world:{stage}")
    os.replace(tmp, artifact)  # atomic on POSIX and Windows (same volume)
    crash_point(f"after_world:{stage}")


def residue_preserver(world: Path):
    """preserve_residue seam: 'commit residue to attempt ref' in stub
    form — clean torn tmp, report a ref if any residue existed."""
    def preserve(execution_id: str):
        residue = False
        tmp = world / f"tmp-engine-{execution_id}"
        if tmp.exists():
            tmp.unlink()
            residue = True
        if (world / f"engine-{execution_id}.done").exists():
            residue = True
        return f"refs/attempts/stub/{execution_id}" if residue else None
    return preserve


def emit(log: EventLog, ev: Event) -> None:
    log.append(ev)
    crash_point(f"after_append:{ev.type.value}")


# ── the dispatcher: one deterministic step from projection state ─
def step(log: EventLog, proj: StateProjection, world: Path, issue: str) -> None:
    istate = proj.issues.get(issue)

    if istate is None:
        emit(log, Event(EventType.ISSUE_CREATED, issue_id=issue, run_id=RUN_ID,
                        payload={"source": "stub", "title": f"issue {issue}"}))
        return
    if istate is IssueState.PENDING:
        emit(log, Event(EventType.ISSUE_ACTIVATED, issue_id=issue, run_id=RUN_ID,
                        payload={"base_commit": "stub-base"}))
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
        world_action(world, "engine", ex.execution_id)
        emit(log, Event(EventType.EXECUTION_FINISHED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"start_commit": "stub-base",
                                 "end_commit": f"attempt-{ex.execution_id}",
                                 "exit_status": 0, "pid": os.getpid()}))
        return

    if ex.state is ExecutionState.VALIDATING:
        emit(log, Event(EventType.VALIDATION_PASSED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"validated_commit": f"attempt-{ex.execution_id}",
                                 "gate_results": []}))
        return

    if ex.state is ExecutionState.REVIEWING:
        emit(log, Event(EventType.REVIEW_APPROVED, issue_id=issue,
                        execution_id=ex.execution_id, run_id=RUN_ID,
                        payload={"reviewed_commit": f"attempt-{ex.execution_id}",
                                 "reviewer_provider": "stub",
                                 "verdict": "APPROVE"}))
        return

    if ex.state is ExecutionState.ACCEPTED:
        if not ex.commit_intended:
            emit(log, Event(EventType.COMMIT_INTENT, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"end_commit": f"attempt-{ex.execution_id}",
                                     "target_branch": "agent-work"}))
            return
        if not ex.commit_created:
            # check-then-act commit; a pre-existing artifact means a crash
            # landed between the world effect and its fact — backfill
            # (doc 03 reconciler check 2 semantics, healed at the seam here)
            backfilled = (world / f"commit-{issue}.done").exists()
            world_action(world, "commit", issue)
            emit(log, Event(EventType.COMMIT_CREATED, issue_id=issue,
                            execution_id=ex.execution_id, run_id=RUN_ID,
                            payload={"merge_commit": f"merge-{issue}",
                                     "target_branch": "agent-work",
                                     "backfilled": backfilled}))
            return
        emit(log, Event(EventType.ISSUE_COMPLETED, issue_id=issue, run_id=RUN_ID,
                        payload={"reason": "accepted"}))
        return

    raise AssertionError(f"dispatcher has no move for {issue} / {ex}")


def main() -> int:
    base = Path(sys.argv[1])
    world = base / "world"
    world.mkdir(parents=True, exist_ok=True)

    log = EventLog(base / "events.jsonl")
    # Recovery is unconditional at startup — same code path the real
    # runtime will use, residue seam bound to the stub world.
    proj, _report = recover(log, preserve_residue=residue_preserver(world))

    for issue in ISSUES:
        while proj.issues.get(issue) not in (
            IssueState.DONE, IssueState.NEEDS_HUMAN, IssueState.NEEDS_DECOMPOSITION
        ):
            step(log, proj, world, issue)
            # Re-derive from the log each step (replay, not memory-trust):
            # deliberately expensive-honest for the harness.
            proj = StateProjection().rebuild(log.replay())

    ok = all(proj.issues.get(i) is IssueState.DONE for i in ISSUES)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
