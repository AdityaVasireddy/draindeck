"""Unit 3: proxy-cost SQL aggregation over execution_views (spec §2.4).

Per-scope sums include every attempt; only current-generation, only valid cost;
missing cost adds nothing; average is over DONE issues; a stale generation never
leaks into a total.
"""
from __future__ import annotations

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard import proxy_cost_agg as agg


def _setup(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    conn.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, 'C:/repo', NULL, NULL, '2026-08-26T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, availability, updated_at) "
        "VALUES (1, 10, 'AVAILABLE', '2026-08-26T00:00:00Z')"
    )
    return conn


def _exec(conn, execution_id, *, gen=10, repo=1, issue_id=None, run_id=None, state="DONE",
          micro=None, cost_valid=0, in_tok=None, out_tok=None, tokens_valid=0):
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, inconsistent, last_event_id, run_id, proxy_micro_usd, cost_valid, "
        "input_tokens, output_tokens, tokens_valid, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?, ?, ?, ?, '2026-08-26T00:00:00Z')",
        (repo, gen, execution_id, issue_id, state, run_id, micro, cost_valid, in_tok, out_tok,
         tokens_valid),
    )


def _issue(conn, issue_id, *, gen=10, repo=1, state="DONE"):
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
        "title, inconsistent, last_event_id, updated_at) "
        "VALUES (?, ?, ?, ?, 't', 0, 1, '2026-08-26T00:00:00Z')",
        (repo, gen, issue_id, state),
    )


def test_issue_sums_all_attempts_including_missing(tmp_path):
    conn = _setup(tmp_path)
    # 3 attempts of issue 42: two metered, one missing cost.
    _exec(conn, "42-e1", issue_id="42", micro=1_000_000, cost_valid=1,
          in_tok=100, out_tok=50, tokens_valid=1)
    _exec(conn, "42-e2", issue_id="42", micro=840_000, cost_valid=1)
    _exec(conn, "42-e3", issue_id="42", micro=None, cost_valid=0)
    obj = agg.issue_proxy_cost(conn, 1, "42")
    assert obj["observedMicroUsd"] == 1_840_000
    assert obj["totalExecutions"] == 3
    assert obj["meteredExecutions"] == 2
    assert obj["missingCostExecutions"] == 1
    assert obj["completeness"] == "PARTIAL"
    assert obj["tokenMeteredExecutions"] == 1
    assert obj["inputTokensObserved"] == 100


