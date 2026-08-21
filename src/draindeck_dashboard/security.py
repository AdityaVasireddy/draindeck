"""Local web security (docs/19 "Local web security"): loopback-only
Host/Origin enforcement and restrictive response headers. CORS is disabled
by omission — no ``CORSMiddleware`` is ever registered anywhere in this
package.
"""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "localhost", "::1"})


def _hostname_only(value: str) -> str:
    """Strip a trailing :port from a Host-header-shaped value. IPv6
    literals arrive bracketed ("[::1]:8420"); bracket contents are
    returned without the brackets to match urlparse().hostname's form."""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    return value.split(":", 1)[0]


class LoopbackOnlyMiddleware(BaseHTTPMiddleware):
    """Rejects any request whose Host header — or Origin header, when
    present — does not name a loopback address. Defense in depth alongside
    binding only to 127.0.0.1: a misconfigured proxy or DNS-rebinding
    attempt is refused here even if the socket is somehow reached from
    elsewhere."""

    async def dispatch(self, request: Request, call_next):
        host = request.headers.get("host")
        if host is None or _hostname_only(host) not in _LOOPBACK_HOSTNAMES:
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "NON_LOOPBACK_HOST",
                                    "message": "Host header must be a loopback address"}},
            )
        origin = request.headers.get("origin")
        if origin is not None:
            hostname = urlparse(origin).hostname or ""
            if hostname not in _LOOPBACK_HOSTNAMES:
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "NON_LOOPBACK_ORIGIN",
                                        "message": "Origin header must be a loopback address"}},
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Restrictive self-only CSP, frame-ancestors 'none', nosniff, and a
    conservative referrer policy on every response, including rejections
    from LoopbackOnlyMiddleware — this must be the outermost middleware so
    it wraps every response the app produces."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


class _BodyTooLarge(Exception):
    pass


DEFAULT_MAX_BODY_BYTES = 64 * 1024


async def _reject_body_too_large(scope, receive, send, max_bytes: int) -> None:
    response = JSONResponse(
        status_code=413,
        content={"error": {"code": "REQUEST_BODY_TOO_LARGE",
                            "message": f"request body exceeds {max_bytes} bytes"}},
    )
    await response(scope, receive, send)


class MaxBodySizeMiddleware:
    """Bounds request body size (docs/19 "API body...are bounded").

    Primary check: reject on ``Content-Length`` before ``self.app`` is ever
    invoked. This must be the primary mechanism, not a fallback — FastAPI's
    own body-parsing (for a pydantic-model request body) catches ANY
    exception raised from ``receive()`` during parsing and converts it into
    its own generic 400, so a `receive()`-stream exception raised from
    *inside* app code never reaches this middleware's own error response;
    rejecting before dispatch is the only way to guarantee a 413.

    Secondary, best-effort guard: the streaming counter below still bounds
    actual bytes received for a request that lies about — or omits —
    Content-Length. Given the swallowing behavior above, such a request is
    still rejected (the app never completes normally), but not guaranteed
    to surface as exactly a clean 413 — an accepted, honestly-documented
    gap for this local, loopback-only tool, not a bypass of the bound
    itself.
    """

    def __init__(self, app, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        max_bytes = self.max_bytes
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = None
                if declared is not None and declared > max_bytes:
                    await _reject_body_too_large(scope, receive, send, max_bytes)
                    return
                break

        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await _reject_body_too_large(scope, receive, send, max_bytes)
