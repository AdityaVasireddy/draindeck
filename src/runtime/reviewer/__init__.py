"""Reviewer seam (ADR-05/08): abstracted day one because two real providers
exist (Qwen-on-Ollama, Claude) and the call shape is trivial —
prompt → structured verdict. The reviewer NEVER sees git or the repo; it
receives only a diff + issue + guidelines + validation output (doc 02 §5)."""
from .base import (
    ReviewerError,
    ReviewerProvider,
    ReviewerUnavailableError,
    ReviewParseError,
    ReviewPack,
    ReviewVerdict,
)

__all__ = [
    "ReviewerProvider",
    "ReviewPack",
    "ReviewVerdict",
    "ReviewerError",
    "ReviewerUnavailableError",
    "ReviewParseError",
]
