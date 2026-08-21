"""Dashboard-side RunStarted/RunFinished rendering (docs/19 "Run lifecycle
compatibility"): run metadata is available only when a matching RunStarted
was actually observed -- never inferred from run_id's string shape -- and a
run_id with no such evidence renders the exact fallback text, never a blank
panel. This reducer never raises on malformed/reordered evidence (same
tolerance contract as the rest of projections.py)."""
from __future__ import annotations

import json

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.projections import (
    RUN_METADATA_UNAVAILABLE,
    RUN_NO_CONTROLLED_FINISH_OBSERVED,
    build_projection,
    has_run_metadata,
)
from draindeck_dashboard.views import list_executions, list_runs

NEW_RUN_ID = "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6"
LEGACY_RUN_ID = "run-20260601T000000Z"


def _insert_evidence(conn, repo_id, gen_id, event_id, event_type, *, issue_id=None,
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


def _run_started_payload(**overrides) -> dict:
    payload = {
        "engine": {"provider": "claude-headless", "model": "default"},
        "reviewer": {"provider": "qwen", "model": "qwen2.5-coder"},
        "budget": {
            "max_attempts_per_issue": 3, "max_executions_per_run": 10,
            "hard_stop_proxy_cost_per_run_usd": 15.0, "proxy_pricing": "api_list_rates",
        },
        "config_digest": "a" * 64,
    }
    payload.update(overrides)
    return payload


def test_run_started_makes_metadata_available(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())

    result = build_projection(conn, 1, gen_id)

    assert has_run_metadata(result, NEW_RUN_ID) is True
    run = result.runs[NEW_RUN_ID]
    assert run.engine_provider == "claude-headless"
    assert run.engine_model == "default"
    assert run.reviewer_provider == "qwen"
    assert run.reviewer_model == "qwen2.5-coder"
    assert run.config_digest == "a" * 64
    assert run.outcome is None
    assert run.inconsistent is False


def test_run_finished_attaches_outcome_to_existing_run(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})

    result = build_projection(conn, 1, gen_id)

    assert result.runs[NEW_RUN_ID].outcome == "COMPLETED"


def test_run_finished_without_matching_run_started_is_dropped_not_crashed(tmp_path):
    """Reordered/torn evidence: a RunFinished with no RunStarted observed yet
    must never raise, and must never fabricate an available run."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert has_run_metadata(result, NEW_RUN_ID) is False
    assert NEW_RUN_ID not in result.runs


def test_legacy_run_id_with_no_run_started_is_unavailable(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionSpawned", issue_id="42",
                     execution_id="42-e1", run_id=LEGACY_RUN_ID)

    result = build_projection(conn, 1, gen_id)

    assert has_run_metadata(result, LEGACY_RUN_ID) is False


def test_execution_with_no_run_id_at_all_is_unavailable(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionSpawned", issue_id="42",
                     execution_id="42-e1", run_id=None)

    result = build_projection(conn, 1, gen_id)

    assert has_run_metadata(result, None) is False


def test_duplicate_run_started_marks_inconsistent_but_stays_available(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())

    result = build_projection(conn, 1, gen_id)

    assert has_run_metadata(result, NEW_RUN_ID) is True
    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_malformed_run_started_then_valid_one_recovers_the_valid_data(tmp_path):
    """Adversarial-review finding: "first observed wins" must not mean a
    malformed first record permanently hides a fully valid second one --
    the valid data must be recovered, while the duplicate itself is still
    flagged inconsistent (two RunStarted for one run is anomalous either
    way)."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload={"engine": {"provider": "claude-headless"}})  # missing model
    _insert_evidence(conn, 1, gen_id, 2, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())  # fully valid

    result = build_projection(conn, 1, gen_id)  # must not raise

    run = result.runs[NEW_RUN_ID]
    assert run.inconsistent is True  # duplicate is still anomalous
    assert run.engine_model == "default"  # but the valid record's data won
    assert run.config_digest == "a" * 64


def test_valid_run_started_then_malformed_one_keeps_the_valid_data(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())  # fully valid
    _insert_evidence(conn, 1, gen_id, 2, "RunStarted", run_id=NEW_RUN_ID,
                     payload={"engine": {"provider": "claude-headless"}})  # missing model

    result = build_projection(conn, 1, gen_id)  # must not raise

    run = result.runs[NEW_RUN_ID]
    assert run.inconsistent is True
    assert run.engine_model == "default"  # first valid record's data survives


