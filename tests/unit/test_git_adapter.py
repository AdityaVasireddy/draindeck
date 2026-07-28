"""GitCliAdapter unit tests — every idempotency law from docs/11 §1.2 and
the crash-window re-entry points b2/b4/b5/b6 from §2.1, exercised against
real temp git repositories.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.repo.adapter import MergeConflictError, RepoError  # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter               # noqa: E402


def _run(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"setup git {args} failed: {p.stderr}")
    return p.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A temp repo on branch 'trunk' with one seed commit."""
    _run(tmp_path, "init", "-b", "trunk")
    _run(tmp_path, "config", "core.autocrlf", "false")
    (tmp_path / "README").write_text("seed\n")
    _run(tmp_path, "add", "-A")
    _run(tmp_path, "commit", "-m", "seed")
    return tmp_path


@pytest.fixture()
def adapter(repo: Path) -> GitCliAdapter:
    return GitCliAdapter(repo)


# ── construction / version ───────────────────────────────────────────
def test_rejects_non_repo(tmp_path: Path):
    with pytest.raises(RepoError):
        GitCliAdapter(tmp_path / "nope")


def test_construction_ok(adapter: GitCliAdapter):
    assert adapter.current_commit()


# ── read-only witnesses ──────────────────────────────────────────────
def test_head_of(adapter: GitCliAdapter):
    assert adapter.head_of("trunk") == adapter.current_commit()
    assert adapter.head_of("does-not-exist") is None


def test_is_dirty(adapter: GitCliAdapter, repo: Path):
    assert adapter.is_dirty() is False
    (repo / "new.txt").write_text("x")          # untracked
    assert adapter.is_dirty() is True
    adapter.reset_hard("HEAD")
    assert adapter.is_dirty() is False
    (repo / "README").write_text("changed\n")   # tracked modification
    assert adapter.is_dirty() is True


def test_commit_exists(adapter: GitCliAdapter):
    assert adapter.commit_exists(adapter.current_commit())
    assert not adapter.commit_exists("0" * 40)


def test_is_ancestor(adapter: GitCliAdapter, repo: Path):
    base = adapter.current_commit()
    (repo / "a.txt").write_text("a")
    child = adapter.snapshot_commit("c1")
    assert adapter.is_ancestor(base, child)
    assert adapter.is_ancestor(base, base)      # reflexive
    assert not adapter.is_ancestor(child, base)


def test_ref_target(adapter: GitCliAdapter):
    assert adapter.ref_target("refs/heads/trunk") == adapter.current_commit()
    assert adapter.ref_target("refs/attempts/nope/x") is None


def test_diff_derivable(adapter: GitCliAdapter, repo: Path):
    base = adapter.current_commit()
    (repo / "README").write_text("edited\n")
    head = adapter.snapshot_commit("edit")
    d = adapter.diff(base, head)
    assert "edited" in d and "README" in d


# ── snapshot_commit: CONVERGENT ──────────────────────────────────────
def test_snapshot_none_when_clean(adapter: GitCliAdapter):
    assert adapter.snapshot_commit("noop") is None


def test_snapshot_commits_untracked_and_tracked(adapter: GitCliAdapter, repo: Path):
    (repo / "tracked_new.txt").write_text("t")
    sha = adapter.snapshot_commit("snap")
    assert sha and sha == adapter.current_commit()
    assert adapter.is_dirty() is False
    # CONVERGENT: re-running on a now-clean tree returns None.
    assert adapter.snapshot_commit("snap again") is None


# ── set_attempt_ref: the evidence-never-regresses law ────────────────
def test_set_attempt_ref_unset_then_noop(adapter: GitCliAdapter):
    c = adapter.current_commit()
    ref = adapter.set_attempt_ref("042", "042-e1", c)
    assert ref == "refs/attempts/042/042-e1"
    assert adapter.ref_target(ref) == c
    # X -> X is an idempotent no-op.
    assert adapter.set_attempt_ref("042", "042-e1", c) == ref


def test_set_attempt_ref_fast_forward(adapter: GitCliAdapter, repo: Path):
    c1 = adapter.current_commit()
    adapter.set_attempt_ref("042", "042-e1", c1)
    (repo / "more.txt").write_text("m")
    c2 = adapter.snapshot_commit("more")
    # residue re-snapshotted on top: X -> Y where X is an ancestor of Y.
    adapter.set_attempt_ref("042", "042-e1", c2)
    assert adapter.ref_target("refs/attempts/042/042-e1") == c2


def test_set_attempt_ref_regression_raises(adapter: GitCliAdapter, repo: Path):
    c1 = adapter.current_commit()
    (repo / "more.txt").write_text("m")
    c2 = adapter.snapshot_commit("more")
    adapter.set_attempt_ref("042", "042-e1", c2)
    # ref is at c2; moving it back to its ancestor c1 regresses evidence.
    # Law uses is_ancestor(current=c2, target=c1) which is False → reject.
    with pytest.raises(RepoError):
        adapter.set_attempt_ref("042", "042-e1", c1)


def test_set_attempt_ref_rejects_non_commit(adapter: GitCliAdapter):
    with pytest.raises(RepoError):
        adapter.set_attempt_ref("042", "042-e1", "0" * 40)


