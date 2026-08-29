from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.compiler import compile_issues_md
from draindeck_intake.issues_md import IssuesMdSource
from draindeck_intake.model import CanonicalIssueV1
from draindeck_intake.sources import (
    CollectionError,
    IssuePage,
    SourceError,
    collect_issues,
)
from runtime.queue.issues_md import parse


def canonical(issue_id: str) -> CanonicalIssueV1:
    return CanonicalIssueV1(
        issue_id=issue_id,
        source_kind="issues-md",
        source_id=issue_id,
        title=f"Issue {issue_id}",
    )


class FakeSource:
    name = "fake"

    def __init__(self, pages: dict[str | None, IssuePage]) -> None:
        self.pages = pages
        self.calls: list[tuple[str | None, int]] = []

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage:
        self.calls.append((cursor, limit))
        return self.pages[cursor]


def test_collector_follows_opaque_cursors_and_preserves_page_order() -> None:
    source = FakeSource(
        {
            None: IssuePage((canonical("one"), canonical("two")), "opaque-a"),
            "opaque-a": IssuePage((canonical("three"),), None),
        }
    )

    result = collect_issues(source, page_size=2, max_issues=3)

    assert [item.issue_id for item in result] == ["one", "two", "three"]
    assert source.calls == [(None, 2), ("opaque-a", 2)]


def test_collector_rejects_invalid_bounds_before_calling_source() -> None:
    source = FakeSource({})
    for page_size, max_issues in ((0, 1), (101, 1), (1, 0), (True, 1)):
        with pytest.raises(CollectionError, match="page_size|max_issues"):
            collect_issues(source, page_size=page_size, max_issues=max_issues)
    assert source.calls == []


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ({None: IssuePage((canonical("one"),), "")}, "empty cursor"),
        (
            {
                None: IssuePage((canonical("one"),), "a"),
                "a": IssuePage((canonical("two"),), "a"),
            },
            "cursor cycle",
        ),
        ({None: IssuePage((), "more")}, "empty continuation"),
        (
            {None: IssuePage((canonical("one"), canonical("two")), None)},
            "page larger",
        ),
        (
            {
                None: IssuePage((canonical("one"),), "next"),
                "next": IssuePage((canonical("one"),), None),
            },
            "duplicate",
        ),
        (
            {
                None: IssuePage((canonical("one"),), "next"),
                "next": IssuePage((canonical("two"),), None),
            },
            "maximum",
        ),
    ],
)
def test_collector_fails_closed_on_untrusted_pagination(
    pages: dict[str | None, IssuePage], message: str
) -> None:
    page_size = 1 if message in {"page larger", "maximum"} else 2
    max_issues = 1 if message == "maximum" else 10
    with pytest.raises(CollectionError, match=message):
        collect_issues(FakeSource(pages), page_size=page_size, max_issues=max_issues)


def test_local_source_round_trip_and_optional_prefix(tmp_path: Path) -> None:
    source_file = tmp_path / "Issues.md"
    source_file.write_text(
        """Preamble ignored.
## 7: Local issue
Body line
Depends-On: 6
### Acceptance
- Works locally

## 6: Foundation
Foundation body
""",
        encoding="utf-8",
        newline="",
    )
    source = IssuesMdSource(source_file, id_prefix="local")

    collected = collect_issues(source, page_size=1, max_issues=5)
    rendered = compile_issues_md(collected)
    parsed = parse(rendered)

    assert [item.id for item in parsed] == ["local-6", "local-7"]
    by_id = {item.id: item for item in parsed}
    assert by_id["local-7"].depends_on == ["local-6"]
    assert by_id["local-7"].acceptance_criteria == ["Works locally"]
    assert "Body line" in by_id["local-7"].body


def test_local_source_rejects_oversized_invalid_and_colliding_input(
    tmp_path: Path,
) -> None:
    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(b"x" * 11)
    with pytest.raises(SourceError, match="maximum"):
        IssuesMdSource(oversized, max_input_bytes=10).fetch_page(cursor=None, limit=1)

    malformed = tmp_path / "malformed.md"
    malformed.write_text("## malformed heading\n", encoding="utf-8")
    with pytest.raises(SourceError, match="invalid Issues.md"):
        IssuesMdSource(malformed).fetch_page(cursor=None, limit=1)

    collision = tmp_path / "collision.md"
    collision.write_text("## A: Upper\n## a: Lower\n", encoding="utf-8")
    with pytest.raises(CollectionError, match="duplicate"):
        collect_issues(
            IssuesMdSource(collision, id_prefix="local"),
            page_size=10,
            max_issues=10,
        )
