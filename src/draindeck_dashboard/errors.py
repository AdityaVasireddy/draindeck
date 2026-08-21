"""Typed API errors and their consistent JSON envelope (docs/19: every
mapped error is ``{ "error": { "code", "message", "details?" } }``).
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class DashboardApiError(Exception):
    status_code: int = 400

    def __init__(self, code: str, message: str, *,
                 status_code: Optional[int] = None,
                 details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code

    def to_response(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


class NotFoundError(DashboardApiError):
    status_code = 404

    def __init__(self, message: str = "resource not found", **kw) -> None:
        super().__init__("NOT_FOUND", message, **kw)


class ForbiddenError(DashboardApiError):
    status_code = 403

    def __init__(self, message: str = "forbidden", **kw) -> None:
        super().__init__("FORBIDDEN", message, **kw)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DashboardApiError)
    async def _handle_dashboard_api_error(request: Request, exc: DashboardApiError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())
