from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.linear import LINEAR_ISSUES_QUERY, LinearSource
from draindeck_intake.sources import SourceError


class FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def request_json(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


def response_with(*nodes: object, page_info: object | None = None) -> dict[str, object]:
    return {
        "data": {
            "issues": {
                "nodes": list(nodes),
                "pageInfo": page_info
                if page_info is not None
                else {"hasNextPage": False, "endCursor": None},
            }
        }
    }


def test_linear_uses_fixed_graphql_contract_and_maps_issue() -> None:
    transport = FakeTransport(
        response_with(
            {
                "identifier": "ENG-77",
                "title": "Protect pagination",
                "description": "Reject cursor cycles",
                "url": "https://linear.app/acme/issue/ENG-77/protect-pagination",
                "updatedAt": "2026-08-29T12:00:00.000Z",
                "priority": 2,
                "state": {"name": "In Progress"},
                "labels": {"nodes": [{"name": "backend"}]},
            },
            page_info={"hasNextPage": True, "endCursor": "opaque-next"},
        )
    )
    source = LinearSource(
        transport,
        team_key="ENG",
        api_key="linear-key-value",
        id_prefix="linear",
    )

    page = source.fetch_page(cursor=None, limit=25)

    assert page.next_cursor == "opaque-next"
    issue = page.issues[0]
    assert issue.issue_id == "linear-eng-77"
    assert issue.source_id == "ENG-77"
    assert issue.source_state == "In Progress"
    assert issue.labels == ("backend", "priority:2")
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.linear.app/graphql"
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": "linear-key-value",
    }
    assert call["body"] == {
        "query": LINEAR_ISSUES_QUERY,
        "variables": {"first": 25, "after": None, "teamKey": "ENG"},
    }
    assert call["expect"] == "object"


def test_linear_sends_opaque_relay_cursor() -> None:
    transport = FakeTransport(response_with())
    source = LinearSource(transport, team_key="ENG", api_key="key")
    source.fetch_page(cursor="opaque/value+", limit=10)
    assert transport.calls[0]["body"]["variables"]["after"] == "opaque/value+"


def test_linear_rejects_graphql_errors_without_echoing_provider_messages() -> None:
    source = LinearSource(
        FakeTransport(
            {
                "errors": [{"message": "credential linear-secret-value is invalid"}],
                "data": None,
            }
        ),
        team_key="ENG",
        api_key="linear-secret-value",
    )
    with pytest.raises(SourceError, match="GraphQL errors") as caught:
        source.fetch_page(cursor=None, limit=10)
    assert "linear-secret-value" not in str(caught.value)


@pytest.mark.parametrize(
    "page_info",
    [
        None,
        {},
        {"hasNextPage": "yes", "endCursor": "next"},
        {"hasNextPage": True, "endCursor": None},
        {"hasNextPage": True, "endCursor": ""},
    ],
)
def test_linear_rejects_malformed_page_info(page_info: object) -> None:
    payload = {
        "data": {"issues": {"nodes": [], "pageInfo": page_info}}
    }
    source = LinearSource(FakeTransport(payload), team_key="ENG", api_key="key")
    with pytest.raises(SourceError, match="pageInfo"):
        source.fetch_page(cursor=None, limit=10)


def test_linear_ignores_end_cursor_when_no_next_page_exists() -> None:
    source = LinearSource(
        FakeTransport(
            response_with(
                page_info={"hasNextPage": False, "endCursor": "last-node-cursor"}
            )
        ),
        team_key="ENG",
        api_key="key",
    )
    assert source.fetch_page(cursor=None, limit=10).next_cursor is None


@pytest.mark.parametrize(
    "node",
    [
        {},
        {"identifier": "ENG-1", "title": None},
        {
            "identifier": "ENG-1",
            "title": "Bad labels",
            "state": {"name": "Todo"},
            "labels": [],
        },
        {
            "identifier": "ENG-1",
            "title": "Bad state",
            "state": None,
            "labels": {"nodes": []},
        },
        {
            "identifier": "ENG-1",
            "title": "Bad priority",
            "priority": True,
            "state": {"name": "Todo"},
            "labels": {"nodes": []},
        },
    ],
)
def test_linear_rejects_malformed_issue_nodes(node: object) -> None:
    source = LinearSource(
        FakeTransport(response_with(node)), team_key="ENG", api_key="key"
    )
    with pytest.raises(SourceError, match="malformed Linear issue"):
        source.fetch_page(cursor=None, limit=10)


def test_linear_rejects_invalid_team_key_credentials_and_cursor() -> None:
    with pytest.raises(SourceError, match="team_key"):
        LinearSource(FakeTransport({}), team_key="bad team", api_key="key")
    with pytest.raises(SourceError, match="api_key"):
        LinearSource(FakeTransport({}), team_key="ENG", api_key="bad\nkey")
    source = LinearSource(
        FakeTransport(response_with()), team_key="ENG", api_key="key"
    )
    with pytest.raises(SourceError, match="cursor"):
        source.fetch_page(cursor="bad\nvalue", limit=10)
