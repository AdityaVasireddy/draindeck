"""Unit 4 (docs/27 SS7): bounded, parameterized, current-generation-joined
cross-repository query layer over the persisted read models -- no
per-request full projection replay.
"""
from __future__ import annotations

import pytest

from draindeck_dashboard import api_queries
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import (
    IndexPreparingError,
    InvalidFilterError,
    InvalidSortError,
    PageOutOfRangeError,
)


def _repo(conn, name="repo", availability="AVAILABLE", gen_number=1):
    cur = conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES (?, ?, ?, '2026-08-23T00:00:00Z')",
        (f"C:/{name}", f"C:/{name}/events.jsonl", f"c:/{name}/events.jsonl"),
    )
    repo_id = cur.lastrowid
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, ?, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')",
        (repo_id, gen_number),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, ?, '2026-08-23T00:00:00Z')",
        (repo_id, gen_id, availability),
    )
    return repo_id, gen_id


def _setup(tmp_path):
    return connect_and_init(tmp_path / "dash.sqlite3")


# --- bounded_offset primitive ---

def test_bounded_offset_rejects_beyond_cap():
    with pytest.raises(PageOutOfRangeError):
        api_queries.check_offset_cap(10_001, cap=10_000)


def test_bounded_offset_accepts_at_cap():
    api_queries.check_offset_cap(10_000, cap=10_000)  # must not raise


# --- repository_summaries ---

def test_repository_summaries_lists_all_repositories(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "a")
    _repo(conn, "b")
    result = api_queries.repository_summaries(conn, limit=50, offset=0)
    assert result["total"] == 2
    assert {item["displayName"] for item in result["items"]} == {"a", "b"}


def test_repository_summaries_display_name_is_final_path_segment(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "myrepo")
    result = api_queries.repository_summaries(conn, limit=50, offset=0)
    assert result["items"][0]["displayName"] == "myrepo"


def test_repository_summaries_filters_by_availability(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "a", availability="AVAILABLE")
    _repo(conn, "b", availability="OFFLINE")
    result = api_queries.repository_summaries(conn, limit=50, offset=0, availability="OFFLINE")
    assert [i["displayName"] for i in result["items"]] == ["b"]


def test_repository_summaries_filters_by_search_query(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "alpha")
    _repo(conn, "beta")
    result = api_queries.repository_summaries(conn, limit=50, offset=0, q="alp")
    assert [i["displayName"] for i in result["items"]] == ["alpha"]


def test_repository_summaries_filters_by_has_attention(tmp_path):
    conn = _setup(tmp_path)
    repo_a, _ = _repo(conn, "a")
    _repo(conn, "b")
    conn.execute(
        "INSERT INTO attention_conditions (condition_key, occurrence, repository_id, kind, "
        "severity, message, first_detected_at, last_detected_at) VALUES ('k', 1, ?, "
        "'REPOSITORY_OFFLINE', 'warning', 'm', '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z')",
        (repo_a,),
    )
    result = api_queries.repository_summaries(conn, limit=50, offset=0, has_attention=True)
    assert [i["displayName"] for i in result["items"]] == ["a"]
    assert result["items"][0]["attentionCount"] == 1


