"""Unit 1: proxy cost/tokens are captured on the ExecutionView at the single
accepted ExecutionFinished transition (spec §2.1). Duplicate/inconsistent
terminal evidence never overwrites it; a crash terminal yields no cost.
"""
from __future__ import annotations

import json

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.projections import build_projection


def _insert(conn, repo_id, gen_id, event_id, event_type, *, issue_id=None,
            execution_id=None, run_id=None, payload=None, integrity="OK"):
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
        "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
        "event_ts, payload_json, record_hash, length_bytes, stored_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, '2026-08-20T00:00:00Z', ?, 'h', 1, "
        "'2026-08-20T00:00:00Z')",
        (repo_id, gen_id, f"cursor-{event_id}", integrity, event_id, event_type,
         issue_id, execution_id, run_id, json.dumps(payload) if payload is not None else None),
    )


def _setup(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    conn.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, 'C:/repo', NULL, NULL, '2026-08-20T00:00:00Z')"
    )
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 1, 'lineage', 1, 1, 1, '2026-08-20T00:00:00Z')"
    ).lastrowid
    return conn, gen_id


def _finish_payload(dollars=1.84, input_tokens=41200, output_tokens=9800, outcome=None):
    p = {"usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                   "dollars": dollars}}
    if outcome is not None:
        p["outcome"] = outcome
    return p


def test_accepted_finish_captures_cost_and_tokens(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", issue_id="42", execution_id="42-e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="42-e1",
            payload=_finish_payload())

    v = build_projection(conn, 1, gen_id).executions["42-e1"]
    assert v.proxy_micro_usd == 1_840_000
    assert v.cost_valid is True
    assert v.input_tokens == 41200
    assert v.output_tokens == 9800
    assert v.tokens_valid is True


def test_metered_zero_is_captured(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(dollars=0))
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.proxy_micro_usd == 0
    assert v.cost_valid is True


def test_invalid_dollars_leaves_cost_unknown(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(dollars=-5))
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.proxy_micro_usd is None
    assert v.cost_valid is False
    # Tokens still valid -- coverage is independent.
    assert v.tokens_valid is True
    assert v.input_tokens == 41200


def test_invalid_tokens_independent_of_valid_cost(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(input_tokens=-1, output_tokens=1.5))
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.cost_valid is True
    assert v.proxy_micro_usd == 1_840_000
    assert v.tokens_valid is False
    assert v.input_tokens is None
    assert v.output_tokens is None


def test_missing_usage_object_is_unknown_cost_and_tokens(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1", payload={})
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.cost_valid is False
    assert v.proxy_micro_usd is None
    assert v.tokens_valid is False


def test_duplicate_finish_does_not_overwrite_first_cost(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(dollars=1.84))
    # A second, duplicate ExecutionFinished with a different cost: it is NOT an
    # accepted transition (state is no longer EXECUTING), flags inconsistent,
    # and must never overwrite or double-count the first captured cost (D1).
    _insert(conn, 1, gen_id, 3, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(dollars=99.0))
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.inconsistent is True
    assert v.proxy_micro_usd == 1_840_000  # first accepted value retained


def test_crash_terminal_has_no_cost(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionCrashed", execution_id="e1", payload={})
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.cost_valid is False
    assert v.proxy_micro_usd is None
    assert v.tokens_valid is False


def test_rejected_finish_still_meters_cost(tmp_path):
    # A REJECTED ExecutionFinished is still an accepted terminal transition
    # (EXECUTING -> REJECTED) and its usage counts (spec §2.4: issue sums
    # include rejections).
    conn, gen_id = _setup(tmp_path)
    _insert(conn, 1, gen_id, 1, "ExecutionSpawned", execution_id="e1")
    _insert(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="e1",
            payload=_finish_payload(dollars=0.5, outcome="REJECTED"))
    v = build_projection(conn, 1, gen_id).executions["e1"]
    assert v.state == "REJECTED"
    assert v.proxy_micro_usd == 500_000
    assert v.cost_valid is True
