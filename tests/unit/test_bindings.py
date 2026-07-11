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
    log2 = EventLog(log.path)
    _, rep2 = recover(log2, **bind_reconciler(adapter, TRUNK))
    assert rep2.orphans_crashed == []                        # nothing to redo


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


def test_check2_idempotent_second_pass(world):
    repo, adapter, log, base = world
    adapter.checkout_branch("issue/042", create_from=base)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature")
    _intent_log(log, base, end)
    recover(log, **bind_reconciler(adapter, TRUNK))
    log2 = EventLog(log.path)
    _, rep2 = recover(log2, **bind_reconciler(adapter, TRUNK))
    assert EventType.COMMIT_CREATED.value not in rep2.emitted
    assert len(_created_events(log2)) == 1                    # no double-commit


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
