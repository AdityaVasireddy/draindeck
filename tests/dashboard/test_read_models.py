"""Unit 2 Sub-step A (docs/27 SS8.4): persistent tolerant read models.

`rebuild_read_models` is the full-generation candidate-rebuild-and-publish
primitive (idempotent, retryable, atomically visible). `apply_changed_entities`
is the entity-scoped incremental path used on every ordinary tick: it
replays only the touched issue/execution/run/containment's own evidence
(never a full-generation scan) and upserts just that entity's row, so a
normal TORN->OK tail repair or a fresh append never forces a full-generation
rebuild. Both paths must produce results identical to the pure reducer
(`build_projection`) -- parity is the core correctness property.
"""
from __future__ import annotations

import json

from draindeck_dashboard import lease
from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.projections import build_projection
from draindeck_dashboard.read_models import (
    LeaseLostError,
    apply_changed_entities,
    mark_error,
    mark_preparing,
    mark_rebuilding,
    prune_old_generation_views,
    read_model_status,
    rebuild_read_models,
)

_OWNER = "test-owner"


def _insert_evidence(conn, repo_id, gen_id, event_id, event_type, *, issue_id=None,
                     execution_id=None, run_id=None, payload=None, integrity="OK",
                     event_ts="2026-08-23T00:00:00Z"):
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
        "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
        "event_ts, payload_json, record_hash, length_bytes, stored_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'h', 1, "
        "'2026-08-23T00:00:00Z')",
        (repo_id, gen_id, f"cursor-{gen_id}-{event_id}", integrity, event_id, event_type,
         issue_id, execution_id, run_id, event_ts,
         json.dumps(payload) if payload is not None else None),
    )


def _setup(tmp_path):
    conn = connect_and_init(tmp_path / "dash.sqlite3")
    conn.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, 'C:/repo', NULL, NULL, '2026-08-23T00:00:00Z')"
    )
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 1, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')"
    ).lastrowid
    # rebuild_read_models now requires the caller to hold the indexer
    # lease (this session's merge-blocker fix) -- every test in this file
    # that calls it needs a held lease first, under this same _OWNER token.
    lease.acquire_or_renew(conn, _OWNER)
    return conn, gen_id


def _issue_view_row(conn, repo_id, gen_id, issue_id):
    return conn.execute(
        "SELECT state, title, inconsistent, last_event_id FROM issue_views "
        "WHERE repository_id = ? AND identity_generation_id = ? AND issue_id = ?",
        (repo_id, gen_id, issue_id),
    ).fetchone()


def test_rebuild_read_models_matches_pure_reducer_for_issues(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "t"})
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42", payload={"base_commit": "a"})
    _insert_evidence(conn, 1, gen_id, 3, "IssueCompleted", issue_id="42", payload={})

    rebuild_read_models(conn, 1, gen_id, _OWNER)
    pure = build_projection(conn, 1, gen_id)

    row = _issue_view_row(conn, 1, gen_id, "42")
    assert row == (pure.issues["42"].state, pure.issues["42"].title,
                   int(pure.issues["42"].inconsistent), pure.issues["42"].last_event_id)
    assert row[0] == "DONE"


def test_rebuild_read_models_persists_executions_runs_and_containments(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionSpawned", issue_id="42", execution_id="42-e1",
                     run_id="run-1")
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 3, "RunStarted", run_id="run-1", payload={
        "engine": {"provider": "anthropic", "model": "claude"},
        "reviewer": {"provider": "qwen", "model": None},
        "budget": {"max_attempts_per_issue": 1, "max_executions_per_run": 1,
                   "hard_stop_proxy_cost_per_run_usd": 1.0, "proxy_pricing": "api_list_rates"},
        "config_digest": "a" * 64,
    })

    rebuild_read_models(conn, 1, gen_id, _OWNER)

    exec_row = conn.execute(
        "SELECT state, run_id FROM execution_views WHERE repository_id=1 AND "
        "identity_generation_id=? AND execution_id='42-e1'", (gen_id,)
    ).fetchone()
    assert exec_row == ("Pending reconciliation", "run-1")

    containment_row = conn.execute(
        "SELECT state, workspace_key FROM containment_views WHERE repository_id=1 AND "
        "identity_generation_id=? AND execution_id='42-e1' AND containment_generation='g1'",
        (gen_id,)
    ).fetchone()
    assert containment_row == ("PREPARED", "ws-1")

    run_row = conn.execute(
        "SELECT engine_provider, config_digest FROM run_views WHERE repository_id=1 AND "
        "identity_generation_id=? AND run_id='run-1'", (gen_id,)
    ).fetchone()
    assert run_row == ("anthropic", "a" * 64)