def test_repository_summaries_rejects_unknown_sort(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(InvalidSortError):
        api_queries.repository_summaries(conn, limit=50, offset=0, sort="nonsense")


def test_repository_summaries_sort_by_created_at_direction(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "first")
    _repo(conn, "second")
    conn.execute("UPDATE repositories SET created_at = '2020-01-01T00:00:00Z' WHERE project_path = 'C:/second'")
    result = api_queries.repository_summaries(conn, limit=50, offset=0, sort="createdAt", direction="asc")
    assert [i["displayName"] for i in result["items"]] == ["second", "first"]


def test_repository_summaries_offset_beyond_cap_rejected(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(PageOutOfRangeError):
        api_queries.repository_summaries(conn, limit=50, offset=10_001)


def test_repository_summaries_latest_run_tie_does_not_duplicate_repository(tmp_path):
    """Unit 15 (docs/27 SS14 scale testing surfaced this): two runs for the
    same repository finishing at the exact same second-resolution
    timestamp is realistic under concurrent/batch execution, not just a
    fixture artifact -- the "latest run" join must pick exactly one row
    per repository even when `updated_at` ties, never fan out and
    multiply the repository in the result set or its total count."""
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    for i in range(5):
        conn.execute(
            "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, "
            "inconsistent, observed_started_at, observed_finished_at, updated_at) "
            "VALUES (?, ?, ?, 'COMPLETED', 0, '2026-08-23T00:00:00Z', '2026-08-23T01:00:00Z', "
            "'2026-08-23T01:00:00Z')",
            (repo_id, gen_id, f"r{i}"),
        )
    result = api_queries.repository_summaries(conn, limit=50, offset=0)
    assert result["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["latestRun"]["outcome"] == "COMPLETED"


# --- overview ---

def test_overview_aggregates_across_repositories(tmp_path):
    conn = _setup(tmp_path)
    repo_a, gen_a = _repo(conn, "a", availability="AVAILABLE")
    repo_b, gen_b = _repo(conn, "b", availability="OFFLINE")
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_a, gen_a),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i2', 'PENDING', '2026-08-23T00:00:00Z')", (repo_b, gen_b),
    )
    result = api_queries.overview(conn)
    assert result["repositories"]["total"] == 2
    assert result["repositories"]["byAvailability"]["AVAILABLE"] == 1
    assert result["repositories"]["byAvailability"]["OFFLINE"] == 1
    assert result["issues"]["byState"]["DONE"] == 1
    assert result["issues"]["byState"]["PENDING"] == 1
    assert result["issues"]["total"] == 2
    assert "basis" in result
    assert "projectionState" in result


def test_overview_with_no_repositories_is_all_zero(tmp_path):
    conn = _setup(tmp_path)
    result = api_queries.overview(conn)
    assert result["repositories"]["total"] == 0
    assert result["issues"]["total"] == 0


# --- cross-repository current-generation scoping ---

def test_cross_repository_issues_only_returns_current_generation_rows(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen1 = _repo(conn, "a")
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'stale', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen1),
    )
    gen2 = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 2, 'lineage-2', 2, 2, 1, '2026-08-23T00:00:01Z')", (repo_id,),
    ).lastrowid
    conn.execute(
        "UPDATE checkpoints SET identity_generation_id = ? WHERE repository_id = ?", (gen2, repo_id),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'current', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen2),
    )
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0)
    assert [i["issueId"] for i in result["items"]] == ["current"]


# --- read-model readiness (docs/27 SS3.2 decision 9: INDEX_PREPARING/REBUILDING) ---

def _mark_ready(conn, repo_id, gen_id, *, completed_evidence_id=0):
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'READY', ?, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id, gen_id, completed_evidence_id),
    )


def test_repository_scoped_issues_query_raises_index_preparing_with_no_snapshot_at_all(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")  # no read_model_state row inserted
    with pytest.raises(IndexPreparingError):
        api_queries.cross_repository_issues(conn, limit=50, offset=0, repository_id=repo_id)


def test_repository_scoped_runs_query_raises_index_preparing_while_status_is_preparing(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'PREPARING', NULL, '2026-08-23T00:00:00Z', NULL, NULL)",
        (repo_id, gen_id),
    )
    with pytest.raises(IndexPreparingError):
        api_queries.cross_repository_runs(conn, limit=50, offset=0, repository_id=repo_id)


def test_repository_scoped_executions_query_raises_index_preparing_on_failed_status(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'FAILED', NULL, '2026-08-23T00:00:00Z', NULL, 'RuntimeError')",
        (repo_id, gen_id),
    )
    with pytest.raises(IndexPreparingError):
        api_queries.cross_repository_executions(conn, limit=50, offset=0, repository_id=repo_id)


def test_repository_scoped_query_labels_rebuilding_status_stale_and_still_serves_data(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _mark_ready(conn, repo_id, gen_id, completed_evidence_id=5)
    conn.execute("UPDATE read_model_state SET status = 'REBUILDING' WHERE repository_id = ?", (repo_id,))
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0, repository_id=repo_id)
    assert result["stale"] is True
    assert [i["issueId"] for i in result["items"]] == ["i1"]  # data still served, not blocked


def test_repository_scoped_query_ready_status_never_carries_a_stale_flag(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _mark_ready(conn, repo_id, gen_id)
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0, repository_id=repo_id)
    assert "stale" not in result


def test_cross_repository_query_never_raises_for_a_preparing_repository_but_discloses_it(tmp_path):
    """A cross-repository (unscoped) request must never block over ONE
    repository's readiness -- it just discloses which repositories aren't
    part of a complete snapshot via projectionState (docs/27 SS3.2
    decision 9's "never expose partially rebuilt rows as complete" is
    satisfied here by DISCLOSING incompleteness, not by omission)."""
    conn = _setup(tmp_path)
    ready_repo, ready_gen = _repo(conn, "ready")
    _mark_ready(conn, ready_repo, ready_gen)
    preparing_repo, preparing_gen = _repo(conn, "preparing")
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'PREPARING', NULL, '2026-08-23T00:00:00Z', NULL, NULL)",
        (preparing_repo, preparing_gen),
    )
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0)  # no repository_id filter
    assert preparing_repo in result["projectionState"]["preparingRepositoryIds"]
    assert result["projectionState"]["complete"] is False


