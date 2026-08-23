"""Tolerant issue/execution projection: normal lifecycles project cleanly;
unknown event types and illegal/out-of-order transitions degrade to
`inconsistent`/`unknown_event_type_count` rather than raising."""
from __future__ import annotations

import json

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.projections import (
    PENDING_RECONCILIATION,
    build_projection,
)


def _insert_evidence(conn, repo_id, gen_id, event_id, event_type, *, issue_id=None,
                     execution_id=None, payload=None, integrity="OK"):
    conn.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
        "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
        "event_ts, payload_json, record_hash, length_bytes, stored_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, '2026-08-20T00:00:00Z', ?, 'h', 1, "
        "'2026-08-20T00:00:00Z')",
        (repo_id, gen_id, f"cursor-{event_id}", integrity, event_id, event_type,
         issue_id, execution_id, json.dumps(payload) if payload is not None else None),
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


def test_issue_lifecycle_completes_to_done_with_title(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42",
                     payload={"title": "fix the bug"})
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42",
                     payload={"base_commit": "abc123"})
    _insert_evidence(conn, 1, gen_id, 3, "IssueCompleted", issue_id="42", payload={})

    result = build_projection(conn, 1, gen_id)

    assert result.issues["42"].state == "DONE"
    assert result.issues["42"].title == "fix the bug"
    assert result.issues["42"].inconsistent is False
    assert result.unknown_event_type_count == 0


def test_execution_stuck_in_executing_shows_pending_reconciliation(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionSpawned", issue_id="42", execution_id="42-e1")

    result = build_projection(conn, 1, gen_id)

    assert result.executions["42-e1"].state == PENDING_RECONCILIATION
    assert result.executions["42-e1"].inconsistent is False


def test_execution_full_path_to_accepted_is_not_pending_reconciliation(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionSpawned", issue_id="42", execution_id="42-e1")
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="42-e1",
                     payload={"outcome": "OK"})
    _insert_evidence(conn, 1, gen_id, 3, "ValidationPassed", execution_id="42-e1", payload={})
    _insert_evidence(conn, 1, gen_id, 4, "ReviewApproved", execution_id="42-e1", payload={})

    result = build_projection(conn, 1, gen_id)

    assert result.executions["42-e1"].state == "ACCEPTED"


def test_execution_rejected_via_finish_outcome(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionSpawned", issue_id="42", execution_id="42-e1")
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionFinished", execution_id="42-e1",
                     payload={"outcome": "REJECTED"})

    result = build_projection(conn, 1, gen_id)

    assert result.executions["42-e1"].state == "REJECTED"


def test_unknown_event_type_is_counted_not_crashed(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 2, "SomeFutureEventType", issue_id="42")

    result = build_projection(conn, 1, gen_id)

    assert result.unknown_event_type_count == 1
    assert result.issues["42"].state == "PENDING"


def test_illegal_transition_marks_inconsistent_not_raise(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    # ISSUE_COMPLETED directly from PENDING (never activated) is illegal.
    _insert_evidence(conn, 1, gen_id, 2, "IssueCompleted", issue_id="42", payload={})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.issues["42"].inconsistent is True
    assert result.issues["42"].state == "PENDING"  # last known good state retained


def test_duplicate_issue_created_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", payload={"title": "a"})
    _insert_evidence(conn, 1, gen_id, 2, "IssueCreated", issue_id="42", payload={"title": "b"})

    result = build_projection(conn, 1, gen_id)

    assert result.issues["42"].inconsistent is True
    assert result.issues["42"].title == "a"  # first creation wins, not silently overwritten


def test_transition_for_unknown_issue_id_is_skipped_not_crashed(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueActivated", issue_id="never-created", payload={})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.issues == {}


def test_projection_is_scoped_to_one_identity_generation(tmp_path):
    conn, gen1 = _setup(tmp_path)
    gen2 = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, 2, 'lineage-2', 2, 2, 1, '2026-08-20T00:00:01Z')"
    ).lastrowid
    _insert_evidence(conn, 1, gen1, 1, "IssueCreated", issue_id="from-gen-1")
    _insert_evidence(conn, 1, gen2, 1, "IssueCreated", issue_id="from-gen-2")

    result = build_projection(conn, 1, gen2)

    assert "from-gen-2" in result.issues
    assert "from-gen-1" not in result.issues


def test_non_ok_evidence_is_never_projected(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42", integrity="TORN")

    result = build_projection(conn, 1, gen_id)

    assert result.issues == {}


# --- Containment generations (Unit 2 / docs/27 SS8.2, doc 03 amendment) ---


def test_containment_full_lifecycle_prepared_established_released(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionSpawned", issue_id="42", execution_id="42-e1")
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionContainmentEstablished", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 4, "ExecutionContainmentReleased", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)

    view = result.containments[("42-e1", "g1")]
    assert view.state == "RELEASED"
    assert view.workspace_key == "ws-1"
    assert view.inconsistent is False


def test_containment_termination_unconfirmed_from_established(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentEstablished", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionTerminationUnconfirmed", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)

    assert result.containments[("42-e1", "g1")].state == "UNCONFIRMED"


def test_containment_released_directly_from_prepared_is_legal(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentReleased", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)

    assert result.containments[("42-e1", "g1")].state == "RELEASED"
    assert result.containments[("42-e1", "g1")].inconsistent is False


def test_containment_established_without_matching_prepared_is_skipped(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentEstablished", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.containments == {}


def test_containment_terminated_after_release_is_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentReleased", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionTerminationUnconfirmed", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    view = result.containments[("42-e1", "g1")]
    assert view.inconsistent is True
    assert view.state == "RELEASED"  # last known good state retained


def test_containment_duplicate_prepared_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)

    assert result.containments[("42-e1", "g1")].inconsistent is True
    assert result.containments[("42-e1", "g1")].state == "PREPARED"


def test_containment_workspace_key_mismatch_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentEstablished", execution_id="42-e1",
                     payload={"workspace_key": "ws-DIFFERENT", "containment_generation": "g1"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    view = result.containments[("42-e1", "g1")]
    assert view.inconsistent is True
    assert view.state == "PREPARED"


def test_containment_generations_are_independent_per_execution_and_generation(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentReleased", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    # A second generation for the SAME execution (retry after release) is a
    # distinct, independent containment row -- not a duplicate.
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1", "containment_generation": "g2"})

    result = build_projection(conn, 1, gen_id)

    assert result.containments[("42-e1", "g1")].state == "RELEASED"
    assert result.containments[("42-e1", "g1")].inconsistent is False
    assert result.containments[("42-e1", "g2")].state == "PREPARED"
    assert result.containments[("42-e1", "g2")].inconsistent is False


def test_containment_missing_execution_id_or_generation_is_skipped(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "ExecutionContainmentPrepared", execution_id=None,
                     payload={"workspace_key": "ws-1", "containment_generation": "g1"})
    _insert_evidence(conn, 1, gen_id, 2, "ExecutionContainmentPrepared", execution_id="42-e1",
                     payload={"workspace_key": "ws-1"})  # missing containment_generation

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.containments == {}
