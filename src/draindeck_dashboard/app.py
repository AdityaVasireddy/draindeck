"""App factory (ADR-26 decision 1; docs/19).

FastAPI/Uvicorn live only in this package — core ``src/runtime`` never
imports from here or from FastAPI/Starlette/Uvicorn directly.
"""
from __future__ import annotations

import json
import hashlib
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from . import api_queries
from . import proxy_cost_agg
from .artifacts import artifact_root_for_log, resolve_contained_artifact
from .config import DashboardConfig
from .db import connect_and_init
from .diffs import compute_diff
from .errors import DashboardApiError, InvalidFilterError, NotFoundError, register_error_handlers
from .health import build_health
from .projections import RUN_METADATA_UNAVAILABLE
from .repositories import (
    delete_repository,
    get_repository,
    list_repositories,
    register_repository,
)
from .scheduler import Scheduler
from .search import search as run_search
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
    list_runs,
)
from runtime.init.detect import CommandProposal, build_command, detect_stacks
from runtime.init.generate import render_config
from runtime.init.service import (
    TargetConfigurationError,
    TargetConfigurationRequest,
    apply_target_configuration,
    prepare_target_configuration,
)


def _run_metadata_field(conn, repo_id: int, run_id: Optional[str]) -> dict:
    """v2 read-model counterpart to views.py's _run_metadata_field (which
    reads from a live build_projection replay) -- same shape, same exact
    RUN_METADATA_UNAVAILABLE fallback text, so Execution Detail never
    shows a blank metadata panel (docs/19) regardless of which endpoint
    served it. Availability comes from whether a run_views row exists for
    this run_id in the CURRENT generation, never from run_id's string shape."""
    if run_id is None:
        return {"available": False, "message": RUN_METADATA_UNAVAILABLE}
    row = conn.execute(
        "SELECT rv.run_id, rv.engine_provider, rv.engine_model, rv.reviewer_provider, "
        "rv.reviewer_model, rv.budget_json, rv.config_digest, rv.outcome, rv.inconsistent "
        "FROM run_views rv JOIN checkpoints c ON c.repository_id = rv.repository_id "
        "AND c.identity_generation_id = rv.identity_generation_id "
        "WHERE rv.repository_id = ? AND rv.run_id = ?", (repo_id, run_id),
    ).fetchone()
    if row is None:
        return {"available": False, "message": RUN_METADATA_UNAVAILABLE}
    return {
        "available": True, "runId": row[0], "engineProvider": row[1], "engineModel": row[2],
        "reviewerProvider": row[3], "reviewerModel": row[4],
        "budget": json.loads(row[5]) if row[5] else {}, "configDigest": row[6],
        "outcome": row[7], "inconsistent": bool(row[8]),
    }


_PAGE_LIMIT_DEFAULT = 50
_PAGE_LIMIT_MAX = 200

_STATIC_DIR = Path(__file__).parent / "static"


def _dashboard_version() -> str:
    try:
        return _pkg_version("draindeck")
    except PackageNotFoundError:
        return "unknown"


class _RegisterRepositoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectPath: str
    logPath: Optional[str] = None


class _TargetConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectPath: str
    renderedYaml: str
    expectedConfigDigest: Optional[str] = None
    branchChangeConfirmed: bool = False


class _RenderTargetConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    projectPath: str
    branch: str
    commands: list[str]


def _require_git_worktree(project_path: str) -> Path:
    repo_path = Path(project_path)
    if not repo_path.is_absolute() or not repo_path.is_dir() or not (repo_path / ".git").exists():
        raise DashboardApiError(
            "CONFIG_INVALID", "projectPath must be an existing Git worktree", status_code=400,
        )
    return repo_path


