"""Reconciler seam binding tests — the crash-window tables from docs/11
§2 exercised against a real temp git repo and a real EventLog through the
production recovery path (recover(log, **bind_reconciler(adapter, ...))).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.log import EventLog                         # noqa: E402
from runtime.events.schema import Event, EventType              # noqa: E402
from runtime.recovery.bindings import (                          # noqa: E402
    ReconcilerTamperError,
    bind_reconciler,
)
from runtime.recovery.reconciler import recover                 # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter              # noqa: E402
from runtime.state.model import ExecutionState                  # noqa: E402

TRUNK = "trunk"


def _run(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"setup git {args} failed: {p.stderr}")
    return p.stdout.strip()


@pytest.fixture()
def world(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init", "-b", TRUNK)
    _run(repo, "config", "core.autocrlf", "false")
    (repo / "README").write_text("seed\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "seed")
    adapter = GitCliAdapter(repo)
    log = EventLog(tmp_path / "events.jsonl")
    base = adapter.current_commit()
    return repo, adapter, log, base


def _activate(log: EventLog, base: str, issue: str = "042") -> None:
    log.append(Event(EventType.ISSUE_CREATED, issue_id=issue,
                     payload={"title": issue}))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id=issue,
                     payload={"base_commit": base}))
    log.append(Event(EventType.EXECUTION_SPAWNED, issue_id=issue,
                     execution_id=f"{issue}-e1",
                     payload={"spawn_reason": "initial", "pid": 1}))


def _crashed_events(log: EventLog):
    return [e for e in log.replay() if e.type is EventType.EXECUTION_CRASHED]


def _created_events(log: EventLog):
    return [e for e in log.replay() if e.type is EventType.COMMIT_CREATED]


# ── check 1: b-windows ───────────────────────────────────────────────
def test_b1_clean_at_base_no_residue(world):
    repo, adapter, log, base = world
    _activate(log, base)
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert rep.orphans_crashed == ["042-e1"]
    assert proj.executions["042-e1"].state is ExecutionState.CRASHED
    crashed = _crashed_events(log)
    assert crashed[0].payload["residue_ref"] is None      # nothing happened


def test_b2_dirty_tree_preserves_residue(world):
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "work.py").write_text("half-written")          # tracked-to-be
    (repo / "scratch.tmp").write_text("junk")               # untracked
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    ref = _crashed_events(log)[0].payload["residue_ref"]
    assert ref == "refs/attempts/042/042-e1"
    assert adapter.ref_target(ref) is not None              # real commit
    # residue is derivable as a diff from base (ADR-15)
    assert "work.py" in adapter.diff(base, ref)


def test_b5_snapshot_done_ref_not_set(world):
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "work.py").write_text("done")
    residue_sha = adapter.snapshot_commit("engine residue")  # b5: committed
    assert residue_sha and residue_sha != base
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    ref = _crashed_events(log)[0].payload["residue_ref"]
    assert adapter.ref_target(ref) == residue_sha            # captured via HEAD


def test_b6_ref_already_set_reentrant(world):
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "work.py").write_text("done")
    residue_sha = adapter.snapshot_commit("engine residue")
    ref_pre = adapter.set_attempt_ref("042", "042-e1", residue_sha)  # b6
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    ref = _crashed_events(log)[0].payload["residue_ref"]
    assert ref == ref_pre
    assert adapter.ref_target(ref) == residue_sha            # unchanged


def test_check1_idempotent_second_pass(world):
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "work.py").write_text("x")
    recover(log, **bind_reconciler(adapter, TRUNK))
    log.close()
    with EventLog(log.path) as log2:
        _, rep2 = recover(log2, **bind_reconciler(adapter, TRUNK))
        assert rep2.orphans_crashed == []                    # nothing to redo


def test_check1_never_witnesses_finished(world):
    """Even with a snapshot commit that looks like a finished end_commit,
    recovery emits ExecutionCrashed, never ExecutionFinished (doc 03)."""
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "work.py").write_text("looks complete")
    adapter.snapshot_commit("looks like end_commit")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert EventType.EXECUTION_CRASHED.value in rep.emitted
    assert EventType.EXECUTION_FINISHED.value not in rep.emitted


# ── check 2: c-windows ───────────────────────────────────────────────
def _intent_log(log: EventLog, base: str, end: str, issue: str = "042") -> None:
    _activate(log, base, issue)
    xid = f"{issue}-e1"
    log.append(Event(EventType.EXECUTION_FINISHED, issue_id=issue, execution_id=xid,
                     payload={"start_commit": base, "end_commit": end,
                              "exit_status": 0, "pid": 1}))
    log.append(Event(EventType.VALIDATION_PASSED, issue_id=issue, execution_id=xid,
                     payload={"validated_commit": end, "gate_results": []}))
    log.append(Event(EventType.REVIEW_APPROVED, issue_id=issue, execution_id=xid,
                     payload={"reviewed_commit": end, "verdict": "APPROVE"}))
    log.append(Event(EventType.COMMIT_INTENT, issue_id=issue, execution_id=xid,
                     payload={"end_commit": end, "target_branch": TRUNK}))


def test_c1_unmerged_redo(world):
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    _intent_log(log, base, end)                              # c1: trunk unmoved
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    created = _created_events(log)
    assert len(created) == 1
    assert created[0].payload["backfilled"] is False        # recovery merged
    mc = created[0].payload["merge_commit"]
    assert adapter.head_of(TRUNK) == mc
    assert adapter.is_ancestor(end, TRUNK)


def test_c3_already_merged_backfill(world):
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    mc = adapter.merge_to(TRUNK, end, "merge 042")           # c3: merge happened
    _intent_log(log, base, end)
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    created = _created_events(log)
    assert len(created) == 1
    assert created[0].payload["backfilled"] is True          # only the fact
    assert created[0].payload["merge_commit"] == mc


def test_c1_checked_out_target_collision_redo(world):
    """Doc 26 regression: HEAD sitting on target_branch (the repo's normal
    at-rest state between runs) when check 2 needs to redo an unmerged
    merge must not hit merge_to's checked-out-target guard. Recovery must
    reconstruct issue/{issue} from base_commit, move HEAD there, then
    merge exactly as test_c1_unmerged_redo does."""
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    adapter.checkout_branch(TRUNK)                        # simulates the collision
    _intent_log(log, base, end)                            # c1: trunk unmoved
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    created = _created_events(log)
    assert len(created) == 1
    assert created[0].payload["backfilled"] is False        # recovery merged
    mc = created[0].payload["merge_commit"]
    assert adapter.head_of(TRUNK) == mc
    assert adapter.is_ancestor(end, TRUNK)
    # HEAD moved off target onto the reconstructed issue branch. Check 3
    # (which runs after check 2 in the same recover() call) then re-pins it
    # to end_commit, since ACCEPTED-with-commit_created falls through
    # _expected_commit's VALIDATING/REVIEWING/ACCEPTED branch (ADR-25).
    assert adapter.current_commit() == end
    assert adapter.head_of("issue/042") == end


def test_check2_idempotent_second_pass(world):
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    _intent_log(log, base, end)
    recover(log, **bind_reconciler(adapter, TRUNK))
    log.close()
    with EventLog(log.path) as log2:
        _, rep2 = recover(log2, **bind_reconciler(adapter, TRUNK))
        assert EventType.COMMIT_CREATED.value not in rep2.emitted
        assert len(_created_events(log2)) == 1                # no double-commit


def test_check2_tamper_raises(world):
    """end is on trunk but no merge commit carries it — a human ff/squash.
    Recovery refuses to forge the join key."""
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    _run(repo, "update-ref", f"refs/heads/{TRUNK}", end)      # fast-forward, no merge
    _intent_log(log, base, end)
    with pytest.raises(ReconcilerTamperError):
        recover(log, **bind_reconciler(adapter, TRUNK))


# ── check 3: dirty workspace ─────────────────────────────────────────
def test_check3_reviewing_stays_at_end_commit(world):
    """VALIDATING/REVIEWING must keep pinning at end_commit exactly as
    before ADR-25 — both states are designed to be re-runnable/re-callable
    against the produced tree after a crash (state/model.py's
    ExecutionState comments: VALIDATING "re-runnable against pinned
    tree", REVIEWING "re-callable; verdicts cacheable by (issue, tree)").
    ADR-25 narrows its start_commit fallback to ACCEPTED-without-
    CommitCreated only (next test) — this test guards against
    re-widening it back to REVIEWING/VALIDATING, which would validate/
    review the wrong, pre-execution tree after a restart."""
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")            # lands directly on TRUNK
    log.append(Event(EventType.EXECUTION_FINISHED, issue_id="042", execution_id="042-e1",
                     payload={"start_commit": base, "end_commit": end,
                              "exit_status": 0, "pid": 1}))
    log.append(Event(EventType.VALIDATION_PASSED, issue_id="042", execution_id="042-e1",
                     payload={"validated_commit": end, "gate_results": []}))
    (repo / "planted.txt").write_text("dirty at crash")   # force check 3 to actually run
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert proj.executions["042-e1"].state is ExecutionState.REVIEWING
    assert adapter.current_commit() == end                # pinned at end_commit, not start
    assert adapter.head_of(TRUNK) == end


def test_check3_accepted_no_commit_created_expected_is_start_commit(world):
    """ADR-25 regression (real LUVZ incident, 2026-08-19), narrowed to
    ACCEPTED: while an execution is ACCEPTED (ReviewApproved landed) but
    its CommitCreated has not yet been witnessed — the exact crash window
    a reviewer transport failure followed by a successful retry leaves
    behind — check 3 must reset the checked-out branch back to the
    execution's start_commit, never its unmerged end_commit. The old code
    unconditionally returned end_commit for VALIDATING/REVIEWING/ACCEPTED,
    moving the branch itself onto an unwitnessed commit; check 2 then
    correctly refused to forge a merge for it on every subsequent pass —
    a deterministic re-halt, not a transient failure. CommitIntent/
    CommitCreated are only ever legal in ACCEPTED
    (projections.py::_accepted_view), and ACCEPTED has no outgoing
    transition (state/transitions.py), so this is the only state the
    collision can ever occur in."""
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")            # lands directly on TRUNK
    assert adapter.head_of(TRUNK) == end                 # simulates the crash: branch already moved
    log.append(Event(EventType.EXECUTION_FINISHED, issue_id="042", execution_id="042-e1",
                     payload={"start_commit": base, "end_commit": end,
                              "exit_status": 0, "pid": 1}))
    log.append(Event(EventType.VALIDATION_PASSED, issue_id="042", execution_id="042-e1",
                     payload={"validated_commit": end, "gate_results": []}))
    log.append(Event(EventType.REVIEW_APPROVED, issue_id="042", execution_id="042-e1",
                     payload={"reviewed_commit": end, "verdict": "APPROVE"}))
    proj, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert proj.executions["042-e1"].state is ExecutionState.ACCEPTED
    assert adapter.current_commit() == base               # reset to start_commit, not end
    assert adapter.head_of(TRUNK) == base                  # branch pointer restored, not left on end
    assert adapter.list_attempt_refs("042")                # end still reachable, archived not lost
    # Second pass must be a clean no-op — the old bug made this halt with
    # ReconcilerTamperError on every subsequent run against the same world.
    log.close()
    with EventLog(log.path) as log2:
        _, rep2 = recover(log2, **bind_reconciler(adapter, TRUNK))
        assert rep2.workspace_repairs == []


def test_check3_archives_and_resets(world):
    """Issue ACTIVE, latest execution CRASHED (b7), workspace dirty →
    archive residue, reset to base, no event, repair recorded."""
    repo, adapter, log, base = world
    _activate(log, base)
    log.append(Event(EventType.EXECUTION_CRASHED, issue_id="042",
                     execution_id="042-e1",
                     payload={"residue_ref": None, "last_known_state": "EXECUTING"}))
    (repo / "leftover.txt").write_text("dirty")               # untracked residue
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert adapter.is_dirty() is False                        # reset happened
    assert adapter.current_commit() == base
    assert rep.workspace_repairs                              # not silent
    assert adapter.list_attempt_refs("042")                   # residue archived


def test_check3_clean_workspace_noop(world):
    repo, adapter, log, base = world
    _activate(log, base)
    log.append(Event(EventType.EXECUTION_CRASHED, issue_id="042",
                     execution_id="042-e1",
                     payload={"residue_ref": None, "last_known_state": "EXECUTING"}))
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert rep.workspace_repairs == []                        # already at base


# ── check 3: untracked-file provenance (resolve-item, 2026-08-18) ────
def test_check3_no_active_issue_preserves_preexisting_untracked(world):
    """The real LUVZ incident, reproduced: a legitimate pre-existing
    untracked file (Issues.md) sitting in the target repo with NO active
    Draindeck issue must survive startup reconciliation unchanged — not be
    archived to an attempt ref and swept by clean -fd."""
    repo, adapter, log, base = world
    (repo / "Issues.md").write_text("- [ ] real user content\n")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert (repo / "Issues.md").exists()
    assert (repo / "Issues.md").read_text() == "- [ ] real user content\n"
    assert rep.workspace_repairs == []
    assert adapter.list_attempt_refs() == {}


def test_check3_active_issue_no_execution_preserves_untracked(world):
    """An active issue with no execution spawned yet has no ownership
    baseline either — untracked dirt still must not be touched."""
    repo, adapter, log, base = world
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042", payload={"title": "042"}))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042",
                     payload={"base_commit": base}))
    (repo / "Issues.md").write_text("pre-existing\n")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert (repo / "Issues.md").exists()
    assert rep.workspace_repairs == []


def test_check3_preserves_baseline_but_cleans_new_residue(world):
    """A crashed execution's own baseline (recorded at spawn, before its
    engine could touch anything) protects files that predate it, while a
    file that appeared afterward — genuine crash residue — is still
    archived and cleaned, proving the fix doesn't just disable check 3."""
    repo, adapter, log, base = world
    (repo / "Issues.md").write_text("pre-existing, present before spawn\n")
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042", payload={"title": "042"}))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042",
                     payload={"base_commit": base}))
    log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="042",
                     execution_id="042-e1",
                     payload={"spawn_reason": "initial", "pid": 1,
                              "pre_execution_untracked": ["Issues.md"]}))
    # Crash residue that appeared strictly after spawn.
    (repo / "scratch.tmp").write_text("engine byproduct\n")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert rep.orphans_crashed == ["042-e1"]                  # check 1 ran
    assert (repo / "Issues.md").exists(), \
        "baseline-known pre-existing file must survive"
    assert (repo / "Issues.md").read_text() == "pre-existing, present before spawn\n"
    assert not (repo / "scratch.tmp").exists(), \
        "genuine post-spawn residue must still be cleaned"
    ref = _crashed_events(log)[0].payload["residue_ref"]
    assert ref is not None                                     # residue preserved
    assert "scratch.tmp" in adapter.diff(base, ref)