def test_run_started_with_malformed_shape_stays_available_but_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload={"engine": "not-an-object"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert has_run_metadata(result, NEW_RUN_ID) is True  # presence, not shape, decides
    assert result.runs[NEW_RUN_ID].inconsistent is True
    assert result.runs[NEW_RUN_ID].engine_provider is None


def test_run_started_engine_missing_model_field_marks_inconsistent(tmp_path):
    """Adversarial-review finding: a non-empty but incomplete engine object
    (present dict, missing the required `model` key) must be flagged --
    whole-subdict truthiness alone previously let this through unnoticed."""
    conn, gen_id = _setup(tmp_path)
    payload = _run_started_payload(engine={"provider": "claude-headless"})
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)

    assert has_run_metadata(result, NEW_RUN_ID) is True
    assert result.runs[NEW_RUN_ID].inconsistent is True
    assert result.runs[NEW_RUN_ID].engine_provider == "claude-headless"
    assert result.runs[NEW_RUN_ID].engine_model is None


def test_run_started_reviewer_missing_model_key_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    payload = _run_started_payload(reviewer={"provider": "qwen"})
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_started_reviewer_explicit_null_model_is_not_inconsistent(tmp_path):
    """Null reviewer.model is a documented valid case (doc 03 amendment) --
    must NOT be confused with a missing key."""
    conn, gen_id = _setup(tmp_path)
    payload = _run_started_payload(reviewer={"provider": "qwen", "model": None})
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)

    assert result.runs[NEW_RUN_ID].inconsistent is False
    assert result.runs[NEW_RUN_ID].reviewer_model is None


def test_run_started_budget_missing_field_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    budget = _run_started_payload()["budget"]
    del budget["proxy_pricing"]
    payload = _run_started_payload(budget=budget)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_finished_plausible_but_unknown_outcome_marks_inconsistent(tmp_path):
    """Adversarial-review finding: a plausible-looking but not-in-the-7-value
    closed set outcome string was previously accepted verbatim."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "NOT_A_REAL_OUTCOME", "detail": None})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True
    assert result.runs[NEW_RUN_ID].outcome is None


def test_unknown_run_finished_outcome_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": None, "detail": None})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_duplicate_run_finished_marks_inconsistent_and_keeps_first_outcome(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})
    _insert_evidence(conn, 1, gen_id, 3, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "HALTED", "detail": None})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].outcome == "COMPLETED"  # first one wins
    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_malformed_run_finished_then_valid_one_recovers_the_outcome(tmp_path):
    """Same review finding as RunStarted above, for RunFinished: a
    non-null-detail first record must not permanently hide a fully valid
    second COMPLETED record."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": "malformed-first"})
    _insert_evidence(conn, 1, gen_id, 3, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})

    result = build_projection(conn, 1, gen_id)  # must not raise

    run = result.runs[NEW_RUN_ID]
    assert run.inconsistent is True  # duplicate is still anomalous
    assert run.outcome == "COMPLETED"  # but the valid record's outcome won


def test_valid_run_finished_then_malformed_one_keeps_the_valid_outcome(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})
    _insert_evidence(conn, 1, gen_id, 3, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "HALTED", "detail": "malformed-second"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    run = result.runs[NEW_RUN_ID]
    assert run.inconsistent is True
    assert run.outcome == "COMPLETED"  # first valid outcome survives


def test_run_finished_non_null_detail_marks_inconsistent(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": "some exception text"})

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True
    assert result.runs[NEW_RUN_ID].outcome is None  # never trusted alongside a bad detail


def test_run_started_unexpected_top_level_key_marks_inconsistent(tmp_path):
    payload = _run_started_payload(extra_field="should not be here")
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert has_run_metadata(result, NEW_RUN_ID) is True
    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_started_unexpected_nested_key_marks_inconsistent(tmp_path):
    payload = _run_started_payload(
        engine={"provider": "claude-headless", "model": "default", "extra": 1})
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_started_malformed_digest_format_marks_inconsistent(tmp_path):
    """Wrong length/case, not just missing/empty -- the digest must match
    the 64-lowercase-hex format, mirroring the core runtime's own check."""
    payload = _run_started_payload(config_digest="A" * 64)  # uppercase
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True
    assert result.runs[NEW_RUN_ID].config_digest == "A" * 64  # preserved as observed, not fixed up


def test_run_started_digest_wrong_length_marks_inconsistent(tmp_path):
    payload = _run_started_payload(config_digest="a" * 10)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_started_budget_infinite_cost_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], hard_stop_proxy_cost_per_run_usd=float("inf"))
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True


