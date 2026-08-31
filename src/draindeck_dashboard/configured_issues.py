"""Configured issue reading (ADR-30 / spec/dashboard-issue-run-control.md
"Registration and configured issue source").

Delegates every parse to the existing `runtime.queue.issues_md.parse` --
this module implements no second heading/dependency parser. The configured
file supplies identity/text/dependencies/order only; workflow state comes
only from the existing observer/indexed projection (`read_models`/
`projections`), never from source text. The config and issue file are
re-read on every call -- nothing here is cached across requests.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

from runtime.config import Config, ConfigError, load_config
from runtime.queue.issues_md import IssueSpec, IssuesParseError, parse

from .errors import DashboardApiError
from .read_models import read_model_status
from .repositories import get_repository

# The parser only recognizes an un-bulleted `Depends-On:` line; a bulleted
# one is silently treated as plain body text (no dependency). This regex
# exists only to surface that known gotcha in the UI/API -- it never feeds
# a second dependency interpretation back into the returned issue list.
_BULLETED_DEPENDS_ON = re.compile(r"^[ \t]*[-*][ \t]+Depends-On\s*:", re.IGNORECASE | re.MULTILINE)


class ConfiguredIssuesError(DashboardApiError):
    pass


def _resolve_issues_file(cfg: Config) -> Path:
    p = Path(cfg.project.issues_file)
    return p if p.is_absolute() else Path(cfg.project.repository) / p


def _issue_dict(spec: IssueSpec, state: str) -> dict:
    return {
        "issueId": spec.id,
        "title": spec.title,
        "body": spec.body,
        "dependsOn": list(spec.depends_on),
        "acceptanceCriteria": list(spec.acceptance_criteria),
        "state": state,
    }


def get_configured_issues(conn, repo_id: int) -> dict:
    registration = get_repository(conn, repo_id)  # raises NotFoundError
    config_path = registration["configPath"]
    if config_path is None:
        raise ConfiguredIssuesError(
            "CONFIG_NOT_REGISTERED",
            "repository has no validated canonical config; supply one through "
            "registration before reading configured issues",
            status_code=409,
        )

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        raise ConfiguredIssuesError("CONFIG_INVALID", str(exc), status_code=409) from exc

    issues_file = _resolve_issues_file(cfg)
    if not issues_file.exists():
        raise ConfiguredIssuesError(
            "ISSUES_FILE_NOT_FOUND", f"issues file not found: {issues_file}", status_code=409,
        )
    if not issues_file.is_file():
        raise ConfiguredIssuesError(
            "ISSUES_FILE_NOT_REGULAR_FILE",
            f"issues file is not a regular file: {issues_file}", status_code=409,
        )

    try:
        raw = issues_file.read_bytes()
    except OSError as exc:
        raise ConfiguredIssuesError("ISSUES_FILE_UNREADABLE", str(exc), status_code=409) from exc

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfiguredIssuesError("ISSUES_FILE_INVALID_UTF8", str(exc), status_code=409) from exc

    try:
        specs = parse(text)
    except IssuesParseError as exc:
        raise ConfiguredIssuesError("ISSUES_PARSE_ERROR", str(exc), status_code=409) from exc

    revision = hashlib.sha256(raw).hexdigest()
    parser_warning = bool(_BULLETED_DEPENDS_ON.search(text))

    status = read_model_status(conn, repo_id)
    ready = status is not None and status["status"] == "READY"

    active_outside_file: list[str] = []
    issues: list[dict]
    if ready:
        # Reads the materialized issue_views table (the same read model
        # api_queries.py's scalable list uses), scoped to the read model's
        # own current generation -- never a per-request full-evidence
        # recompute, and never stale data from a generation this read
        # model has since rolled over past.
        rows = conn.execute(
            "SELECT issue_id, state FROM issue_views "
            "WHERE repository_id = ? AND identity_generation_id = ?",
            (repo_id, status["identityGenerationId"]),
        ).fetchall()
        states = {row[0]: row[1] for row in rows}
        configured_ids = {s.id for s in specs}
        active_outside_file = sorted(
            iid for iid, st in states.items() if st == "ACTIVE" and iid not in configured_ids
        )
        issues = [_issue_dict(s, states.get(s.id, "NOT_INGESTED")) for s in specs]
    else:
        # No runnable conclusion is permitted while the projection is
        # anything but READY (missing/PREPARING/REBUILDING/ERROR) -- issue
        # text is still shown, honestly, but every state is UNAVAILABLE.
        issues = [_issue_dict(s, "UNAVAILABLE") for s in specs]

    return {
        "configPath": config_path,
        "issuesFilePath": str(issues_file),
        "issuesFileRevision": revision,
        "parserWarning": parser_warning,
        # Run-level budget context for the UI's pre-mutation confirmation
        # (spec "User experience"); read straight from the loaded config,
        # never a second source of truth.
        "budget": {
            "maxAttemptsPerIssue": cfg.budget.max_attempts_per_issue,
            "maxExecutionsPerRun": cfg.budget.max_executions_per_run,
            "hardStopProxyCostPerRunUsd": cfg.budget.hard_stop_proxy_cost_per_run_usd,
        },
        "readModelStatus": status["status"] if status is not None else "UNAVAILABLE",
        # Surfaced for the pure planner (RED 3/4) to refuse a new selection
        # that omits an authoritative ACTIVE issue no longer in the file;
        # this reader only detects and reports the condition.
        "activeIssuesOutsideFile": active_outside_file,
        "issues": issues,
    }
