from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from http.client import IncompleteRead
from urllib.error import HTTPError

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from draindeck_intake.github import GitHubSource
from draindeck_intake.http import BoundedJsonTransport, TransportError
from draindeck_intake.sources import SourceError


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakeOpener:
    def __init__(self, response: bytes | Exception) -> None:
        self.response = response
        self.requests: list[tuple[object, float]] = []

    def open(self, request: object, *, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return FakeResponse(self.response)


def test_transport_builds_bounded_https_json_request() -> None:
    opener = FakeOpener(b'{"ok":true}')
    transport = BoundedJsonTransport(
        allowed_hosts={"api.example.com"},
        timeout_seconds=7.5,
        max_response_bytes=100,
        opener=opener,
    )

    result = transport.request_json(
        "POST",
        "https://api.example.com/v1/items",
        headers={"Accept": "application/json", "X-Test": "safe"},
        query={"page": 2, "tag": "a b"},
        body={"name": "item"},
        expect="object",
    )

    assert result == {"ok": True}
    request, timeout = opener.requests[0]
    assert request.full_url == "https://api.example.com/v1/items?page=2&tag=a+b"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"name": "item"}
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 7.5


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/items",
        "https://elsewhere.example/items",
        "https://user:secret@api.example.com/items",
    ],
)
def test_transport_rejects_unsafe_urls_before_io(url: str) -> None:
    opener = FakeOpener(b"{}")
    transport = BoundedJsonTransport(
        allowed_hosts={"api.example.com"}, opener=opener
    )
    with pytest.raises(TransportError, match="HTTPS|host|credentials"):
        transport.request_json("GET", url, expect="object")
    assert opener.requests == []


def test_transport_rejects_redirects_oversize_invalid_json_and_wrong_shape() -> None:
    redirect = HTTPError(
        "https://api.example.com/items",
        302,
        "Found",
        {"Location": "https://elsewhere.example/steal"},
        io.BytesIO(b"secret-body"),
    )
    cases = [
        (redirect, 100, "HTTP status 302"),
        (b"x" * 11, 10, "maximum"),
        (b"not-json", 100, "valid JSON"),
        (b'{"value":NaN}', 100, "valid JSON"),
        (IncompleteRead(b"{", 10), 100, "request failed"),
        (b"[]", 100, "object"),
    ]
    for response, maximum, message in cases:
        transport = BoundedJsonTransport(
            allowed_hosts={"api.example.com"},
            max_response_bytes=maximum,
            opener=FakeOpener(response),
        )
        with pytest.raises(TransportError, match=message) as caught:
            transport.request_json(
                "GET",
                "https://api.example.com/items",
                headers={"Authorization": "Bearer do-not-leak"},
                expect="object",
            )
        assert "do-not-leak" not in str(caught.value)
        assert "secret-body" not in str(caught.value)


class FakeTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def request_json(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


class SequencedTransport(FakeTransport):
    def __init__(self, responses: list[object]) -> None:
        super().__init__(responses)

    def request_json(self, method: str, url: str, **kwargs: object) -> object:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response.pop(0)


def test_github_maps_issues_excludes_pull_requests_and_paginates() -> None:
    transport = FakeTransport(
        [
            {
                "number": 12,
                "title": "Handle retries",
                "body": "Bound them",
                "html_url": "https://github.com/Acme/Widget/issues/12",
                "state": "open",
                "updated_at": "2026-08-29T12:00:00Z",
                "labels": [{"name": "reliability"}, {"name": "backend"}],
            },
            {
                "number": 13,
                "title": "This is a pull request",
                "pull_request": {"url": "https://api.github.com/pulls/13"},
            },
        ]
    )
    source = GitHubSource(
        transport, owner="Acme", repo="Widget", id_prefix="gh", token="token-value"
    )

    page = source.fetch_page(cursor=None, limit=2)

    assert page.next_cursor == "2"
    assert len(page.issues) == 1
    issue = page.issues[0]
    assert issue.issue_id == "gh-acme-widget-12"
    assert issue.source_id == "Acme/Widget#12"
    assert issue.labels == ("reliability", "backend")
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.github.com/repos/Acme/Widget/issues"
    assert call["query"] == {
        "state": "open",
        "sort": "created",
        "direction": "asc",
        "per_page": 2,
        "page": 1,
    }
    assert call["headers"] == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "draindeck-intake/1",
        "Authorization": "Bearer token-value",
    }
    assert call["expect"] == "list"


@pytest.mark.parametrize(
    "response",
    [
        [{"number": True, "title": "bad"}],
        [{"number": 1, "title": None}],
        [{"number": 1, "title": "bad", "labels": "not-a-list"}],
        [{"number": 1, "title": "bad", "labels": [{}]}],
    ],
)
def test_github_rejects_malformed_provider_records(response: object) -> None:
    source = GitHubSource(FakeTransport(response), owner="acme", repo="widget")
    with pytest.raises(SourceError, match="malformed GitHub issue"):
        source.fetch_page(cursor=None, limit=10)


def test_github_rejects_bad_cursor_scope_and_header_injection() -> None:
    transport = FakeTransport([])
    with pytest.raises(SourceError, match="token"):
        GitHubSource(transport, owner="acme", repo="widget", token="bad\nvalue")
    with pytest.raises(SourceError, match="owner"):
        GitHubSource(transport, owner="../acme", repo="widget")
    source = GitHubSource(transport, owner="acme", repo="widget")
    with pytest.raises(SourceError, match="cursor"):
        source.fetch_page(cursor="zero", limit=10)


def test_github_skips_full_pull_request_only_pages_within_one_source_page() -> None:
    transport = SequencedTransport(
        [
            [{"number": 1, "title": "PR", "pull_request": {}}],
            [{"number": 2, "title": "Issue"}],
        ]
    )
    source = GitHubSource(transport, owner="acme", repo="widget")

    page = source.fetch_page(cursor=None, limit=1)

    assert [issue.issue_id for issue in page.issues] == ["gh-acme-widget-2"]
    assert page.next_cursor == "3"
    assert [call["query"]["page"] for call in transport.calls] == [1, 2]