def test_run_started_budget_nan_cost_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], hard_stop_proxy_cost_per_run_usd=float("nan"))
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    result = build_projection(conn, 1, gen_id)  # must not raise

    assert result.runs[NEW_RUN_ID].inconsistent is True


# ── Dashboard budget validation matches Doc 03 exactly (2026-08-21) ─────
def _assert_inconsistent_but_preserved(conn, gen_id, payload, run_id=NEW_RUN_ID):
    """Malformed observed values are preserved on the view, not fixed up
    or discarded -- only `inconsistent` signals the anomaly."""
    result = build_projection(conn, 1, gen_id)  # must not raise
    run = result.runs[run_id]
    assert run.inconsistent is True
    return run


def test_run_started_budget_zero_max_attempts_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], max_attempts_per_issue=0)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    run = _assert_inconsistent_but_preserved(conn, gen_id, payload)
    assert run.budget["max_attempts_per_issue"] == 0


def test_run_started_budget_negative_max_executions_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], max_executions_per_run=-3)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    run = _assert_inconsistent_but_preserved(conn, gen_id, payload)
    assert run.budget["max_executions_per_run"] == -3


def test_run_started_budget_fractional_max_attempts_marks_inconsistent(tmp_path):
    """Doc 03 requires an integer, not merely a number equal to an
    integer -- 3.5 (and even 3.0) must be rejected."""
    budget = dict(_run_started_payload()["budget"], max_attempts_per_issue=3.5)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_fractional_max_executions_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], max_executions_per_run=10.0)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_bool_max_attempts_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], max_attempts_per_issue=True)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_bool_max_executions_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], max_executions_per_run=False)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_bool_cost_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], hard_stop_proxy_cost_per_run_usd=True)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_zero_cost_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], hard_stop_proxy_cost_per_run_usd=0.0)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    run = _assert_inconsistent_but_preserved(conn, gen_id, payload)
    assert run.budget["hard_stop_proxy_cost_per_run_usd"] == 0.0


def test_run_started_budget_negative_cost_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], hard_stop_proxy_cost_per_run_usd=-1.5)
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    _assert_inconsistent_but_preserved(conn, gen_id, payload)


def test_run_started_budget_wrong_proxy_pricing_marks_inconsistent(tmp_path):
    budget = dict(_run_started_payload()["budget"], proxy_pricing="flat_rate")
    payload = _run_started_payload(budget=budget)
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID, payload=payload)

    run = _assert_inconsistent_but_preserved(conn, gen_id, payload)
    assert run.budget["proxy_pricing"] == "flat_rate"  # preserved, not fixed up


def test_run_started_budget_all_valid_values_stay_consistent(tmp_path):
    """No over-tightening: the exact valid shape from Doc 03 must never be
    flagged inconsistent."""
    conn, gen_id = _setup(tmp_path)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())

    result = build_projection(conn, 1, gen_id)

    assert result.runs[NEW_RUN_ID].inconsistent is False


# ── views.py: end-to-end through list_executions ────────────────────────
def test_list_executions_exposes_available_run_metadata(tmp_path):
    conn, gen_id = _setup(tmp_path)
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, "
        "updated_at) VALUES (1, ?, '2026-08-20T00:00:00Z')", (gen_id,),
    )
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})
    _insert_evidence(conn, 1, gen_id, 3, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 4, "IssueActivated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 5, "ExecutionSpawned", issue_id="42",
                     execution_id="42-e1", run_id=NEW_RUN_ID)

    page = list_executions(conn, 1, limit=50, offset=0)

    item = page["items"][0]
    assert item["runId"] == NEW_RUN_ID
    assert item["runMetadata"]["available"] is True
    assert item["runMetadata"]["engineProvider"] == "claude-headless"
    assert item["runMetadata"]["outcome"] == "COMPLETED"