def test_run_view_persists_real_observed_started_and_finished_timestamps(tmp_path):
    """Unit 16 (fresh-context review finding): observed_started_at/
    observed_finished_at are schema columns read by three query-layer
    functions but were never written by _write_run_view -- confirmed by
    running the REAL evidence -> reducer -> persisted-row path end to end
    (not by fabricating the columns via a direct SQL insert, which is what
    let this go undetected)."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id="run-1", event_ts="2026-08-23T10:00:00Z",
                     payload={
                         "engine": {"provider": "anthropic", "model": "claude"},
                         "reviewer": {"provider": "qwen", "model": None},
                         "budget": {"max_attempts_per_issue": 1, "max_executions_per_run": 1,
                                    "hard_stop_proxy_cost_per_run_usd": 1.0,
                                    "proxy_pricing": "api_list_rates"},
                         "config_digest": "a" * 64,
                     })
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id="run-1", event_ts="2026-08-23T11:30:00Z",
                     payload={"outcome": "COMPLETED", "detail": None})

    rebuild_read_models(conn, 1, gen_id, _OWNER)

    run_row = conn.execute(
        "SELECT observed_started_at, observed_finished_at FROM run_views WHERE repository_id=1 "
        "AND identity_generation_id=? AND run_id='run-1'", (gen_id,)
    ).fetchone()
    assert run_row == ("2026-08-23T10:00:00Z", "2026-08-23T11:30:00Z")


def test_apply_changed_entities_also_persists_observed_run_timestamps(tmp_path):
    """The entity-scoped incremental path (the one every real production
    tick actually uses) must persist the same fields as the full rebuild
    -- not just rebuild_read_models, which nothing in indexer.py calls."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id="run-2", event_ts="2026-08-23T09:00:00Z",
                     payload={
                         "engine": {"provider": "anthropic", "model": "claude"},
                         "reviewer": {"provider": "qwen", "model": None},
                         "budget": {"max_attempts_per_issue": 1, "max_executions_per_run": 1,
                                    "hard_stop_proxy_cost_per_run_usd": 1.0,
                                    "proxy_pricing": "api_list_rates"},
                         "config_digest": "b" * 64,
                     })

    apply_changed_entities(conn, 1, gen_id, run_ids={"run-2"})

    run_row = conn.execute(
        "SELECT observed_started_at, observed_finished_at FROM run_views WHERE repository_id=1 "
        "AND identity_generation_id=? AND run_id='run-2'", (gen_id,)
    ).fetchone()
    assert run_row == ("2026-08-23T09:00:00Z", None)


def test_rebuild_read_models_is_idempotent_and_atomically_replaces_stale_rows(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "t"})
    rebuild_read_models(conn, 1, gen_id, _OWNER)
    rebuild_read_models(conn, 1, gen_id, _OWNER)  # must not raise or duplicate

    count = conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=1 AND identity_generation_id=? "
        "AND issue_id='42'", (gen_id,)
    ).fetchone()[0]
    assert count == 1


