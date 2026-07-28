"""GitCliAdapter — the v1 RepositoryAdapter over the git CLI.

Every git call goes through ``_git`` (cwd-pinned, prompt-disabled, timed,
identity-injected). The object-database merge (``merge_to``) never touches
the worktree, so a crashed merge can only ever be "ref moved or not",
distinguishable by ``is_ancestor`` — doc 02 §4.2's witness (see docs/11
§1.3). Windows note: paths via pathlib; never assume ``/`` separators.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from .adapter import MergeConflictError, RepoError, RepositoryAdapter

# merge-tree --write-tree (the object-DB merge) needs git >= 2.38 (Oct 2022).
_MIN_GIT = (2, 38)

# Identity injected per-invocation so commits never depend on the target
# repo's user.name/user.email config (which may be unset).
_IDENTITY = [
    "-c", "user.name=issue-runtime",
    "-c", "user.email=runtime@local",
]


class GitCliAdapter(RepositoryAdapter):
    def __init__(
        self,
        repo_path: Path | str,
        ref_namespace: str = "refs/attempts",
        *,
        timeout_seconds: float = 60.0,
    ):
        self.repo_path = Path(repo_path)
        self.ns = ref_namespace.rstrip("/")
        self.timeout = timeout_seconds
        if not (self.repo_path / ".git").exists():
            # A worktree checkout uses a .git FILE, not dir; both pass exists().
            raise RepoError(f"not a git repository: {self.repo_path}")
        self._check_git_version()
        # Resolve the real git dir once (handles .git-file worktrees).
        self._git_dir = Path(
            self._git("rev-parse", "--git-dir").stdout.strip()
        )
        if not self._git_dir.is_absolute():
            self._git_dir = self.repo_path / self._git_dir

    # ── the one runner ───────────────────────────────────────────────
    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"  # never hang waiting on auth
        try:
            proc = subprocess.run(
                ["git", *_IDENTITY, *args],
                cwd=self.repo_path,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise RepoError(f"git {' '.join(args)} timed out after {self.timeout}s") from e
        except OSError as e:
            raise RepoError(f"git not runnable: {e}") from e
        if check and proc.returncode != 0:
            raise RepoError(
                f"git {' '.join(args)} failed (rc={proc.returncode}): "
                f"{proc.stderr.strip()}"
            )
        return proc

    def _checkpoint(self, name: str) -> None:
        """Instrumentation seam between a multi-step git operation's
        internal boundaries. Production: no-op. The crash harness overrides
        it to inject an uncatchable kill mid-``snapshot_commit`` /
        ``merge_to``, exercising windows that a timed external kill cannot
        reliably land inside a single git subprocess."""

    def _check_git_version(self) -> None:
        out = self._git("version").stdout.strip()  # "git version 2.53.0.windows.1"
        parts = out.split()
        nums = parts[2].split(".") if len(parts) >= 3 else []
        try:
            found = (int(nums[0]), int(nums[1]))
        except (IndexError, ValueError):
            raise RepoError(f"cannot parse git version from {out!r}")
        if found < _MIN_GIT:
            raise RepoError(
                f"git {found[0]}.{found[1]} < required "
                f"{_MIN_GIT[0]}.{_MIN_GIT[1]} (merge-tree --write-tree); "
                f"upgrade git or file an ADR for a worktree-merge fallback"
            )

    # ── read-only witnesses ──────────────────────────────────────────
    def current_commit(self) -> str:
        return self._git("rev-parse", "HEAD").stdout.strip()

    def head_of(self, branch: str) -> Optional[str]:
        p = self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}",
                      check=False)
        out = p.stdout.strip()
        return out or None

    def is_dirty(self) -> bool:
        # --porcelain includes untracked (??) and excludes ignored by default.
        return bool(self._git("status", "--porcelain").stdout.strip())

    def commit_exists(self, sha: str) -> bool:
        return self._git("cat-file", "-e", f"{sha}^{{commit}}",
                         check=False).returncode == 0

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        p = self._git("merge-base", "--is-ancestor", ancestor, descendant,
                      check=False)
        if p.returncode == 0:
            return True
        if p.returncode == 1:
            return False
        raise RepoError(
            f"merge-base --is-ancestor {ancestor} {descendant} "
            f"errored (rc={p.returncode}): {p.stderr.strip()}"
        )

    def ref_target(self, ref: str) -> Optional[str]:
        p = self._git("rev-parse", "--verify", "--quiet", ref, check=False)
        out = p.stdout.strip()
        return out or None

    def list_attempt_refs(self, issue_id: Optional[str] = None) -> dict[str, str]:
        pattern = self.ns if issue_id is None else f"{self.ns}/{issue_id}"
        p = self._git("for-each-ref", "--format=%(refname)%09%(objectname)",
                      pattern)
        out: dict[str, str] = {}
        for line in p.stdout.splitlines():
            if "\t" in line:
                name, sha = line.split("\t", 1)
                out[name] = sha
        return out

    def diff(self, base: str, head: str) -> str:
        return self._git("diff", base, head).stdout

    def find_merge_commit(self, target_branch: str, merged: str) -> Optional[str]:
        head = self.head_of(target_branch)
        if head is None:
            return None
        merged_full = self._git("rev-parse", "--verify", "--quiet", merged,
                                check=False).stdout.strip()
        if not merged_full:
            return None
        # One pass: each line is "<merge> <parent1> <parent2>".
        p = self._git("rev-list", "--first-parent", "--merges", "--parents",
                      target_branch)
        for line in p.stdout.splitlines():
            toks = line.split()
            if len(toks) >= 3 and toks[2] == merged_full:
                return toks[0]
        return None

    # ── mutations ────────────────────────────────────────────────────
    def checkout_branch(self, branch: str, *, create_from: Optional[str] = None) -> None:
        if self.is_dirty():
            raise RepoError(
                f"refuse to checkout {branch}: worktree dirty "
                f"(upstream sequencing bug — residue must be preserved first)"
            )
        if create_from is not None:
            self._git("checkout", "-B", branch, create_from)
        else:
            self._git("checkout", branch)

    def snapshot_commit(self, message: str) -> Optional[str]:
        if not self.is_dirty():
            return None  # never an empty commit (check-then-act)
        self._git("add", "-A")
        self._checkpoint("snapshot:post-add")
        # --no-verify: the target repo's hooks must not block or mutate
        # evidence preservation (our validation gates are the real hooks).
        self._git("commit", "--no-verify", "-m", message)
        return self.current_commit()

    def set_attempt_ref(self, issue_id: str, execution_id: str, commit: str) -> str:
        ref = f"{self.ns}/{issue_id}/{execution_id}"
        target = self._git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}",
                           check=False).stdout.strip()
        if not target:
            raise RepoError(f"set_attempt_ref: {commit} is not a commit")
        current = self.ref_target(ref)
        if current == target:
            return ref  # X -> X no-op (idempotent)
        if current is not None and not self.is_ancestor(current, target):
            raise RepoError(
                f"set_attempt_ref {ref}: refuse to regress evidence "
                f"({current[:12]} is not an ancestor of {target[:12]})"
            )
        self._git("update-ref", ref, target)
        return ref

    def reset_hard(self, commit: str) -> None:
        self._git("reset", "--hard", commit)   # clears MERGE_HEAD too
        self._git("clean", "-fd")              # untracked files a reset leaves

    def merge_to(self, target_branch: str, commit: str, message: str) -> str:
        target_head = self.head_of(target_branch)
        if target_head is None:
            raise RepoError(f"merge_to: target branch {target_branch!r} does not exist")
        cur = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if cur == target_branch:
            raise RepoError(
                f"merge_to: HEAD is on {target_branch}; moving a checked-out "
                f"branch's ref desyncs index and worktree"
            )
        # 1. compute the merged tree in the object DB (no worktree touch)
        mt = self._git("merge-tree", "--write-tree", target_head, commit,
                       check=False)
        if mt.returncode == 1:
            raise MergeConflictError(
                f"merge_to: {commit} conflicts with {target_branch} "
                f"(tamper signal in v1): {mt.stdout.strip()}"
            )
        if mt.returncode != 0:
            raise RepoError(
                f"merge-tree failed (rc={mt.returncode}): {mt.stderr.strip()}"
            )
        tree = mt.stdout.splitlines()[0].strip()
        self._checkpoint("merge:post-tree")
        # 2. seal the two-parent merge commit
        mc = self._git("commit-tree", tree, "-p", target_head, "-p", commit,
                       "-m", message).stdout.strip()
        self._checkpoint("merge:post-commit-tree")
        # 3. atomically advance the branch ref, CAS on its old value
        self._git("update-ref", f"refs/heads/{target_branch}", mc, target_head)
        self._checkpoint("merge:post-update-ref")
        return mc

    def delete_attempt_ref(self, issue_id: str, execution_id: str) -> bool:
        ref = f"{self.ns}/{issue_id}/{execution_id}"
        if self.ref_target(ref) is None:
            return False
        self._git("update-ref", "-d", ref)
        return True

    def recover_workspace(self) -> list[str]:
        repairs: list[str] = []
        lock = self._git_dir / "index.lock"
        if lock.exists():
            lock.unlink()
            repairs.append("removed stale .git/index.lock")
        # Our merges never touch the worktree, so MERGE_HEAD should never
        # appear; clear it defensively if a prior tool left one behind.
        merge_head = self._git_dir / "MERGE_HEAD"
        if merge_head.exists():
            for name in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE"):
                f = self._git_dir / name
                if f.exists():
                    f.unlink()
            repairs.append("aborted in-progress merge state")
        return repairs