def test_cross_repository_query_projection_state_complete_when_every_repo_is_ready(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _mark_ready(conn, repo_id, gen_id)
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0)
    assert result["projectionState"] == {
        "complete": True, "preparingRepositoryIds": [], "staleRepositoryIds": [],
    }


def test_projection_state_summary_counts_a_repository_with_no_read_model_state_row_as_preparing(tmp_path):
    """A repository registered but never yet ticked (no read_model_state
    row at all) is at least as "not ready" as one explicitly PREPARING --
    the LEFT JOIN in projection_state_summary must catch this case too."""
    conn = _setup(tmp_path)
    repo_id, _gen_id = _repo(conn, "a")  # no read_model_state row inserted
    summary = api_queries.projection_state_summary(conn)
    assert repo_id in summary["preparingRepositoryIds"]
    assert summary["complete"] is False


def test_cross_repository_issues_filters_by_repository_id(tmp_path):
    conn = _setup(tmp_path)
    repo_a, gen_a = _repo(conn, "a")
    repo_b, gen_b = _repo(conn, "b")
    # A repository-scoped query now requires a READY read_model_state row
    # (Unit 16: check_read_model_readiness) -- without one, this would
    # correctly raise IndexPreparingError rather than silently answering
    # from directly-inserted fixture rows a real backfill never produced.
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'READY', 0, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_a, gen_a),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'ia', 'DONE', '2026-08-23T00:00:00Z')", (repo_a, gen_a),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'ib', 'DONE', '2026-08-23T00:00:00Z')", (repo_b, gen_b),
    )
    result = api_queries.cross_repository_issues(conn, limit=50, offset=0, repository_id=repo_a)
    assert [i["issueId"] for i in result["items"]] == ["ia"]
    assert result["items"][0]["repository"]["id"] == repo_a


def test_cross_repository_executions_group_by_issue(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
            "issue_id, state, updated_at) VALUES (?, ?, ?, 'i1', 'ACCEPTED', '2026-08-23T00:00:00Z')",
            (repo_id, gen_id, f"e{i}"),
        )
    result = api_queries.cross_repository_executions(conn, limit=50, offset=0, group_by="issue")
    assert result["items"][0]["issue"]["issueId"] == "i1"
    assert result["items"][0]["totalExecutions"] == 3
    assert result["items"][0]["byState"]["ACCEPTED"] == 3
    assert len(result["items"][0]["newestExecutions"]) <= 5


