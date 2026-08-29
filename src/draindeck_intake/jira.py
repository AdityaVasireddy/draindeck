"""Read-only Jira Cloud enhanced-search adapter and ADF extraction."""
from __future__ import annotations

import base64
import re
from urllib.parse import quote, urlsplit

from .http import JsonTransport
from .model import CanonicalIssueV1, IssueValidationError, make_scoped_issue_id
from .sources import IssuePage, SourceError

_MULTIPLE_NEWLINES = re.compile(r"\n{2,}")
_ADF_BLOCKS = frozenset(
    {
        "blockquote",
        "codeBlock",
        "heading",
        "listItem",
        "panel",
        "paragraph",
        "tableCell",
        "tableHeader",
        "tableRow",
    }
)
MAX_ADF_DEPTH = 100
MAX_ADF_NODES = 10_000


def adf_to_text(document: object) -> str:
    """Extract bounded plain text from a Jira v3 Atlassian Document Format value."""
    if document is None:
        return ""
    if not isinstance(document, dict) or document.get("type") != "doc":
        raise SourceError("Jira ADF description must be a doc object")
    parts: list[str] = []
    visited = 0

    def walk(node: object, depth: int) -> None:
        nonlocal visited
        visited += 1
        if visited > MAX_ADF_NODES or depth > MAX_ADF_DEPTH:
            raise SourceError("Jira ADF exceeds structural limits")
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise SourceError("Jira ADF contains a malformed node")
        node_type = node["type"]
        if node_type == "text":
            text = node.get("text")
            if not isinstance(text, str):
                raise SourceError("Jira ADF text node is malformed")
            parts.append(text)
            return
        if node_type == "hardBreak":
            parts.append("\n")
            return
        content = node.get("content", [])
        if not isinstance(content, list):
            raise SourceError("Jira ADF node content must be a list")
        for child in content:
            walk(child, depth + 1)
        if node_type in _ADF_BLOCKS and parts and not parts[-1].endswith("\n"):
            parts.append("\n")

    walk(document, 0)
    return _MULTIPLE_NEWLINES.sub("\n", "".join(parts)).strip()


def _credential(value: object, *, field: str, allow_colon: bool = True) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4_096
        or "\r" in value
        or "\n" in value
        or (not allow_colon and ":" in value)
    ):
        raise SourceError(f"Jira {field} is invalid")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceError(f"malformed Jira issue: {field}")
    return value


class JiraSource:
    name = "jira"

    def __init__(
        self,
        transport: JsonTransport,
        *,
        base_url: str,
        jql: str,
        email: str,
        api_token: str,
        id_prefix: str = "jira",
    ) -> None:
        try:
            parsed = urlsplit(base_url)
            port = parsed.port
        except (TypeError, ValueError) as exc:
            raise SourceError("Jira base_url is invalid") from exc
        hostname = parsed.hostname.lower() if parsed.hostname else ""
        if (
            parsed.scheme.lower() != "https"
            or not hostname.endswith(".atlassian.net")
            or hostname == "atlassian.net"
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise SourceError("Jira base_url must be an HTTPS *.atlassian.net root")
        if (
            not isinstance(jql, str)
            or not jql
            or jql.strip() != jql
            or len(jql) > 20_000
            or "\r" in jql
            or "\n" in jql
        ):
            raise SourceError("Jira jql is invalid")
        self._transport = transport
        self._base_url = f"https://{hostname}"
        self._jql = jql
        self._email = _credential(email, field="email", allow_colon=False)
        self._api_token = _credential(api_token, field="api_token")
        self._id_prefix = id_prefix

    def _map_issue(self, raw: object) -> CanonicalIssueV1:
        if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
            raise SourceError("malformed Jira issue: key")
        key = raw["key"]
        fields = raw.get("fields")
        if not isinstance(fields, dict) or not isinstance(fields.get("summary"), str):
            raise SourceError("malformed Jira issue: fields")
        labels_raw = fields.get("labels", [])
        if not isinstance(labels_raw, list) or any(
            not isinstance(label, str) for label in labels_raw
        ):
            raise SourceError("malformed Jira issue: labels")
        status_raw = fields.get("status")
        if status_raw is None:
            status = None
        elif isinstance(status_raw, dict) and isinstance(status_raw.get("name"), str):
            status = status_raw["name"]
        else:
            raise SourceError("malformed Jira issue: status")
        try:
            return CanonicalIssueV1(
                issue_id=make_scoped_issue_id(self._id_prefix, key),
                source_kind="jira",
                source_id=key,
                title=fields["summary"],
                body=adf_to_text(fields.get("description")),
                labels=tuple(labels_raw),
                source_url=f"{self._base_url}/browse/{quote(key, safe='')}",
                source_state=status,
                updated_at=_optional_string(fields.get("updated"), field="updated"),
            )
        except IssueValidationError as exc:
            raise SourceError("malformed Jira issue: canonical fields") from exc

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise SourceError("Jira limit must be between 1 and 100")
        if cursor is not None and (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor) > 4_096
            or "\r" in cursor
            or "\n" in cursor
        ):
            raise SourceError("Jira cursor is invalid")
        credential = base64.b64encode(
            f"{self._email}:{self._api_token}".encode("utf-8")
        ).decode("ascii")
        body: dict[str, object] = {
            "jql": self._jql,
            "fields": ["summary", "description", "labels", "status", "updated"],
            "maxResults": limit,
        }
        if cursor is not None:
            body["nextPageToken"] = cursor
        raw = self._transport.request_json(
            "POST",
            f"{self._base_url}/rest/api/3/search/jql",
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {credential}",
            },
            body=body,
            expect="object",
        )
        if not isinstance(raw, dict) or not isinstance(raw.get("issues"), list):
            raise SourceError("malformed Jira response: issues")
        next_cursor = raw.get("nextPageToken")
        if next_cursor is not None and (
            not isinstance(next_cursor, str) or not next_cursor
        ):
            raise SourceError("malformed Jira response: nextPageToken")
        return IssuePage(tuple(self._map_issue(item) for item in raw["issues"]), next_cursor)
