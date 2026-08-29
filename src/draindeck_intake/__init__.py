"""Optional provider-independent issue intake for Draindeck."""

from .compiler import MANAGED_MARKER, CompileError, compile_issues_md
from .model import (
    CanonicalIssueV1,
    IssueSourceKind,
    IssueValidationError,
    make_scoped_issue_id,
    normalize_id_segment,
)
from .sources import (
    CollectionError,
    IssuePage,
    IssueSource,
    SourceError,
    collect_issues,
)

__all__ = [
    "CanonicalIssueV1",
    "CompileError",
    "CollectionError",
    "IssuePage",
    "IssueSource",
    "IssueSourceKind",
    "IssueValidationError",
    "MANAGED_MARKER",
    "compile_issues_md",
    "collect_issues",
    "make_scoped_issue_id",
    "normalize_id_segment",
    "SourceError",
]
