"""Shared source protocol and bounded pagination collector."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .model import CanonicalIssueV1

MAX_PAGE_SIZE = 100


class SourceError(RuntimeError):
    """A source could not produce trustworthy canonical issues."""


class CollectionError(SourceError):
    """A source violated bounded pagination or uniqueness rules."""


@dataclass(frozen=True, slots=True)
class IssuePage:
    issues: tuple[CanonicalIssueV1, ...]
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.issues, (str, bytes)):
            raise CollectionError("issues must be a collection")
        try:
            issues = tuple(self.issues)
        except TypeError as exc:
            raise CollectionError("issues must be iterable") from exc
        if any(not isinstance(issue, CanonicalIssueV1) for issue in issues):
            raise CollectionError("issues must contain canonical issues")
        object.__setattr__(self, "issues", issues)
        if self.next_cursor is not None and not isinstance(self.next_cursor, str):
            raise CollectionError("next_cursor must be a string or null")


class IssueSource(Protocol):
    name: str

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage: ...


def _bounded_integer(value: object, *, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CollectionError(f"{field} must be a positive integer")
    if maximum is not None and value > maximum:
        raise CollectionError(f"{field} cannot exceed {maximum}")
    return value


def collect_issues(
    source: IssueSource, *, page_size: int = 100, max_issues: int = 1_000
) -> tuple[CanonicalIssueV1, ...]:
    """Collect a finite source snapshot while distrusting its pagination."""
    page_size = _bounded_integer(
        page_size, field="page_size", maximum=MAX_PAGE_SIZE
    )
    max_issues = _bounded_integer(max_issues, field="max_issues")
    collected: list[CanonicalIssueV1] = []
    issue_ids: set[str] = set()
    used_cursors: set[str] = set()
    cursor: str | None = None

    while True:
        if cursor is not None:
            if cursor in used_cursors:
                raise CollectionError("source cursor cycle detected")
            used_cursors.add(cursor)
        page = source.fetch_page(cursor=cursor, limit=page_size)
        if not isinstance(page, IssuePage):
            raise CollectionError("source returned an invalid page")
        if len(page.issues) > page_size:
            raise CollectionError("source returned a page larger than requested")
        if not page.issues and page.next_cursor is not None:
            raise CollectionError("source returned an empty continuation page")

        for issue in page.issues:
            if issue.issue_id in issue_ids:
                raise CollectionError(
                    f"source returned duplicate canonical issue id: {issue.issue_id}"
                )
            issue_ids.add(issue.issue_id)
            collected.append(issue)
            if len(collected) > max_issues:
                raise CollectionError("source exceeded the maximum issue count")

        next_cursor = page.next_cursor
        if next_cursor is None:
            return tuple(collected)
        if not next_cursor:
            raise CollectionError("source returned an empty cursor")
        if next_cursor == cursor or next_cursor in used_cursors:
            raise CollectionError("source cursor cycle detected")
        cursor = next_cursor
