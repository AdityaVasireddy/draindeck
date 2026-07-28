"""RepositoryAdapter — the git/workspace boundary (doc 09 §7, reconciled
against doc 03 §2/§5 and doc 02 §3/§4).

Design stance (see docs/11 §1.1): MECHANISM ONLY, ZERO POLICY. The adapter
never appends events, never reads the event log, never reads config. It is
constructed once from ``config.project.repository`` /
``config.attempts.ref_namespace`` and every other path/branch is a method
argument (ADR-20 — no repo path, branch, or command literal under src/).
Event emission and sequencing stay in ``recovery/`` and the future
orchestrator; the adapter only reports and mutates git state.

Idempotency vocabulary used in the method contracts below:
  * IDEMPOTENT       — re-running lands on the identical result (queries;
                       reset_hard; checkout_branch; set_attempt_ref no-op).
  * CONVERGENT       — re-running after a partial crash reaches a
                       consistent state, though the return value may differ
                       (snapshot_commit returns None once the tree is clean).
  * NOT IDEMPOTENT   — the caller MUST check-then-act (merge_to); recovery
                       and the orchestrator gate it with is_ancestor.

The abandonable/deterministic split (ADR-13) lives one layer up: the
adapter exposes the deterministic, check-then-act primitives that make
crash-safe re-entry possible; it does not decide when to abandon.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class RepoError(RuntimeError):
    """A git command failed or the repo is in an unexpected state. Carries
    the command and stderr; nothing is swallowed."""


class MergeConflictError(RepoError):
    """A merge could not be computed without conflicts. In v1 this is
    structurally a tamper signal (single writer, sequential merges from a
    pinned base), so the orchestrator escalates rather than resolves."""


class RepositoryAdapter(ABC):
    """The contract. ``GitCliAdapter`` is the sole v1 implementation."""

    # ── read-only witnesses (all IDEMPOTENT, no side effects) ────────

    @abstractmethod
    def current_commit(self) -> str:
        """HEAD's commit sha. Used to capture start_commit and to check the
        pin-restore invariant. Raises RepoError on an unborn HEAD."""

    @abstractmethod
    def head_of(self, branch: str) -> Optional[str]:
        """Commit sha at the tip of ``branch``, or None if it does not
        exist. Used for base_commit capture and the check-3 expectation."""

    @abstractmethod
    def is_dirty(self) -> bool:
        """True iff the worktree has tracked modifications OR untracked
        files (ignored files excluded). The check-3 trigger and the I1
        clean-base guard."""

    @abstractmethod
    def commit_exists(self, sha: str) -> bool:
        """True iff ``sha`` resolves to a commit object (doc 09 §7
        verify_commit_exists)."""

    @abstractmethod
    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        """True iff ``ancestor`` is an ancestor of (or equal to)
        ``descendant``. Check 2's witness, verbatim doc 02 §4.2."""

    @abstractmethod
    def ref_target(self, ref: str) -> Optional[str]:
        """Commit sha a fully-qualified ref points at, or None if the ref
        does not exist. Enables idempotent re-entry of residue
        preservation (§2.1 window b6)."""

    @abstractmethod
    def list_attempt_refs(self, issue_id: Optional[str] = None) -> dict[str, str]:
        """Map of {ref_name: commit_sha} under the attempt namespace,
        optionally filtered to one issue. Reconciler + GC support."""

    @abstractmethod
    def diff(self, base: str, head: str) -> str:
        """``git diff base head`` as unified text. Diffs are always derived,
        never stored (ADR-15)."""

    @abstractmethod
    def find_merge_commit(self, target_branch: str, merged: str) -> Optional[str]:
        """The merge commit on ``target_branch``'s first-parent chain whose
        second parent is ``merged``, or None. Supplies
        CommitCreated.merge_commit on the check-2 backfill path (doc 03
        §3 #9). Deterministic because merge_to always makes two-parent,
        no-fast-forward merges."""

    # ── mutations ────────────────────────────────────────────────────

    @abstractmethod
    def checkout_branch(self, branch: str, *, create_from: Optional[str] = None) -> None:
        """Switch to ``branch``. With ``create_from``, force-create it at
        that commit (issue branches cut from a pinned base, doc 02 §3).
        IDEMPOTENT. Pre: worktree clean — a dirty checkout is an upstream
        sequencing bug and raises. The force-reset of an existing branch
        tip is safe only because the transition table preserves attempt
        refs before any reset/re-branch."""

    @abstractmethod
    def snapshot_commit(self, message: str) -> Optional[str]:
        """Stage everything (``add -A``) and commit on the current HEAD;
        return the new sha, or None if the worktree was clean (never an
        empty commit). CONVERGENT: re-running after a completed snapshot
        returns None because the tree is clean, so callers use
        ``snapshot_commit(...) or current_commit()`` for full re-run
        safety. Commits bypass target-repo hooks (--no-verify): evidence
        preservation must not be blockable by the target repo."""

    @abstractmethod
    def set_attempt_ref(self, issue_id: str, execution_id: str, commit: str) -> str:
        """Point ``<ns>/<issue>/<execution>`` at ``commit``; return the ref
        name. Evidence refs must never regress (ADR-15): unset→X ok; X→X
        no-op (IDEMPOTENT); X→Y only if X is an ancestor of Y, else
        RepoError."""

    @abstractmethod
    def reset_hard(self, commit: str) -> None:
        """``reset --hard commit`` AND ``clean -fd`` (untracked files that a
        bare reset leaves behind would break I1). Ignored files survive
        (``-x`` omitted) — unreachable by commits, so the pin is
        unaffected. Also clears in-progress merge state. IDEMPOTENT. Pre
        (orchestrator-sequenced): residue already preserved to a ref."""

    @abstractmethod
    def merge_to(self, target_branch: str, commit: str, message: str) -> str:
        """Merge ``commit`` into ``target_branch`` as a two-parent,
        no-fast-forward merge computed entirely in the object database
        (never touching the worktree); return the merge commit sha.
        NOT IDEMPOTENT — two calls make two merges; the caller MUST
        check-then-act with ``is_ancestor`` first (ADR-13). Pre: HEAD is
        not on ``target_branch``. Raises MergeConflictError on conflict."""

    @abstractmethod
    def delete_attempt_ref(self, issue_id: str, execution_id: str) -> bool:
        """Delete the single attempt ref ``<ns>/<issue_id>/<execution_id>``;
        return True if a ref was removed, False if it did not exist. ADR-15
        Amendment 1: GC is scoped to the COMPLETING execution's own
        now-redundant ref (its content is already reachable via the merge
        it just produced) — never the whole issue, which would collaterally
        delete a crashed sibling execution's only residue anchor.
        IDEMPOTENT (deleting an absent ref is a no-op returning False)."""

    @abstractmethod
    def recover_workspace(self) -> list[str]:
        """Clear stale ``.git/index.lock`` and abort in-progress merge
        state left by a killed git process; return a list of repairs made
        (empty = nothing to repair). Safe ONLY because recovery runs before
        anything is spawned and v1 is single-writer (ADR-04) — no live
        process can legitimately hold these. Called once at the top of
        recovery."""
