"""Bounded adapter for an existing local Draindeck Issues.md file."""
from __future__ import annotations

from pathlib import Path

from runtime.queue.issues_md import IssuesParseError, parse

from .model import CanonicalIssueV1, IssueValidationError, make_scoped_issue_id
from .sources import IssuePage, SourceError

DEFAULT_MAX_INPUT_BYTES = 10 * 1024 * 1024


class IssuesMdSource:
    name = "issues-md"

    def __init__(
        self,
        path: str | Path,
        *,
        id_prefix: str | None = None,
        max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
    ) -> None:
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int):
            raise SourceError("max_input_bytes must be a positive integer")
        if max_input_bytes < 1:
            raise SourceError("max_input_bytes must be a positive integer")
        self._path = Path(path)
        self._id_prefix = id_prefix
        self._max_input_bytes = max_input_bytes
        self._issues: tuple[CanonicalIssueV1, ...] | None = None

    def _load(self) -> tuple[CanonicalIssueV1, ...]:
        try:
            with self._path.open("rb") as stream:
                raw = stream.read(self._max_input_bytes + 1)
        except OSError as exc:
            raise SourceError(f"unable to read Issues.md: {exc.__class__.__name__}") from exc
        if len(raw) > self._max_input_bytes:
            raise SourceError("Issues.md exceeds the configured maximum input size")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceError("Issues.md must be valid UTF-8") from exc
        try:
            parsed = parse(text)
            id_map = {
                item.id: (
                    make_scoped_issue_id(self._id_prefix, item.id)
                    if self._id_prefix is not None
                    else item.id
                )
                for item in parsed
            }
            return tuple(
                CanonicalIssueV1(
                    issue_id=id_map[item.id],
                    source_kind="issues-md",
                    source_id=item.id,
                    title=item.title,
                    body=item.body,
                    depends_on=tuple(id_map.get(dep, dep) for dep in item.depends_on),
                    acceptance_criteria=tuple(item.acceptance_criteria),
                )
                for item in parsed
            )
        except (IssuesParseError, IssueValidationError) as exc:
            raise SourceError(f"invalid Issues.md input: {exc}") from exc

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise SourceError("limit must be a positive integer")
        if cursor is None:
            offset = 0
        elif cursor.isascii() and cursor.isdecimal():
            offset = int(cursor)
        else:
            raise SourceError("Issues.md cursor is invalid")
        if self._issues is None:
            self._issues = self._load()
        end = min(offset + limit, len(self._issues))
        next_cursor = str(end) if end < len(self._issues) else None
        return IssuePage(self._issues[offset:end], next_cursor)