def test_run_scope(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e1", run_id="run-1", micro=500_000, cost_valid=1)
    _exec(conn, "e2", run_id="run-1", micro=500_000, cost_valid=1)
    _exec(conn, "e3", run_id="run-2", micro=999_000, cost_valid=1)
    obj = agg.run_proxy_cost(conn, 1, "run-1")
    assert obj["observedMicroUsd"] == 1_000_000
    assert obj["completeness"] == "COMPLETE"
    assert obj["totalExecutions"] == 2


def test_repository_and_global(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e1", issue_id="1", micro=1_000_000, cost_valid=1)
    _exec(conn, "e2", issue_id="2", micro=2_000_000, cost_valid=1)
    assert agg.repository_proxy_cost(conn, 1)["observedMicroUsd"] == 3_000_000
    assert agg.global_proxy_cost(conn)["observedMicroUsd"] == 3_000_000


def test_unavailable_scope(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e1", issue_id="1", micro=None, cost_valid=0)
    obj = agg.issue_proxy_cost(conn, 1, "1")
    assert obj["completeness"] == "UNAVAILABLE"
    assert obj["observedMicroUsd"] is None
    assert obj["totalExecutions"] == 1


def test_stale_generation_not_counted(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "cur", issue_id="1", gen=10, micro=1_000_000, cost_valid=1)
    _exec(conn, "old", issue_id="1", gen=9, micro=9_000_000, cost_valid=1)  # stale
    assert agg.repository_proxy_cost(conn, 1)["observedMicroUsd"] == 1_000_000


def test_metered_zero_is_complete(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e1", issue_id="1", micro=0, cost_valid=1)
    obj = agg.issue_proxy_cost(conn, 1, "1")
    assert obj["completeness"] == "COMPLETE"
    assert obj["observedMicroUsd"] == 0


def test_by_group_batched(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "a1", issue_id="A", micro=1_000_000, cost_valid=1)
    _exec(conn, "a2", issue_id="A", micro=1_000_000, cost_valid=1)
    _exec(conn, "b1", issue_id="B", micro=None, cost_valid=0)
    groups = agg.by_group_proxy_cost(conn, "issue_id", [(1, "A"), (1, "B"), (1, "C")])
    assert groups[(1, "A")]["observedMicroUsd"] == 2_000_000
    assert groups[(1, "A")]["completeness"] == "COMPLETE"
    assert groups[(1, "B")]["completeness"] == "UNAVAILABLE"
    assert (1, "C") not in groups  # no executions -> caller uses unavailable default


def test_average_per_completed_issue(tmp_path):
    conn = _setup(tmp_path)
    _issue(conn, "done1", state="DONE")
    _issue(conn, "done2", state="DONE")
    _issue(conn, "open1", state="ACTIVE")
    _exec(conn, "d1", issue_id="done1", micro=2_000_000, cost_valid=1)
    _exec(conn, "d2", issue_id="done2", micro=2_000_000, cost_valid=1)
    _exec(conn, "o1", issue_id="open1", micro=9_000_000, cost_valid=1)  # excluded (not DONE)
    obj = agg.average_proxy_cost_per_completed_issue(conn, 1)
    assert obj["completedIssues"] == 2
    assert obj["observedMicroUsd"] == 2_000_000  # (2+2)/2
    assert obj["observed"] is False
    assert obj["totalExecutions"] == 2


def test_average_null_when_no_done_issues(tmp_path):
    conn = _setup(tmp_path)
    _issue(conn, "open1", state="ACTIVE")
    _exec(conn, "o1", issue_id="open1", micro=5_000_000, cost_valid=1)
    obj = agg.average_proxy_cost_per_completed_issue(conn, 1)
    assert obj["completedIssues"] == 0
    assert obj["observedMicroUsd"] is None


def test_average_partial_label(tmp_path):
    conn = _setup(tmp_path)
    _issue(conn, "done1", state="DONE")
    _issue(conn, "done2", state="DONE")
    _exec(conn, "d1", issue_id="done1", micro=2_000_000, cost_valid=1)
    _exec(conn, "d2", issue_id="done2", micro=None, cost_valid=0)  # missing
    obj = agg.average_proxy_cost_per_completed_issue(conn, 1)
    assert obj["observed"] is True  # partial -> Observed average
    assert obj["observedMicroUsd"] == 1_000_000  # 2_000_000 / 2 issues


def test_cost_order_by_unavailable_last_both_directions(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e_hi", issue_id="1", micro=3_000_000, cost_valid=1)
    _exec(conn, "e_lo", issue_id="1", micro=1_000_000, cost_valid=1)
    _exec(conn, "e_na", issue_id="1", micro=None, cost_valid=0)

    for direction, first_metered in (("asc", "e_lo"), ("desc", "e_hi")):
        order = agg.cost_order_by("ev.proxy_micro_usd", "ev.execution_id", direction)
        rows = [r[0] for r in conn.execute(
            f"SELECT ev.execution_id FROM execution_views ev "
            f"JOIN checkpoints c ON c.repository_id = ev.repository_id "
            f"AND c.identity_generation_id = ev.identity_generation_id ORDER BY {order}"
        ).fetchall()]
        assert rows[0] == first_metered
        assert rows[-1] == "e_na"  # UNAVAILABLE always last


def test_cost_order_by_stable_id_tie_break(tmp_path):
    conn = _setup(tmp_path)
    _exec(conn, "e_b", issue_id="1", micro=1_000_000, cost_valid=1)
    _exec(conn, "e_a", issue_id="1", micro=1_000_000, cost_valid=1)
    order = agg.cost_order_by("ev.proxy_micro_usd", "ev.execution_id", "desc")
    rows = [r[0] for r in conn.execute(
        f"SELECT ev.execution_id FROM execution_views ev "
        f"JOIN checkpoints c ON c.repository_id = ev.repository_id "
        f"AND c.identity_generation_id = ev.identity_generation_id ORDER BY {order}"
    ).fetchall()]
    assert rows == ["e_a", "e_b"]  # equal cost -> ascending id tie-break


def test_cost_order_by_rejects_bad_direction(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        agg.cost_order_by("ev.proxy_micro_usd", "ev.execution_id", "sideways")
