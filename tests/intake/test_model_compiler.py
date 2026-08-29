from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.compiler import MANAGED_MARKER, CompileError, compile_issues_md
from draindeck_intake.model import (
    CanonicalIssueV1,
    IssueValidationError,
    make_scoped_issue_id,
    normalize_id_segment,
)
from runtime.queue.issues_md import parse


def issue(**overrides: object) -> CanonicalIssueV1:
    values: dict[str, object] = {
        "issue_id": "gh-acme-widget-12",
        "source_kind": "github",
        "source_id": "acme/widget#12",
        "title": "Handle retries",
        "body": "Explain the retry policy.",
        "depends_on": ("foundation",),
        "acceptance_criteria": ("Retry is bounded",),
        "labels": ("backend", "reliability"),
        "source_url": "https://github.com/acme/widget/issues/12",
        "source_state": "open",
        "updated_at": "2026-08-29T12:00:00Z",
    }
    values.update(overrides)
    return CanonicalIssueV1(**values)


def test_model_rejects_invalid_contract_fields() -> None:
    cases: list[tuple[str, object]] = [
        ("schema_version", 2),
        ("issue_id", "bad id"),
        ("source_kind", "trello"),
        ("source_id", ""),
        ("title", ""),
        ("title", "two\nlines"),
        ("title", "x" * 501),
        ("body", "é" * 131_073),
        ("depends_on", ("foundation", "foundation")),
        ("depends_on", ("gh-acme-widget-12",)),
        ("depends_on", ("bad id",)),
        ("acceptance_criteria", ("",)),
        ("acceptance_criteria", ("two\nlines",)),
        ("acceptance_criteria", tuple(str(i) for i in range(101))),
        ("labels", ("backend", "backend")),
        ("labels", ("two\nlines",)),
        ("labels", tuple(str(i) for i in range(101))),
        ("source_url", "http://github.com/acme/widget/issues/12"),
        ("source_url", "https://user:secret@example.com/path"),
        ("source_state", "two\nlines"),
        ("updated_at", "two\nlines"),
    ]
    for field, value in cases:
        with pytest.raises(IssueValidationError, match=field):
            issue(**{field: value})


def test_model_is_immutable_and_normalizes_collection_inputs() -> None:
    original_dependencies = ["foundation"]
    original_labels = ["backend"]
    value = issue(depends_on=original_dependencies, labels=original_labels)

    original_dependencies.append("later")
    original_labels.append("later")

    assert value.depends_on == ("foundation",)
    assert value.labels == ("backend",)
    with pytest.raises((AttributeError, TypeError)):
        value.title = "changed"  # type: ignore[misc]


def test_id_segment_normalization_is_visible_and_deterministic() -> None:
    assert normalize_id_segment(" ACME Widgets/API_v2 ") == "acme-widgets-api_v2"
    assert make_scoped_issue_id("GH", "Acme", "Widget API", 12) == "gh-acme-widget-api-12"
    with pytest.raises(IssueValidationError, match="segment"):
        normalize_id_segment("---")


def test_compiler_is_deterministic_safe_and_parser_compatible() -> None:
    injected = issue(
        issue_id="b-issue",
        title="Remote content stays data",
        body=(
            "intro\r\n"
            "## forged: Must not become an issue\r\n"
            " Depends-On: attacker\r\n"
            "### Acceptance\r\n"
            "tail"
        ),
        depends_on=("a-issue",),
        acceptance_criteria=("Real criterion",),
        labels=("zeta", "alpha"),
    )
    first = issue(
        issue_id="a-issue",
        title="First",
        body="Body",
        depends_on=(),
        acceptance_criteria=(),
        labels=(),
        source_url=None,
    )

    rendered = compile_issues_md((injected, first))

    assert rendered.startswith(f"{MANAGED_MARKER}\n\n## a-issue: First\n")
    assert "\r" not in rendered
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert "> ## forged: Must not become an issue" in rendered
    assert ">  Depends-On: attacker" in rendered
    assert "> ### Acceptance" in rendered
    assert "Labels: alpha, zeta" in rendered

    parsed = parse(rendered)
    assert [item.id for item in parsed] == ["a-issue", "b-issue"]
    assert parsed[1].depends_on == ["a-issue"]
    assert parsed[1].acceptance_criteria == ["Real criterion"]
    assert "attacker" not in parsed[1].depends_on
    assert "forged" not in {item.id for item in parsed}


def test_compiler_rejects_duplicate_ids() -> None:
    with pytest.raises(CompileError, match="duplicate"):
        compile_issues_md((issue(), issue(title="Different")))