def test_check3_terminal_issue_no_longer_active_preserves_untracked(world):
    """Once an issue leaves ACTIVE, `_active_issue` finds nothing — the
    prior execution's baseline must not leak into a later, unrelated
    untracked file appearing with no issue in flight at all."""
    repo, adapter, log, base = world
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042", payload={"title": "042"}))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042",
                     payload={"base_commit": base}))
    log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="042",
                     execution_id="042-e1",
                     payload={"spawn_reason": "initial", "pid": 1,
                              "pre_execution_untracked": []}))
    log.append(Event(EventType.EXECUTION_FINISHED, issue_id="042",
                     execution_id="042-e1",
                     payload={"start_commit": base, "end_commit": base,
                              "exit_status": 0, "pid": 1}))
    log.append(Event(EventType.VALIDATION_PASSED, issue_id="042",
                     execution_id="042-e1",
                     payload={"validated_commit": base, "gate_results": []}))
    log.append(Event(EventType.REVIEW_APPROVED, issue_id="042",
                     execution_id="042-e1",
                     payload={"reviewed_commit": base, "verdict": "APPROVE"}))
    log.append(Event(EventType.COMMIT_INTENT, issue_id="042",
                     execution_id="042-e1",
                     payload={"end_commit": base, "target_branch": TRUNK}))
    log.append(Event(EventType.COMMIT_CREATED, issue_id="042",
                     execution_id="042-e1",
                     payload={"merge_commit": base, "target_branch": TRUNK,
                              "backfilled": True}))
    log.append(Event(EventType.ISSUE_COMPLETED, issue_id="042",
                     payload={"reason": "accepted"}))
    (repo / "notes.txt").write_text("added by a human after the issue shipped\n")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert (repo / "notes.txt").exists()
    assert rep.workspace_repairs == []


# ── recover_workspace: stale lock (b4) via the bound seam ────────────
def test_recover_workspace_clears_lock(world):
    repo, adapter, log, base = world
    _activate(log, base)
    (repo / ".git" / "index.lock").write_text("")            # killed mid add/commit
    (repo / "work.py").write_text("residue")
    _, rep = recover(log, **bind_reconciler(adapter, TRUNK))
    assert any("index.lock" in r for r in rep.workspace_repairs)
    # and preservation still proceeded
    assert _crashed_events(log)[0].payload["residue_ref"] is not None
