"""Read-only Linear GraphQL adapter with Relay pagination."""
from __future__ import annotations

import re

from .http import JsonTransport
from .model import CanonicalIssueV1, IssueValidationError, make_scoped_issue_id
from .sources import IssuePage, SourceError

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
LINEAR_ISSUES_QUERY = """query DraindeckIntakeIssues(
  $first: Int!
  $after: String
  $teamKey: String!
) {
  issues(
    first: $first
    after: $after
    filter: {team: {key: {eq: $teamKey}}}
  ) {
    nodes {
      identifier
      title
      description
      url
      updatedAt
      priority
      state { name }
      labels(first: 101) { nodes { name } pageInfo { hasNextPage endCursor } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

_TEAM_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")


def _required_string(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise SourceError(f"malformed Linear issue: {field}")
    return value


def _optional_string(record: dict[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is not None and not isinstance(value, str):
        raise SourceError(f"malformed Linear issue: {field}")
    return value


class LinearSource:
    name = "linear"

    def __init__(
        self,
        transport: JsonTransport,
        *,
        team_key: str,
        api_key: str,
        id_prefix: str = "linear",
    ) -> None:
        if not isinstance(team_key, str) or not _TEAM_KEY.fullmatch(team_key):
            raise SourceError("Linear team_key is invalid")
        if (
            not isinstance(api_key, str)
            or not api_key
            or len(api_key) > 4_096
            or "\r" in api_key
            or "\n" in api_key
        ):
            raise SourceError("Linear api_key is invalid")
        self._transport = transport
        self._team_key = team_key
        self._api_key = api_key
        self._id_prefix = id_prefix

    def _map_issue(self, raw: object) -> CanonicalIssueV1:
        if not isinstance(raw, dict):
            raise SourceError("malformed Linear issue: record")
        identifier = _required_string(raw, "identifier")
        title = _required_string(raw, "title")
        url = _required_string(raw, "url")
        updated_at = _required_string(raw, "updatedAt")
        description = _optional_string(raw, "description") or ""

        priority = raw.get("priority")
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 0 <= priority <= 4
        ):
            raise SourceError("malformed Linear issue: priority")
        state_raw = raw.get("state")
        if not isinstance(state_raw, dict) or not isinstance(state_raw.get("name"), str):
            raise SourceError("malformed Linear issue: state")
        labels_raw = raw.get("labels")
        if not isinstance(labels_raw, dict) or not isinstance(labels_raw.get("nodes"), list):
            raise SourceError("malformed Linear issue: labels")
        labels_page_info = labels_raw.get("pageInfo")
        if (
            not isinstance(labels_page_info, dict)
            or not isinstance(labels_page_info.get("hasNextPage"), bool)
            or labels_page_info["hasNextPage"]
        ):
            raise SourceError("malformed Linear issue: labels pagination")
        labels: list[str] = []
        for label in labels_raw["nodes"]:
            if not isinstance(label, dict) or not isinstance(label.get("name"), str):
                raise SourceError("malformed Linear issue: labels")
            labels.append(label["name"])
        if priority:
            labels.append(f"priority:{priority}")
        try:
            return CanonicalIssueV1(
                issue_id=make_scoped_issue_id(self._id_prefix, identifier),
                source_kind="linear",
                source_id=identifier,
                title=title,
                body=description,
                labels=tuple(labels),
                source_url=url,
                source_state=state_raw["name"],
                updated_at=updated_at,
            )
        except IssueValidationError as exc:
            raise SourceError("malformed Linear issue: canonical fields") from exc

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise SourceError("Linear limit must be between 1 and 100")
        if cursor is not None and (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor) > 4_096
            or "\r" in cursor
            or "\n" in cursor
        ):
            raise SourceError("Linear cursor is invalid")
        raw = self._transport.request_json(
            "POST",
            LINEAR_ENDPOINT,
            headers={
                "Accept": "application/json",
                "Authorization": self._api_key,
            },
            body={
                "query": LINEAR_ISSUES_QUERY,
                "variables": {
                    "first": limit,
                    "after": cursor,
                    "teamKey": self._team_key,
                },
            },
            expect="object",
        )
        if not isinstance(raw, dict):
            raise SourceError("malformed Linear response")
        errors = raw.get("errors")
        if errors is not None and not isinstance(errors, list):
            raise SourceError("malformed Linear response: errors")
        if errors:
            raise SourceError("Linear returned GraphQL errors")
        data = raw.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("issues"), dict):
            raise SourceError("malformed Linear response: data")
        connection = data["issues"]
        nodes = connection.get("nodes")
        page_info = connection.get("pageInfo")
        if not isinstance(nodes, list):
            raise SourceError("malformed Linear response: nodes")
        if not isinstance(page_info, dict):
            raise SourceError("malformed Linear response: pageInfo")
        has_next_page = page_info.get("hasNextPage")
        end_cursor = page_info.get("endCursor")
        if not isinstance(has_next_page, bool):
            raise SourceError("malformed Linear response: pageInfo")
        if has_next_page and (not isinstance(end_cursor, str) or not end_cursor):
            raise SourceError("malformed Linear response: pageInfo")
        next_cursor = end_cursor if has_next_page else None
        return IssuePage(tuple(self._map_issue(node) for node in nodes), next_cursor)
