"""Bounded proxy-cost aggregation over ``execution_views`` (spec §2.4/§3).

Every aggregate joins ``checkpoints.identity_generation_id`` so only
current-generation executions are ever summed -- a post-rollover repository
never leaks a stale generation's cost. List endpoints use ``by_group_proxy_cost``
(one fixed query per page, tuple-membership scoped to the page's ids), never one
query per row. Cost/token validity is honoured exactly as captured: an execution
with ``cost_valid = 0`` contributes to ``totalExecutions`` but adds nothing to
the sum (missing cost is unknown, never zero).
"""
from __future__ import annotations

import sqlite3
from typing import Iterable, Optional

from .proxy_cost import build_average_object, build_proxy_cost_object

# The six aggregate expressions, given the execution_views alias. Conditional
# sums realise "only OK, only valid cost/tokens counts", and COALESCE keeps the
# execution/token metered COUNTs integer-typed even over an empty group.
def _agg_exprs(ev: str = "ev") -> str:
    return (
        f"COUNT(*), "
        f"COALESCE(SUM({ev}.cost_valid), 0), "
        f"SUM(CASE WHEN {ev}.cost_valid = 1 THEN {ev}.proxy_micro_usd END), "
        f"COALESCE(SUM({ev}.tokens_valid), 0), "
        f"SUM(CASE WHEN {ev}.tokens_valid = 1 THEN {ev}.input_tokens END), "
        f"SUM(CASE WHEN {ev}.tokens_valid = 1 THEN {ev}.output_tokens END)"
    )


def _object_from_agg(row) -> dict:
    total, metered, observed_micro, token_metered, input_tokens, output_tokens = row
    return build_proxy_cost_object(
        total=total, metered=metered, observed_micro=observed_micro,
        token_metered=token_metered, input_tokens=input_tokens, output_tokens=output_tokens,
    )


def _gen_join(ev: str = "ev") -> str:
    return (
        f"JOIN checkpoints c ON c.repository_id = {ev}.repository_id "
        f"AND c.identity_generation_id = {ev}.identity_generation_id"
    )


def cost_order_by(micro_col: str, id_col: str, direction: str) -> str:
    """An ORDER BY fragment sorting by proxy cost with UNAVAILABLE (NULL cost)
    ALWAYS last -- in both directions -- and a stable id tie-break (spec §3.4).

    ``micro_col`` is the per-row/aggregated micro-USD column (NULL means
    unavailable: an execution with cost_valid=0 stores NULL, and an aggregated
    issue/run with no metered executions yields NULL). ``<col> IS NULL`` sorts
    ASC regardless of ``direction`` so unavailable rows never rise to the top of
    a descending sort. Both column names are fixed internal literals, never
    caller input; ``direction`` is validated against a two-value allowlist.
    """
    if direction not in ("asc", "desc"):
        raise ValueError(f"unsupported direction {direction!r}")
    return (
        f"{micro_col} IS NULL ASC, {micro_col} {direction.upper()}, {id_col} ASC"
    )


def execution_proxy_cost(proxy_micro_usd: Optional[int], cost_valid, input_tokens: Optional[int],
                         output_tokens: Optional[int], tokens_valid) -> dict:
    """The single-execution ``proxyCost`` object, built directly from that
    execution_views row's own columns -- no query needed (spec §2.4)."""
    cost_valid = bool(cost_valid)
    tokens_valid = bool(tokens_valid)
    return build_proxy_cost_object(
        total=1,
        metered=1 if cost_valid else 0,
        observed_micro=proxy_micro_usd if cost_valid else None,
        token_metered=1 if tokens_valid else 0,
        input_tokens=input_tokens if tokens_valid else None,
        output_tokens=output_tokens if tokens_valid else None,
    )


def _scope_cost(conn: sqlite3.Connection, extra_where: str, params: list) -> dict:
    sql = (
        f"SELECT {_agg_exprs()} FROM execution_views ev {_gen_join()} "
        f"WHERE 1=1 {extra_where}"
    )
    row = conn.execute(sql, params).fetchone()
    return _object_from_agg(row)


def global_proxy_cost(conn: sqlite3.Connection) -> dict:
    """Portfolio-wide proxy cost over every repository's current generation."""
    return _scope_cost(conn, "", [])


