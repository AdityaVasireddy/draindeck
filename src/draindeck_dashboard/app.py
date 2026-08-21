"""App factory (ADR-26 decision 1; docs/19).

FastAPI/Uvicorn live only in this package — core ``src/runtime`` never
imports from here or from FastAPI/Starlette/Uvicorn directly.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .artifacts import artifact_root_for_log, resolve_contained_artifact
from .config import DashboardConfig
from .db import connect_and_init
from .diffs import compute_diff
from .errors import NotFoundError, register_error_handlers
from .health import build_health
from .repositories import (
    delete_repository,
    get_repository,
    list_repositories,
    register_repository,
)
from .scheduler import Scheduler
from .security import (
    DEFAULT_MAX_BODY_BYTES,
    LoopbackOnlyMiddleware,
    MaxBodySizeMiddleware,
    SecurityHeadersMiddleware,
)
from .sse import ChangeTailer, stream_events
from .views import (
    get_execution_finished_payload,
    list_evidence,
    list_executions,
    list_issues,
)

_PAGE_LIMIT_DEFAULT = 50
_PAGE_LIMIT_MAX = 200

_STATIC_DIR = Path(__file__).parent / "static"


class _RegisterRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectPath: str
    logPath: Optional[str] = None


def create_app(cfg: DashboardConfig) -> FastAPI:
    conn = connect_and_init(cfg.db_path)
    tailer = ChangeTailer(conn)
    scheduler = Scheduler(conn, cfg.observer_executable)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # One database tailer, and one ingestion scheduler, per process
        # (docs/19): started once here, not per request/connection. The
        # scheduler only actually indexes while this process holds the
        # single indexer-writer lease -- see scheduler.py.
        tailer.start()
        scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            tailer.stop()

    app = FastAPI(title="Draindeck Dashboard", docs_url=None, redoc_url=None,
                  lifespan=lifespan)

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

    app.state.db = conn
    app.state.config = cfg
    app.state.tailer = tailer
    app.state.scheduler = scheduler

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

    @app.get("/api/repositories/{repo_id}/health")
    async def repository_health(repo_id: int) -> dict:
        get_repository(app.state.db, repo_id)  # 404 if missing
        return build_health(app.state.db, repo_id)

    @app.get("/api/repositories/{repo_id}/issues")
    async def repository_issues(
        repo_id: int,
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        get_repository(app.state.db, repo_id)
        return list_issues(app.state.db, repo_id, limit=limit, offset=offset)

    @app.get("/api/repositories/{repo_id}/executions")
    async def repository_executions(
        repo_id: int,
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        get_repository(app.state.db, repo_id)
        return list_executions(app.state.db, repo_id, limit=limit, offset=offset)

    @app.get("/api/repositories/{repo_id}/evidence")
    async def repository_evidence(
        repo_id: int,
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        get_repository(app.state.db, repo_id)
        return list_evidence(app.state.db, repo_id, limit=limit, offset=offset)

    @app.get("/api/repositories/{repo_id}/executions/{execution_id}/transcript")
    async def execution_transcript(repo_id: int, execution_id: str) -> PlainTextResponse:
        repo = get_repository(app.state.db, repo_id)  # 404 if repo missing
        if repo["logPath"] is None:
            raise NotFoundError("repository has no configured log path")
        payload = get_execution_finished_payload(app.state.db, repo_id, execution_id)
        if payload is None:
            raise NotFoundError("no ExecutionFinished evidence found for this execution")
        stored_path = payload.get("transcript_path")
        if not isinstance(stored_path, str):
            raise NotFoundError("execution evidence has no transcript_path")
        root = artifact_root_for_log(repo["logPath"])
        resolved = resolve_contained_artifact(root, stored_path)
        return PlainTextResponse(resolved.read_text(encoding="utf-8", errors="replace"))

    @app.get("/api/repositories/{repo_id}/executions/{execution_id}/diff")
    async def execution_diff(repo_id: int, execution_id: str) -> dict:
        repo = get_repository(app.state.db, repo_id)  # 404 if repo missing
        payload = get_execution_finished_payload(app.state.db, repo_id, execution_id)
        if payload is None:
            raise NotFoundError("no ExecutionFinished evidence found for this execution")
        return compute_diff(
            repo["projectPath"], payload.get("start_commit"), payload.get("end_commit"))

    @app.get("/api/events")
    async def events(request: Request, after: Optional[int] = None) -> StreamingResponse:
        # SSE resume convention: a browser's EventSource automatically
        # resends its own Last-Event-ID header on reconnect, taking
        # priority over any stale `after` query param a client might also
        # send.
        last_event_id = request.headers.get("last-event-id")
        if last_event_id is not None:
            try:
                after = int(last_event_id)
            except ValueError:
                after = None
        return StreamingResponse(
            stream_events(app.state.tailer, after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if _STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")

    return app