def test_list_executions_renders_exact_fallback_text_for_legacy_run(tmp_path):
    conn, gen_id = _setup(tmp_path)
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, "
        "updated_at) VALUES (1, ?, '2026-08-20T00:00:00Z')", (gen_id,),
    )
    _insert_evidence(conn, 1, gen_id, 1, "IssueCreated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 2, "IssueActivated", issue_id="42")
    _insert_evidence(conn, 1, gen_id, 3, "ExecutionSpawned", issue_id="42",
                     execution_id="42-e1", run_id=LEGACY_RUN_ID)

    page = list_executions(conn, 1, limit=50, offset=0)

    item = page["items"][0]
    assert item["runMetadata"] == {
        "available": False, "message": RUN_METADATA_UNAVAILABLE,
    }
    # never blank/absent
    assert item["runMetadata"]["message"] == "run metadata unavailable (legacy/ambiguous)"


# ── views.py: list_runs (paginated /runs resource) ──────────────────────
def _with_checkpoint(conn, gen_id):
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, "
        "updated_at) VALUES (1, ?, '2026-08-20T00:00:00Z')", (gen_id,),
    )


def test_list_runs_shows_a_completed_run_with_full_metadata(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _with_checkpoint(conn, gen_id)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "COMPLETED", "detail": None})

    page = list_runs(conn, 1, limit=50, offset=0)

    assert page["total"] == 1
    run = page["items"][0]
    assert run["runId"] == NEW_RUN_ID
    assert run["engineProvider"] == "claude-headless"
    assert run["engineModel"] == "default"
    assert run["reviewerProvider"] == "qwen"
    assert run["reviewerModel"] == "qwen2.5-coder"
    assert run["budget"] == {
        "max_attempts_per_issue": 3, "max_executions_per_run": 10,
        "hard_stop_proxy_cost_per_run_usd": 15.0, "proxy_pricing": "api_list_rates",
    }
    assert run["configDigest"] == "a" * 64
    assert run["outcome"] == "COMPLETED"
    assert run["displayOutcome"] == "COMPLETED"


def test_list_runs_produces_a_visible_run_with_zero_executions(tmp_path):
    """Review requirement: a RunStarted followed by an early controlled
    failure (CHECKOUT_FAILED here) must still appear in /runs even though
    no ExecutionSpawned -- and therefore no execution row -- ever existed."""
    conn, gen_id = _setup(tmp_path)
    _with_checkpoint(conn, gen_id)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=NEW_RUN_ID,
                     payload={"outcome": "CHECKOUT_FAILED", "detail": None})

    runs_page = list_runs(conn, 1, limit=50, offset=0)
    executions_page = list_executions(conn, 1, limit=50, offset=0)

    assert runs_page["total"] == 1
    assert runs_page["items"][0]["outcome"] == "CHECKOUT_FAILED"
    assert executions_page["total"] == 0  # no execution ever existed for this run


def test_list_runs_covers_every_zero_execution_early_failure_outcome(tmp_path):
    for i, outcome in enumerate(
        ["CHECKOUT_FAILED", "REVIEWER_UNREACHABLE", "BASELINE_FAILED", "INGEST_FAILED"]
    ):
        run_id = f"run-2026082{i}T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa{i}"
        conn, gen_id = _setup(tmp_path / f"g{i}")
        _with_checkpoint(conn, gen_id)
        _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=run_id,
                         payload=_run_started_payload())
        _insert_evidence(conn, 1, gen_id, 2, "RunFinished", run_id=run_id,
                         payload={"outcome": outcome, "detail": None})

        page = list_runs(conn, 1, limit=50, offset=0)

        assert page["total"] == 1
        assert page["items"][0]["outcome"] == outcome
        assert list_executions(conn, 1, limit=50, offset=0)["total"] == 0


def test_list_runs_unresolved_run_says_no_controlled_finish_never_running(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _with_checkpoint(conn, gen_id)
    _insert_evidence(conn, 1, gen_id, 1, "RunStarted", run_id=NEW_RUN_ID,
                     payload=_run_started_payload())
    # No RunFinished at all -- e.g. abrupt death, or simply still in progress.

    page = list_runs(conn, 1, limit=50, offset=0)

    run = page["items"][0]
    assert run["outcome"] is None
    assert run["displayOutcome"] == RUN_NO_CONTROLLED_FINISH_OBSERVED
    assert run["displayOutcome"] == "no controlled finish observed"
    assert "running" not in run["displayOutcome"].lower()


def test_list_runs_is_paginated(tmp_path):
    conn, gen_id = _setup(tmp_path)
    _with_checkpoint(conn, gen_id)
    for i in range(3):
        run_id = f"run-2026082{i}T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa{i}"
        _insert_evidence(conn, 1, gen_id, i * 2 + 1, "RunStarted", run_id=run_id,
                         payload=_run_started_payload())

    page = list_runs(conn, 1, limit=2, offset=0)

    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["limit"] == 2
    assert page["offset"] == 0
