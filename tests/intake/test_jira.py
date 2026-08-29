from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.jira import JiraSource, adf_to_text
from draindeck_intake.sources import SourceError


class FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def request_json(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def test_adf_to_text_handles_nested_blocks_hard_breaks_and_null() -> None:
    document = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "First"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "second"},
                ],
            },
            {
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "Item"}],
                            }
                        ],
                    }
                ],
            },
        ],
    }

    assert adf_to_text(None) == ""
    assert adf_to_text(document) == "First\nsecond\nItem"


@pytest.mark.parametrize(
    "document",
    [
        "plain text is not ADF",
        {"type": "doc", "content": "not-a-list"},
        {"type": "doc", "content": [{"type": "text", "text": 3}]},
        {"type": "doc", "content": [{}]},
    ],
)
def test_adf_to_text_rejects_malformed_documents(document: object) -> None:
    with pytest.raises(SourceError, match="ADF"):
        adf_to_text(document)


def test_jira_uses_enhanced_search_and_maps_canonical_issue() -> None:
    transport = FakeTransport(
        {
            "issues": [
                {
                    "key": "ENG-42",
                    "fields": {
                        "summary": "Bound queue retries",
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Do the work"}
                                    ],
                                }
                            ],
                        },
                        "labels": ["backend", "reliability"],
                        "status": {"name": "In Progress"},
                        "updated": "2026-08-29T12:00:00.000+0000",
                    },
                }
            ],
            "nextPageToken": "opaque-next",
            "isLast": False,
        }
    )
    source = JiraSource(
        transport,
        base_url="https://acme.atlassian.net/",
        jql='project = ENG AND status != Done',
        email="operator@example.com",
        api_token="api-token-value",
        id_prefix="jira",
    )

    page = source.fetch_page(cursor=None, limit=50)

    assert page.next_cursor == "opaque-next"
    issue = page.issues[0]
    assert issue.issue_id == "jira-eng-42"
    assert issue.source_id == "ENG-42"
    assert issue.source_url == "https://acme.atlassian.net/browse/ENG-42"
    assert issue.body == "Do the work"
    assert issue.labels == ("backend", "reliability")
    assert issue.source_state == "In Progress"
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://acme.atlassian.net/rest/api/3/search/jql"
    assert call["expect"] == "object"
    assert call["body"] == {
        "jql": 'project = ENG AND status != Done',
        "fields": ["summary", "description", "labels", "status", "updated"],
        "maxResults": 50,
    }
    encoded = base64.b64encode(
        b"operator@example.com:api-token-value"
    ).decode("ascii")
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": f"Basic {encoded}",
    }


def test_jira_sends_opaque_next_page_token() -> None:
    transport = FakeTransport({"issues": [], "isLast": True})
    source = JiraSource(
        transport,
        base_url="https://acme.atlassian.net",
        jql="project = ENG",
        email="operator@example.com",
        api_token="token",
    )
    page = source.fetch_page(cursor="opaque/value+", limit=10)
    assert page.next_cursor is None
    assert transport.calls[0]["body"]["nextPageToken"] == "opaque/value+"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://acme.atlassian.net",
        "https://atlassian.net",
        "https://acme.example.com",
        "https://user:secret@acme.atlassian.net",
        "https://acme.atlassian.net/extra",
    ],
)
def test_jira_rejects_non_cloud_or_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(SourceError, match="base_url"):
        JiraSource(
            FakeTransport({}),
            base_url=base_url,
            jql="project = ENG",
            email="operator@example.com",
            api_token="token",
        )


@pytest.mark.parametrize(
    "response",
    [
        [],
        {"issues": "not-a-list"},
        {"issues": [{}]},
        {"issues": [{"key": "ENG-1", "fields": {"summary": None}}]},
        {"issues": [], "isLast": "true"},
        {"issues": [], "isLast": True, "nextPageToken": 3},
        {"issues": [], "isLast": True, "nextPageToken": ""},
    ],
)
def test_jira_rejects_malformed_provider_responses(response: object) -> None:
    source = JiraSource(
        FakeTransport(response),
        base_url="https://acme.atlassian.net",
        jql="project = ENG",
        email="operator@example.com",
        api_token="token",
    )
    with pytest.raises(SourceError, match="malformed Jira"):
        source.fetch_page(cursor=None, limit=10)


@pytest.mark.parametrize(
    "response",
    [
        {"issues": [], "isLast": False},
        {"issues": [], "isLast": True, "nextPageToken": "unexpected"},
    ],
)
def test_jira_requires_consistent_completion_token(response: object) -> None:
    source = JiraSource(
        FakeTransport(response),
        base_url="https://acme.atlassian.net",
        jql="project = ENG",
        email="operator@example.com",
        api_token="token",
    )
    with pytest.raises(SourceError, match="isLast"):
        source.fetch_page(cursor=None, limit=10)


def test_jira_rejects_credential_and_cursor_injection() -> None:
    with pytest.raises(SourceError, match="email|token"):
        JiraSource(
            FakeTransport({}),
            base_url="https://acme.atlassian.net",
            jql="project = ENG",
            email="operator@example.com\nInjected",
            api_token="token",
        )
    source = JiraSource(
        FakeTransport({"issues": []}),
        base_url="https://acme.atlassian.net",
        jql="project = ENG",
        email="operator@example.com",
        api_token="token",
    )
    with pytest.raises(SourceError, match="cursor"):
        source.fetch_page(cursor="bad\nvalue", limit=10)