def _configuration_error(exc: TargetConfigurationError) -> DashboardApiError:
    statuses = {
        "CONFIG_REVISION_CONFLICT": 409,
        "WORKSPACE_LEASE_UNAVAILABLE": 423,
        "RECOVERY_REQUIRED": 409,
        "RUNTIME_STATE_UNSAFE": 409,
        "DIRTY_WORKTREE": 409,
    }
    return DashboardApiError(exc.code, str(exc), status_code=statuses.get(exc.code, 400))


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

    @app.get("/api/about")
    async def about() -> dict:
        return {
            "host": cfg.host,
            "port": cfg.port,
            "dbPath": cfg.db_path,
            "version": _dashboard_version(),
        }

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

    @app.get("/api/target-configurations/detect")
    async def detect_target_stack(projectPath: str) -> dict:
        """Read-only stack detection for the New Target form's "detected
        defaults" step -- reuses the exact same `runtime.init.detect`
        modules `draindeck init` uses, so the Dashboard never reimplements
        detection or YAML templating in JavaScript. Never proposes or runs
        an install command (spec non-goal: the Dashboard never executes
        anything while configuring a target)."""
        repo_path = _require_git_worktree(projectPath)
        matches = detect_stacks(repo_path)
        chosen_row = matches[0] if matches else None
        chosen = build_command(chosen_row, repo_path) if chosen_row is not None else None
        return {
            "detectedStacks": [m.stack for m in matches],
            "chosenStack": chosen_row.stack if chosen_row is not None else None,
            "proposedCommands": chosen.commands if chosen is not None else [],
        }

    @app.post("/api/target-configurations/render")
    async def render_target_configuration(payload: _RenderTargetConfigurationRequest) -> dict:
        """Renders the exact proposed config.local.yaml text server-side
        (same runtime.init.generate.render_config the CLI uses) so the
        browser only ever reviews/edits structured fields, never assembles
        or quotes YAML itself. `commands=[]` renders the acknowledged-no-
        validation-gate block (ADR-24) -- the form is responsible for
        getting an explicit user acknowledgement before sending that."""
        repo_path = _require_git_worktree(payload.projectPath)
        matches = detect_stacks(repo_path)
        chosen_stack = matches[0].stack if matches else "manual"
        text = render_config(
            repo_path=repo_path, branch=payload.branch, branch_tip="",
            all_matches=matches, chosen_stack=chosen_stack,
            chosen=CommandProposal(commands=list(payload.commands)),
        )
        return {"renderedYaml": text, "chosenStack": chosen_stack}

    @app.post("/api/target-configurations/preview")
    async def preview_target_configuration(payload: _TargetConfigurationRequest) -> dict:
        try:
            preview = prepare_target_configuration(TargetConfigurationRequest(
                repository_path=Path(payload.projectPath), rendered_yaml=payload.renderedYaml,
                expected_config_digest=payload.expectedConfigDigest,
                branch_change_confirmed=payload.branchChangeConfirmed,
            ))
        except TargetConfigurationError as exc:
            raise _configuration_error(exc) from exc
        return {
            "configPath": str(preview.config_path),
            "currentConfigDigest": preview.current_config_digest,
            "proposedConfigDigest": preview.proposed_config_digest,
            "renderedYaml": preview.rendered_yaml,
            "resolvedLogPath": str(preview.resolved_log_path),
            "branchOperation": preview.branch_operation,
            "branchConfirmationRequired": preview.branch_confirmation_required,
        }

    @app.post("/api/target-configurations", status_code=201)
    async def apply_new_target_configuration(payload: _TargetConfigurationRequest) -> dict:
        try:
            result = apply_target_configuration(TargetConfigurationRequest(
                repository_path=Path(payload.projectPath), rendered_yaml=payload.renderedYaml,
                expected_config_digest=payload.expectedConfigDigest,
                branch_change_confirmed=payload.branchChangeConfirmed,
            ))
            registration = register_repository(
                app.state.db, project_path=payload.projectPath, log_path=str(result.resolved_log_path))
        except TargetConfigurationError as exc:
            raise _configuration_error(exc) from exc
        return {"result": {"configPath": str(result.config_path), "configDigest": result.config_digest,
                           "branchOperation": result.branch_operation},
                "registration": registration}

    @app.get("/api/repositories/{repo_id}/configuration")
    async def get_target_configuration(repo_id: int) -> dict:
        registration = get_repository(app.state.db, repo_id)
        config_path = Path(registration["projectPath"]) / ".draindeck" / "config.local.yaml"
        if not config_path.is_file():
            raise NotFoundError("canonical target configuration not found")
        rendered = config_path.read_text(encoding="utf-8")
        return {"configPath": str(config_path), "renderedYaml": rendered,
                "currentConfigDigest": hashlib.sha256(rendered.encode("utf-8")).hexdigest()}

    @app.patch("/api/repositories/{repo_id}/configuration")
    async def update_target_configuration(repo_id: int, payload: _TargetConfigurationRequest) -> dict:
        registration = get_repository(app.state.db, repo_id)
        if Path(payload.projectPath).resolve() != Path(registration["projectPath"]).resolve():
            raise DashboardApiError("CONFIG_INVALID", "projectPath must match the registered repository", status_code=400)
        try:
            result = apply_target_configuration(TargetConfigurationRequest(
                repository_path=Path(payload.projectPath), rendered_yaml=payload.renderedYaml,
                expected_config_digest=payload.expectedConfigDigest,
                branch_change_confirmed=payload.branchChangeConfirmed,
            ))
        except TargetConfigurationError as exc:
            raise _configuration_error(exc) from exc
        return {"configPath": str(result.config_path), "configDigest": result.config_digest,
                "branchOperation": result.branch_operation}

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

    @app.get("/api/repositories/{repo_id}/runs")
    async def repository_runs(
        repo_id: int,
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        get_repository(app.state.db, repo_id)
        return list_runs(app.state.db, repo_id, limit=limit, offset=offset)

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

    # --- ADR-27 additive cross-repository/search/detail routes (Unit 5) ---
    # Thin wrappers only -- all business SQL lives in api_queries.py/
    # search.py/attention.py; a DashboardApiError subclass raised by any of
    # them (InvalidSort/InvalidFilter/QueryTooShort/PageOutOfRange/...) is
    # converted to its typed envelope by the existing generic handler.

    @app.get("/api/overview")
    async def api_overview() -> dict:
        return api_queries.overview(app.state.db)

    @app.get("/api/repository-summaries")
    async def api_repository_summaries(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0),
        q: Optional[str] = None, availability: Optional[str] = None,
        hasAttention: Optional[bool] = None, sort: str = "name", direction: str = "asc",
    ) -> dict:
        return api_queries.repository_summaries(
            app.state.db, limit=limit, offset=offset, q=q, availability=availability,
            has_attention=hasAttention, sort=sort, direction=direction,
        )

    @app.get("/api/attention")
    async def api_attention(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0), status: str = "current",
        severity: Optional[str] = None, repositoryId: Optional[int] = None,
    ) -> dict:
        api_queries.check_offset_cap(offset, cap=api_queries.NEW_ROUTE_OFFSET_CAP)
        where = ["1=1"]
        params: list = []
        if status == "current":
            where.append("resolved_at IS NULL")
        elif status == "resolved":
            where.append("resolved_at IS NOT NULL")
        elif status != "all":
            raise InvalidFilterError(f"unsupported status {status!r}")
        if severity is not None:
            where.append("severity = ?")
            params.append(severity)
        if repositoryId is not None:
            where.append("repository_id = ?")
            params.append(repositoryId)
        # docs/27 SS6.4's 10-second LEASE_UNCLAIMED "no startup flash" gate
        # (attention.py deliberately does not enforce this itself -- it's a
        # query-layer/visibility concern, not a detection-time one, so
        # first_detected_at stays an honest anchor). Scoped narrowly to
        # kind='LEASE_UNCLAIMED': LEASE_STALE (critical) is never delayed,
        # and an already-RESOLVED LEASE_UNCLAIMED row (history, not a live
        # flash risk) is never hidden regardless of age.
        where.append(
            "(kind != 'LEASE_UNCLAIMED' OR resolved_at IS NOT NULL OR "
            "first_detected_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-10 seconds'))"
        )
        where_sql = " AND ".join(where)
        total = app.state.db.execute(
            f"SELECT COUNT(*) FROM attention_conditions WHERE {where_sql}", params
        ).fetchone()[0]
        rows = app.state.db.execute(
            f"SELECT condition_key, kind, severity, repository_id, subject_type, subject_id, "
            f"message, target_url, first_detected_at, last_detected_at, resolved_at "
            f"FROM attention_conditions WHERE {where_sql} "
            "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
            "first_detected_at LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = [
            {"conditionId": key, "kind": kind, "severity": sev,
             "repository": ({"id": repo_id} if repo_id is not None else None),
             "subject": ({"type": st, "id": sid} if st is not None else None),
             "message": msg, "targetUrl": url, "firstDetectedAt": first, "lastDetectedAt": last,
             "resolvedAt": resolved}
            for (key, kind, sev, repo_id, st, sid, msg, url, first, last, resolved) in rows
        ]
        return {"items": items, "limit": limit, "offset": offset, "total": total}

    @app.get("/api/search")
    async def api_search(q: str, limit: int = Query(default=5, ge=1, le=10)) -> dict:
        return run_search(app.state.db, q, limit=limit)

    @app.get("/api/issues")
    async def api_cross_repository_issues(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0), repositoryId: Optional[int] = None,
        state: Optional[str] = None, sort: str = "issueId", direction: str = "asc",
    ) -> dict:
        return api_queries.cross_repository_issues(
            app.state.db, limit=limit, offset=offset, repository_id=repositoryId, state=state,
            sort=sort, direction=direction,
        )

    @app.get("/api/runs")
    async def api_cross_repository_runs(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0), repositoryId: Optional[int] = None,
        outcome: Optional[str] = None, sort: str = "runId", direction: str = "asc",
    ) -> dict:
        return api_queries.cross_repository_runs(
            app.state.db, limit=limit, offset=offset, repository_id=repositoryId, outcome=outcome,
            sort=sort, direction=direction,
        )

    @app.get("/api/executions")
    async def api_cross_repository_executions(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0), repositoryId: Optional[int] = None,
        state: Optional[str] = None, groupBy: str = "execution", sort: str = "executionId",
        direction: str = "asc",
    ) -> dict:
        return api_queries.cross_repository_executions(
            app.state.db, limit=limit, offset=offset, repository_id=repositoryId, state=state,
            group_by=groupBy, sort=sort, direction=direction,
        )

    @app.get("/api/evidence")
    async def api_cross_repository_evidence(
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        beforeEvidenceId: Optional[int] = None, afterEvidenceId: Optional[int] = None,
        direction: str = "desc", repositoryId: Optional[int] = None,
    ) -> dict:
        return api_queries.evidence_keyset(
            app.state.db, limit=limit, before_evidence_id=beforeEvidenceId,
            after_evidence_id=afterEvidenceId, direction=direction, repository_id=repositoryId,
        )

    @app.get("/api/repositories/{repo_id}/overview")
    async def api_repository_overview(repo_id: int) -> dict:
        registration = get_repository(app.state.db, repo_id)  # 404 if missing
        health = build_health(app.state.db, repo_id)
        return {
            "registration": registration, "health": health,
            "attention": api_queries.repository_attention_summary(app.state.db, repo_id),
            "proxyCost": proxy_cost_agg.repository_proxy_cost(app.state.db, repo_id),
            "averageProxyCostPerCompletedIssue":
                proxy_cost_agg.average_proxy_cost_per_completed_issue(app.state.db, repo_id),
        }

    @app.get("/api/repositories/{repo_id}/issues/{issue_id}")
    async def api_issue_detail(repo_id: int, issue_id: str) -> dict:
        get_repository(app.state.db, repo_id)
        api_queries.check_read_model_readiness(app.state.db, repo_id)
        row = app.state.db.execute(
            "SELECT iv.issue_id, iv.state, iv.title, iv.inconsistent, iv.last_event_id "
            "FROM issue_views iv JOIN checkpoints c ON c.repository_id = iv.repository_id "
            "AND c.identity_generation_id = iv.identity_generation_id "
            "WHERE iv.repository_id = ? AND iv.issue_id = ?", (repo_id, issue_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"issue {issue_id} not found in repository {repo_id}")
        attempt_rows = app.state.db.execute(
            "SELECT ev.execution_id, ev.state, ev.proxy_micro_usd, ev.cost_valid, "
            "ev.input_tokens, ev.output_tokens, ev.tokens_valid FROM execution_views ev "
            "JOIN checkpoints c ON c.repository_id = ev.repository_id "
            "AND c.identity_generation_id = ev.identity_generation_id "
            "WHERE ev.repository_id = ? AND ev.issue_id = ? ORDER BY ev.execution_id",
            (repo_id, issue_id),
        ).fetchall()
        attempts = [
            {"executionId": ar[0], "state": ar[1],
             "proxyCost": proxy_cost_agg.execution_proxy_cost(ar[2], ar[3], ar[4], ar[5], ar[6])}
            for ar in attempt_rows
        ]
        return {"issueId": row[0], "state": row[1], "title": row[2], "inconsistent": bool(row[3]),
               "lastEventId": row[4],
               "proxyCost": proxy_cost_agg.issue_proxy_cost(app.state.db, repo_id, issue_id),
               "executionAttempts": attempts}

    @app.get("/api/repositories/{repo_id}/runs/{run_id}")
    async def api_run_detail(repo_id: int, run_id: str) -> dict:
        get_repository(app.state.db, repo_id)
        api_queries.check_read_model_readiness(app.state.db, repo_id)
        row = app.state.db.execute(
            "SELECT rv.run_id, rv.engine_provider, rv.engine_model, rv.reviewer_provider, "
            "rv.reviewer_model, rv.budget_json, rv.config_digest, rv.outcome, rv.inconsistent, "
            "rv.last_event_id, rv.observed_started_at, rv.observed_finished_at FROM run_views rv "
            "JOIN checkpoints c ON c.repository_id = rv.repository_id "
            "AND c.identity_generation_id = rv.identity_generation_id "
            "WHERE rv.repository_id = ? AND rv.run_id = ?", (repo_id, run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"run {run_id} not found in repository {repo_id}")
        return {
            "runId": row[0], "engineProvider": row[1], "engineModel": row[2],
            "reviewerProvider": row[3], "reviewerModel": row[4],
            "budget": json.loads(row[5]) if row[5] else {}, "configDigest": row[6],
            "outcome": row[7], "displayOutcome": row[7] or "no controlled finish observed",
            "inconsistent": bool(row[8]), "lastEventId": row[9],
            "observedStartedAt": row[10], "observedFinishedAt": row[11],
            "proxyCost": proxy_cost_agg.run_proxy_cost(app.state.db, repo_id, run_id),
        }

    @app.get("/api/repositories/{repo_id}/executions/{execution_id}")
    async def api_execution_detail(repo_id: int, execution_id: str) -> dict:
        get_repository(app.state.db, repo_id)
        api_queries.check_read_model_readiness(app.state.db, repo_id)
        row = app.state.db.execute(
            "SELECT ev.execution_id, ev.issue_id, ev.state, ev.inconsistent, ev.last_event_id, "
            "ev.run_id, ev.proxy_micro_usd, ev.cost_valid, ev.input_tokens, ev.output_tokens, "
            "ev.tokens_valid FROM execution_views ev JOIN checkpoints c "
            "ON c.repository_id = ev.repository_id AND c.identity_generation_id = ev.identity_generation_id "
            "WHERE ev.repository_id = ? AND ev.execution_id = ?", (repo_id, execution_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"execution {execution_id} not found in repository {repo_id}")
        containment_rows = app.state.db.execute(
            "SELECT cv.containment_generation, cv.workspace_key, cv.state, cv.inconsistent "
            "FROM containment_views cv JOIN checkpoints c ON c.repository_id = cv.repository_id "
            "AND c.identity_generation_id = cv.identity_generation_id "
            "WHERE cv.repository_id = ? AND cv.execution_id = ? ORDER BY cv.containment_generation",
            (repo_id, execution_id),
        ).fetchall()
        return {
            "executionId": row[0], "issueId": row[1], "state": row[2], "inconsistent": bool(row[3]),
            "lastEventId": row[4], "runId": row[5],
            "runMetadata": _run_metadata_field(app.state.db, repo_id, row[5]),
            "proxyCost": proxy_cost_agg.execution_proxy_cost(row[6], row[7], row[8], row[9], row[10]),
            "containments": [
                {"containmentGeneration": gen, "workspaceKey": wk, "state": st,
                 "inconsistent": bool(inc)}
                for gen, wk, st, inc in containment_rows
            ],
        }

    @app.get("/api/repositories/{repo_id}/evidence/{evidence_id}")
    async def api_evidence_detail(repo_id: int, evidence_id: int) -> dict:
        get_repository(app.state.db, repo_id)
        row = app.state.db.execute(
            "SELECT e.id, e.record_cursor, e.integrity, e.event_id, e.event_type, "
            "e.schema_version, e.issue_id, e.execution_id, e.run_id, e.event_ts, e.record_hash, "
            "e.length_bytes FROM evidence e JOIN checkpoints c ON c.repository_id = e.repository_id "
            "AND c.identity_generation_id = e.identity_generation_id "
            "WHERE e.repository_id = ? AND e.id = ?", (repo_id, evidence_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(f"evidence {evidence_id} not found in repository {repo_id}")
        return {
            "evidenceId": row[0], "cursor": row[1], "integrity": row[2], "eventId": row[3],
            "eventType": row[4], "schemaVersion": row[5], "issueId": row[6], "executionId": row[7],
            "runId": row[8], "ts": row[9], "recordHash": row[10], "lengthBytes": row[11],
        }

    @app.get("/api/repositories/{repo_id}/{entity_type}/{entity_id}/timeline")
    async def api_entity_timeline(
        repo_id: int, entity_type: str, entity_id: str,
        limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
        offset: int = Query(default=0, ge=0), direction: str = "asc",
    ) -> dict:
        get_repository(app.state.db, repo_id)
        return api_queries.entity_timeline(
            app.state.db, repo_id, entity_type, entity_id, limit=limit, offset=offset,
            direction=direction,
        )

    @app.get("/api/repositories/{repo_id}/{entity_type}/{entity_id}/topology")
    async def api_entity_topology(repo_id: int, entity_type: str, entity_id: str) -> dict:
        get_repository(app.state.db, repo_id)
        return api_queries.entity_topology(app.state.db, repo_id, entity_type, entity_id)

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

    # --- Stable UI routing (Unit 6; docs/27 SS9.1) ---
    # API routes are already fully registered above this point. Static
    # assets mount only at /assets (never at "/", so it can never swallow
    # an unmatched /api/* path into a 404-from-StaticFiles instead of
    # FastAPI's own routing 404). An explicit allowlist of approved UI
    # route PATTERNS returns the same semantic app shell for a direct
    # reload/deep-link; a genuinely unknown path falls through to
    # Starlette's ordinary 404 -- there is no catch-all mount left to hide
    # it. Legacy /styles.css and /app.js get their own compatibility
    # routes since they no longer live under the "/" root.
    if _STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR)), name="assets")

        @app.get("/styles.css", include_in_schema=False)
        async def legacy_styles_css() -> FileResponse:
            return FileResponse(_STATIC_DIR / "styles.css", media_type="text/css")

        @app.get("/app.js", include_in_schema=False)
        async def legacy_app_js() -> FileResponse:
            return FileResponse(_STATIC_DIR / "app.js", media_type="application/javascript")

        async def _app_shell() -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html", media_type="text/html")

        _ui_route_patterns = [
            "/",
            "/repositories", "/repositories/new", "/repositories/{repo_id}",
            "/repositories/{repo_id}/runs", "/repositories/{repo_id}/runs/{run_id}",
            "/repositories/{repo_id}/issues", "/repositories/{repo_id}/issues/{issue_id}",
            "/repositories/{repo_id}/executions", "/repositories/{repo_id}/executions/{execution_id}",
            "/repositories/{repo_id}/evidence", "/repositories/{repo_id}/evidence/{evidence_id}",
            "/attention", "/runs", "/issues", "/executions", "/evidence", "/about",
        ]
        for pattern in _ui_route_patterns:
            app.add_api_route(pattern, _app_shell, methods=["GET"], include_in_schema=False)

    return app
