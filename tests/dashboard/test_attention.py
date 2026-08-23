"""Unit 3 (docs/27 SS6.4, SS8.5): attention condition detection/reconciliation.

Attention is Dashboard-derived history, not a runtime warning stream:
first/last detection times mean "detected by this Dashboard database."
Reconciliation opens/refreshes/resolves/re-opens (recurs) conditions
against a closed kind/severity/message/target vocabulary; generation
rollover resolves stale generation-scoped conditions automatically because
the freshly-derived current-generation condition set simply no longer
contains their keys.
"""
from __future__ import annotations

from draindeck_dashboard import attention, lease
from draindeck_dashboard.db import connect_and_init


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
    return conn, gen_id


def _set_checkpoint(conn, repo_id, gen_id, **overrides):
    fields = {
        "last_record_cursor": None, "last_record_hash": None,
        "halted_oversized": 0, "reduced_confidence": 0, "availability": "AVAILABLE",
    }
    fields.update(overrides)
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, '2026-08-23T00:00:00Z') "
        "ON CONFLICT(repository_id) DO UPDATE SET identity_generation_id=excluded.identity_generation_id, "
        "halted_oversized=excluded.halted_oversized, reduced_confidence=excluded.reduced_confidence, "
        "availability=excluded.availability",
        (repo_id, gen_id, fields["last_record_cursor"], fields["last_record_hash"],
         fields["halted_oversized"], fields["reduced_confidence"], fields["availability"]),
    )


def _open_rows(conn, repo_id=None):
    if repo_id is None:
        return conn.execute(
            "SELECT condition_key, kind, severity, subject_type, subject_id, message, target_url, "
            "occurrence, first_detected_at, last_detected_at FROM attention_conditions "
            "WHERE resolved_at IS NULL ORDER BY id"
        ).fetchall()
    return conn.execute(
        "SELECT condition_key, kind, severity, subject_type, subject_id, message, target_url, "
        "occurrence, first_detected_at, last_detected_at FROM attention_conditions "
        "WHERE repository_id = ? AND resolved_at IS NULL ORDER BY id", (repo_id,)
    ).fetchall()


# --- reconciliation lifecycle: open / refresh / resolve / recur ---

def test_condition_opens_on_first_detection(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)

    conditions = attention.derive_repository_conditions(conn, 1)
    attention.reconcile_repository_conditions(conn, 1, conditions)

    rows = _open_rows(conn, 1)
    assert len(rows) == 1
    assert rows[0][1] == "INDEXING_HALTED_OVERSIZED"
    assert rows[0][2] == "critical"
    assert rows[0][7] == 1  # occurrence


def test_repeated_reconciliation_refreshes_without_duplicating(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)

    conditions = attention.derive_repository_conditions(conn, 1)
    attention.reconcile_repository_conditions(conn, 1, conditions)
    first_detected = _open_rows(conn, 1)[0][8]

    attention.reconcile_repository_conditions(conn, 1, conditions)
    rows = _open_rows(conn, 1)
    assert len(rows) == 1  # not duplicated
    assert rows[0][8] == first_detected  # first_detected_at unchanged


