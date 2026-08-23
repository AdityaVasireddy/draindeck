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


# docs/27 SS7.5: typed codes for the new bounded query layer's own
# parsing/range errors, distinct from FastAPI's own path/body 422 shapes.
class InvalidQueryError(DashboardApiError):
    status_code = 422

    def __init__(self, message: str = "invalid query", **kw) -> None:
        super().__init__("INVALID_QUERY", message, **kw)


class InvalidFilterError(DashboardApiError):
    status_code = 422

    def __init__(self, message: str = "invalid filter", **kw) -> None:
        super().__init__("INVALID_FILTER", message, **kw)


class InvalidSortError(DashboardApiError):
    status_code = 422

    def __init__(self, message: str = "invalid sort", **kw) -> None:
        super().__init__("INVALID_SORT", message, **kw)


class QueryTooShortError(DashboardApiError):
    status_code = 422

    def __init__(self, message: str = "query too short", **kw) -> None:
        super().__init__("QUERY_TOO_SHORT", message, **kw)


class PageOutOfRangeError(DashboardApiError):
    status_code = 422

    def __init__(self, message: str = "page out of range", **kw) -> None:
        super().__init__("PAGE_OUT_OF_RANGE", message, **kw)


class IndexPreparingError(DashboardApiError):
    status_code = 503

    def __init__(self, message: str = "indexed views are still preparing", **kw) -> None:
        super().__init__("INDEX_PREPARING", message, **kw)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DashboardApiError)
    async def _handle_dashboard_api_error(request: Request, exc: DashboardApiError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())
