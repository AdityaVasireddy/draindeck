"""Unit 2: the persisted execution_views row carries the captured proxy
cost/tokens through both the full-generation rebuild and the incremental
per-entity path (spec §4.1)."""
from __future__ import annotations

import json

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.lease import acquire_or_renew
from draindeck_dashboard.read_models import apply_changed_entities, rebuild_read_models


def _insert(conn, gen_id, event_id, event_type, *, execution_id=None, issue_id=None, payload=None):
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
        "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
        "event_ts, payload_json, record_hash, length_bytes, stored_at) "
        "VALUES (1, ?, ?, 'OK', ?, ?, 1, ?, ?, NULL, '2026-08-26T00:00:00Z', ?, 'h', 1, "
        "'2026-08-26T00:00:00Z')",
        (gen_id, f"cursor-{event_id}", event_id, event_type, issue_id, execution_id,
         json.dumps(payload) if payload is not None else None),
    )


def _setup(tmp_path):
    conn = connect_and_init(tmp_path / "d.sqlite3")
    conn.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, 'C:/repo', NULL, NULL, '2026-08-26T00:00:00Z')"
    )
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 1, 'lineage', 1, 1, 1, '2026-08-26T00:00:00Z')"
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, availability, updated_at) VALUES (1, ?, 'cursor-2', 'h', 'AVAILABLE', "
        "'2026-08-26T00:00:00Z')",
        (gen_id,),
    )
    return conn, gen_id


def _finish(dollars=1.84):
    return {"usage": {"input_tokens": 41200, "output_tokens": 9800, "dollars": dollars}}


def test_rebuild_persists_cost_columns(tmp_path):
    conn, gen_id = _setup(tmp_path)
    assert acquire_or_renew(conn, "owner-1") is True
    _insert(conn, gen_id, 1, "ExecutionSpawned", execution_id="e1", issue_id="42")
    _insert(conn, gen_id, 2, "ExecutionFinished", execution_id="e1", payload=_finish())

    rebuild_read_models(conn, 1, gen_id, "owner-1")

    row = conn.execute(
        "SELECT proxy_micro_usd, cost_valid, input_tokens, output_tokens, tokens_valid "
        "FROM execution_views WHERE execution_id = 'e1'"
    ).fetchone()
    assert row == (1_840_000, 1, 41200, 9800, 1)


def test_incremental_persists_cost_columns(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert(conn, gen_id, 1, "ExecutionSpawned", execution_id="e1", issue_id="42")
    _insert(conn, gen_id, 2, "ExecutionFinished", execution_id="e1", payload=_finish(dollars=0.5))

    apply_changed_entities(conn, 1, gen_id, execution_ids=["e1"])

    row = conn.execute(
        "SELECT proxy_micro_usd, cost_valid FROM execution_views WHERE execution_id = 'e1'"
    ).fetchone()
    assert row == (500_000, 1)
