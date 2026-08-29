"""Immutable canonical issue contracts for provider-independent intake."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Literal
from urllib.parse import urlsplit

IssueSourceKind = Literal["issues-md", "github", "jira", "linear"]

_ISSUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_INVALID_SEGMENT = re.compile(r"[^a-z0-9_-]+")
_SEPARATOR_RUN = re.compile(r"[-_]{2,}")
_SOURCE_KINDS = frozenset({"issues-md", "github", "jira", "linear"})
_LINE_BOUNDARIES = frozenset("\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029")

MAX_TITLE_CHARS = 500
MAX_BODY_BYTES = 256 * 1024
MAX_SOURCE_ID_CHARS = 2_048
MAX_URL_CHARS = 2_048
MAX_ITEMS = 100
MAX_ITEM_CHARS = 2_000
MAX_SOURCE_STATE_CHARS = 256
MAX_UPDATED_AT_CHARS = 128


class IssueValidationError(ValueError):
    """A canonical issue violates its fail-closed public contract."""


def _single_line(value: object, *, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise IssueValidationError(f"{field} must be a string")
    if not value or value.strip() != value:
        raise IssueValidationError(f"{field} must be non-empty and trimmed")
    if any(character in _LINE_BOUNDARIES for character in value):
        raise IssueValidationError(f"{field} must be a single line")
    if len(value) > maximum:
        raise IssueValidationError(f"{field} exceeds {maximum} characters")
    return value


def _optional_single_line(
    value: object, *, field: str, maximum: int
) -> str | None:
    if value is None:
        return None
    return _single_line(value, field=field, maximum=maximum)


def _tuple_of_lines(
    values: Iterable[object], *, field: str, maximum_items: int = MAX_ITEMS
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise IssueValidationError(f"{field} must be a collection of strings")
    try:
        result = tuple(
            _single_line(value, field=field, maximum=MAX_ITEM_CHARS)
            for value in values
        )
    except TypeError as exc:
        raise IssueValidationError(f"{field} must be iterable") from exc
    if len(result) > maximum_items:
        raise IssueValidationError(f"{field} exceeds {maximum_items} items")
    if len(set(result)) != len(result):
        raise IssueValidationError(f"{field} contains duplicates")
    return result


def validate_issue_id(value: object, *, field: str = "issue_id") -> str:
    if not isinstance(value, str) or not _ISSUE_ID.fullmatch(value):
        raise IssueValidationError(
            f"{field} must match [A-Za-z0-9][A-Za-z0-9_-]*"
        )
    return value


def normalize_id_segment(value: object) -> str:
    """Normalize one visible provider identifier segment without hiding loss."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise IssueValidationError("ID segment must be text or an integer")
    normalized = _INVALID_SEGMENT.sub("-", str(value).strip().lower())
    normalized = _SEPARATOR_RUN.sub("-", normalized).strip("-_")
    if not normalized:
        raise IssueValidationError("ID segment becomes empty after normalization")
    return normalized


def make_scoped_issue_id(prefix: object, *segments: object) -> str:
    if not segments:
        raise IssueValidationError("at least one provider ID segment is required")
    result = "-".join(normalize_id_segment(value) for value in (prefix, *segments))
    return validate_issue_id(result)


@dataclass(frozen=True, slots=True)
class CanonicalIssueV1:
    """Provider-neutral immutable issue accepted by the compiler."""

    issue_id: str
    source_kind: IssueSourceKind
    source_id: str
    title: str
    body: str = ""
    depends_on: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    source_url: str | None = None
    source_state: str | None = None
    updated_at: str | None = None
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise IssueValidationError("schema_version must be exactly 1")
        object.__setattr__(self, "issue_id", validate_issue_id(self.issue_id))
        if self.source_kind not in _SOURCE_KINDS:
            raise IssueValidationError(f"source_kind is unsupported: {self.source_kind!r}")
        object.__setattr__(
            self,
            "source_id",
            _single_line(
                self.source_id, field="source_id", maximum=MAX_SOURCE_ID_CHARS
            ),
        )
        object.__setattr__(
            self,
            "title",
            _single_line(self.title, field="title", maximum=MAX_TITLE_CHARS),
        )
        if not isinstance(self.body, str):
            raise IssueValidationError("body must be a string")
        if len(self.body.encode("utf-8")) > MAX_BODY_BYTES:
            raise IssueValidationError(f"body exceeds {MAX_BODY_BYTES} UTF-8 bytes")

        dependencies = _tuple_of_lines(self.depends_on, field="depends_on")
        dependencies = tuple(validate_issue_id(item, field="depends_on") for item in dependencies)
        if self.issue_id in dependencies:
            raise IssueValidationError("depends_on cannot contain issue_id")
        object.__setattr__(self, "depends_on", dependencies)
        object.__setattr__(
            self,
            "acceptance_criteria",
            _tuple_of_lines(self.acceptance_criteria, field="acceptance_criteria"),
        )
        object.__setattr__(
            self, "labels", _tuple_of_lines(self.labels, field="labels")
        )

        if self.source_url is not None:
            source_url = _single_line(
                self.source_url, field="source_url", maximum=MAX_URL_CHARS
            )
            parsed = urlsplit(source_url)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise IssueValidationError(
                    "source_url must be HTTPS without embedded credentials"
                )
            object.__setattr__(self, "source_url", source_url)

        object.__setattr__(
            self,
            "source_state",
            _optional_single_line(
                self.source_state,
                field="source_state",
                maximum=MAX_SOURCE_STATE_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "updated_at",
            _optional_single_line(
                self.updated_at, field="updated_at", maximum=MAX_UPDATED_AT_CHARS
            ),
        )