def test_rebuild_read_models_updates_read_model_state_to_ready(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    rebuild_read_models(conn, 1, gen_id, _OWNER)

    status = read_model_status(conn, 1)
    assert status["status"] == "READY"
    assert status["identityGenerationId"] == gen_id


def test_mark_preparing_sets_status_with_no_prior_snapshot(tmp_path):
    conn, gen_id = _setup(tmp_path)
    mark_preparing(conn, 1, gen_id)
    status = read_model_status(conn, 1)
    assert status["status"] == "PREPARING"
    assert status["identityGenerationId"] == gen_id
    assert status["completedEvidenceId"] is None
    assert status["completedAt"] is None


def test_mark_preparing_on_a_new_generation_clears_the_old_generations_snapshot_fields(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    rebuild_read_models(conn, 1, gen_id, _OWNER)  # READY, with a real completed_evidence_id

    new_gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 2, 'lineage2', 1, 1, 1, '2026-08-23T00:00:00Z')"
    ).lastrowid
    mark_preparing(conn, 1, new_gen_id)

    status = read_model_status(conn, 1)
    assert status["status"] == "PREPARING"
    assert status["identityGenerationId"] == new_gen_id
    # The OLD generation's completed_evidence_id would be dishonest here --
    # it describes evidence in a generation this row no longer represents.
    assert status["completedEvidenceId"] is None
    assert status["completedAt"] is None


def test_mark_rebuilding_flips_ready_to_rebuilding_without_losing_the_last_snapshot(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    rebuild_read_models(conn, 1, gen_id, _OWNER)  # READY
    before = read_model_status(conn, 1)

    mark_rebuilding(conn, 1)

    after = read_model_status(conn, 1)
    assert after["status"] == "REBUILDING"
    # The last complete snapshot's identity is preserved -- this is exactly
    # what lets a caller serve it "labelled stale/rebuilding" instead of
    # blocking (docs/27 SS3.2 decision 9).
    assert after["identityGenerationId"] == before["identityGenerationId"]
    assert after["completedEvidenceId"] == before["completedEvidenceId"]
    assert after["completedAt"] == before["completedAt"]


def test_mark_rebuilding_is_a_no_op_when_status_is_still_preparing(tmp_path):
    conn, gen_id = _setup(tmp_path)
    mark_preparing(conn, 1, gen_id)
    mark_rebuilding(conn, 1)
    status = read_model_status(conn, 1)
    # An unsafe mutation on a generation that was never itself completed
    # doesn't need its own status -- PREPARING already means "no complete
    # snapshot," and the eventual rebuild picks up the mutation too.
    assert status["status"] == "PREPARING"


def test_mark_error_records_error_code(tmp_path):
    conn, gen_id = _setup(tmp_path)
    mark_preparing(conn, 1, gen_id)
    mark_error(conn, 1, gen_id, "REBUILD_CRASHED")
    status = read_model_status(conn, 1)
    assert status["status"] == "ERROR"
    assert status["errorCode"] == "REBUILD_CRASHED"


def test_mark_error_for_a_stale_generation_id_does_not_overwrite_a_newer_ready_status(tmp_path):
    """An error report that arrives for an OLD generation_id (e.g. a
    retried worker job racing a newer rollover) must never regress the
    CURRENT generation's real status -- mark_error is scoped by
    (repo_id, identity_generation_id), not repo_id alone."""
    conn, gen_id = _setup(tmp_path)
    mark_preparing(conn, 1, gen_id)
    new_gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 2, 'lineage2', 1, 1, 1, '2026-08-23T00:00:00Z')"
    ).lastrowid
    _insert_evidence(conn, 1, new_gen_id, 1, "IssueCreated", issue_id="42")
    rebuild_read_models(conn, 1, new_gen_id, _OWNER)  # current generation is READY

    mark_error(conn, 1, gen_id, "REBUILD_CRASHED")  # a stale report for the OLD generation

    status = read_model_status(conn, 1)
    assert status["status"] == "READY"
    assert status["identityGenerationId"] == new_gen_id


