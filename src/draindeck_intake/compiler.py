"""Deterministic, parser-safe rendering of canonical issues."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .model import CanonicalIssueV1

MANAGED_MARKER = "<!-- draindeck-intake:managed v1 -->"

_ISSUE_HEADING = re.compile(r"^\s*##\s+")
_DEPENDS = re.compile(r"^\s*Depends-On\s*:", re.IGNORECASE)
_ACCEPTANCE = re.compile(r"^\s*###\s+Acceptance\s*$", re.IGNORECASE)


class CompileError(ValueError):
    """Canonical issues cannot be compiled without ambiguity."""


def _quote_structural_body_line(line: str) -> str:
    if (
        _ISSUE_HEADING.match(line)
        or _DEPENDS.match(line)
        or _ACCEPTANCE.match(line)
    ):
        return f"> {line}"
    return line


def _render_issue(issue: CanonicalIssueV1) -> str:
    lines = [f"## {issue.issue_id}: {issue.title}"]
    body_lines = [_quote_structural_body_line(line) for line in issue.body.splitlines()]
    if issue.body:
        lines.extend(("", *body_lines))

    metadata = [f"Source: {issue.source_kind}:{issue.source_id}"]
    if issue.source_url is not None:
        metadata.append(f"Source-URL: {issue.source_url}")
    if issue.source_state is not None:
        metadata.append(f"Source-State: {issue.source_state}")
    if issue.updated_at is not None:
        metadata.append(f"Updated-At: {issue.updated_at}")
    if issue.labels:
        metadata.append(f"Labels: {', '.join(sorted(issue.labels))}")
    if issue.depends_on:
        metadata.append(f"Depends-On: {', '.join(issue.depends_on)}")
    lines.extend(("", *metadata))
    if issue.acceptance_criteria:
        lines.append("### Acceptance")
        lines.extend(f"- {criterion}" for criterion in issue.acceptance_criteria)
    return "\n".join(lines)


def compile_issues_md(issues: Iterable[CanonicalIssueV1]) -> str:
    """Render issues in stable ID order with exactly one trailing LF."""
    ordered = sorted(tuple(issues), key=lambda issue: issue.issue_id)
    seen: set[str] = set()
    for issue in ordered:
        if issue.issue_id in seen:
            raise CompileError(f"duplicate canonical issue id: {issue.issue_id}")
        seen.add(issue.issue_id)
    blocks = [MANAGED_MARKER, *(_render_issue(issue) for issue in ordered)]
    return "\n\n".join(blocks) + "\n"
