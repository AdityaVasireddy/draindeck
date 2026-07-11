"""Kill-9 durability harness — RECONCILED against doc 03 (Phase 1 gate).

Deterministic mode: an uncatchable kill injected at EVERY named transition point
(×2 occurrences), then restart clean until completion. Random mode:
external kill at random moments, self-calibrated to worker wall time and
self-verifying that kills actually land. Cross-platform: SIGKILL on POSIX,
TerminateProcess on Windows (see died_by_kill / run_worker).

Invariants after every scenario:
  I-a  log replays cleanly, event_id contiguous from 1
  I-b  replay deterministic: two rebuilds ⇒ identical digests
  I-c  all issues DONE
  I-d  exactly one CommitCreated per issue (no double-commit)
  I-e  every execution terminal-consistent: ACCEPTED+committed (exactly
       one per issue) or REJECTED/CRASHED; nothing left mid-flight
  I-f  world effects exactly once: one commit artifact per issue, an
       engine artifact per accepted execution, no torn tmp files
  I-g  intent/fact pairing: Finished/Crashed follow their Spawned;
       CommitCreated follows CommitIntent for the same execution
  I-h  never-replayed rule observable: each execution's Finished pid ==
       its Spawned pid (no process ever finishes another's execution)
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# Worker self-kill exit code (worker._hard_kill_self); mirrors 128+SIGKILL.
_SELF_KILL_CODE = 137


def died_by_kill(rc: int) -> bool:
    """True iff the worker was terminated (self-kill or external), not a
    clean exit (0) or an unhandled exception. Platform-aware:

    POSIX: a signal death is reported as a negative return code; SIGKILL
      (self or Popen.kill) is -9.
    Windows: there are no negative signal codes. TerminateProcess sets
      the exit code — Popen.kill() uses 1, and the worker's self-kill
      uses 137. A clean success is 0; an unhandled Python exception is 1,
      which we must NOT count as a kill, so on Windows an external
      Popen.kill collides with exception-rc 1. We disambiguate by having
      run_worker tag externally-killed runs explicitly (see below)."""
    if os.name != "nt":
        import signal
        return rc == -signal.SIGKILL
    return rc == _SELF_KILL_CODE

from runtime.events.log import EventLog                     # noqa: E402
from runtime.events.projections import StateProjection      # noqa: E402
from runtime.events.schema import EventType                 # noqa: E402
from runtime.state.model import ExecutionState, IssueState  # noqa: E402

WORKER = Path(__file__).with_name("worker.py")
ISSUES = ["042", "043", "044"]

CRASH_POINTS = [
    "after_append:IssueCreated",
    "after_append:IssueActivated",
    "after_append:ExecutionSpawned",
    "before_world:engine",
    "mid_world:engine",
    "after_world:engine",
    "after_append:ExecutionFinished",
    "after_append:ValidationPassed",
    "after_append:ReviewApproved",
    "after_append:CommitIntent",
    "before_world:commit",
    "mid_world:commit",
    "after_world:commit",
    "after_append:CommitCreated",
    "after_append:IssueCompleted",
]


def run_worker(base: Path, crash: str | None = None,
               kill_after: float | None = None) -> tuple[str, int]:
    """Run the worker once. Returns (outcome, rc) where outcome is:
      'completed' — clean exit 0 (all issues DONE)
      'killed'    — terminated by injected self-kill or our external kill
      'errored'   — nonzero exit that is neither (e.g. an exception, or a
                    worker rc=2 meaning it finished but not all DONE)

    Deciding the outcome here — rather than inferring it from rc at the
    assertion site — is what makes the harness platform-independent: on
    Windows an external TerminateProcess and an unhandled exception both
    surface as rc=1, indistinguishable after the fact, but run_worker
    knows which kills it issued and whether the injected self-kill code
    came back."""
    env = dict(os.environ)
    env.pop("RUNTIME_CRASH_POINT", None)
    if crash:
        env["RUNTIME_CRASH_POINT"] = crash
    p = subprocess.Popen([sys.executable, str(WORKER), str(base)], env=env)
    externally_killed = False
    if kill_after is not None:
        time.sleep(kill_after)
        if p.poll() is None:
            p.kill()  # SIGKILL (POSIX) / TerminateProcess (Windows)
            externally_killed = True
    p.wait()
    rc = p.returncode
    if externally_killed:
        return "killed", rc
    if died_by_kill(rc):          # injected self-kill inside the worker
        return "killed", rc
    if rc == 0:
        return "completed", rc
    return "errored", rc


def verify(base: Path, scenario: str) -> None:
    log = EventLog(base / "events.jsonl")
    events = list(log.replay())                              # I-a
    p1 = StateProjection().rebuild(iter(events))
    p2 = StateProjection().rebuild(log.replay())
    assert p1.digest() == p2.digest(), f"{scenario}: replay not deterministic"  # I-b

    for i in ISSUES:                                         # I-c
        assert p1.issues.get(i) is IssueState.DONE, \
            f"{scenario}: issue {i} is {p1.issues.get(i)}, not DONE"

    created: dict[str, int] = {}
    spawned_pid: dict[str, int] = {}
    intent_seen: set[str] = set()
    for ev in events:
        if ev.type is EventType.EXECUTION_SPAWNED:
            spawned_pid[ev.execution_id] = ev.payload.get("pid")
        if ev.type in (EventType.EXECUTION_FINISHED, EventType.EXECUTION_CRASHED):
            assert ev.execution_id in spawned_pid, \
                f"{scenario}: {ev.type.value} (event {ev.event_id}) precedes its intent"  # I-g
        if ev.type is EventType.EXECUTION_FINISHED:          # I-h
            assert ev.payload.get("pid") == spawned_pid[ev.execution_id], \
                f"{scenario}: execution {ev.execution_id} finished by a " \
                f"different process than spawned it — replayed execution!"
        if ev.type is EventType.COMMIT_INTENT:
            intent_seen.add(ev.execution_id)
        if ev.type is EventType.COMMIT_CREATED:
            assert ev.execution_id in intent_seen, \
                f"{scenario}: CommitCreated before CommitIntent (event {ev.event_id})"  # I-g
            created[ev.issue_id] = created.get(ev.issue_id, 0) + 1
    for i in ISSUES:                                         # I-d
        assert created.get(i) == 1, \
            f"{scenario}: issue {i} has {created.get(i, 0)} CommitCreated events"

    accepted_by_issue: dict[str, int] = {}                   # I-e
    for x in p1.executions.values():
        if x.state is ExecutionState.ACCEPTED:
            assert x.commit_intended and x.commit_created, \
                f"{scenario}: {x.execution_id} ACCEPTED but commit sequence incomplete"
            accepted_by_issue[x.issue_id] = accepted_by_issue.get(x.issue_id, 0) + 1
        else:
            assert x.state in (ExecutionState.REJECTED, ExecutionState.CRASHED), \
                f"{scenario}: execution {x.execution_id} left in {x.state.value}"
    for i in ISSUES:
        assert accepted_by_issue.get(i) == 1, \
            f"{scenario}: issue {i} has {accepted_by_issue.get(i, 0)} accepted executions"

    world = base / "world"                                   # I-f
    for i in ISSUES:
        assert (world / f"commit-{i}.done").exists(), \
            f"{scenario}: missing commit artifact for {i}"
    for x in p1.executions.values():
        if x.state is ExecutionState.ACCEPTED:
            assert (world / f"engine-{x.execution_id}.done").exists(), \
                f"{scenario}: accepted exec {x.execution_id} has no engine artifact"
    leftovers = list(world.glob("tmp-*"))
    assert not leftovers, f"{scenario}: torn tmp files remain: {leftovers}"
    log.close()


def restart_until_done(base: Path, scenario: str, max_restarts: int = 40) -> None:
    for _ in range(max_restarts):
        outcome, rc = run_worker(base)
        if outcome == "completed":
            return
        assert outcome != "errored", \
            f"{scenario}: clean restart failed (outcome={outcome}, rc={rc})"
    raise AssertionError(f"{scenario}: not done after {max_restarts} restarts")


def scenario_dir(root: Path, name: str) -> Path:
    d = root / name.replace(":", "_")
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/crash-harness")
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 42)
    passed = 0

    # Self-calibrate the random-kill window to THIS machine's worker wall
    # time, so the harness is portable across OS process-spawn speeds
    # (Windows spawns far slower than Linux). Time one clean control run,
    # then aim kills across roughly its whole span. This replaces the old
    # hardcoded 5–90 ms window that was tuned to Linux only.
    cal = scenario_dir(root, "_calibration")
    t0 = time.time()
    outcome, rc = run_worker(cal)
    assert outcome == "completed", f"calibration run failed: {outcome} rc={rc}"
    wall = time.time() - t0
    kill_lo, kill_hi = 0.10 * wall, 0.95 * wall
    print(f"calibration: worker wall {wall:.3f}s → kill window "
          f"[{kill_lo:.3f}, {kill_hi:.3f}]s")

    for point in CRASH_POINTS:
        for nth in (1, 2):
            name = f"det[{point}:{nth}]"
            base = scenario_dir(root, name)
            outcome, rc = run_worker(base, crash=f"{point}:{nth}")
            assert outcome == "killed", \
                f"{name}: expected kill death, got outcome={outcome} rc={rc} — injection not hit?"
            restart_until_done(base, name)
            verify(base, name)
            passed += 1
            print(f"PASS {name}")

    total_kills = 0
    for i in range(15):
        name = f"rand[{i}]"
        base = scenario_dir(root, name)
        kills = 0
        while True:
            outcome, rc = run_worker(base, kill_after=random.uniform(kill_lo, kill_hi))
            if outcome == "completed":
                break
            assert outcome == "killed", f"{name}: outcome={outcome} rc={rc}"
            kills += 1
            assert kills < 60, f"{name}: never completed"
        verify(base, name)
        passed += 1
        total_kills += kills
        print(f"PASS {name} ({kills} kills survived)")
    assert total_kills >= 10, (
        f"random mode landed only {total_kills} kills across 15 rounds — "
        "window no longer overlaps the workload; recalibrate")

    base = scenario_dir(root, "control")
    outcome, rc = run_worker(base)
    assert outcome == "completed", f"control: outcome={outcome} rc={rc}"
    verify(base, "control")
    passed += 1
    print("PASS control")

    print(f"\nALL {passed} SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