def test_apply_changed_entities_incrementally_updates_a_single_issue(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "t"})
    rebuild_read_models(conn, 1, gen_id, _OWNER)  # establish baseline READY state

    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42", payload={"base_commit": "a"})
    apply_changed_entities(conn, 1, gen_id, issue_ids={"42"})

    row = _issue_view_row(conn, 1, gen_id, "42")
    assert row[0] == "ACTIVE"


def test_apply_changed_entities_does_not_touch_unrelated_issues(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "a"})
    _insert_evidence(conn, 1, gen_id, 2, "IssueCreated", issue_id="43", payload={"title": "b"})
    rebuild_read_models(conn, 1, gen_id, _OWNER)

    # Mutate issue 43's view row directly to a sentinel the incremental
    # path for issue 42 must never touch.
    conn.execute(
        "UPDATE issue_views SET title = 'SENTINEL' WHERE repository_id=1 AND "
        "identity_generation_id=? AND issue_id='43'", (gen_id,)
    )
    _insert_evidence(conn, 1, gen_id, 3, "IssueActivated", issue_id="42", payload={})
    apply_changed_entities(conn, 1, gen_id, issue_ids={"42"})

    untouched = conn.execute(
        "SELECT title FROM issue_views WHERE repository_id=1 AND identity_generation_id=? "
        "AND issue_id='43'", (gen_id,)
    ).fetchone()[0]
    assert untouched == "SENTINEL"


