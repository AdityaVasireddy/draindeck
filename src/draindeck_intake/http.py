"""Bounded, no-redirect HTTPS JSON transport for credentialed sources."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from http.client import HTTPException
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .sources import SourceError

JsonExpectation = Literal["object", "list", None]

_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_METHODS = frozenset({"GET", "POST"})
MAX_REQUEST_BYTES = 1024 * 1024


class TransportError(SourceError):
    """A remote response could not be safely accepted."""


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


class JsonTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, object] | None = None,
        body: object | None = None,
        expect: JsonExpectation = None,
    ) -> object: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


class BoundedJsonTransport:
    """One-request transport with an exact host allowlist and byte ceiling."""

    def __init__(
        self,
        *,
        allowed_hosts: set[str] | frozenset[str],
        timeout_seconds: float = 30.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        opener: object | None = None,
    ) -> None:
        normalized_hosts = frozenset(host.lower() for host in allowed_hosts)
        if not normalized_hosts or any(not host or "/" in host for host in normalized_hosts):
            raise TransportError("allowed_hosts must contain exact host names")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise TransportError("timeout_seconds must be finite and positive")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes < 1
        ):
            raise TransportError("max_response_bytes must be a positive integer")
        self._allowed_hosts = normalized_hosts
        self._timeout_seconds = float(timeout_seconds)
        self._max_response_bytes = max_response_bytes
        self._opener = opener if opener is not None else build_opener(_NoRedirect())

    def _validated_url(self, url: str, query: Mapping[str, object] | None) -> str:
        if not isinstance(url, str) or "\r" in url or "\n" in url:
            raise TransportError("request URL is invalid")
        parsed = urlsplit(url)
        if parsed.scheme.lower() != "https":
            raise TransportError("request URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise TransportError("request URL must not contain credentials")
        if parsed.hostname is None or parsed.hostname.lower() not in self._allowed_hosts:
            raise TransportError("request URL host is not allowed")
        if parsed.fragment or parsed.query:
            raise TransportError("request URL must not contain query or fragment text")
        if not query:
            return url
        try:
            encoded = urlencode(query, doseq=True)
        except (TypeError, ValueError) as exc:
            raise TransportError("request query is invalid") from exc
        return f"{url}?{encoded}"

    @staticmethod
    def _validated_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
        result: dict[str, str] = {}
        for name, value in (headers or {}).items():
            if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
                raise TransportError("request header name is invalid")
            if not isinstance(value, str) or "\r" in value or "\n" in value:
                raise TransportError("request header value is invalid")
            result[name] = value
        return result

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, object] | None = None,
        body: object | None = None,
        expect: JsonExpectation = None,
    ) -> object:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if normalized_method not in _METHODS:
            raise TransportError("request method is not allowed")
        if expect not in (None, "object", "list"):
            raise TransportError("JSON expectation is invalid")
        request_url = self._validated_url(url, query)
        request_headers = self._validated_headers(headers)
        data: bytes | None = None
        if body is not None:
            try:
                data = json.dumps(
                    body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise TransportError("request body is not JSON serializable") from exc
            if len(data) > MAX_REQUEST_BYTES:
                raise TransportError("request body exceeds the maximum size")
            request_headers.setdefault("Content-Type", "application/json")
        request = Request(
            request_url,
            data=data,
            headers=request_headers,
            method=normalized_method,
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                raw = response.read(self._max_response_bytes + 1)
        except HTTPError as exc:
            raise TransportError(f"remote service returned HTTP status {exc.code}") from exc
        except (HTTPException, URLError, OSError, TimeoutError) as exc:
            raise TransportError(
                f"remote request failed: {exc.__class__.__name__}"
            ) from exc
        if len(raw) > self._max_response_bytes:
            raise TransportError("remote response exceeds the configured maximum size")
        try:
            value = json.loads(
                raw.decode("utf-8"), parse_constant=_reject_json_constant
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise TransportError("remote response is not valid JSON") from exc
        if expect == "object" and not isinstance(value, dict):
            raise TransportError("remote JSON response must be an object")
        if expect == "list" and not isinstance(value, list):
            raise TransportError("remote JSON response must be a list")
        return value