def test_condition_resolves_when_no_longer_derived(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    _set_checkpoint(conn, 1, gen_id, halted_oversized=0)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    assert _open_rows(conn, 1) == []
    resolved = conn.execute(
        "SELECT resolved_at FROM attention_conditions WHERE repository_id = 1"
    ).fetchone()
    assert resolved[0] is not None


def test_condition_recurs_with_incremented_occurrence_and_new_open_row(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    _set_checkpoint(conn, 1, gen_id, halted_oversized=0)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    rows = _open_rows(conn, 1)
    assert len(rows) == 1
    assert rows[0][7] == 2  # occurrence incremented, history not overwritten
    total_rows = conn.execute(
        "SELECT COUNT(*) FROM attention_conditions WHERE repository_id = 1"
    ).fetchone()[0]
    assert total_rows == 2  # the resolved occurrence-1 row plus the new open occurrence-2 row


# --- closed kind/severity/message/target vocabulary ---

def test_repository_offline_is_warning(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, availability="OFFLINE")
    conditions = attention.derive_repository_conditions(conn, 1)
    kinds = {c.kind: c for c in conditions}
    assert kinds["REPOSITORY_OFFLINE"].severity == "warning"
    assert kinds["REPOSITORY_OFFLINE"].message == "Registered log is currently offline."
    assert kinds["REPOSITORY_OFFLINE"].target_url == "/repositories/1"


def test_reduced_identity_confidence_is_warning(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, reduced_confidence=1)
    conditions = attention.derive_repository_conditions(conn, 1)
    kinds = {c.kind for c in conditions}
    assert "REDUCED_IDENTITY_CONFIDENCE" in kinds


def test_corrupt_evidence_is_critical_one_per_event_id(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO corruptions (repository_id, identity_generation_id, event_id, cursor_a, "
        "hash_a, cursor_b, hash_b, detected_at) VALUES (1, ?, 7, 'a', 'ha', 'b', 'hb', '2026-08-23T00:00:00Z')",
        (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    corrupt = [c for c in conditions if c.kind == "CORRUPT_EVIDENCE"]
    assert len(corrupt) == 1
    assert corrupt[0].severity == "critical"
    assert corrupt[0].message == "Conflicting OK records share event ID 7."
    assert corrupt[0].subject_id == "7"


def test_malformed_evidence_present_is_warning(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, stored_at) "
        "VALUES (1, ?, 'c1', 'MALFORMED', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    kinds = {c.kind for c in conditions}
    assert "MALFORMED_EVIDENCE" in kinds


def test_unknown_event_types_reports_exact_count(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    for i in range(3):
        conn.execute(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
            "event_type, stored_at) VALUES (1, ?, ?, 'OK', 'SomeFutureEventType', '2026-08-23T00:00:00Z')",
            (gen_id, f"c{i}"),
        )
    conditions = attention.derive_repository_conditions(conn, 1)
    unknown = next(c for c in conditions if c.kind == "UNKNOWN_EVENT_TYPES")
    assert unknown.severity == "warning"
    assert unknown.message == "3 unknown complete event types retained as evidence."


def test_issue_needs_human_and_needs_decomposition(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (1, ?, 'i1', 'NEEDS_HUMAN', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (1, ?, 'i2', 'NEEDS_DECOMPOSITION', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    by_kind = {c.kind: c for c in conditions}
    assert by_kind["ISSUE_NEEDS_HUMAN"].subject_id == "i1"
    assert by_kind["ISSUE_NEEDS_HUMAN"].target_url == "/repositories/1/issues/i1"
    assert by_kind["ISSUE_NEEDS_DECOMPOSITION"].subject_id == "i2"


def test_inconsistent_issue_execution_and_run(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
        "inconsistent, updated_at) VALUES (1, ?, 'i1', 'PENDING', 1, '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "inconsistent, updated_at) VALUES (1, ?, 'e1', 'ACCEPTED', 1, '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, inconsistent, updated_at) "
        "VALUES (1, ?, 'r1', 1, '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    kinds = {c.kind for c in conditions}
    assert {"INCONSISTENT_ISSUE", "INCONSISTENT_EXECUTION", "INCONSISTENT_RUN"} <= kinds


def test_containment_unconfirmed_is_critical(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "updated_at) VALUES (1, ?, 'e1', 'VALIDATING', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, state, updated_at) VALUES (1, ?, 'e1', 'g1', 'UNCONFIRMED', "
        "'2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    c = next(c for c in conditions if c.kind == "CONTAINMENT_UNCONFIRMED")
    assert c.severity == "critical"
    assert c.message == "Termination could not be confirmed for containment g1."
    assert c.target_url == "/repositories/1/executions/e1"


def test_containment_unreleased_only_when_execution_is_terminal(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    # Not yet terminal (VALIDATING): established-but-open containment must
    # NOT be flagged unreleased yet.
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "updated_at) VALUES (1, ?, 'e1', 'VALIDATING', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, state, updated_at) VALUES (1, ?, 'e1', 'g1', 'ESTABLISHED', "
        "'2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    assert not any(c.kind == "CONTAINMENT_UNRELEASED" for c in conditions)

    conn.execute(
        "UPDATE execution_views SET state = 'ACCEPTED' WHERE repository_id=1 AND "
        "identity_generation_id=? AND execution_id='e1'", (gen_id,),
    )
    conditions2 = attention.derive_repository_conditions(conn, 1)
    c = next(c for c in conditions2 if c.kind == "CONTAINMENT_UNRELEASED")
    assert c.severity == "critical"
    assert c.message == "Terminal execution retains unreleased containment g1."


def test_two_containment_generations_for_same_execution_are_independent_conditions(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "updated_at) VALUES (1, ?, 'e1', 'ACCEPTED', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, state, updated_at) VALUES (1, ?, 'e1', 'g1', 'UNCONFIRMED', "
        "'2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO containment_views (repository_id, identity_generation_id, execution_id, "
        "containment_generation, state, updated_at) VALUES (1, ?, 'e1', 'g2', 'UNCONFIRMED', "
        "'2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    unconfirmed = [c for c in conditions if c.kind == "CONTAINMENT_UNCONFIRMED"]
    assert len(unconfirmed) == 2
    assert len({c.condition_key for c in unconfirmed}) == 2  # distinct keys, not merged


def test_pending_reconciliation_no_finish_and_torn_are_never_attention_conditions(tmp_path):
    """These remain honest observed states on their own entity screens but
    are explicitly excluded from Attention (docs/27 SS6.4)."""
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id)
    conn.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, state, "
        "updated_at) VALUES (1, ?, 'e1', 'Pending reconciliation', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conn.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, outcome, updated_at) "
        "VALUES (1, ?, 'r1', NULL, '2026-08-23T00:00:00Z')", (gen_id,),  # no controlled finish
    )
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, stored_at) "
        "VALUES (1, ?, 'c1', 'TORN', '2026-08-23T00:00:00Z')", (gen_id,),
    )
    conditions = attention.derive_repository_conditions(conn, 1)
    assert conditions == []


def test_generation_rollover_resolves_stale_generation_scoped_conditions(tmp_path):
    conn, gen1 = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen1, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))
    assert len(_open_rows(conn, 1)) == 1

    gen2 = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 2, 'lineage-2', 2, 2, 1, '2026-08-23T00:00:01Z')"
    ).lastrowid
    _set_checkpoint(conn, 1, gen2, halted_oversized=0)  # rollover clears the condition
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))

    assert _open_rows(conn, 1) == []


# --- system-wide lease conditions ---

def test_lease_stale_is_critical_system_wide(tmp_path):
    conn, _ = _setup(tmp_path)
    lease.acquire_or_renew(conn, "owner-a")
    conn.execute(
        "UPDATE indexer_lease SET heartbeat_at = '2020-01-01T00:00:00.000000Z' WHERE id = 1"
    )
    conditions = attention.derive_system_conditions(conn)
    c = next(c for c in conditions if c.kind == "LEASE_STALE")
    assert c.severity == "critical"
    assert c.repository_id is None
    attention.reconcile_system_conditions(conn, conditions)
    rows = _open_rows(conn, repo_id=None)
    assert len(rows) == 1
    assert rows[0][1] == "LEASE_STALE"


def test_lease_unclaimed_condition_is_warning_and_system_wide(tmp_path):
    conn, _ = _setup(tmp_path)  # no lease row at all -- unclaimed
    conditions = attention.derive_system_conditions(conn)
    c = next(c for c in conditions if c.kind == "LEASE_UNCLAIMED")
    assert c.severity == "warning"
    assert c.repository_id is None


def test_lease_held_produces_no_lease_condition(tmp_path):
    conn, _ = _setup(tmp_path)
    lease.acquire_or_renew(conn, "owner-a")
    conditions = attention.derive_system_conditions(conn)
    assert not any(c.kind in ("LEASE_STALE", "LEASE_UNCLAIMED") for c in conditions)


# --- SSE invalidations (docs/27 SS8.5: one per opened/resolved condition) ---

def _changes(conn, repo_id, entity_type="attention"):
    return conn.execute(
        "SELECT entity_id FROM changes WHERE repository_id = ? AND entity_type = ? ORDER BY change_sequence",
        (repo_id, entity_type),
    ).fetchall()


def test_opening_a_condition_records_exactly_one_attention_change(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))
    assert len(_changes(conn, 1)) == 1


def test_refreshing_an_open_condition_records_no_additional_change(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    conditions = attention.derive_repository_conditions(conn, 1)
    attention.reconcile_repository_conditions(conn, 1, conditions)
    attention.reconcile_repository_conditions(conn, 1, conditions)
    assert len(_changes(conn, 1)) == 1  # only the original open, no re-invalidation on refresh


def test_resolving_a_condition_records_one_more_attention_change(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _set_checkpoint(conn, 1, gen_id, halted_oversized=1)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))
    _set_checkpoint(conn, 1, gen_id, halted_oversized=0)
    attention.reconcile_repository_conditions(conn, 1, attention.derive_repository_conditions(conn, 1))
    assert len(_changes(conn, 1)) == 2  # one open + one resolve


def test_system_wide_attention_changes_use_reserved_repository_id_zero(tmp_path):
    conn, _ = _setup(tmp_path)  # no lease -- unclaimed
    attention.reconcile_system_conditions(conn, attention.derive_system_conditions(conn))
    assert len(_changes(conn, 0)) == 1


def test_lease_condition_resolves_once_held_again(tmp_path):
    conn, _ = _setup(tmp_path)
    attention.reconcile_system_conditions(conn, attention.derive_system_conditions(conn))  # unclaimed opens
    assert len(_open_rows(conn, repo_id=None)) == 1

    lease.acquire_or_renew(conn, "owner-a")
    attention.reconcile_system_conditions(conn, attention.derive_system_conditions(conn))
    assert _open_rows(conn, repo_id=None) == []