def test_cross_repository_executions_group_by_execution_is_default(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "state, updated_at) VALUES (?, ?, 'e1', 'ACCEPTED', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    result = api_queries.cross_repository_executions(conn, limit=50, offset=0)
    assert result["items"][0]["executionId"] == "e1"


def test_cross_repository_executions_group_by_issue_is_not_n_plus_one(tmp_path):
    """Unit 15 (docs/27 SS13.2's N+1 assertion requirement; flagged as a
    residual item since Unit 4): the number of SQL statements executed for
    a groupBy=issue page must not grow with the number of issue groups on
    that page -- a bounded-but-per-group query pattern still degrades p95
    at scale even though it can never return unbounded rows."""
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    n_issues = 20
    for i in range(n_issues):
        issue_id = f"i{i}"
        conn.execute(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
            "VALUES (?, ?, ?, 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id, issue_id),
        )
        for j in range(3):
            conn.execute(
                "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
                "issue_id, state, last_event_id, updated_at) VALUES (?, ?, ?, ?, 'ACCEPTED', ?, "
                "'2026-08-23T00:00:00Z')",
                (repo_id, gen_id, f"{issue_id}-e{j}", issue_id, j),
            )

    statements = []
    conn.set_trace_callback(statements.append)
    try:
        result = api_queries.cross_repository_executions(conn, limit=50, offset=0, group_by="issue")
    finally:
        conn.set_trace_callback(None)

    assert result["total"] == n_issues
    assert len(result["items"]) == n_issues
    for item in result["items"]:
        assert item["totalExecutions"] == 3
        assert item["byState"]["ACCEPTED"] == 3
        assert len(item["newestExecutions"]) <= 5
    # A fixed, small number of statements regardless of n_issues -- not
    # 2 extra queries per issue group (which would be 2*20=40+ here).
    assert len(statements) <= 6, f"expected O(1) statements, got {len(statements)}: {statements}"


# --- evidence keyset pagination ---

def _add_evidence(conn, repo_id, gen_id, n):
    for i in range(n):
        conn.execute(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
            "stored_at) VALUES (?, ?, ?, 'OK', '2026-08-23T00:00:00Z')",
            (repo_id, gen_id, f"c{i}"),
        )


def test_evidence_keyset_default_desc_order(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _add_evidence(conn, repo_id, gen_id, 5)
    result = api_queries.evidence_keyset(conn, limit=10)
    ids = [i["evidenceId"] for i in result["items"]]
    assert ids == sorted(ids, reverse=True)
    assert result["hasMore"] is False


def test_evidence_keyset_pagination_via_before_id(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _add_evidence(conn, repo_id, gen_id, 5)
    first_page = api_queries.evidence_keyset(conn, limit=2)
    assert len(first_page["items"]) == 2
    assert first_page["hasMore"] is True
    second_page = api_queries.evidence_keyset(conn, limit=2, before_evidence_id=first_page["next"])
    assert len(second_page["items"]) == 2
    assert first_page["items"][-1]["evidenceId"] > second_page["items"][0]["evidenceId"]


def test_evidence_keyset_never_uses_deep_offset(tmp_path):
    """No `offset` parameter exists on this function at all -- the API
    surface itself makes a deep OFFSET scan structurally impossible."""
    assert "offset" not in api_queries.evidence_keyset.__code__.co_varnames


# --- legacy repository-scoped evidence offset cap tightening ---

def test_legacy_evidence_offset_above_100k_is_rejected(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    with pytest.raises(PageOutOfRangeError):
        api_queries.check_offset_cap(100_001, cap=api_queries.LEGACY_EVIDENCE_OFFSET_CAP)


def test_legacy_evidence_offset_cap_constant_is_100000():
    assert api_queries.LEGACY_EVIDENCE_OFFSET_CAP == 100_000


def test_new_route_offset_cap_constant_is_10000():
    assert api_queries.NEW_ROUTE_OFFSET_CAP == 10_000


# --- entity timeline (metadata-only) ---

def test_entity_timeline_returns_metadata_only_never_payload(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, payload_json, stored_at) "
        "VALUES (?, ?, 'c1', 'OK', 1, 'IssueCreated', 'i1', '{\"secret\":true}', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    result = api_queries.entity_timeline(conn, repo_id, "issues", "i1", limit=50, offset=0)
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert "payload" not in item and "payloadJson" not in item
    assert item["eventType"] == "IssueCreated"
    assert item["evidenceId"] is not None


def test_entity_timeline_scoped_to_entity_and_ordered(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, stored_at) VALUES (?, ?, 'c1', 'OK', 2, 'IssueActivated', "
        "'i1', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, stored_at) VALUES (?, ?, 'c0', 'OK', 1, 'IssueCreated', "
        "'i1', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, stored_at) VALUES (?, ?, 'c2', 'OK', 1, 'IssueCreated', "
        "'other-issue', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    result = api_queries.entity_timeline(conn, repo_id, "issues", "i1", limit=50, offset=0)
    assert [i["eventType"] for i in result["items"]] == ["IssueCreated", "IssueActivated"]


def test_entity_timeline_unknown_entity_type_rejected(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    with pytest.raises(InvalidFilterError):
        api_queries.entity_timeline(conn, repo_id, "bogus", "x", limit=50, offset=0)


# --- topology ---

def test_topology_issue_scope_returns_execution_and_evidence_nodes(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _mark_ready(conn, repo_id, gen_id)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, issue_id, "
        "state, run_id, updated_at) VALUES (?, ?, 'e1', 'i1', 'ACCEPTED', 'r1', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, execution_id, run_id, stored_at) VALUES (?, ?, 'c1', 'OK', 1, "
        "'ExecutionSpawned', 'i1', 'e1', 'r1', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    result = api_queries.entity_topology(conn, repo_id, "issues", "i1")
    node_kinds = {n["kind"] for n in result["nodes"]}
    assert "issue" in node_kinds
    assert "execution" in node_kinds
    assert "evidence" in node_kinds
    edge_types = {e["type"] for e in result["edges"]}
    assert "issue_has_execution" in edge_types
    assert "entity_has_evidence" in edge_types
    assert result["truncated"] is False


def test_topology_is_bounded_and_marks_truncated(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn, "a")
    _mark_ready(conn, repo_id, gen_id)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, ?, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    for i in range(5):
        conn.execute(
            "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
            "issue_id, state, updated_at) VALUES (?, ?, ?, 'i1', 'ACCEPTED', '2026-08-23T00:00:00Z')",
            (repo_id, gen_id, f"e{i}"),
        )
    result = api_queries.entity_topology(conn, repo_id, "issues", "i1", max_nodes=3, max_edges=100)
    assert len(result["nodes"]) <= 3
    assert result["truncated"] is True
