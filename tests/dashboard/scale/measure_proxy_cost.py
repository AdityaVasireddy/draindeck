"""Unit 6 scale/index-deferral measurement (spec §4.1, plan §5).

Builds the standard 20-repo / 1,000-issue / 10,000-execution / 100,000-evidence
scale fixture, populates ~half the execution_views rows with valid proxy cost,
and times the cost aggregate queries that back the new endpoints -- the ones
that could plausibly need a dedicated index:

  * global_proxy_cost              (portfolio total, Home)
  * average_proxy_cost_per_completed_issue (Home / repo overview)
  * top_cost_issues                (Home top-cost chart)
  * cross_repository_issues sort=cost (the LEFT JOIN per-issue aggregate + sort)
  * by_group_proxy_cost for one 100-row page (issues/runs list attach)

Exits non-zero if any query exceeds BUDGET_S, which is deliberately a small
fraction of a normal request budget. If every query is within budget on the
existing indexes (execution_views(repository_id, identity_generation_id,
issue_id) / (..., run_id) from Unit 1's v1->v2 DDL), the spec's index deferral
stands; otherwise a dedicated index must be added in the v2->v3 migration.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from draindeck_dashboard import api_queries, proxy_cost_agg  # noqa: E402
from draindeck_dashboard.db import connect_and_init  # noqa: E402

from seed_fixture import build_fixture  # noqa: E402

BUDGET_S = 0.5


def _populate_costs(conn) -> None:
    # Give ~half the executions a valid metered cost, the rest unknown -- a
    # realistic PARTIAL mix that exercises both the SUM and the NULL-handling.
    conn.execute(
        "UPDATE execution_views SET proxy_micro_usd = (ABS(last_event_id) % 5000000), "
        "cost_valid = 1, input_tokens = 1000, output_tokens = 500, tokens_valid = 1 "
        "WHERE (last_event_id % 2) = 0"
    )


def _timed(label: str, fn) -> float:
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    print(f"  {label:<42} {elapsed * 1000:8.1f} ms")
    return elapsed


def main() -> None:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("proxy_cost_scale.sqlite3")
    conn = connect_and_init(db_path)
    stats = build_fixture(conn)
    _populate_costs(conn)
    print(f"Fixture: {stats}")
    print("Proxy-cost aggregate timings (budget "
          f"{BUDGET_S * 1000:.0f} ms each):")

    timings = {
        "global_proxy_cost": _timed(
            "global_proxy_cost", lambda: proxy_cost_agg.global_proxy_cost(conn)),
        "average_per_completed_issue": _timed(
            "average_per_completed_issue",
            lambda: proxy_cost_agg.average_proxy_cost_per_completed_issue(conn)),
        "top_cost_issues": _timed(
            "top_cost_issues", lambda: proxy_cost_agg.top_cost_issues(conn, limit=10)),
        "issues_sort_cost_page": _timed(
            "cross_repository_issues sort=cost (page)",
            lambda: api_queries.cross_repository_issues(
                conn, limit=100, offset=0, sort="cost", direction="desc")),
        "by_group_issue_page": _timed(
            "by_group_proxy_cost (100-issue page)",
            lambda: proxy_cost_agg.by_group_proxy_cost(
                conn, "issue_id",
                [row for row in conn.execute(
                    "SELECT repository_id, issue_id FROM issue_views LIMIT 100").fetchall()])),
    }

    over = {k: v for k, v in timings.items() if v > BUDGET_S}
    if over:
        print("\nOVER BUDGET:")
        for k, v in over.items():
            print(f"  {k}: {v * 1000:.1f} ms > {BUDGET_S * 1000:.0f} ms")
        print("=> add a dedicated cost index in the v2->v3 migration and re-measure.")
        sys.exit(1)
    print("\nAll cost aggregates within budget on existing indexes; "
          "index deferral stands (spec §4.1).")


if __name__ == "__main__":
    main()
