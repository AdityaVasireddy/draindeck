"""Read-only GitHub repository-issues adapter."""
from __future__ import annotations

import re
from urllib.parse import quote

from .http import JsonTransport
from .model import CanonicalIssueV1, IssueValidationError, make_scoped_issue_id
from .sources import IssuePage, SourceError

_SCOPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


def _scope(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SCOPE.fullmatch(value) or value in {".", ".."}:
        raise SourceError(f"GitHub {field} is invalid")
    return value


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SourceError(f"malformed GitHub issue: {field}")
    return value


class GitHubSource:
    name = "github"

    def __init__(
        self,
        transport: JsonTransport,
        *,
        owner: str,
        repo: str,
        id_prefix: str = "gh",
        token: str | None = None,
    ) -> None:
        self._transport = transport
        self._owner = _scope(owner, field="owner")
        self._repo = _scope(repo, field="repo")
        self._id_prefix = id_prefix
        if token is not None and (
            not isinstance(token, str)
            or not token
            or len(token) > 4_096
            or "\r" in token
            or "\n" in token
        ):
            raise SourceError("GitHub token is invalid")
        self._token = token

    def _map_issue(self, raw: object) -> CanonicalIssueV1 | None:
        if not isinstance(raw, dict):
            raise SourceError("malformed GitHub issue: record")
        if "pull_request" in raw:
            return None
        number = raw.get("number")
        title = raw.get("title")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise SourceError("malformed GitHub issue: number")
        if not isinstance(title, str):
            raise SourceError("malformed GitHub issue: title")
        labels_raw = raw.get("labels", [])
        if not isinstance(labels_raw, list):
            raise SourceError("malformed GitHub issue: labels")
        labels: list[str] = []
        for label in labels_raw:
            if not isinstance(label, dict) or not isinstance(label.get("name"), str):
                raise SourceError("malformed GitHub issue: labels")
            labels.append(label["name"])
        body = raw.get("body")
        if body is None:
            body = ""
        if not isinstance(body, str):
            raise SourceError("malformed GitHub issue: body")
        try:
            return CanonicalIssueV1(
                issue_id=make_scoped_issue_id(
                    self._id_prefix, self._owner, self._repo, number
                ),
                source_kind="github",
                source_id=f"{self._owner}/{self._repo}#{number}",
                title=title,
                body=body,
                labels=tuple(labels),
                source_url=_optional_text(raw.get("html_url"), field="html_url"),
                source_state=_optional_text(raw.get("state"), field="state"),
                updated_at=_optional_text(raw.get("updated_at"), field="updated_at"),
            )
        except IssueValidationError as exc:
            raise SourceError("malformed GitHub issue: canonical fields") from exc

    def fetch_page(self, *, cursor: str | None, limit: int) -> IssuePage:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise SourceError("GitHub limit must be between 1 and 100")
        if cursor is None:
            page_number = 1
        elif cursor.isascii() and cursor.isdecimal() and int(cursor) >= 1:
            page_number = int(cursor)
        else:
            raise SourceError("GitHub cursor is invalid")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "draindeck-intake/1",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"
        raw = self._transport.request_json(
            "GET",
            (
                "https://api.github.com/repos/"
                f"{quote(self._owner, safe='')}/{quote(self._repo, safe='')}/issues"
            ),
            headers=headers,
            query={
                "state": "open",
                "sort": "created",
                "direction": "asc",
                "per_page": limit,
                "page": page_number,
            },
            expect="list",
        )
        if not isinstance(raw, list):
            raise SourceError("malformed GitHub response")
        mapped = tuple(
            issue for item in raw if (issue := self._map_issue(item)) is not None
        )
        next_cursor = str(page_number + 1) if len(raw) == limit else None
        return IssuePage(mapped, next_cursor)
