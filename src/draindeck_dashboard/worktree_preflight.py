"""Doc 33 Part A: clean-worktree launch preflight.

A Dashboard-side, **read-only** check that the target git worktree is clean
before a run is launched against it -- catching the reproduced failure (an
untracked ``Issues.md`` that would make the runtime's checkout fail
``CHECKOUT_FAILED`` and block the queue) *before* any subprocess is spawned,
with a typed, actionable reason.

Reuses this project's single worktree-status classifier via the read-only
``runtime.repo.git_adapter.read_worktree_status`` witness -- never a second,
reimplemented ``git status`` parser, and never the mutation-capable
``GitCliAdapter`` class itself (the architecture gate permits only the
read-only name here, mirroring the workspace-lease process-identity carve-out).
Never writes, checks out, merges, or repairs anything.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from runtime.config import ConfigError, load_config
from runtime.repo.git_adapter import WorktreeStatus, read_worktree_status

from .errors import DashboardApiError
from .repositories import get_repository

# The exact operator-facing alert copy (doc 33 Part C / spec). Kept here so the
# advisory endpoint and any refusal share one wording.
PREFLIGHT_DIRTY_MESSAGE = (
    "Commit or clean all tracked and untracked changes, including Issues.md, "
    "before running issues."
)


class WorktreeNotCleanError(DashboardApiError):
    status_code = 409

    def __init__(self, message: str = PREFLIGHT_DIRTY_MESSAGE, **kw) -> None:
        super().__init__("WORKTREE_NOT_CLEAN", message, **kw)


@dataclass(frozen=True)
class WorktreePreflight:
    clean: bool
    blocking: bool
    untracked_count: int
    detail: str

    @property
    def message(self) -> str:
        return "clean" if self.clean else PREFLIGHT_DIRTY_MESSAGE

    def to_response(self) -> dict:
        return {
            "clean": self.clean,
            "blocking": self.blocking,
            "untrackedCount": self.untracked_count,
            "message": self.message,
            "detail": self.detail,
        }


def _repo_path_for(conn, repo_id: int) -> str:
    """Resolves the target repository worktree path from the registered,
    canonical config -- the same config the runtime itself validates."""
    registration = get_repository(conn, repo_id)  # NotFoundError if unknown
    config_path = registration["configPath"]
    if config_path is None:
        raise DashboardApiError(
            "CONFIG_NOT_REGISTERED",
            "repository has no validated canonical config; cannot check worktree",
            status_code=409,
        )
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        raise DashboardApiError("CONFIG_INVALID", str(exc), status_code=409) from exc
    return str(cfg.project.repository)


def evaluate_worktree_preflight(
    conn, repo_id: int, *,
    status_probe: Callable[[str], WorktreeStatus] = read_worktree_status,
) -> WorktreePreflight:
    """Returns a truthful, read-only worktree-cleanliness result. "Clean"
    means no tracked/staged/deleted/renamed/conflicted entries AND zero
    untracked files (an untracked ``Issues.md`` is dirty). Fails **closed**:
    if the status cannot be determined (not a git repo, git error), the result
    is not-clean with a diagnostic detail -- never an exception and never a
    false "clean"."""
    repo_path = _repo_path_for(conn, repo_id)
    try:
        status = status_probe(repo_path)
    except Exception as exc:  # noqa: BLE001 - fail closed on any probe failure
        return WorktreePreflight(
            clean=False, blocking=True, untracked_count=0,
            detail=f"worktree status unavailable: {exc}",
        )
    clean = not status.blocking and status.untracked_count == 0
    if clean:
        detail = "clean"
    elif status.blocking:
        detail = "tracked/staged/deleted/renamed/conflicted changes present"
    else:
        detail = f"{status.untracked_count} untracked file(s) present"
    return WorktreePreflight(
        clean=clean, blocking=status.blocking,
        untracked_count=status.untracked_count, detail=detail,
    )
