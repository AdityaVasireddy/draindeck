"""Bounded, parameterized, current-generation-joined query layer (ADR-27
decision 4/8; docs/27 SS7).

Every cross-repository query joins ``checkpoints.identity_generation_id``
so only current-generation rows are ever returned -- a repository mid- or
post-rollover never leaks a stale generation's issues/executions/runs.
Sort columns/directions are always selected from a server-side allowlist
constant, never interpolated from caller input (docs/27 SS12); the only
values ever bound as query parameters are caller-supplied.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .errors import IndexPreparingError, InvalidFilterError, InvalidSortError, PageOutOfRangeError
from .read_models import read_model_status
from . import proxy_cost_agg

NEW_ROUTE_OFFSET_CAP = 10_000
LEGACY_EVIDENCE_OFFSET_CAP = 100_000
_EXECUTION_GROUP_PREVIEW_LIMIT = 5


def check_offset_cap(offset: int, *, cap: int) -> None:
    if offset > cap:
        raise PageOutOfRangeError(f"offset {offset} exceeds the maximum of {cap}")


def _paginate(items: list, *, limit: int, offset: int, total: int) -> dict:
    return {"items": items, "limit": limit, "offset": offset, "total": total}


def check_read_model_readiness(conn: sqlite3.Connection, repository_id: Optional[int]) -> Optional[dict]:
    """docs/27 SS3.2 decision 9: an endpoint scoped to ONE repository whose
    issue_views/run_views/execution_views/containment_views may not yet
    reflect a complete snapshot must never silently answer with what looks
    like a genuine (if empty) result. `repository_id=None` means a
    cross-repository endpoint -- callers instead attach `projectionState`
    (see `projection_state_summary`) rather than blocking the whole
    response over one repository's readiness.

    Returns `None` when nothing needs to be labelled (repository_id is
    None, or genuinely READY). Returns `{"stale": True}` when a complete
    snapshot exists but is now known out of date (REBUILDING) -- callers
    serve the existing rows anyway, just labelled. Raises
    `IndexPreparingError` when no complete snapshot exists at all
    (PREPARING, ERROR, no read_model_state row yet, or any OTHER,
    unrecognized status value).

    Deliberately an ALLOWLIST (only READY/REBUILDING pass) rather than a
    denylist of the known not-ready values -- fails CLOSED on anything
    unrecognized (security review, this session's merge-blocker round).
    A denylist previously let a legacy `status='FAILED'` row (the value
    this exact codebase wrote before the FAILED->ERROR rename) silently
    fall through as if it were a genuine complete snapshot; startup
    migration (`migrations.py`'s `run_migrations`) now rewrites any such
    row to `'ERROR'` in place, and this allowlist is the defense-in-depth
    backstop for that correction, not the only thing relying on it."""
    if repository_id is None:
        return None
    status = read_model_status(conn, repository_id)
    if status is None or status["status"] not in ("READY", "REBUILDING"):
        raise IndexPreparingError()
    if status["status"] == "REBUILDING":
        return {"stale": True}
    return None


def projection_state_summary(conn: sqlite3.Connection) -> dict:
    """The cross-repository counterpart to `check_read_model_readiness`:
    never blocks, just discloses which repositories' rows (if any) are
    not part of a complete snapshot, so a caller aggregating across many
    repositories can honestly label the result rather than presenting a
    silently-incomplete total as complete."""
    # A repository with NO read_model_state row at all (registered, but
    # not yet through its very first tick) is at least as "not ready" as
    # one explicitly marked PREPARING -- the LEFT JOIN catches that case
    # too, not just an explicit status value. Allowlist (NOT IN
    # READY/REBUILDING), not a denylist -- same fail-closed reasoning as
    # check_read_model_readiness's docstring above.
    preparing = [row[0] for row in conn.execute(
        "SELECT r.id FROM repositories r LEFT JOIN read_model_state rms "
        "ON rms.repository_id = r.id "
        "WHERE rms.repository_id IS NULL OR rms.status NOT IN ('READY', 'REBUILDING')"
    ).fetchall()]
    stale = [row[0] for row in conn.execute(
        "SELECT repository_id FROM read_model_state WHERE status = 'REBUILDING'"
    ).fetchall()]
    return {
        "complete": not preparing and not stale,
        "preparingRepositoryIds": preparing,
        "staleRepositoryIds": stale,
    }


# --- repository summaries ---

_REPO_SORT_COLUMNS = {
    "name": "r.project_path",
    "createdAt": "r.created_at",
    "availability": "c.availability",
    "latestRunAt": "latest_run_at",
    "attentionCount": "attention_count",
}


def repository_summaries(conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0,
                         q: Optional[str] = None, availability: Optional[str] = None,
                         has_attention: Optional[bool] = None, sort: str = "name",
                         direction: str = "asc") -> dict:
    check_offset_cap(offset, cap=NEW_ROUTE_OFFSET_CAP)
    column = _REPO_SORT_COLUMNS.get(sort)
    if column is None:
        raise InvalidSortError(f"unsupported repository sort {sort!r}")
    if direction not in ("asc", "desc"):
        raise InvalidSortError(f"unsupported sort direction {direction!r}")

    where = ["1=1"]
    params: list = []
    if q is not None:
        where.append("r.project_path LIKE ? ESCAPE '\\'")
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.append(f"%{escaped}%")
    if availability is not None:
        where.append("c.availability = ?")
        params.append(availability)
    attn_expr = "COALESCE(ac.attention_count, 0)"
    if has_attention is True:
        where.append(f"{attn_expr} > 0")
    elif has_attention is False:
        where.append(f"{attn_expr} = 0")
    where_sql = " AND ".join(where)

    # column may reference the plain "attention_count"/"latest_run_at"
    # sort aliases from _REPO_SORT_COLUMNS; resolve them to their real
    # joined-column expressions for ORDER BY.
    order_column = {"attention_count": attn_expr, "latest_run_at": "lr.latest_run_at"}.get(column, column)

    # count_joins omits the "latest run" window-function subquery below --
    # neither the WHERE clause nor a plain COUNT(*) ever reference `lr`,
    # so joining it would needlessly re-materialize a ROW_NUMBER() window
    # over every run on every page-count call, reintroducing the exact
    # per-request cost the tie-break fix (above) was written to avoid.
    count_joins = (
        "FROM repositories r "
        "LEFT JOIN checkpoints c ON c.repository_id = r.id "
        "LEFT JOIN ("
        "  SELECT repository_id, COUNT(*) AS attention_count FROM attention_conditions "
        "  WHERE resolved_at IS NULL GROUP BY repository_id"
        ") ac ON ac.repository_id = r.id"
    )
    joins = (
        count_joins + " "
        "LEFT JOIN ("
        "  SELECT repository_id, latest_outcome, latest_run_at FROM ("
        "    SELECT rv.repository_id, rv.outcome AS latest_outcome, "
        "      COALESCE(rv.observed_finished_at, rv.observed_started_at) AS latest_run_at, "
        # A tied updated_at (realistic under second-resolution timestamps
        # and concurrent/batch runs) must still resolve to exactly one row
        # per repository -- never fan out and multiply the repository in
        # the outer result set. run_id is an arbitrary but stable
        # tie-break, not a meaningful ordering.
        "      ROW_NUMBER() OVER (PARTITION BY rv.repository_id "
        "        ORDER BY rv.updated_at DESC, rv.run_id DESC) AS rn "
        "    FROM run_views rv "
        "    JOIN checkpoints c2 ON c2.repository_id = rv.repository_id "
        "      AND c2.identity_generation_id = rv.identity_generation_id"
        "  ) WHERE rn = 1"
        ") lr ON lr.repository_id = r.id"
    )
    sql = (
        f"SELECT r.id, r.project_path, r.log_path, r.created_at, c.availability, "
        f"  {attn_expr} AS attention_count, lr.latest_outcome, lr.latest_run_at "
        f"{joins} WHERE {where_sql} "
        f"ORDER BY {order_column} {direction.upper()}, r.id "
        "LIMIT ? OFFSET ?"
    )
    count_sql = f"SELECT COUNT(*) {count_joins} WHERE {where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    items = []
    for (repo_id, project_path, log_path, created_at, avail, attn_count,
         latest_outcome, latest_run_at) in rows:
        items.append({
            "id": repo_id,
            "projectPath": project_path,
            "logPath": log_path,
            "createdAt": created_at,
            "displayName": project_path.replace("\\", "/").rsplit("/", 1)[-1],
            "availability": avail,
            "attentionCount": attn_count,
            "latestRun": ({"outcome": latest_outcome, "observedAt": latest_run_at}
                         if latest_run_at is not None else None),
        })
    return _paginate(items, limit=limit, offset=offset, total=total)


def repository_attention_summary(conn: sqlite3.Connection, repo_id: int, *, preview_limit: int = 5) -> dict:
    """The SAME persisted `attention_conditions` table `/api/attention` and
    `repository_summaries`'s `attentionCount` already read (Unit 16
    contract-honesty finding: Repository Overview previously called
    `derive_repository_conditions()` fresh on every request instead, so
    the "current attention" number shown here and the one shown on
    Repositories/Attention could genuinely disagree in the window before
    the next lease-owner reconciliation tick). Only the lease-owning
    writer ever persists condition changes (attention.py), so reading the
    stored rows here -- rather than recomputing -- is what makes every
    screen agree on the same number at the same instant."""
    total = conn.execute(
        "SELECT COUNT(*) FROM attention_conditions WHERE repository_id = ? AND resolved_at IS NULL",
        (repo_id,),
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT kind, severity, message, target_url FROM attention_conditions "
        "WHERE repository_id = ? AND resolved_at IS NULL "
        "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
        "first_detected_at LIMIT ?",
        (repo_id, preview_limit),
    ).fetchall()
    return {
        "current": total,
        "items": [
            {"kind": kind, "severity": severity, "message": message, "targetUrl": url}
            for kind, severity, message, url in rows
        ],
    }


# --- overview ---

def overview(conn: sqlite3.Connection) -> dict:
    repo_total = conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
    by_availability_rows = conn.execute(
        "SELECT COALESCE(c.availability, 'NOT_OBSERVED'), COUNT(*) FROM repositories r "
        "LEFT JOIN checkpoints c ON c.repository_id = r.id GROUP BY 1"
    ).fetchall()
    by_availability = {k: 0 for k in ("AVAILABLE", "EMPTY", "NOT_INITIALIZED", "OFFLINE", "NOT_OBSERVED")}
    for key, count in by_availability_rows:
        by_availability[key] = count

    # Same 10-second LEASE_UNCLAIMED "no startup flash" gate as /api/attention
    # (app.py) -- this aggregate must never disagree with the list endpoint
    # about whether a fresh LEASE_UNCLAIMED condition is visible yet.
    # LEASE_STALE is never delayed; an already-resolved row is never hidden.
    attention_rows = conn.execute(
        "SELECT severity, COUNT(*) FROM attention_conditions WHERE resolved_at IS NULL "
        "AND (kind != 'LEASE_UNCLAIMED' OR "
        "first_detected_at <= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', '-10 seconds')) "
        "GROUP BY severity"
    ).fetchall()
    attention_by_severity = {"critical": 0, "warning": 0, "information": 0}
    for severity, count in attention_rows:
        attention_by_severity[severity] = count
    attention_current = sum(attention_by_severity.values())

    issues_by_state = dict(conn.execute(
        "SELECT iv.state, COUNT(*) FROM issue_views iv "
        "JOIN checkpoints c ON c.repository_id = iv.repository_id "
        "  AND c.identity_generation_id = iv.identity_generation_id "
        "GROUP BY iv.state"
    ).fetchall())
    runs_by_outcome = dict(conn.execute(
        "SELECT COALESCE(rv.outcome, 'NO_CONTROLLED_FINISH'), COUNT(*) FROM run_views rv "
        "JOIN checkpoints c ON c.repository_id = rv.repository_id "
        "  AND c.identity_generation_id = rv.identity_generation_id "
        "GROUP BY 1"
    ).fetchall())
    executions_by_state = dict(conn.execute(
        "SELECT ev.state, COUNT(*) FROM execution_views ev "
        "JOIN checkpoints c ON c.repository_id = ev.repository_id "
        "  AND c.identity_generation_id = ev.identity_generation_id "
        "GROUP BY ev.state"
    ).fetchall())
    evidence_by_integrity = dict(conn.execute(
        "SELECT e.integrity, COUNT(*) FROM evidence e "
        "JOIN checkpoints c ON c.repository_id = e.repository_id "
        "  AND c.identity_generation_id = e.identity_generation_id "
        "GROUP BY e.integrity"
    ).fetchall())

    return {
        "repositories": {"total": repo_total, "byAvailability": by_availability},
        "attention": {"current": attention_current, **attention_by_severity},
        "issues": {"total": sum(issues_by_state.values()), "byState": issues_by_state},
        "runs": {"total": sum(runs_by_outcome.values()), "byDisplayOutcome": runs_by_outcome},
        "executions": {"total": sum(executions_by_state.values()), "byState": executions_by_state},
        "evidence": {"total": sum(evidence_by_integrity.values()), "byIntegrity": evidence_by_integrity},
        "basis": "current identity generation per registered repository",
        "projectionState": projection_state_summary(conn),
        "proxyCost": proxy_cost_agg.global_proxy_cost(conn),
        "averageProxyCostPerCompletedIssue":
            proxy_cost_agg.average_proxy_cost_per_completed_issue(conn),
        "topCostIssues": proxy_cost_agg.top_cost_issues(conn),
    }


# --- cross-repository issues/runs/executions ---

_ISSUE_SORT_COLUMNS = {"issueId": "iv.issue_id", "state": "iv.state", "lastEventId": "iv.last_event_id"}
_RUN_SORT_COLUMNS = {"runId": "rv.run_id", "outcome": "rv.outcome",
                    "observedStartedAt": "rv.observed_started_at"}
_EXECUTION_SORT_COLUMNS = {"executionId": "ev.execution_id", "state": "ev.state",
                          "issueId": "ev.issue_id"}


def _current_generation_join(entity_table: str, alias: str) -> str:
    return (
        f"JOIN checkpoints c ON c.repository_id = {alias}.repository_id "
        f"AND c.identity_generation_id = {alias}.identity_generation_id "
        f"JOIN repositories r ON r.id = {alias}.repository_id"
    )


def cross_repository_issues(conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0,
                            repository_id: Optional[int] = None, state: Optional[str] = None,
                            sort: str = "issueId", direction: str = "asc") -> dict:
    check_offset_cap(offset, cap=NEW_ROUTE_OFFSET_CAP)
    readiness = check_read_model_readiness(conn, repository_id)  # raises if a scoped repo isn't ready
    if direction not in ("asc", "desc"):
        raise InvalidSortError(f"unsupported sort direction {direction!r}")
    cost_sort = sort == "cost"
    column = _ISSUE_SORT_COLUMNS.get(sort)
    if column is None and not cost_sort:
        raise InvalidSortError(f"unsupported issue sort {sort!r}")

    where = ["1=1"]
    params: list = []
    if repository_id is not None:
        where.append("iv.repository_id = ?")
        params.append(repository_id)
    if state is not None:
        where.append("iv.state = ?")
        params.append(state)

    gen_join = _current_generation_join("issue_views", "iv")
    # Cost sort needs the aggregated per-issue observed cost in ORDER BY; a
    # LEFT JOIN keeps issues with no metered executions (NULL cost -> sorted
    # last by cost_order_by). Non-cost sorts avoid the aggregate join entirely.
    cost_join = (
        " LEFT JOIN (SELECT ev.repository_id, ev.issue_id, "
        "  SUM(CASE WHEN ev.cost_valid = 1 THEN ev.proxy_micro_usd END) AS observed_micro "
        "  FROM execution_views ev JOIN checkpoints cc "
        "    ON cc.repository_id = ev.repository_id "
        "    AND cc.identity_generation_id = ev.identity_generation_id "
        "  GROUP BY ev.repository_id, ev.issue_id) pc "
        "  ON pc.repository_id = iv.repository_id AND pc.issue_id = iv.issue_id"
    ) if cost_sort else ""
    base = f"FROM issue_views iv {gen_join}{cost_join} WHERE {' AND '.join(where)}"
    if cost_sort:
        order_clause = proxy_cost_agg.cost_order_by("pc.observed_micro", "iv.issue_id", direction)
    else:
        order_clause = f"{column} {direction.upper()}, iv.issue_id"
    total = conn.execute(
        f"SELECT COUNT(*) FROM issue_views iv {gen_join} WHERE {' AND '.join(where)}",
        params,
    ).fetchone()[0]
    rows = conn.execute(
        f"SELECT iv.issue_id, iv.state, iv.title, iv.inconsistent, iv.last_event_id, "
        f"r.id, r.project_path {base} ORDER BY {order_clause} "
        "LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    cost_by_issue = proxy_cost_agg.by_group_proxy_cost(
        conn, "issue_id", [(r[5], r[0]) for r in rows])
    items = [
        {"issueId": issue_id, "state": state_, "title": title, "inconsistent": bool(inconsistent),
         "lastEventId": last_event_id,
         "repository": {"id": repo_id, "displayName": path.replace("\\", "/").rsplit("/", 1)[-1]},
         "proxyCost": cost_by_issue.get((repo_id, issue_id), proxy_cost_agg.unavailable_object())}
        for issue_id, state_, title, inconsistent, last_event_id, repo_id, path in rows
    ]
    result = _paginate(items, limit=limit, offset=offset, total=total)
    if readiness is not None:
        result.update(readiness)
    elif repository_id is None:
        result["projectionState"] = projection_state_summary(conn)
    return result


def cross_repository_runs(conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0,
                          repository_id: Optional[int] = None, outcome: Optional[str] = None,
                          sort: str = "runId", direction: str = "asc") -> dict:
    check_offset_cap(offset, cap=NEW_ROUTE_OFFSET_CAP)
    readiness = check_read_model_readiness(conn, repository_id)
    column = _RUN_SORT_COLUMNS.get(sort)
    if column is None:
        raise InvalidSortError(f"unsupported run sort {sort!r}")
    if direction not in ("asc", "desc"):
        raise InvalidSortError(f"unsupported sort direction {direction!r}")

    where = ["1=1"]
    params: list = []
    if repository_id is not None:
        where.append("rv.repository_id = ?")
        params.append(repository_id)
    if outcome is not None:
        where.append("COALESCE(rv.outcome, 'NO_CONTROLLED_FINISH') = ?")
        params.append(outcome)

    base = (
        "FROM run_views rv " + _current_generation_join("run_views", "rv") +
        f" WHERE {' AND '.join(where)}"
    )
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT rv.run_id, rv.engine_provider, rv.reviewer_provider, rv.outcome, "
        f"rv.inconsistent, rv.last_event_id, rv.observed_started_at, rv.observed_finished_at, "
        f"r.id, r.project_path {base} ORDER BY {column} {direction.upper()}, rv.run_id "
        "LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    cost_by_run = proxy_cost_agg.by_group_proxy_cost(
        conn, "run_id", [(r[8], r[0]) for r in rows])
    items = [
        {"runId": run_id, "engineProvider": engine, "reviewerProvider": reviewer, "outcome": outcome_,
         "displayOutcome": outcome_ or "no controlled finish observed", "inconsistent": bool(inconsistent),
         "lastEventId": last_event_id, "observedStartedAt": started_at, "observedFinishedAt": finished_at,
         "repository": {"id": repo_id, "displayName": path.replace("\\", "/").rsplit("/", 1)[-1]},
         "proxyCost": cost_by_run.get((repo_id, run_id), proxy_cost_agg.unavailable_object())}
        for (run_id, engine, reviewer, outcome_, inconsistent, last_event_id, started_at, finished_at,
             repo_id, path) in rows
    ]
    result = _paginate(items, limit=limit, offset=offset, total=total)
    if readiness is not None:
        result.update(readiness)
    elif repository_id is None:
        result["projectionState"] = projection_state_summary(conn)
    return result


def cross_repository_executions(conn: sqlite3.Connection, *, limit: int = 50, offset: int = 0,
                                repository_id: Optional[int] = None, state: Optional[str] = None,
                                group_by: str = "execution", sort: str = "executionId",
                                direction: str = "asc") -> dict:
    check_offset_cap(offset, cap=NEW_ROUTE_OFFSET_CAP)
    readiness = check_read_model_readiness(conn, repository_id)
    if group_by not in ("execution", "issue"):
        raise InvalidFilterError(f"unsupported groupBy {group_by!r}")

    where = ["1=1"]
    params: list = []
    if repository_id is not None:
        where.append("ev.repository_id = ?")
        params.append(repository_id)
    if state is not None:
        where.append("ev.state = ?")
        params.append(state)
    base = (
        "FROM execution_views ev " + _current_generation_join("execution_views", "ev") +
        f" WHERE {' AND '.join(where)}"
    )

    def _attach_readiness(result: dict) -> dict:
        if readiness is not None:
            result.update(readiness)
        elif repository_id is None:
            result["projectionState"] = projection_state_summary(conn)
        return result

    if group_by == "execution":
        if direction not in ("asc", "desc"):
            raise InvalidSortError(f"unsupported sort direction {direction!r}")
        cost_sort = sort == "cost"
        column = _EXECUTION_SORT_COLUMNS.get(sort)
        if column is None and not cost_sort:
            raise InvalidSortError(f"unsupported execution sort {sort!r}")
        # Cost is a column on the execution_views row (NULL when cost_valid=0),
        # so the NULL-last cost ordering needs no join.
        order_clause = (
            proxy_cost_agg.cost_order_by("ev.proxy_micro_usd", "ev.execution_id", direction)
            if cost_sort else f"{column} {direction.upper()}, ev.execution_id"
        )
        total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT ev.execution_id, ev.issue_id, ev.state, ev.inconsistent, ev.last_event_id, "
            f"ev.run_id, r.id, r.project_path, ev.proxy_micro_usd, ev.cost_valid, "
            f"ev.input_tokens, ev.output_tokens, ev.tokens_valid {base} "
            f"ORDER BY {order_clause} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        items = [
            {"executionId": xid, "issueId": issue_id, "state": state_, "inconsistent": bool(inconsistent),
             "lastEventId": last_event_id, "runId": run_id,
             "repository": {"id": repo_id, "displayName": path.replace("\\", "/").rsplit("/", 1)[-1]},
             "proxyCost": proxy_cost_agg.execution_proxy_cost(micro, cost_valid, in_tok, out_tok, tok_valid)}
            for (xid, issue_id, state_, inconsistent, last_event_id, run_id, repo_id, path,
                 micro, cost_valid, in_tok, out_tok, tok_valid) in rows
        ]
        return _attach_readiness(_paginate(items, limit=limit, offset=offset, total=total))

    # groupBy=issue: paginate ISSUE groups, not a client-page join.
    group_base = (
        "FROM (SELECT DISTINCT ev.repository_id, ev.identity_generation_id, ev.issue_id "
        "FROM execution_views ev " + _current_generation_join("execution_views", "ev") +
        f" WHERE {' AND '.join(where)} AND ev.issue_id IS NOT NULL) g "
        "JOIN issue_views iv ON iv.repository_id = g.repository_id "
        "  AND iv.identity_generation_id = g.identity_generation_id AND iv.issue_id = g.issue_id "
        "JOIN repositories r ON r.id = g.repository_id"
    )
    total = conn.execute(f"SELECT COUNT(*) {group_base}", params).fetchone()[0]
    group_rows = conn.execute(
        f"SELECT g.repository_id, g.identity_generation_id, g.issue_id, iv.state, iv.title, "
        f"r.project_path {group_base} ORDER BY g.issue_id LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    items = [
        {"issue": {"issueId": issue_id, "state": issue_state, "title": title},
         "repository": {"id": repo_id, "displayName": path.replace("\\", "/").rsplit("/", 1)[-1]},
         "totalExecutions": 0, "byState": {}, "newestExecutions": [], "executionsTruncated": False}
        for repo_id, _gen_id, issue_id, issue_state, title, path in group_rows
    ]
    if not group_rows:
        return _attach_readiness(_paginate(items, limit=limit, offset=offset, total=total))

    # Two fixed-cost queries covering every group on this page -- never one
    # pair of queries per group -- using a tuple-membership VALUES list
    # (still fully parameterized) to scope both the state counts and the
    # per-group "newest N" preview (via a window function) to exactly the
    # (repository, generation, issue) triples already selected above.
    group_keys = [(repo_id, gen_id, issue_id) for repo_id, gen_id, issue_id, *_ in group_rows]
    values_sql = ", ".join(["(?, ?, ?)"] * len(group_keys))
    values_params = [v for key in group_keys for v in key]

    by_state_map: dict = {}
    for repo_id, issue_id, state_, count in conn.execute(
        "SELECT repository_id, issue_id, state, COUNT(*) FROM execution_views "
        f"WHERE (repository_id, identity_generation_id, issue_id) IN (VALUES {values_sql}) "
        "GROUP BY repository_id, issue_id, state",
        values_params,
    ).fetchall():
        by_state_map.setdefault((repo_id, issue_id), {})[state_] = count

    newest_map: dict = {}
    for repo_id, issue_id, execution_id in conn.execute(
        "SELECT repository_id, issue_id, execution_id FROM (SELECT repository_id, issue_id, "
        "execution_id, ROW_NUMBER() OVER (PARTITION BY repository_id, issue_id "
        "ORDER BY last_event_id DESC) AS rn FROM execution_views "
        f"WHERE (repository_id, identity_generation_id, issue_id) IN (VALUES {values_sql})) "
        "WHERE rn <= ? ORDER BY repository_id, issue_id, rn",
        [*values_params, _EXECUTION_GROUP_PREVIEW_LIMIT],
    ).fetchall():
        newest_map.setdefault((repo_id, issue_id), []).append(execution_id)

    for item, (repo_id, _gen_id, issue_id, *_rest) in zip(items, group_rows):
        by_state = by_state_map.get((repo_id, issue_id), {})
        total_executions = sum(by_state.values())
        item["totalExecutions"] = total_executions
        item["byState"] = by_state
        item["newestExecutions"] = newest_map.get((repo_id, issue_id), [])
        item["executionsTruncated"] = total_executions > _EXECUTION_GROUP_PREVIEW_LIMIT

    return _attach_readiness(_paginate(items, limit=limit, offset=offset, total=total))


# --- evidence: cross-repository keyset pagination ---

def evidence_keyset(conn: sqlite3.Connection, *, limit: int = 50,
                    before_evidence_id: Optional[int] = None,
                    after_evidence_id: Optional[int] = None,
                    direction: str = "desc", repository_id: Optional[int] = None) -> dict:
    """Ordered by globally unique evidence.id; never a deep SQL OFFSET.
    `before_evidence_id`/`after_evidence_id` bound the id range exclusively;
    at most one should be supplied by a well-formed caller."""
    if direction not in ("asc", "desc"):
        raise InvalidSortError(f"unsupported direction {direction!r}")

    where = ["1=1"]
    params: list = []
    if repository_id is not None:
        where.append("e.repository_id = ?")
        params.append(repository_id)
    if before_evidence_id is not None:
        where.append("e.id < ?")
        params.append(before_evidence_id)
    if after_evidence_id is not None:
        where.append("e.id > ?")
        params.append(after_evidence_id)

    order = "DESC" if direction == "desc" else "ASC"
    base = (
        "FROM evidence e JOIN checkpoints c ON c.repository_id = e.repository_id "
        "AND c.identity_generation_id = e.identity_generation_id "
        "JOIN repositories r ON r.id = e.repository_id "
        f"WHERE {' AND '.join(where)}"
    )
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    # Fetch one extra row to determine hasMore without a second COUNT query.
    rows = conn.execute(
        f"SELECT e.id, e.record_cursor, e.integrity, e.event_id, e.event_type, "
        f"e.schema_version, e.issue_id, e.execution_id, e.run_id, e.event_ts, e.record_hash, "
        f"e.length_bytes, r.id, r.project_path {base} ORDER BY e.id {order} LIMIT ?",
        [*params, limit + 1],
    ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        {"evidenceId": eid, "cursor": cursor, "integrity": integrity, "eventId": event_id,
         "eventType": event_type, "schemaVersion": schema_version, "issueId": issue_id,
         "executionId": execution_id, "runId": run_id, "ts": ts, "recordHash": record_hash,
         "lengthBytes": length_bytes,
         "repository": {"id": repo_id, "displayName": path.replace("\\", "/").rsplit("/", 1)[-1]}}
        for (eid, cursor, integrity, event_id, event_type, schema_version, issue_id, execution_id,
             run_id, ts, record_hash, length_bytes, repo_id, path) in rows
    ]
    next_cursor = items[-1]["evidenceId"] if items and has_more else None
    previous_cursor = items[0]["evidenceId"] if items else None
    return {
        "items": items, "limit": limit, "next": next_cursor, "previous": previous_cursor,
        "hasMore": has_more, "total": total,
    }


# --- entity timeline (metadata-only) ---

_TIMELINE_ENTITY_COLUMNS = {"issues": "issue_id", "runs": "run_id", "executions": "execution_id"}


def entity_timeline(conn: sqlite3.Connection, repo_id: int, entity_type: str, entity_id: str, *,
                    limit: int = 50, offset: int = 0, direction: str = "asc") -> dict:
    """docs/27 SS7.3: evidenceId/cursor/integrity/eventId/eventType/
    schemaVersion/issueId/executionId/runId/ts/recordHash/lengthBytes only
    -- never payload_json or raw record bytes."""
    column = _TIMELINE_ENTITY_COLUMNS.get(entity_type)
    if column is None:
        raise InvalidFilterError(f"unsupported entityType {entity_type!r}")
    check_offset_cap(offset, cap=NEW_ROUTE_OFFSET_CAP)
    if direction not in ("asc", "desc"):
        raise InvalidSortError(f"unsupported direction {direction!r}")

    base = (
        f"FROM evidence e JOIN checkpoints c ON c.repository_id = e.repository_id "
        f"AND c.identity_generation_id = e.identity_generation_id "
        f"WHERE e.repository_id = ? AND e.{column} = ?"
    )
    params = [repo_id, entity_id]
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    # Chronological (docs/27 SS6.6) means logical event order, not raw
    # evidence-arrival order -- these usually coincide but can diverge
    # transiently during backfill/tail-repair. event_id is always present
    # on the OK rows this WHERE clause matches (issue_id/execution_id/
    # run_id are only populated for integrity='OK'); e.id tie-breaks.
    order = direction.upper()
    rows = conn.execute(
        f"SELECT e.id, e.record_cursor, e.integrity, e.event_id, e.event_type, e.schema_version, "
        f"e.issue_id, e.execution_id, e.run_id, e.event_ts, e.record_hash, e.length_bytes "
        f"{base} ORDER BY e.event_id {order}, e.id {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    items = [
        {"evidenceId": eid, "cursor": cursor, "integrity": integrity, "eventId": event_id,
         "eventType": event_type, "schemaVersion": schema_version, "issueId": issue_id,
         "executionId": execution_id, "runId": run_id, "ts": ts, "recordHash": record_hash,
         "lengthBytes": length_bytes}
        for (eid, cursor, integrity, event_id, event_type, schema_version, issue_id, execution_id,
             run_id, ts, record_hash, length_bytes) in rows
    ]
    return _paginate(items, limit=limit, offset=offset, total=total)


# --- topology (bounded, scoped) ---

DEFAULT_TOPOLOGY_MAX_NODES = 100
DEFAULT_TOPOLOGY_MAX_EDGES = 200
_TOPOLOGY_ENTITY_COLUMNS = _TIMELINE_ENTITY_COLUMNS


def entity_topology(conn: sqlite3.Connection, repo_id: int, entity_type: str, entity_id: str, *,
                    max_nodes: int = DEFAULT_TOPOLOGY_MAX_NODES,
                    max_edges: int = DEFAULT_TOPOLOGY_MAX_EDGES) -> dict:
    """Scoped issue/run topology (docs/27 SS7.3): observed run -> execution
    -> issue/evidence relationships from stored identifiers only, capped
    at max_nodes/max_edges. Never a whole-portfolio graph."""
    column = _TOPOLOGY_ENTITY_COLUMNS.get(entity_type)
    if column is None:
        raise InvalidFilterError(f"unsupported entityType {entity_type!r}")
    check_read_model_readiness(conn, repo_id)  # this function always reads execution_views

    gen_row = conn.execute(
        "SELECT identity_generation_id FROM checkpoints WHERE repository_id = ?", (repo_id,)
    ).fetchone()
    if gen_row is None:
        return {"nodes": [], "edges": [], "truncated": False,
               "limits": {"maxNodes": max_nodes, "maxEdges": max_edges},
               "basis": "current identity generation"}
    gen_id = gen_row[0]

    nodes: list = []
    edges: list = []
    truncated = False

    def _add_node(kind: str, node_id: str) -> bool:
        nonlocal truncated
        if any(n["kind"] == kind and n["id"] == node_id for n in nodes):
            return True
        if len(nodes) >= max_nodes:
            truncated = True
            return False
        nodes.append({"kind": kind, "id": node_id})
        return True

    def _add_edge(edge_type: str, source: tuple, target: tuple) -> None:
        nonlocal truncated
        if len(edges) >= max_edges:
            truncated = True
            return
        edges.append({"type": edge_type, "source": {"kind": source[0], "id": source[1]},
                      "target": {"kind": target[0], "id": target[1]}})

    if entity_type == "issues":
        issue_id = entity_id
        _add_node("issue", issue_id)
        exec_rows = conn.execute(
            "SELECT execution_id, run_id FROM execution_views WHERE repository_id = ? "
            "AND identity_generation_id = ? AND issue_id = ? ORDER BY execution_id",
            (repo_id, gen_id, issue_id),
        ).fetchall()
        for execution_id, run_id in exec_rows:
            if not _add_node("execution", execution_id):
                continue
            _add_edge("issue_has_execution", ("issue", issue_id), ("execution", execution_id))
            if run_id is not None and _add_node("run", run_id):
                _add_edge("run_has_execution", ("run", run_id), ("execution", execution_id))
            ev_rows = conn.execute(
                "SELECT id FROM evidence WHERE repository_id = ? AND identity_generation_id = ? "
                "AND execution_id = ? ORDER BY id", (repo_id, gen_id, execution_id),
            ).fetchall()
            for (evidence_id,) in ev_rows:
                if _add_node("evidence", str(evidence_id)):
                    _add_edge("entity_has_evidence", ("execution", execution_id),
                             ("evidence", str(evidence_id)))
    elif entity_type == "runs":
        run_id = entity_id
        _add_node("run", run_id)
        exec_rows = conn.execute(
            "SELECT execution_id, issue_id FROM execution_views WHERE repository_id = ? "
            "AND identity_generation_id = ? AND run_id = ? ORDER BY execution_id",
            (repo_id, gen_id, run_id),
        ).fetchall()
        for execution_id, issue_id in exec_rows:
            if not _add_node("execution", execution_id):
                continue
            _add_edge("run_has_execution", ("run", run_id), ("execution", execution_id))
            if issue_id is not None and _add_node("issue", issue_id):
                _add_edge("issue_has_execution", ("issue", issue_id), ("execution", execution_id))
    else:  # executions
        execution_id = entity_id
        _add_node("execution", execution_id)
        ev_rows = conn.execute(
            "SELECT id FROM evidence WHERE repository_id = ? AND identity_generation_id = ? "
            "AND execution_id = ? ORDER BY id", (repo_id, gen_id, execution_id),
        ).fetchall()
        for (evidence_id,) in ev_rows:
            if _add_node("evidence", str(evidence_id)):
                _add_edge("entity_has_evidence", ("execution", execution_id),
                         ("evidence", str(evidence_id)))

    return {
        "nodes": nodes, "edges": edges, "truncated": truncated,
        "limits": {"maxNodes": max_nodes, "maxEdges": max_edges},
        "basis": "current identity generation",
    }
