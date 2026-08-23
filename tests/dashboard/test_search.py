"""Unit 5 (docs/27 SS7.1): bounded grouped search. No raw evidence
payload, record bytes, transcript/diff content, or advanced query syntax
is ever searched."""
from __future__ import annotations

import pytest

from draindeck_dashboard import search
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.errors import QueryTooShortError


def _repo(conn, name="myrepo"):
    cur = conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES (?, NULL, NULL, '2026-08-23T00:00:00Z')", (f"C:/{name}",),
    )
    repo_id = cur.lastrowid
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 1, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    return repo_id, gen_id


def _setup(tmp_path):
    return connect_and_init(tmp_path / "dash.sqlite3")


def test_query_shorter_than_two_chars_is_rejected(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(QueryTooShortError):
        search.search(conn, "a")


def test_query_longer_than_200_chars_is_rejected(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(QueryTooShortError):
        search.search(conn, "x" * 201)


def test_search_matches_repository_by_project_path_substring(tmp_path):
    conn = _setup(tmp_path)
    _repo(conn, "stockphotoagent")
    result = search.search(conn, "stockphoto")
    assert len(result["repositories"]) == 1
    assert result["repositories"][0]["type"] == "repository"
    assert "url" in result["repositories"][0]


def test_search_matches_issue_by_title_substring(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, title, "
        "updated_at) VALUES (?, ?, 'i1', 'DONE', 'fix the crash', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    result = search.search(conn, "crash")
    assert len(result["issues"]) == 1
    assert result["issues"][0]["id"] == "i1"


def test_search_matches_issue_by_exact_id(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
        "updated_at) VALUES (?, ?, '42', 'DONE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    result = search.search(conn, "42")
    assert any(i["id"] == "42" for i in result["issues"])


def test_search_matches_run_and_execution_by_id_substring(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, updated_at) "
        "VALUES (?, ?, 'run-abc123', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "updated_at) VALUES (?, ?, 'exec-abc123', 'ACCEPTED', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    result = search.search(conn, "abc123")
    assert len(result["runs"]) == 1
    assert len(result["executions"]) == 1


def test_search_matches_evidence_by_id_cursor_eventid_or_eventtype(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    for i in range(10):  # pad so evidence_id below is >= 2 digits (min query length is 2)
        conn.execute(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
            "stored_at) VALUES (?, ?, ?, 'TORN', '2026-08-23T00:00:00Z')",
            (repo_id, gen_id, f"pad-{i}"),
        )
    cur = conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, stored_at) VALUES (?, ?, 'special-cursor-xyz', 'OK', 99, "
        "'IssueCreated', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    evidence_id = cur.lastrowid

    by_id = search.search(conn, str(evidence_id))
    assert any(e["id"] == str(evidence_id) for e in by_id["evidence"])

    by_cursor = search.search(conn, "special-cursor")
    assert any(e["id"] == str(evidence_id) for e in by_cursor["evidence"])

    by_event_type = search.search(conn, "IssueCreated")
    assert any(e["id"] == str(evidence_id) for e in by_event_type["evidence"])


def test_search_never_exposes_payload_or_raw_bytes(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, payload_json, stored_at) VALUES (?, ?, 'c1', 'OK', 1, "
        "'IssueCreated', '{\"secret\":\"nope\"}', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    result = search.search(conn, "IssueCreated")
    for item in result["evidence"]:
        assert "payload" not in item
        assert "recordBytes" not in item


def test_search_groups_are_capped_at_requested_limit(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    for i in range(10):
        conn.execute(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
            "title, updated_at) VALUES (?, ?, ?, 'DONE', 'matching issue', '2026-08-23T00:00:00Z')",
            (repo_id, gen_id, f"i{i}"),
        )
    result = search.search(conn, "matching", limit=3)
    assert len(result["issues"]) == 3


def test_search_case_insensitive(tmp_path):
    conn = _setup(tmp_path)
    repo_id, gen_id = _repo(conn)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, title, "
        "updated_at) VALUES (?, ?, 'i1', 'DONE', 'Fix The Crash', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    result = search.search(conn, "the crash")
    assert len(result["issues"]) == 1