def test_apply_changed_entities_torn_to_ok_tail_repair_applies_without_full_rebuild(tmp_path):
    """A TORN row later completing to OK at the same cursor is the exact
    boundary-redelivery/tail-repair scenario docs/27 SS8.4 requires be
    applied incrementally -- never forcing a full-generation rebuild."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "t"})
    rebuild_read_models(conn, 1, gen_id, _OWNER)

    # The tail row first arrives TORN (same record_cursor the repair below
    # will later complete at), then gets repaired to OK in place -- exactly
    # indexer.py's real upsert behavior for a boundary-redelivered tail.
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42", payload={}, integrity="TORN")
    apply_changed_entities(conn, 1, gen_id, issue_ids={"42"})  # TORN contributes nothing
    assert _issue_view_row(conn, 1, gen_id, "42")[0] == "PENDING"

    conn.execute(
        "UPDATE evidence SET integrity='OK' WHERE repository_id=1 AND identity_generation_id=? "
        "AND record_cursor=?", (gen_id, f"cursor-{gen_id}-2"),
    )
    apply_changed_entities(conn, 1, gen_id, issue_ids={"42"})

    assert _issue_view_row(conn, 1, gen_id, "42")[0] == "ACTIVE"


def test_apply_changed_entities_recomputes_run_started_valid_flag_correctly(tmp_path):
    """RunView's started_valid/finished_valid anomaly tracking isn't
    persisted as separate columns -- it must be correctly re-derived every
    time by replaying the run's own evidence from scratch, not by trying
    to reconstruct hidden state from the stored row."""
    conn, gen_id = _setup(tmp_path)
    valid_payload = {
        "engine": {"provider": "anthropic", "model": "claude"},
        "reviewer": {"provider": "qwen", "model": None},
        "budget": {"max_attempts_per_issue": 1, "max_executions_per_run": 1,
                   "hard_stop_proxy_cost_per_run_usd": 1.0, "proxy_pricing": "api_list_rates"},
        "config_digest": "a" * 64,
    }
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id="run-1", payload={"garbage": True})
    rebuild_read_models(conn, 1, gen_id, _OWNER)
    row = conn.execute(
        "SELECT inconsistent FROM run_views WHERE repository_id=1 AND identity_generation_id=? "
        "AND run_id='run-1'", (gen_id,)
    ).fetchone()
    assert row[0] == 1  # malformed RunStarted flagged inconsistent

    # A second, VALID RunStarted for the same run_id is itself anomalous
    # (duplicate) but must recover the valid data per projections.py's
    # documented "first observed wins, unless it was garbage" rule.
    _insert_evidence(conn, 1, gen_id, 2, "RunStarted", run_id="run-1", payload=valid_payload)
    apply_changed_entities(conn, 1, gen_id, run_ids={"run-1"})

    engine_provider = conn.execute(
        "SELECT engine_provider FROM run_views WHERE repository_id=1 AND identity_generation_id=? "
        "AND run_id='run-1'", (gen_id,)
    ).fetchone()[0]
    assert engine_provider == "anthropic"


def test_apply_changed_entities_containment_recomputes_all_generations_for_execution(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    rebuild_read_models(conn, 1, gen_id, _OWNER)

    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentEstablished", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    apply_changed_entities(conn, 1, gen_id, execution_ids={"42-e1"})

    state = conn.execute(
        "SELECT state FROM containment_views WHERE repository_id=1 AND identity_generation_id=? "
        "AND execution_id='42-e1' AND containment_generation='g1'", (gen_id,)
    ).fetchone()[0]
    assert state == "ESTABLISHED"


def test_prune_old_generation_views_removes_only_stale_generation_rows(tmp_path):
    conn, gen1 = _setup(tmp_path)
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    rebuild_read_models(conn, 1, gen1, _OWNER)

    gen2 = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 2, 'lineage-2', 2, 2, 1, '2026-08-23T00:00:01Z')"
    ).lastrowid
    _insert_evidence(conn, 1, gen2, 1, "IssueCreated", issue_id="from-gen-2")
    rebuild_read_models(conn, 1, gen2, _OWNER)

    prune_old_generation_views(conn, 1, keep_generation_id=gen2)

    remaining_gen1 = conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=1 AND identity_generation_id=?",
        (gen1,),
    ).fetchone()[0]
    remaining_gen2 = conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=1 AND identity_generation_id=?",
        (gen2,),
    ).fetchone()[0]
    assert remaining_gen1 == 0
    assert remaining_gen2 == 1


# --- generation rollover: old-generation preservation (this session's merge-blocker fix) ---

def _new_generation(conn, repo_id, number, lineage):
    return conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, ?, ?, 1, 1, 1, '2026-08-23T00:00:01Z')",
        (repo_id, number, lineage),
    ).lastrowid


def _issue_view_count(conn, repo_id, gen_id):
    return conn.execute(
        "SELECT COUNT(*) FROM issue_views WHERE repository_id=? AND identity_generation_id=?",
        (repo_id, gen_id),
    ).fetchone()[0]


def test_old_generation_rows_survive_while_new_generation_is_preparing(tmp_path):
    """docs/27 SS8.4 (this session's merge-blocker fix): a generation
    rollover must never destroy the old, complete generation's view rows
    merely because a NEW generation opened -- only a successful READY
    publish for the new generation may prune them. mark_preparing (what a
    real rollover actually calls) must never itself touch the old rows."""
    conn, gen1 = _setup(tmp_path)
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    rebuild_read_models(conn, 1, gen1, _OWNER)
    assert _issue_view_count(conn, 1, gen1) == 1

    gen2 = _new_generation(conn, 1, 2, "lineage-2")
    mark_preparing(conn, 1, gen2)  # what indexer.py's rollover path actually calls

    assert read_model_status(conn, 1)["status"] == "PREPARING"
    assert _issue_view_count(conn, 1, gen1) == 1  # NOT pruned yet -- new gen isn't READY


def test_old_generation_rows_survive_a_failed_rebuild_attempt_on_the_new_generation(tmp_path, monkeypatch):
    """Failure: an exception during the new generation's candidate rebuild
    must roll the whole transaction back, leaving the old generation's
    rows exactly as they were -- pruning is inside that same transaction,
    so it can never partially apply."""
    conn, gen1 = _setup(tmp_path)
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    rebuild_read_models(conn, 1, gen1, _OWNER)

    gen2 = _new_generation(conn, 1, 2, "lineage-2")
    mark_preparing(conn, 1, gen2)
    _insert_evidence(conn, 1, gen2, 1, "IssueCreated", issue_id="from-gen-2")

    import draindeck_dashboard.read_models as read_models_module

    def boom(rows):
        raise RuntimeError("simulated candidate-computation crash")

    monkeypatch.setattr(read_models_module, "apply_ok_evidence_rows", boom)

    try:
        rebuild_read_models(conn, 1, gen2, _OWNER)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass

    assert _issue_view_count(conn, 1, gen1) == 1  # untouched by the failed attempt
    assert _issue_view_count(conn, 1, gen2) == 0  # never published either
    assert read_model_status(conn, 1)["status"] == "PREPARING"  # unchanged by the failed attempt


def test_old_generation_rows_survive_lease_loss_on_the_new_generation(tmp_path, monkeypatch):
    """Lease loss: same guarantee as the failure case above, via the
    pre-publication ownership re-check instead of an exception in the
    candidate computation itself."""
    conn, gen1 = _setup(tmp_path)
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    rebuild_read_models(conn, 1, gen1, _OWNER)

    gen2 = _new_generation(conn, 1, 2, "lineage-2")
    mark_preparing(conn, 1, gen2)
    _insert_evidence(conn, 1, gen2, 1, "IssueCreated", issue_id="from-gen-2")

    import draindeck_dashboard.read_models as read_models_module
    real_fetch = read_models_module.fetch_ok_evidence_rows

    def fetch_then_steal_lease(conn_arg, repo_id_arg, gen_id_arg):
        rows = real_fetch(conn_arg, repo_id_arg, gen_id_arg)
        conn_arg.execute("UPDATE indexer_lease SET owner_token = 'other-owner' WHERE id = 1")
        return rows

    monkeypatch.setattr(read_models_module, "fetch_ok_evidence_rows", fetch_then_steal_lease)

    try:
        rebuild_read_models(conn, 1, gen2, _OWNER)
        assert False, "expected LeaseLostError"
    except LeaseLostError:
        pass

    assert _issue_view_count(conn, 1, gen1) == 1  # untouched by the rejected publish
    assert _issue_view_count(conn, 1, gen2) == 0
    assert read_model_status(conn, 1)["status"] == "PREPARING"


def test_old_generation_rows_survive_retry_and_are_pruned_only_on_eventual_success(tmp_path, monkeypatch):
    """Retry: a failed attempt followed by a successful one -- old rows
    must survive the failure AND still be present right up until the
    retry actually commits, at which point (and ONLY then) they're
    pruned."""
    conn, gen1 = _setup(tmp_path)
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    rebuild_read_models(conn, 1, gen1, _OWNER)

    gen2 = _new_generation(conn, 1, 2, "lineage-2")
    mark_preparing(conn, 1, gen2)
    _insert_evidence(conn, 1, gen2, 1, "IssueCreated", issue_id="from-gen-2")

    import draindeck_dashboard.read_models as read_models_module
    real_apply = read_models_module.apply_ok_evidence_rows
    call_count = {"n": 0}

    def flaky_apply(rows):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated first-attempt crash")
        return real_apply(rows)

    monkeypatch.setattr(read_models_module, "apply_ok_evidence_rows", flaky_apply)

    try:
        rebuild_read_models(conn, 1, gen2, _OWNER)
        assert False, "expected RuntimeError on first attempt"
    except RuntimeError:
        pass
    assert _issue_view_count(conn, 1, gen1) == 1  # still there after the failed first attempt

    rebuild_read_models(conn, 1, gen2, _OWNER)  # retry succeeds

    assert read_model_status(conn, 1)["status"] == "READY"
    assert read_model_status(conn, 1)["identityGenerationId"] == gen2
    assert _issue_view_count(conn, 1, gen1) == 0  # pruned only now, on the successful retry
    assert _issue_view_count(conn, 1, gen2) == 1
