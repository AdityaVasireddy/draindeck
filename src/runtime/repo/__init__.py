"""Repository adapter — the single enforcement point for ADR-20's
repository-agnosticism. Everything that touches the target repo's git or
filesystem goes through RepositoryAdapter; nothing under src/ names a
path, branch, or command literal (those live only in config.yaml).
"""
from .adapter import (
    MergeConflictError,
    RepoError,
    RepositoryAdapter,
)
from .git_adapter import GitCliAdapter

__all__ = [
    "RepositoryAdapter",
    "RepoError",
    "MergeConflictError",
    "GitCliAdapter",
]