def repository_proxy_cost(conn: sqlite3.Connection, repo_id: int) -> dict:
    return _scope_cost(conn, "AND ev.repository_id = ?", [repo_id])


def issue_proxy_cost(conn: sqlite3.Connection, repo_id: int, issue_id: str) -> dict:
    """Sum over EVERY execution attempt of the issue -- retries, rejections,
    and validation failures included (spec §2.4)."""
    return _scope_cost(conn, "AND ev.repository_id = ? AND ev.issue_id = ?", [repo_id, issue_id])


def run_proxy_cost(conn: sqlite3.Connection, repo_id: int, run_id: str) -> dict:
    return _scope_cost(conn, "AND ev.repository_id = ? AND ev.run_id = ?", [repo_id, run_id])


def by_group_proxy_cost(conn: sqlite3.Connection, group_col: str,
                        keys: Iterable[tuple]) -> dict:
    """One fixed query for a whole list page: proxy cost per (repository_id,
    ``group_col`` value) group, scoped to the current generation and to exactly
    the (repository_id, value) pairs on the page. ``group_col`` is a fixed
    internal literal (``issue_id`` or ``run_id``), never caller input.

    Returns ``{(repository_id, group_value): proxyCost}``. Groups with no
    executions are simply absent -- the caller supplies an UNAVAILABLE default
    for a page row with no matching executions.
    """
    if group_col not in ("issue_id", "run_id"):
        raise ValueError(f"unsupported group_col {group_col!r}")
    key_list = [(repo_id, value) for repo_id, value in keys]
    if not key_list:
        return {}
    values_sql = ", ".join(["(?, ?)"] * len(key_list))
    params = [v for key in key_list for v in key]
    sql = (
        f"SELECT ev.repository_id, ev.{group_col}, {_agg_exprs()} "
        f"FROM execution_views ev {_gen_join()} "
        f"WHERE (ev.repository_id, ev.{group_col}) IN (VALUES {values_sql}) "
        f"GROUP BY ev.repository_id, ev.{group_col}"
    )
    out: dict = {}
    for row in conn.execute(sql, params).fetchall():
        repo_id, group_value = row[0], row[1]
        out[(repo_id, group_value)] = _object_from_agg(row[2:])
    return out


def unavailable_object() -> dict:
    """The proxyCost object for a scope with zero included executions."""
    return build_proxy_cost_object(total=0, metered=0, observed_micro=None,
                                   token_metered=0, input_tokens=None, output_tokens=None)


def average_proxy_cost_per_completed_issue(conn: sqlite3.Connection,
                                           repo_id: Optional[int] = None) -> dict:
    """Average proxy cost per DONE issue (spec §2.6). Denominator: issues in
    exact state DONE (current generation, optionally one repository). Numerator:
    summed proxy cost of those issues' executions (every attempt). Returns a null
    amount when there are no DONE issues, and discloses both issue coverage
    (completedIssues) and usage coverage (costMeteredExecutions/totalExecutions).
    """
    repo_where = "AND iv.repository_id = ?" if repo_id is not None else ""
    repo_params = [repo_id] if repo_id is not None else []

    completed_issues = conn.execute(
        f"SELECT COUNT(*) FROM issue_views iv {_gen_join('iv')} "
        f"WHERE iv.state = 'DONE' {repo_where}",
        repo_params,
    ).fetchone()[0]

    ev_repo_where = "AND ev.repository_id = ?" if repo_id is not None else ""
    total_executions, cost_metered, observed_micro = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(ev.cost_valid), 0), "
        f"SUM(CASE WHEN ev.cost_valid = 1 THEN ev.proxy_micro_usd END) "
        f"FROM execution_views ev {_gen_join()} "
        f"JOIN issue_views iv ON iv.repository_id = ev.repository_id "
        f"  AND iv.identity_generation_id = ev.identity_generation_id "
        f"  AND iv.issue_id = ev.issue_id "
        f"WHERE iv.state = 'DONE' {ev_repo_where}",
        repo_params,
    ).fetchone()

    return build_average_object(
        completed_issues=completed_issues, total_executions=total_executions,
        cost_metered_executions=cost_metered, observed_micro=observed_micro,
    )
