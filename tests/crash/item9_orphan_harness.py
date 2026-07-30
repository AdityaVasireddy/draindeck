"""Item-9 orphan-crash-recovery fault-injection harness (design gate follow-up).

Converts the INFERRED cells in docs/15-item9-outcome-matrix.md (commit ab2e798) to
VERIFIED by actually exercising the five outcome rows (A-E) against a SCRATCH git
repo — never C:\\Projects\\StockPhotoAgent. Two kinds of exercise, per the matrix's
own admission of what needs live timing vs. what's a pure code path:

  * Rows A and the /T discriminator: full LIVE dry-runs — real `cmd_run` subprocess,
    real `claude -p` child, a real `taskkill` against the orchestrator only (no /T),
    with exactly one deliberate /T kill to self-validate the live/self-dead
    discriminator Row D depends on. These are DISTINCT claims, scored on two
    independent axes (see _run_live_scenario's docstring) — never collapsed into one
    verdict, because a child that self-exits before the kill still lets Row A pass
    (ExecutionCrashed emitted) while proving nothing about live reaping (Row D).

  * Rows B, C, E: fixtures in the style of tests/crash/harness.py's f4/f5 — real git
    (GitCliAdapter on a scratch repo), hand-constructed event logs, direct calls into
    the real recover()/bind_reconciler()/Orchestrator._commit_sequence code. No real
    `claude`, no wall-clock kill timing — none of these rows' claims depend on either.

Kill method is FIXED per the design-gate task: `taskkill /PID <pid> /F`, no `/T`,
everywhere except the one labeled discriminator call site. Nothing in src/ is
imported for mutation — only driven externally (subprocess) or through existing
production entry points (recover, bind_reconciler, Orchestrator._commit_sequence /
.step()). If any future change here needs to edit src/, stop and flag it instead —
out of scope for an authoring/self-test turn.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

_SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(_SRC))
_REPO_ROOT = Path(__file__).resolve().parents[2]

import yaml  # noqa: E402

from runtime.events.log import EventLog                       # noqa: E402
from runtime.events.projections import StateProjection        # noqa: E402
from runtime.events.schema import Event, EventType             # noqa: E402
from runtime.recovery.bindings import bind_reconciler          # noqa: E402
from runtime.recovery.reconciler import recover                # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter              # noqa: E402
from runtime.config import Config                                # noqa: E402
from runtime.budget.manager import BudgetManager                 # noqa: E402
from runtime.loop import Orchestrator                             # noqa: E402

RUN_ID = "run-item9-fixture"


# ── shared plumbing ─────────────────────────────────────────────────────
def _rmtree_readonly_safe(path: Path) -> None:
    """git marks .git/objects/** read-only on Windows; plain shutil.rmtree chokes
    on that when re-running the harness against an already-used scratch root."""
    def _on_error(func, p, exc_info):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onexc=_on_error)


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"harness git {args} failed: {p.stderr}")
    return p.stdout.strip()


def init_scratch_repo(root: Path, name: str, seed_files: dict[str, str],
                       branch: str = "agent-work") -> Path:
    """Fresh temp git repo. Returns the SCENARIO base dir (base/repo is the repo,
    base/events.jsonl the log, base/artifacts the engine artifacts dir — matching
    what cmd_run derives from event_log.path's parent)."""
    base = root / name
    if base.exists():
        _rmtree_readonly_safe(base)
    base.mkdir(parents=True)
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / ".gitignore").write_text("*.ignored\n*.tmp\n", encoding="utf-8")
    for relpath, content in seed_files.items():
        p = repo / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return base


def _config_dict(repo: Path, event_log_path: Path) -> dict:
    return {
        "project": {
            "name": "item9-scratch",
            "repository": str(repo),
            "branch": "agent-work",
            "issues_file": "Issues.md",
            "validation": {
                "commands": [f'"{sys.executable}" -c "import sys; sys.exit(0)"'],
                "timeout_seconds": 60,
            },
        },
        "engine": {
            "provider": "claude-headless",
            "auth_mode": "subscription",
            "model": "default",
            "max_turns": 15,
            "timeout_seconds": 300,
        },
        "reviewer": {
            "provider": "qwen",
            "qwen": {"endpoint": "http://localhost:11434", "model": "qwen2.5-coder:14b"},
        },
        "budget": {
            "max_attempts_per_issue": 2,
            "max_executions_per_run": 4,
            "proxy_pricing": "api_list_rates",
            "hard_stop_proxy_cost_per_run_usd": 2.0,
        },
        "experiment": {
            "sample_size": 1,
            "attempt1_success_min": 0.30,
            "cost_per_shipped_issue_max_usd": 3.0,
        },
        "billing": {
            "posture": "pro_subscription_headless",
            "headless_split_status": "paused",
            "verified_on": "2026-07-29",
            "reverify_at": "n/a-scratch-harness",
        },
        "event_log": {"path": str(event_log_path)},
        "attempts": {"ref_namespace": "refs/attempts"},
    }


def write_scratch_config(base: Path, repo: Path) -> Path:
    d = _config_dict(repo, base / "events.jsonl")
    p = base / "config.yaml"
    p.write_text(yaml.dump(d, sort_keys=False), encoding="utf-8")
    return p


def _config_object(repo: Path, event_log_path: Path) -> Config:
    return Config.model_validate(_config_dict(repo, event_log_path))


def spawn_cmd_run(config_path: Path, stdout_log: Path) -> tuple[subprocess.Popen, object]:
    """Real `python -m runtime.main run --config <config_path>` subprocess. Returns
    (Popen, open file handle) — caller must close the handle once the process exits.
    ANTHROPIC_API_KEY is explicitly popped (CLAUDE.md: subscription billing only)."""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    fh = open(stdout_log, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "runtime.main", "run", "--config", str(config_path)],
        cwd=str(_REPO_ROOT), env=env, stdout=fh, stderr=subprocess.STDOUT,
    )
    return proc, fh


def poll_event_log(log_path: Path, predicate, timeout_s: float,
                    interval_s: float = 0.3) -> dict | None:
    """Raw read (open+split+json.loads per line, skip a torn trailing line) —
    deliberately NOT an EventLog instance, to avoid opening a second append-mode
    handle against a file another live process is actively writing to."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if log_path.exists():
            data = log_path.read_bytes()
            for raw in data.split(b"\n"):
                if not raw.strip():
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue  # torn tail line — ignore, matches EventLog.replay()
                if predicate(obj):
                    return obj
        time.sleep(interval_s)
    return None


def read_pidfile(artifacts_dir: Path, execution_id: str) -> dict | None:
    """Same file claude_headless.py:440-444's _read_pidfile reads — read
    independently (black-box observation), not via the engine module."""
    p = artifacts_dir / execution_id / "pid"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def poll_pidfile(artifacts_dir: Path, execution_id: str, timeout_s: float = 30,
                  interval_s: float = 0.2) -> dict | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        rec = read_pidfile(artifacts_dir, execution_id)
        if rec is not None:
            return rec
        time.sleep(interval_s)
    return None


def poll_dirty(repo: Path, timeout_s: float, interval_s: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _git(repo, "status", "--porcelain").strip():
            return True
        time.sleep(interval_s)
    return False


def taskkill(pid: int, *, tree: bool = False) -> subprocess.CompletedProcess:
    args = ["taskkill", "/PID", str(pid), "/F"]
    if tree:
        args.append("/T")
    return subprocess.run(args, capture_output=True, text=True)


def tasklist_pid(pid: int) -> str:
    p = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True,
    )
    return p.stdout.strip()


def pid_present(tasklist_raw: str) -> bool:
    # mirrors claude_headless.py:428-430's own parsing convention
    return bool(tasklist_raw) and tasklist_raw.startswith('"')


# ── Row A / Row D discriminator — live, scratch repo, real claude -p ────
_CALC_SEED = "def add(a, b):\n    return a + b\n"
_ISSUES_MD = (
    "## 1: Add a subtract function to calc.py\n\n"
    "Add a `subtract(a, b)` function to `calc.py` that returns `a - b`. Give it a "
    "short docstring. After writing it, read the file back to confirm the change "
    "is present, then stop.\n"
)


def _run_live_scenario(root: Path, name: str, *, tree_kill: bool) -> dict:
    """One ATTEMPT of a live fault-injection scenario. Two independently-reported
    axes, never merged:

    Axis 1 (recovery correctness, Row A's claim) — PASS iff ExecutionCrashed is
    emitted for the target execution post-resume with a residue_ref that resolves.
    Does not depend on catching the child alive.

    Axis 2 (live-orphan witness, Row D's claim), three-valued:
      PASS         - pre-kill tasklist showed the child PRESENT immediately before
                      the kill fired, AND (for a non-tree kill) resume stdout carries
                      "reaped orphan engine ..." / (for the tree kill) post-kill
                      tasklist shows ABSENT and NO reaped-orphan line — the proven
                      negative.
      INCONCLUSIVE - the child was already gone at the pre-kill gate, or the
                      post-kill/resume evidence doesn't match the expected shape
                      (a race) — proves nothing either way, must be retried.
      FAIL         - the harness's own kill/witness mechanism malfunctioned.
    """
    report: dict = {"witnesses": {}, "name": name, "tree_kill": tree_kill}
    base = init_scratch_repo(root, name, seed_files={"calc.py": _CALC_SEED})
    repo = base / "repo"
    (repo / "Issues.md").write_text(_ISSUES_MD, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add Issues.md")
    config_path = write_scratch_config(base, repo)
    artifacts_dir = base / "artifacts"
    event_log_path = base / "events.jsonl"

    stdout1 = base / "run1_stdout.log"
    proc, fh = spawn_cmd_run(config_path, stdout1)
    report["orchestrator_pid"] = proc.pid

    spawned = poll_event_log(
        event_log_path,
        lambda e: e.get("type") == "ExecutionSpawned" and e.get("execution_id") == "1-e1",
        timeout_s=90,
    )
    if spawned is None:
        fh.close()
        proc.kill()
        report["axis1"] = "FAIL"
        report["axis1_detail"] = "ExecutionSpawned(1-e1) never appeared within timeout"
        report["axis2"] = "FAIL"
        report["axis2_detail"] = "scenario never reached spawn"
        return report
    report["witnesses"]["execution_spawned_event"] = json.dumps(spawned)

    pid_rec = poll_pidfile(artifacts_dir, "1-e1", timeout_s=30)
    if pid_rec is None:
        fh.close()
        proc.kill()
        report["axis1"] = "FAIL"
        report["axis2"] = "FAIL"
        report["axis1_detail"] = report["axis2_detail"] = "pidfile for 1-e1 never appeared"
        return report
    child_pid = pid_rec["pid"]
    report["witnesses"]["pidfile_record"] = json.dumps(pid_rec)
    report["child_pid"] = child_pid

    poll_dirty(repo, timeout_s=60)
    report["witnesses"]["pre_kill_git_status"] = _git(repo, "status", "--porcelain")

    pre_kill_tasklist = tasklist_pid(child_pid)
    report["witnesses"]["pre_kill_tasklist"] = pre_kill_tasklist
    child_alive_pre_kill = pid_present(pre_kill_tasklist)

    if not child_alive_pre_kill:
        fh.close()
        try:
            proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
        report["axis2"] = "INCONCLUSIVE"
        report["axis2_detail"] = (
            "child pid absent at pre-kill alive-gate — self-exited before the kill "
            "could fire; proves nothing about live reaping"
        )
        report["axis1"] = "N/A"
        report["axis1_detail"] = "no crash injected this attempt (child already gone)"
        return report

    kill_res = taskkill(proc.pid, tree=tree_kill)
    report["witnesses"]["taskkill_stdout"] = kill_res.stdout
    report["witnesses"]["taskkill_stderr"] = kill_res.stderr
    report["witnesses"]["taskkill_returncode"] = str(kill_res.returncode)
    if kill_res.returncode not in (0, 128):  # 128 = "process not found" race, tolerated
        report["axis2"] = "FAIL"
        report["axis2_detail"] = f"taskkill itself malfunctioned: rc={kill_res.returncode}"
        fh.close()
        return report

    time.sleep(0.3)
    post_kill_tasklist = tasklist_pid(child_pid)
    report["witnesses"]["post_kill_tasklist"] = post_kill_tasklist
    child_alive_post_kill = pid_present(post_kill_tasklist)

    fh.close()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        pass

    stdout2 = base / "run2_stdout.log"
    proc2, fh2 = spawn_cmd_run(config_path, stdout2)
    try:
        proc2.wait(timeout=300)
        resume_rc = proc2.returncode
    except subprocess.TimeoutExpired:
        proc2.kill()
        resume_rc = None
    finally:
        fh2.close()
    resume_stdout = stdout2.read_text(encoding="utf-8", errors="replace")
    report["witnesses"]["resume_stdout"] = resume_stdout
    report["resume_returncode"] = resume_rc

    reaped_line_present = "reaped orphan engine 1-e1" in resume_stdout

    crashed_ev = poll_event_log(
        event_log_path,
        lambda e: e.get("type") == "ExecutionCrashed" and e.get("execution_id") == "1-e1",
        timeout_s=5,
    )
    report["witnesses"]["execution_crashed_event"] = (
        json.dumps(crashed_ev) if crashed_ev else "ABSENT"
    )

    if crashed_ev is not None:
        residue_ref = crashed_ev["payload"].get("residue_ref")
        report["axis1"] = "PASS"
        report["axis1_detail"] = f"ExecutionCrashed emitted, residue_ref={residue_ref}"
        report["residue_ref"] = residue_ref
    else:
        report["axis1"] = "FAIL"
        report["axis1_detail"] = "ExecutionCrashed not found post-resume"

    if report.get("residue_ref"):
        ref = report["residue_ref"]
        try:
            report["witnesses"]["for_each_ref"] = _git(repo, "for-each-ref", "refs/attempts/1")
            sha = _git(repo, "rev-parse", ref)
            report["witnesses"]["rev_parse_residue_ref"] = sha
            report["witnesses"]["log_residue_commit"] = _git(repo, "log", "-1", "--format=%s", sha)
        except RuntimeError as e:
            report["witnesses"]["residue_ref_git_error"] = str(e)

    ie = poll_event_log(event_log_path,
                         lambda e: e.get("type") == "IssueActivated" and e.get("issue_id") == "1",
                         timeout_s=1)
    if ie:
        report["witnesses"]["issue_activated_base_commit"] = ie["payload"].get("base_commit")
    report["witnesses"]["head_after_recovery"] = _git(repo, "rev-parse", "HEAD")

    if not tree_kill:
        if child_alive_pre_kill and reaped_line_present:
            report["axis2"] = "PASS"
            report["axis2_detail"] = (
                "pre-kill tasklist showed child PRESENT and resume stdout carries "
                "the reaped-orphan line"
            )
        else:
            report["axis2"] = "INCONCLUSIVE"
            report["axis2_detail"] = (
                "pre-kill alive but reaped-orphan line missing post-resume "
                "(post-kill race)"
            )
    else:
        if child_alive_pre_kill and not child_alive_post_kill and not reaped_line_present \
                and crashed_ev is not None:
            report["axis2"] = "PASS"
            report["axis2_detail"] = (
                "discriminator negative confirmed: alive pre-kill, absent post-/T-kill, "
                "no reaped-orphan line, ExecutionCrashed still emitted"
            )
        else:
            report["axis2"] = "INCONCLUSIVE"
            report["axis2_detail"] = "discriminator run did not land the clean negative shape"

    return report


def _run_live_with_retry(root: Path, base_name: str, *, tree_kill: bool,
                          max_attempts: int = 3) -> dict:
    attempts = []
    for i in range(1, max_attempts + 1):
        rep = _run_live_scenario(root, f"{base_name}_attempt{i}", tree_kill=tree_kill)
        attempts.append(rep)
        if rep.get("axis2") != "INCONCLUSIVE":
            break
    final = dict(attempts[-1])
    final["attempts_summary"] = [
        {"name": a["name"], "axis1": a.get("axis1"), "axis2": a.get("axis2"),
         "axis2_detail": a.get("axis2_detail")}
        for a in attempts
    ]
    final["attempt_count"] = len(attempts)
    return final


def run_row_a_live(root: Path) -> dict:
    return _run_live_with_retry(root, "row_a_live", tree_kill=False)


def run_t_discriminator_live(root: Path) -> dict:
    return _run_live_with_retry(root, "t_discriminator_live", tree_kill=True)


# ── Row B — fixture, real git, no real claude ────────────────────────────
def fixture_row_b(root: Path) -> dict:
    report: dict = {"witnesses": {}}
    base = init_scratch_repo(root, "fixture_row_b", seed_files={"work.py": "x = 1\n"})
    repo = base / "repo"
    adapter = GitCliAdapter(repo)
    log = EventLog(base / "events.jsonl")
    base_commit = _git(repo, "rev-parse", "agent-work")

    log.append(Event(EventType.ISSUE_CREATED, issue_id="1", run_id=RUN_ID,
                      payload={"source": "fixture", "title": "row-b"}))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="1", run_id=RUN_ID,
                      payload={"base_commit": base_commit}))
    log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="1", execution_id="1-e1",
                      run_id=RUN_ID,
                      payload={"spawn_reason": "initial", "engine": "fixture",
                               "pid": os.getpid()}))

    adapter.checkout_branch("issue/1", create_from=base_commit)
    # NOT *.tmp / *.ignored — those match init_scratch_repo's own .gitignore, which
    # would make this edit invisible to git status/add and defeat the whole point.
    (repo / "residue_marker.txt").write_text("uncommitted crash residue\n", encoding="utf-8")

    proj, rec_report = recover(
        log, is_execution_alive=lambda _xid: False,
        **bind_reconciler(adapter, "agent-work"),
    )
    report["witnesses"]["recover_checks_run"] = rec_report.checks_run
    report["witnesses"]["recover_orphans_crashed"] = rec_report.orphans_crashed

    events_after_crash = list(EventLog(base / "events.jsonl").replay())
    crashed = [ev for ev in events_after_crash
               if ev.type is EventType.EXECUTION_CRASHED and ev.execution_id == "1-e1"]
    assert crashed, "fixture_row_b: ExecutionCrashed(1-e1) not emitted"
    residue_ref_1 = crashed[0].payload.get("residue_ref")
    assert residue_ref_1, "fixture_row_b: 1-e1 crashed without a residue_ref"
    report["residue_ref_e1"] = residue_ref_1

    def _emit(ev: Event) -> None:
        eid = log.append(ev)
        persisted = Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                           execution_id=ev.execution_id, run_id=ev.run_id, ts=ev.ts,
                           event_id=eid)
        proj.apply(persisted)

    _emit(Event(EventType.EXECUTION_SPAWNED, issue_id="1", execution_id="1-e2",
                run_id=RUN_ID,
                payload={"spawn_reason": "retry", "engine": "fixture", "pid": os.getpid()}))

    adapter.checkout_branch("issue/1", create_from=base_commit)
    (repo / "work.py").write_text("x = 2\n", encoding="utf-8")
    end = adapter.snapshot_commit("work 1-e2")
    adapter.set_attempt_ref("1", "1-e2", end)
    _emit(Event(EventType.EXECUTION_FINISHED, issue_id="1", execution_id="1-e2",
                run_id=RUN_ID,
                payload={"start_commit": base_commit, "end_commit": end,
                         "exit_status": 0, "pid": os.getpid()}))
    _emit(Event(EventType.VALIDATION_PASSED, issue_id="1", execution_id="1-e2",
                run_id=RUN_ID, payload={"validated_commit": end, "gate_results": []}))
    _emit(Event(EventType.REVIEW_APPROVED, issue_id="1", execution_id="1-e2",
                run_id=RUN_ID, payload={"reviewed_commit": end, "reviewer_provider": "fixture",
                                        "verdict": "APPROVE"}))

    cfg = _config_object(repo, base / "events.jsonl")
    budget = BudgetManager(max_executions_per_run=10, hard_stop_proxy_cost_per_run_usd=100.0)
    orch = Orchestrator(cfg=cfg, log=log, proj=proj, adapter=adapter,
                         engine=None, validator=None, reviewer=None, budget=budget,
                         artifacts_dir=base / "artifacts", run_id=RUN_ID)

    for _ in range(3):  # CommitIntent -> CommitCreated -> IssueCompleted+GC
        ex = proj.latest_execution("1")
        orch._commit_sequence("1", ex)

    log.close()

    refs_after = _git(repo, "for-each-ref", "refs/attempts/1",
                       "--format=%(refname) %(objectname)")
    report["witnesses"]["for_each_ref_after_completion"] = refs_after
    rp = _git(repo, "rev-parse", residue_ref_1)
    report["witnesses"]["rev_parse_e1_residue_ref"] = rp
    log_msg = _git(repo, "log", "-1", "--format=%s", rp)
    report["witnesses"]["log_e1_residue_commit_message"] = log_msg
    fsck = _git(repo, "fsck", "--unreachable")
    report["witnesses"]["fsck_unreachable"] = fsck
    mb = subprocess.run(["git", "merge-base", "--is-ancestor", end, "agent-work"], cwd=repo)
    report["witnesses"]["merge_base_is_ancestor_e2_end_vs_agent_work_exit"] = mb.returncode

    e1_ref_survives = "refs/attempts/1/1-e1" in refs_after
    e2_ref_gone = "refs/attempts/1/1-e2" not in refs_after
    e1_not_dangling = rp[:12] not in fsck

    report["assertions"] = {
        "e1_residue_ref_survives": e1_ref_survives,
        "e2_ref_gc_d": e2_ref_gone,
        "e1_residue_not_dangling": e1_not_dangling,
        "e2_end_commit_ancestor_of_agent_work": mb.returncode == 0,
    }
    assert e1_ref_survives, f"fixture_row_b FAILED: e1 residue ref missing after GC: {refs_after}"
    assert e2_ref_gone, f"fixture_row_b FAILED: e2 ref not GC'd: {refs_after}"
    assert e1_not_dangling, f"fixture_row_b FAILED: e1 residue commit is dangling: {fsck}"
    assert mb.returncode == 0, "fixture_row_b FAILED: e2 end_commit not an ancestor of agent-work"
    report["status"] = "PASS"
    return report


# ── Row C — fixture, real git, two sub-cases ─────────────────────────────
def fixture_row_c(root: Path) -> dict:
    report: dict = {"sub_cases": {}}

    for sub_case, pre_merge in (("merge_already_landed", True), ("merge_not_landed", False)):
        base = init_scratch_repo(root, f"fixture_row_c_{sub_case}",
                                  seed_files={"work.py": "x = 1\n"})
        repo = base / "repo"
        adapter = GitCliAdapter(repo)
        log = EventLog(base / "events.jsonl")
        base_commit = _git(repo, "rev-parse", "agent-work")

        log.append(Event(EventType.ISSUE_CREATED, issue_id="1", run_id=RUN_ID,
                          payload={"source": "fixture", "title": "row-c"}))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="1", run_id=RUN_ID,
                          payload={"base_commit": base_commit}))
        log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="1", execution_id="1-e1",
                          run_id=RUN_ID,
                          payload={"spawn_reason": "initial", "engine": "fixture",
                                   "pid": os.getpid()}))

        adapter.checkout_branch("issue/1", create_from=base_commit)
        (repo / "work.py").write_text("x = 2\n", encoding="utf-8")
        end = adapter.snapshot_commit("work 1-e1")
        adapter.set_attempt_ref("1", "1-e1", end)
        log.append(Event(EventType.EXECUTION_FINISHED, issue_id="1", execution_id="1-e1",
                          run_id=RUN_ID,
                          payload={"start_commit": base_commit, "end_commit": end,
                                   "exit_status": 0, "pid": os.getpid()}))
        log.append(Event(EventType.VALIDATION_PASSED, issue_id="1", execution_id="1-e1",
                          run_id=RUN_ID, payload={"validated_commit": end, "gate_results": []}))
        log.append(Event(EventType.REVIEW_APPROVED, issue_id="1", execution_id="1-e1",
                          run_id=RUN_ID, payload={"reviewed_commit": end,
                                                  "reviewer_provider": "fixture",
                                                  "verdict": "APPROVE"}))
        log.append(Event(EventType.COMMIT_INTENT, issue_id="1", execution_id="1-e1",
                          run_id=RUN_ID, payload={"end_commit": end, "target_branch": "agent-work"}))

        pre_merged_commit = None
        if pre_merge:
            pre_merged_commit = adapter.merge_to("agent-work", end, "merge 1")

        recover(log, is_execution_alive=lambda _xid: False,
                **bind_reconciler(adapter, "agent-work"))
        log.close()

        events = list(EventLog(base / "events.jsonl").replay())
        created = [ev for ev in events
                   if ev.type is EventType.COMMIT_CREATED and ev.execution_id == "1-e1"]
        assert len(created) == 1, (
            f"fixture_row_c[{sub_case}] FAILED: expected exactly 1 CommitCreated, "
            f"got {len(created)}")
        backfilled = created[0].payload.get("backfilled")
        assert backfilled == pre_merge, (
            f"fixture_row_c[{sub_case}] FAILED: backfilled={backfilled}, expected {pre_merge}")

        merge_log = subprocess.run(
            ["git", "log", "agent-work", "-1", "--format=%H %P"],
            cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
        event_log_tail = "\n".join(
            json.dumps({"event_id": ev.event_id, "type": ev.type.value,
                        "execution_id": ev.execution_id, "payload": ev.payload})
            for ev in events
        )

        report["sub_cases"][sub_case] = {
            "pre_merged_commit": pre_merged_commit,
            "backfilled": backfilled,
            "expected_backfilled": pre_merge,
            "commit_created_count": len(created),
            "git_log_agent_work": merge_log,
            "event_log_tail": event_log_tail,
            "status": "PASS",
        }

    report["status"] = "PASS"
    return report


# ── Row E — fixture, real git + stubbed engine through real Orchestrator ─
class _FakeEngineRowE:
    """Same shape as tests/unit/test_loop.py's FakeEngine (result_fn(xid) ->
    EngineResult), extended to perform a REAL deterministic file edit as a side
    effect so downstream git witnesses (merge-base, git show diffs) are real,
    not fabricated. No real `claude` call — this is what makes Row E's fixture
    cheap enough to self-test every session."""

    def __init__(self, edits: dict[str, tuple[str, str]]):
        self.edits = edits  # execution_id -> (relative_path, new_content)

    def run(self, xid, prompt_file, workspace):
        from runtime.engine.claude_headless import EngineResult
        relpath, content = self.edits[xid]
        (Path(workspace) / relpath).write_text(content, encoding="utf-8")
        return EngineResult(exit_status=0, timed_out=False, duration_s=0.01,
                             usage={"dollars": 0.0}, num_turns=1,
                             transcript_path=Path("t.jsonl"), stderr_tail="")


class _FakeValidatorRowE:
    def validate(self, workspace, validated_commit, execution_id):
        from runtime.validation.runner import ValidationResult
        return ValidationResult(
            passed=True, validated_commit=validated_commit,
            per_command=[{"name": "fixture", "passed": True, "duration_s": 0.0,
                          "log_path": "x"}],
        )


class _FakeReviewerRowE:
    name = "fixture"

    def review(self, pack):
        from runtime.reviewer.base import ReviewVerdict
        return ReviewVerdict(execution_id=pack.execution_id,
                              reviewed_commit=pack.reviewed_commit,
                              provider="fixture", verdict="APPROVE")


def fixture_row_e(root: Path) -> dict:
    report: dict = {"witnesses": {}}
    shared_seed = (
        "def bug_a():\n    return 'unfixed-a'\n\n\n"
        "def bug_b():\n    return 'unfixed-b'\n"
    )
    base = init_scratch_repo(root, "fixture_row_e", seed_files={"shared.py": shared_seed})
    repo = base / "repo"
    adapter = GitCliAdapter(repo)
    log = EventLog(base / "events.jsonl")

    log.append(Event(EventType.ISSUE_CREATED, issue_id="8", run_id=RUN_ID,
                      payload={"source": "fixture", "title": "fix bug_a"}))
    log.append(Event(EventType.ISSUE_CREATED, issue_id="9", run_id=RUN_ID,
                      payload={"source": "fixture", "title": "fix bug_b"}))
    proj = StateProjection().rebuild(log.replay())

    fixed_a = shared_seed.replace("'unfixed-a'", "'fixed-a'")
    fixed_b = shared_seed.replace("'unfixed-b'", "'fixed-b'")
    engine = _FakeEngineRowE({
        "8-e1": ("shared.py", fixed_a),   # abandoned — never merges (crashed before use)
        "8-e2": ("shared.py", fixed_a),
        "9-e1": ("shared.py", fixed_b),
    })
    cfg = _config_object(repo, base / "events.jsonl")
    budget = BudgetManager(max_executions_per_run=10, hard_stop_proxy_cost_per_run_usd=100.0)
    orch = Orchestrator(cfg=cfg, log=log, proj=proj, adapter=adapter,
                         engine=engine, validator=_FakeValidatorRowE(),
                         reviewer=_FakeReviewerRowE(), budget=budget,
                         artifacts_dir=base / "artifacts", run_id=RUN_ID)

    issue = orch._next_actionable()
    assert issue == "8", f"fixture_row_e: expected issue 8 first, got {issue}"
    orch.step(issue)                       # PENDING -> ACTIVE (IssueActivated)
    issue = orch._next_actionable()
    assert issue == "8"
    orch.step(issue)                       # ACTIVE, ex=None -> ExecutionSpawned(8-e1)

    report["witnesses"]["events_before_crash"] = [
        ev.type.value for ev in EventLog(base / "events.jsonl").replay()
    ]

    # Simulate the crash: real production check-1 path, not a re-implementation.
    proj, _rec_report = recover(log, is_execution_alive=lambda _xid: False,
                                 **bind_reconciler(adapter, "agent-work"))
    crashed = [ev for ev in EventLog(base / "events.jsonl").replay()
               if ev.type is EventType.EXECUTION_CRASHED and ev.execution_id == "8-e1"]
    assert crashed, "fixture_row_e: ExecutionCrashed(8-e1) not emitted"
    report["witnesses"]["execution_crashed_8e1_residue_ref"] = crashed[0].payload.get("residue_ref")

    orch.proj = proj  # rebind to recover()'s freshly-replayed projection
    guard = 0
    while True:
        issue = orch._next_actionable()
        if issue is None:
            break
        orch.step(issue)
        guard += 1
        assert guard < 50, "fixture_row_e: runaway loop, no terminal state reached"

    events = list(EventLog(base / "events.jsonl").replay())
    report["witnesses"]["full_event_log"] = [
        f"{ev.event_id} {ev.type.value} issue={ev.issue_id} exec={ev.execution_id}"
        for ev in events
    ]

    issue8_terminal_id = max(
        ev.event_id for ev in events
        if ev.issue_id == "8" and ev.type in (EventType.ISSUE_COMPLETED, EventType.ISSUE_ESCALATED)
    )
    # IssueCreated("9") is deliberately emitted up front (backlog entry) — that is
    # NOT the scheduling claim under test. The matrix's claim is about ACTIVATION
    # (loop.py:112-122's _next_actionable never returning a PENDING issue while
    # another is ACTIVE), so the relevant "first event" excludes IssueCreated.
    issue9_first_non_created_id = min(
        (ev.event_id for ev in events
         if ev.issue_id == "9" and ev.type is not EventType.ISSUE_CREATED),
        default=None,
    )
    assert issue9_first_non_created_id is not None, (
        "fixture_row_e: issue 9 never activated (no post-creation event at all)")
    assert issue9_first_non_created_id > issue8_terminal_id, (
        f"fixture_row_e FAILED: issue 9's first post-creation event "
        f"({issue9_first_non_created_id}) is not after issue 8's terminal event "
        f"({issue8_terminal_id}) — sequential-scheduling claim falsified")
    issue9_first_id = issue9_first_non_created_id

    issue9_activated = next(ev for ev in events
                             if ev.issue_id == "9" and ev.type is EventType.ISSUE_ACTIVATED)
    issue9_base = issue9_activated.payload["base_commit"]
    issue8_completed = next(ev for ev in events
                             if ev.issue_id == "8" and ev.type is EventType.COMMIT_CREATED)
    issue8_merge = issue8_completed.payload["merge_commit"]

    mb = subprocess.run(["git", "merge-base", "--is-ancestor", issue8_merge, issue9_base],
                         cwd=repo)
    report["witnesses"]["merge_base_is_ancestor_issue8_merge_vs_issue9_base_exit"] = mb.returncode
    report["witnesses"]["git_show_issue9_base_shared_py"] = subprocess.run(
        ["git", "show", f"{issue9_base}:shared.py"], cwd=repo, capture_output=True, text=True,
    ).stdout
    report["witnesses"]["shared_py_pre_run_seed"] = shared_seed

    assert mb.returncode == 0, (
        "fixture_row_e FAILED: issue 8's merge is not an ancestor of issue 9's base "
        "— chaining claim falsified")

    log.close()
    report["status"] = "PASS"
    report["issue8_terminal_event_id"] = issue8_terminal_id
    report["issue9_first_event_id"] = issue9_first_id
    return report


# ── CLI entry ─────────────────────────────────────────────────────────
def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "item9-harness"
    live = "--live" in sys.argv[2:]
    root.mkdir(parents=True, exist_ok=True)

    print("=== fixture_row_b ===")
    print(json.dumps(fixture_row_b(root), indent=2, default=str))

    print("=== fixture_row_c ===")
    print(json.dumps(fixture_row_c(root), indent=2, default=str))

    print("=== fixture_row_e ===")
    print(json.dumps(fixture_row_e(root), indent=2, default=str))

    if live:
        print("=== run_row_a_live ===")
        print(json.dumps(run_row_a_live(root), indent=2, default=str))

        print("=== run_t_discriminator_live ===")
        print(json.dumps(run_t_discriminator_live(root), indent=2, default=str))

    print("\nALL REQUESTED SCENARIOS COMPLETED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
