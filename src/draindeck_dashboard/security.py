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
