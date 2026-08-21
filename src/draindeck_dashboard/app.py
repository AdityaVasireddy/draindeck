"""App factory (ADR-26 decision 1; docs/19).

FastAPI/Uvicorn live only in this package — core ``src/runtime`` never
imports from here or from FastAPI/Starlette/Uvicorn directly.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import DashboardConfig
from .db import connect_and_init
from .errors import register_error_handlers
from .security import LoopbackOnlyMiddleware, SecurityHeadersMiddleware

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(cfg: DashboardConfig) -> FastAPI:
    app = FastAPI(title="Draindeck Dashboard", docs_url=None, redoc_url=None)

    # Middleware order matters: Starlette runs the LAST-added middleware
    # OUTERMOST (first on the way in, last on the way out). Adding
    # SecurityHeadersMiddleware after LoopbackOnlyMiddleware makes it
    # outermost, so headers land on every response including a
    # LoopbackOnlyMiddleware rejection. CORS is disabled by omission — no
    # CORSMiddleware is ever added.
    app.add_middleware(LoopbackOnlyMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)

    conn = connect_and_init(cfg.db_path)
    app.state.db = conn
    app.state.config = cfg

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app