# ── reset_hard: clean -fd earns its keep ─────────────────────────────
def test_reset_hard_removes_untracked(adapter: GitCliAdapter, repo: Path):
    base = adapter.current_commit()
    (repo / "README").write_text("dirty\n")   # tracked change
    (repo / "junk.txt").write_text("junk")     # untracked
    adapter.reset_hard(base)
    assert adapter.is_dirty() is False
    assert not (repo / "junk.txt").exists()    # clean -fd removed it
    assert (repo / "README").read_text() == "seed\n"


# ── checkout_branch ──────────────────────────────────────────────────
def test_checkout_branch_create_from(adapter: GitCliAdapter):
    base = adapter.current_commit()
    adapter.checkout_branch("issue/042", create_from=base)
    assert adapter.head_of("issue/042") == base


def test_checkout_refuses_dirty(adapter: GitCliAdapter, repo: Path):
    (repo / "x.txt").write_text("x")
    with pytest.raises(RepoError):
        adapter.checkout_branch("issue/042", create_from="HEAD")


# ── merge_to: object-DB merge ────────────────────────────────────────
def test_merge_to_makes_two_parent_merge(adapter: GitCliAdapter, repo: Path):
    trunk_head = adapter.head_of("trunk")
    adapter.checkout_branch("issue/042", create_from=trunk_head)
    (repo / "feature.txt").write_text("feat")
    end = adapter.snapshot_commit("feature work")
    mc = adapter.merge_to("trunk", end, "merge 042")
    # target advanced and now contains end_commit
    assert adapter.head_of("trunk") == mc
    assert adapter.is_ancestor(end, "trunk")
    assert adapter.is_ancestor(trunk_head, "trunk")
    # find_merge_commit locates it by second parent
    assert adapter.find_merge_commit("trunk", end) == mc


def test_merge_to_refuses_when_head_on_target(adapter: GitCliAdapter, repo: Path):
    # HEAD is on trunk here.
    (repo / "f.txt").write_text("f")
    end = adapter.snapshot_commit("work on trunk directly")
    # Move HEAD back so 'end' is a sibling reachable object but HEAD==trunk.
    with pytest.raises(RepoError):
        adapter.merge_to("trunk", end, "should refuse")


def test_find_merge_commit_absent(adapter: GitCliAdapter):
    assert adapter.find_merge_commit("trunk", adapter.current_commit()) is None


# ── delete_attempt_ref: idempotent, execution-scoped GC (ADR-15 Am1) ──
def test_delete_attempt_ref_is_execution_scoped(adapter: GitCliAdapter):
    c = adapter.current_commit()
    adapter.set_attempt_ref("042", "042-e1", c)
    adapter.set_attempt_ref("042", "042-e2", c)
    assert adapter.delete_attempt_ref("042", "042-e1") is True
    # sibling execution's ref MUST survive — this is the item-14 fix
    assert adapter.list_attempt_refs("042") == {"refs/attempts/042/042-e2": c}
    assert adapter.delete_attempt_ref("042", "042-e1") is False   # idempotent
    assert adapter.delete_attempt_ref("042", "042-e2") is True
    assert adapter.list_attempt_refs("042") == {}


def test_list_attempt_refs_scoped(adapter: GitCliAdapter):
    c = adapter.current_commit()
    adapter.set_attempt_ref("042", "042-e1", c)
    adapter.set_attempt_ref("043", "043-e1", c)
    assert set(adapter.list_attempt_refs("042")) == {"refs/attempts/042/042-e1"}
    assert len(adapter.list_attempt_refs()) == 2


# ── recover_workspace: stale lock (b4) ───────────────────────────────
def test_recover_workspace_removes_stale_lock(adapter: GitCliAdapter, repo: Path):
    lock = repo / ".git" / "index.lock"
    lock.write_text("")                       # simulate crash mid add/commit
    repairs = adapter.recover_workspace()
    assert any("index.lock" in r for r in repairs)
    assert not lock.exists()
    # after repair, snapshot works again (b4 converges to b2's path)
    (repo / "resumed.txt").write_text("r")
    assert adapter.snapshot_commit("resumed") is not None


def test_recover_workspace_noop_when_clean(adapter: GitCliAdapter):
    assert adapter.recover_workspace() == []


# ── crash-window re-entry (b5, b6) ───────────────────────────────────
def test_b5_snapshot_done_ref_not_set(adapter: GitCliAdapter, repo: Path):
    """b5: snapshot committed, killed before set_attempt_ref. On restart
    the tree is clean at a residue commit != base; recovery captures it
    via current_commit()."""
    base = adapter.current_commit()
    (repo / "residue.txt").write_text("res")
    sha = adapter.snapshot_commit("crash residue")
    assert sha is not None and sha != base
    # re-entry: snapshot now returns None, residue == current_commit()
    residue = adapter.snapshot_commit("retry") or adapter.current_commit()
    assert residue == sha
    ref = adapter.set_attempt_ref("042", "042-e1", residue)
    assert adapter.ref_target(ref) == sha


def test_b6_ref_already_set_reentrant(adapter: GitCliAdapter, repo: Path):
    """b6: set_attempt_ref completed, killed before the ExecutionCrashed
    append. On restart the ref exists; preservation short-circuits."""
    (repo / "residue.txt").write_text("res")
    sha = adapter.snapshot_commit("crash residue")
    ref = adapter.set_attempt_ref("042", "042-e1", sha)
    # re-entry sees the ref already there and returns it unchanged
    assert adapter.ref_target(ref) == sha
    assert adapter.set_attempt_ref("042", "042-e1", sha) == ref
