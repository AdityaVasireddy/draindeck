"""Kill-9 durability harness — GIT-WORLD edition (docs/11 §3, Phase 1 gate).

The "world" is now a REAL temp git repository, not filesystem stubs. An
uncatchable kill is injected at every named transition — including inside
git operations (mid-snapshot, mid-merge) via the adapter's instrumentation
seam — then the worker is restarted clean until completion. Random mode
kills at self-calibrated moments and self-verifies that kills land.
Cross-platform: SIGKILL on POSIX, TerminateProcess on Windows.

Log-level invariants (unchanged from the stub era):
  I-a  log replays cleanly, event_id contiguous from 1
  I-b  replay deterministic: two rebuilds ⇒ identical digests
  I-c  all issues DONE
  I-d  exactly one CommitCreated per issue (no double-commit)
  I-e  every execution terminal-consistent: ACCEPTED+committed (one per
       issue) or REJECTED/CRASHED; nothing left mid-flight
  I-g  intent/fact pairing: Finished/Crashed follow their Spawned;
       CommitCreated follows CommitIntent for the same execution
  I-h  never-replayed rule: each execution's Finished pid == its Spawned pid

Git-level invariants (new — the world is git, docs/11 §3.2):
  I-i  evidence exists: each Finished.end_commit is a real commit == its
       attempt ref; each non-null Crashed.residue_ref resolves and is
       diffable from base (ADR-15 — no evidence destroyed by resets)
  I-j  exactly-once merge: each issue's accepted end_commit is the second
       parent of exactly one merge on trunk's first-parent chain, and that
       set equals the CommitCreated.merge_commit values
  I-k  workspace hygiene: final tree clean, no index.lock, no MERGE_HEAD,
       HEAD on a branch (not detached)
  I-l  join-key integrity: each CommitCreated.merge_commit is an ancestor
       of trunk; trunk's issues/<issue>.txt names the accepted execution
  I-m  residue expectations: a kill at a provably-dirty point yields a
       Crashed with a NON-null residue_ref (a lazy None-returning
       preserve_residue cannot pass — see mutation M1)

Engine-orphan invariant (Session 4 — checked by planted fixture f4):
  I-n  a REAL engine child that outlived an orchestrator crash is reaped at
       startup (reap_orphans, run BEFORE recover), its orphaned execution is
       CRASHED with a residue_ref, and no pidfile is left behind. A no-op
       reap_orphans cannot pass (see mutation M3).
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Diagnostic output contains non-ASCII (→, —); the Windows console default
# code page (cp1252) cannot encode them and would crash the harness — or,
# worse, mask a real assertion message with an encoding error. Force UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# Worker self-kill exit code (worker._hard_kill_self); mirrors 128+SIGKILL.
_SELF_KILL_CODE = 137


def died_by_kill(rc: int) -> bool:
    """True iff the worker was terminated (self-kill or external), not a
    clean exit (0) or an unhandled exception. On POSIX a signal death is a
    negative rc (SIGKILL = -9); on Windows we use the distinctive self-kill
    code and tag externally-killed runs in run_worker."""
    if os.name != "nt":
        import signal
        return rc == -signal.SIGKILL
    return rc == _SELF_KILL_CODE

from runtime.events.log import EventLog                     # noqa: E402
from runtime.events.projections import StateProjection      # noqa: E402
from runtime.events.schema import EventType                 # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter          # noqa: E402
from runtime.state.model import ExecutionState, IssueState  # noqa: E402

WORKER = Path(__file__).with_name("worker.py")
ISSUES = ["042", "043", "044"]
TRUNK = "trunk"

CRASH_POINTS = [
    "after_append:IssueCreated",
    "after_append:IssueActivated",
    "after_append:ExecutionSpawned",
    "engine:post-edit",              # dirty tree, uncommitted (b2/b3)
    "git:snapshot:post-add",         # killed after add, before commit (b4-like)
    "engine:post-snapshot",          # committed residue, ref not set (b5)
    "engine:post-attempt-ref",       # ref set, Finished not appended (b6)
    "after_append:ExecutionFinished",
    "after_append:ValidationFailed",   # reject fact durable; check 3 resets (043)
    "after_append:ValidationPassed",
    "after_append:ReviewRejected",     # reject fact durable; check 3 resets (044)
    "after_append:ReviewApproved",
    "after_append:CommitIntent",
    "git:merge:post-tree",           # merged tree written, no commit-tree (c2)
    "git:merge:post-commit-tree",    # merge commit sealed, ref not moved (c2)
    "git:merge:post-update-ref",     # trunk moved, CommitCreated not appended (c3)
    "after_append:CommitCreated",
    "after_append:IssueCompleted",
]

# Points at which the worktree was provably dirty (or a residue commit
# existed) when killed → the orphan MUST be crashed WITH a residue ref.
RESIDUE_POINTS = {
    "engine:post-edit",
    "git:snapshot:post-add",
    "engine:post-snapshot",
    "engine:post-attempt-ref",
}


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"harness git {args} failed: {p.stderr}")
    return p.stdout.strip()


def init_repo(base: Path) -> Path:
    """One temp git repo as the world: seed commit on 'trunk', then a
    persistent 'work' branch checked out (the worker never checks out
    trunk; merge_to advances it purely in the object DB)."""
    repo = base / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", TRUNK)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitignore").write_text("*.ignored\n")
    (repo / "README").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    _git(repo, "checkout", "-b", "work")
    return repo


def run_worker(base: Path, crash: str | None = None,
               kill_after: float | None = None) -> tuple[str, int]:
    """Run the worker once. Returns (outcome, rc): 'completed' (clean exit 0),
    'killed' (injected self-kill or our external kill), or 'errored'
    (anything else). Deciding here, not at the assertion site, is what makes
    the harness platform-independent (see the prior version's note)."""
    env = dict(os.environ)
    env.pop("RUNTIME_CRASH_POINT", None)
    if crash:
        env["RUNTIME_CRASH_POINT"] = crash
    p = subprocess.Popen([sys.executable, str(WORKER), str(base)], env=env)
    externally_killed = False
    if kill_after is not None:
        time.sleep(kill_after)
        if p.poll() is None:
            p.kill()
            externally_killed = True
    p.wait()
    rc = p.returncode
    if externally_killed:
        return "killed", rc
    if died_by_kill(rc):
        return "killed", rc
    if rc == 0:
        return "completed", rc
    return "errored", rc


def verify(base: Path, scenario: str, crash_point: str | None = None) -> None:
    repo = base / "repo"
    adapter = GitCliAdapter(repo)
    log = EventLog(base / "events.jsonl")
    events = list(log.replay())                              # I-a
    p1 = StateProjection().rebuild(iter(events))
    p2 = StateProjection().rebuild(log.replay())
    assert p1.digest() == p2.digest(), f"{scenario}: replay not deterministic"  # I-b

    for i in ISSUES:                                         # I-c
        assert p1.issues.get(i) is IssueState.DONE, \
            f"{scenario}: issue {i} is {p1.issues.get(i)}, not DONE"

    # ── log-level pairing / counting (I-d, I-g, I-h) ─────────────────
    created: dict[str, int] = {}
    created_merge: dict[str, str] = {}
    spawned_pid: dict[str, int] = {}
    intent_seen: set[str] = set()
    finished_end: dict[str, str] = {}
    crashed_residue: list[tuple[str, str | None]] = []
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
            finished_end[ev.execution_id] = ev.payload.get("end_commit")
        if ev.type is EventType.EXECUTION_CRASHED:
            crashed_residue.append((ev.execution_id, ev.payload.get("residue_ref")))
        if ev.type is EventType.COMMIT_INTENT:
            intent_seen.add(ev.execution_id)
        if ev.type is EventType.COMMIT_CREATED:
            assert ev.execution_id in intent_seen, \
                f"{scenario}: CommitCreated before CommitIntent (event {ev.event_id})"  # I-g
            created[ev.issue_id] = created.get(ev.issue_id, 0) + 1
            created_merge[ev.issue_id] = ev.payload.get("merge_commit")
    for i in ISSUES:                                         # I-d
        assert created.get(i) == 1, \
            f"{scenario}: issue {i} has {created.get(i, 0)} CommitCreated events"

    # ── execution terminal-consistency (I-e) ─────────────────────────
    accepted_by_issue: dict[str, str] = {}
    for x in p1.executions.values():
        if x.state is ExecutionState.ACCEPTED:
            assert x.commit_intended and x.commit_created, \
                f"{scenario}: {x.execution_id} ACCEPTED but commit sequence incomplete"
            assert x.issue_id not in accepted_by_issue, \
                f"{scenario}: issue {x.issue_id} has >1 accepted execution"
            accepted_by_issue[x.issue_id] = x.execution_id
        else:
            assert x.state in (ExecutionState.REJECTED, ExecutionState.CRASHED), \
                f"{scenario}: execution {x.execution_id} left in {x.state.value}"
    for i in ISSUES:
        assert i in accepted_by_issue, f"{scenario}: issue {i} has no accepted execution"

    # ── I-i: evidence exists ─────────────────────────────────────────
    for xid, end in finished_end.items():
        assert adapter.commit_exists(end), \
            f"{scenario}: Finished end_commit {end} for {xid} is not a real commit"
        ref = f"{adapter.ns}/{p1.executions[xid].issue_id}/{xid}"
        assert adapter.ref_target(ref) == end, \
            f"{scenario}: attempt ref {ref} != end_commit {end}"
    for xid, ref in crashed_residue:
        if ref is None:
            continue
        sha = adapter.ref_target(ref)
        assert sha is not None, f"{scenario}: residue_ref {ref} does not resolve"
        base_commit = p1.issue_base_commit.get(p1.executions[xid].issue_id)
        adapter.diff(base_commit, sha)  # derivable, must not raise (ADR-15)

    # ── I-j / I-l: exactly-once merge + join-key integrity ───────────
    for i in ISSUES:
        acc = accepted_by_issue[i]
        end = finished_end[acc]
        mc = adapter.find_merge_commit(TRUNK, end)
        assert mc is not None, \
            f"{scenario}: no merge on {TRUNK} carries {i}'s accepted end_commit"
        assert mc == created_merge[i], \
            f"{scenario}: issue {i} merge_commit {created_merge[i]} != world {mc}"  # I-j
        assert adapter.is_ancestor(mc, TRUNK), \
            f"{scenario}: merge_commit {mc} not an ancestor of {TRUNK}"            # I-l
        shown = _git(repo, "show", f"{TRUNK}:issues/{i}.txt")
        assert acc in shown, \
            f"{scenario}: trunk issues/{i}.txt names {shown!r}, not accepted {acc}"  # I-l

    # ── I-k: workspace hygiene ───────────────────────────────────────
    assert not adapter.is_dirty(), f"{scenario}: workspace dirty at end"
    assert not (repo / ".git" / "index.lock").exists(), f"{scenario}: stale index.lock"
    assert not (repo / ".git" / "MERGE_HEAD").exists(), f"{scenario}: MERGE_HEAD left"
    head_ref = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    assert head_ref != "HEAD", f"{scenario}: HEAD is detached"

    # ── I-m: residue expectation for provably-dirty kills ────────────
    if crash_point in RESIDUE_POINTS:
        assert any(ref is not None for _xid, ref in crashed_residue), \
            f"{scenario}: killed at {crash_point} (tree was dirty) but no " \
            f"ExecutionCrashed carried a residue_ref — preserve_residue lazy?"

    log.close()


def restart_until_done(base: Path, scenario: str, max_restarts: int = 60) -> None:
    for _ in range(max_restarts):
        outcome, rc = run_worker(base)
        if outcome == "completed":
            return
        assert outcome != "errored", \
            f"{scenario}: clean restart failed (outcome={outcome}, rc={rc})"
    raise AssertionError(f"{scenario}: not done after {max_restarts} restarts")


def fresh_scenario(root: Path, name: str) -> Path:
    base = root / name.replace(":", "_")
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    init_repo(base)
    return base


def run_engine_orphan_fixture(root: Path) -> int:
    """f4 (I-n): a REAL engine child that outlived an orchestrator crash must be
    reaped at startup, its orphaned execution CRASHED with residue, and no
    pidfile left behind. Planted like f1/f2/f3 — a live worker cannot be timed
    to die at the exact instant a real child is mid-run (and the blocking run()
    cannot self-kill from inside), which is precisely the class of state
    fixtures exist for (docs/11 §3.4). The production code under test is real:
    ClaudeHeadlessEngine._write_pidfile, reap_orphans, is_execution_alive, and
    recover()+bind_reconciler with is_execution_alive bound. Skips cleanly if
    'claude' is not on PATH (the engine __init__ resolves it); the reap/liveness
    logic is additionally unit-tested. Returns 1 if run, 0 if skipped."""
    from runtime.config import EngineCfg                    # noqa: PLC0415
    from runtime.engine.claude_headless import (            # noqa: PLC0415
        ClaudeHeadlessEngine, EngineError,
    )
    from runtime.events.schema import Event                 # noqa: PLC0415
    from runtime.recovery.bindings import bind_reconciler   # noqa: PLC0415
    from runtime.recovery.reconciler import recover         # noqa: PLC0415

    base = fresh_scenario(root, "fixture[f4-engine-orphan]")
    repo = base / "repo"
    artifacts = base / "artifacts"
    xid = "042-e1"

    try:
        engine = ClaudeHeadlessEngine(
            EngineCfg(provider="claude-headless", auth_mode="subscription"),
            artifacts,
        )
    except EngineError:
        print("SKIP fixture[f4-engine-orphan] (claude not on PATH)")
        return 0

    # Plant the log so the projection carries one EXECUTING orphan (042-e1).
    base_commit = _git(repo, "rev-parse", TRUNK)
    log = EventLog(base / "events.jsonl")
    for ev in (
        Event(EventType.ISSUE_CREATED, issue_id="042", run_id="run-f4",
              payload={"source": "f4", "title": "orphan"}),
        Event(EventType.ISSUE_ACTIVATED, issue_id="042", run_id="run-f4",
              payload={"base_commit": base_commit}),
        Event(EventType.EXECUTION_SPAWNED, issue_id="042", execution_id=xid,
              run_id="run-f4",
              payload={"spawn_reason": "initial", "engine": "claude-headless",
                       "pid": os.getpid()}),
    ):
        log.append(ev)

    # A REAL long-lived child that dirties the workspace, then sleeps; its
    # pidfile is written via the PRODUCTION path (engine._write_pidfile).
    scratch = repo / "orphan-scratch.tmp"
    dummy_src = (
        "import sys,time,pathlib;"
        "pathlib.Path(sys.argv[1]).write_text('engine byproduct');"
        "time.sleep(300)"
    )
    dummy = subprocess.Popen([sys.executable, "-c", dummy_src, str(scratch)])
    try:
        engine._xdir(xid).mkdir(parents=True, exist_ok=True)
        engine._write_pidfile(engine._pidfile(xid), dummy.pid)
        for _ in range(50):                       # wait until provably dirty
            if scratch.exists():
                break
            time.sleep(0.1)
        assert scratch.exists(), "f4: dummy never dirtied the workspace"

        # PRODUCTION startup order: reap_orphans BEFORE recover.
        adapter = GitCliAdapter(repo)
        repairs = engine.reap_orphans()
        proj, _report = recover(
            log,
            is_execution_alive=engine.is_execution_alive,
            **bind_reconciler(adapter, TRUNK),
        )
    finally:
        if dummy.poll() is None:
            dummy.kill()
        try:
            dummy.wait(timeout=10)
        except subprocess.SubprocessError:
            pass
        log.close()

    # I-n(1): orphan reaped and dead.
    assert any(xid in r for r in repairs), \
        f"f4: reap_orphans did not report {xid}: {repairs}"
    assert dummy.returncode is not None, \
        "f4: orphan engine child survived reap_orphans (still running)"
    # I-n(3): no pidfile left behind.
    assert not list(artifacts.glob("*/pid")), "f4: pidfile leaked after recovery"
    # I-n(2): orphan CRASHED with a non-null residue_ref.
    view = proj.executions.get(xid)
    assert view is not None and view.state is ExecutionState.CRASHED, \
        f"f4: {xid} is {view.state.value if view else None}, not CRASHED"
    residues = [
        ev.payload.get("residue_ref")
        for ev in EventLog(base / "events.jsonl").replay()
        if ev.type is EventType.EXECUTION_CRASHED and ev.execution_id == xid
    ]
    assert residues and residues[0] is not None, \
        f"f4: {xid} CRASHED without a residue_ref (dirty tree evidence lost)"
    print("PASS fixture[f4-engine-orphan]")
    return 1


def run_fixtures(root: Path) -> int:
    """Planted-state scenarios that a timed kill cannot produce (docs/11
    §3.4). f3 (check-2 tamper) is covered by unit test
    test_check2_tamper_raises — a raise mid-run would surface as 'errored'
    here, which restart_until_done already forbids."""
    passed = 0

    # f1: stale index.lock + dirty tree at boot → recover_workspace must
    # clear the lock (else every git mutation fails) AND check 3 resets.
    base = fresh_scenario(root, "fixture[f1-stale-lock]")
    repo = base / "repo"
    (repo / ".git" / "index.lock").write_text("")
    (repo / "planted.txt").write_text("dirty at boot")
    restart_until_done(base, "fixture[f1-stale-lock]")
    verify(base, "fixture[f1-stale-lock]")
    passed += 1
    print("PASS fixture[f1-stale-lock]")

    # f2: dirty workspace, no open execution → check 3 archives + resets.
    base = fresh_scenario(root, "fixture[f2-dirty-boot]")
    repo = base / "repo"
    (repo / "planted.txt").write_text("dirty at boot")
    restart_until_done(base, "fixture[f2-dirty-boot]")
    verify(base, "fixture[f2-dirty-boot]")
    passed += 1
    print("PASS fixture[f2-dirty-boot]")

    # f4 (I-n): engine-orphan reaping at startup. Skips if claude is absent.
    passed += run_engine_orphan_fixture(root)

    return passed


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/crash-harness")
    random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 42)
    point_filter = sys.argv[3] if len(sys.argv) > 3 else None  # iterate one point
    passed = 0

    # Self-calibrate the random-kill window to THIS machine's worker wall
    # time (git subprocesses make it far slower than the stub era).
    cal = fresh_scenario(root, "_calibration")
    t0 = time.time()
    outcome, rc = run_worker(cal)
    assert outcome == "completed", f"calibration run failed: {outcome} rc={rc}"
    wall = time.time() - t0
    kill_lo, kill_hi = 0.10 * wall, 0.95 * wall
    print(f"calibration: worker wall {wall:.3f}s → kill window "
          f"[{kill_lo:.3f}, {kill_hi:.3f}]s")

    points = [p for p in CRASH_POINTS if point_filter is None or point_filter in p]
    for point in points:
        for nth in (1, 2):
            name = f"det[{point}:{nth}]"
            base = fresh_scenario(root, name)
            outcome, rc = run_worker(base, crash=f"{point}:{nth}")
            if outcome != "killed":
                # nth==2 may be unreachable if the point fires <2 times in a
                # crash-free run to that stage; only nth==1 is guaranteed.
                assert nth == 2 and outcome == "completed", \
                    f"{name}: expected kill, got outcome={outcome} rc={rc}"
                verify(base, name, crash_point=point)
                passed += 1
                print(f"PASS {name} (point fired <2x; ran clean)")
                continue
            restart_until_done(base, name)
            verify(base, name, crash_point=point)
            passed += 1
            print(f"PASS {name}")

    if point_filter is None:
        total_kills = 0
        for i in range(15):
            name = f"rand[{i}]"
            base = fresh_scenario(root, name)
            kills = 0
            while True:
                outcome, rc = run_worker(base, kill_after=random.uniform(kill_lo, kill_hi))
                if outcome == "completed":
                    break
                assert outcome == "killed", f"{name}: outcome={outcome} rc={rc}"
                kills += 1
                assert kills < 80, f"{name}: never completed"
            verify(base, name)
            passed += 1
            total_kills += kills
            print(f"PASS {name} ({kills} kills survived)")
        assert total_kills >= 10, (
            f"random mode landed only {total_kills} kills across 15 rounds — "
            "window no longer overlaps the workload; recalibrate")

        passed += run_fixtures(root)

        base = fresh_scenario(root, "control")
        outcome, rc = run_worker(base)
        assert outcome == "completed", f"control: outcome={outcome} rc={rc}"
        verify(base, "control")
        passed += 1
        print("PASS control")

    print(f"\nALL {passed} SCENARIOS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
