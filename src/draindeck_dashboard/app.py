"""App factory (ADR-26 decision 1; docs/19).

FastAPI/Uvicorn live only in this package — core ``src/runtime`` never
imports from here or from FastAPI/Starlette/Uvicorn directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .config import DashboardConfig
from .db import connect_and_init
from .errors import register_error_handlers
from .repositories import (
    delete_repository,
    get_repository,
    list_repositories,
    register_repository,
)
from .security import (
    DEFAULT_MAX_BODY_BYTES,
    LoopbackOnlyMiddleware,
    MaxBodySizeMiddleware,
    SecurityHeadersMiddleware,
)

_STATIC_DIR = Path(__file__).parent / "static"


class _RegisterRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectPath: str
    logPath: Optional[str] = None


def create_app(cfg: DashboardConfig) -> FastAPI:
    app = FastAPI(title="Draindeck Dashboard", docs_url=None, redoc_url=None)

    # Middleware order matters: Starlette runs the LAST-added middleware
    # OUTERMOST (first on the way in, last on the way out).
    # MaxBodySizeMiddleware is pure ASGI and must sit closest to the
    # router so it guards the actual receive stream every route consumes.
    # SecurityHeadersMiddleware is added last so it is outermost and wraps
    # every response, including a LoopbackOnlyMiddleware/body-size
    # rejection. CORS is disabled by omission — no CORSMiddleware is ever
    # added.
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=DEFAULT_MAX_BODY_BYTES)
    app.add_middleware(LoopbackOnlyMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)

    conn = connect_and_init(cfg.db_path)
    app.state.db = conn
    app.state.config = cfg

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/repositories", status_code=201)
    async def create_repository(payload: _RegisterRepositoryRequest) -> dict:
        return register_repository(
            app.state.db,
            project_path=payload.projectPath,
            log_path=payload.logPath,
        )

    @app.get("/api/repositories")
    async def get_repositories() -> dict:
        return {"repositories": list_repositories(app.state.db)}

    @app.get("/api/repositories/{repo_id}")
    async def get_one_repository(repo_id: int) -> dict:
        return get_repository(app.state.db, repo_id)

    @app.delete("/api/repositories/{repo_id}", status_code=204)
    async def remove_repository(repo_id: int) -> None:
        delete_repository(app.state.db, repo_id)

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app
