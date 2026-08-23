"""Unit 5 (docs/27 SS7): the additive REST route surface over Units 3/4's
attention/query layer. Thin routes only -- no business SQL here; behavior
is already covered by test_api_queries.py/test_attention.py/test_search.py.
This file proves the routes are wired, return the right shapes/status
codes, and don't disturb existing endpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
    return TestClient(app, base_url="http://127.0.0.1"), app


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


def _register(client, tmp_path, name="repo"):
    repo = _git_worktree(tmp_path, name)
    resp = client.post("/api/repositories", json={"projectPath": str(repo)})
    return resp.json()["id"]


# --- overview / repository-summaries ---

def test_overview_with_no_repositories(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repositories"]["total"] == 0
    assert "basis" in body


def test_repository_summaries_lists_registered_repository(tmp_path):
    client, _ = _client(tmp_path)
    _register(client, tmp_path, "alpha")
    resp = client.get("/api/repository-summaries")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["displayName"] == "alpha"


def test_repository_summaries_rejects_unknown_sort(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/repository-summaries?sort=bogus")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_SORT"


# --- attention ---

def test_attention_lists_current_conditions(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 1, 0, 'AVAILABLE', '2026-08-23T00:00:00Z') "
        "ON CONFLICT(repository_id) DO UPDATE SET halted_oversized = 1",
        (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    from draindeck_dashboard import attention
    attention.reconcile_repository_conditions(
        app.state.db, repo_id, attention.derive_repository_conditions(app.state.db, repo_id))

    resp = client.get("/api/attention")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "INDEXING_HALTED_OVERSIZED"


def test_attention_status_filter(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/attention?status=resolved")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# --- LEASE_UNCLAIMED 10-second "no startup flash" visibility gate (docs/27 SS6.4) ---

def _insert_condition(app, *, kind, severity, first_detected_at, resolved_at=None,
                      condition_key=None, occurrence=1):
    app.state.db.execute(
        "INSERT INTO attention_conditions (condition_key, occurrence, repository_id, "
        "identity_generation_id, kind, severity, subject_type, subject_id, message, target_url, "
        "first_detected_at, last_detected_at, resolved_at) "
        "VALUES (?, ?, NULL, NULL, ?, ?, NULL, NULL, ?, '/about', ?, ?, ?)",
        (condition_key or kind, occurrence, kind, severity, f"{kind} message",
         first_detected_at, first_detected_at, resolved_at),
    )


def test_lease_unclaimed_hidden_within_the_first_10_seconds(tmp_path):
    client, app = _client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_condition(app, kind="LEASE_UNCLAIMED", severity="warning",
                      first_detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/attention?status=current")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_lease_unclaimed_visible_once_10_seconds_have_elapsed(tmp_path):
    client, app = _client(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(seconds=15)
    _insert_condition(app, kind="LEASE_UNCLAIMED", severity="warning",
                      first_detected_at=old.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/attention?status=current")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["kind"] == "LEASE_UNCLAIMED"


def test_lease_stale_is_never_delayed_by_the_lease_unclaimed_gate(tmp_path):
    client, app = _client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_condition(app, kind="LEASE_STALE", severity="critical",
                      first_detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/attention?status=current")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert resp.json()["items"][0]["kind"] == "LEASE_STALE"


def test_a_resolved_lease_unclaimed_row_is_never_hidden_by_the_gate_regardless_of_age(tmp_path):
    """The gate exists only to prevent a live flash to an operator --
    already-resolved history is never a flash risk and must remain
    visible under status=resolved/all regardless of how young it was."""
    client, app = _client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_condition(app, kind="LEASE_UNCLAIMED", severity="warning",
                      first_detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      resolved_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/attention?status=resolved")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def test_overview_attention_count_respects_the_same_lease_unclaimed_gate_as_the_list_endpoint(tmp_path):
    """/api/overview's attention aggregate must never disagree with
    /api/attention about whether a fresh LEASE_UNCLAIMED condition is
    visible yet -- both read the same attention_conditions table and both
    are shown to the same operator."""
    client, app = _client(tmp_path)
    now = datetime.now(timezone.utc)
    _insert_condition(app, kind="LEASE_UNCLAIMED", severity="warning",
                      first_detected_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["attention"]["current"] == 0
    assert body["attention"]["warning"] == 0


def test_overview_attention_count_includes_lease_unclaimed_once_10_seconds_have_elapsed(tmp_path):
    client, app = _client(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(seconds=15)
    _insert_condition(app, kind="LEASE_UNCLAIMED", severity="warning",
                      first_detected_at=old.strftime("%Y-%m-%dT%H:%M:%SZ"))
    resp = client.get("/api/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["attention"]["current"] == 1
    assert body["attention"]["warning"] == 1


# --- search ---

def test_search_endpoint_returns_grouped_results(tmp_path):
    client, _ = _client(tmp_path)
    _register(client, tmp_path, "findme")
    resp = client.get("/api/search?q=findme")
    assert resp.status_code == 200
    body = resp.json()
    assert body["repositories"][0]["label"] == "findme"


def test_search_endpoint_rejects_short_query(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/search?q=a")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "QUERY_TOO_SHORT"


def test_search_endpoint_requires_q_param(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/search")
    assert resp.status_code == 422  # FastAPI's own required-param 422, not our envelope


# --- cross-repository explorers ---

def test_cross_repository_issues_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    # A repository-scoped request now requires a READY read_model_state
    # row (Unit 16: INDEX_PREPARING gating) -- a real backfill would have
    # produced one before issue_views ever had a row in the first place.
    app.state.db.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, 1, 'READY', 0, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id,),
    )
    resp = client.get("/api/issues")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["issueId"] == "i1"

    scoped = client.get(f"/api/issues?repositoryId={repo_id}")
    assert scoped.status_code == 200
    assert len(scoped.json()["items"]) == 1


def test_cross_repository_executions_group_by_issue_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, updated_at) VALUES (?, 1, 'e1', 'i1', 'ACCEPTED', '2026-08-23T00:00:00Z')",
        (repo_id,),
    )
    resp = client.get("/api/executions?groupBy=issue")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["issue"]["issueId"] == "i1"


def test_cross_repository_evidence_keyset_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "stored_at) VALUES (?, 1, 'c1', 'OK', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get("/api/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["cursor"] == "c1"
    assert "offset" not in body


# --- single-entity detail routes ---

def test_repository_overview_endpoint(tmp_path):
    client, _ = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    resp = client.get(f"/api/repositories/{repo_id}/overview")
    assert resp.status_code == 200
    assert resp.json()["registration"]["id"] == repo_id


def test_repository_overview_attention_count_matches_repository_summaries(tmp_path):
    """Unit 16 contract-honesty finding: Repository Overview's attention
    count used to be live-recomputed while repository-summaries read the
    persisted table -- they could genuinely disagree. Both must now read
    the exact same source and therefore always agree."""
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO attention_conditions (condition_key, occurrence, repository_id, "
        "identity_generation_id, kind, severity, subject_type, subject_id, message, target_url, "
        "first_detected_at, last_detected_at, resolved_at) VALUES ('k1', 1, ?, NULL, "
        "'ISSUE_NEEDS_DECOMPOSITION', 'warning', 'issue', 'i1', 'm', '/x', "
        "'2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id,),
    )
    overview_resp = client.get(f"/api/repositories/{repo_id}/overview")
    summaries_resp = client.get("/api/repository-summaries")
    overview_count = overview_resp.json()["attention"]["current"]
    summary_count = next(
        r["attentionCount"] for r in summaries_resp.json()["items"] if r["id"] == repo_id
    )
    assert overview_count == summary_count == 1


def test_repository_overview_unknown_id_is_404(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/repositories/999/overview")
    assert resp.status_code == 404


def test_issue_detail_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, 1, 'READY', 0, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/issues/i1")
    assert resp.status_code == 200
    assert resp.json()["issueId"] == "i1"

    missing = client.get(f"/api/repositories/{repo_id}/issues/does-not-exist")
    assert missing.status_code == 404

    bad_repo = client.get("/api/repositories/notanint/issues/i1")
    assert bad_repo.status_code == 422


# --- execution detail: nested run metadata (Unit 16 contract-honesty finding) ---

def _seed_generation_checkpoint_and_ready(app, repo_id, gen_id=1):
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (gen_id, repo_id),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id, gen_id),
    )
    app.state.db.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'READY', 0, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id, gen_id),
    )


def test_execution_detail_includes_full_run_metadata_when_a_run_exists(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    _seed_generation_checkpoint_and_ready(app, repo_id)
    app.state.db.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, engine_provider, "
        "engine_model, reviewer_provider, reviewer_model, budget_json, config_digest, outcome, "
        "inconsistent, updated_at) VALUES (?, 1, 'r1', 'anthropic', 'claude', 'qwen', NULL, "
        "'{\"max_attempts_per_issue\": 1}', 'digest', 'COMPLETED', 0, '2026-08-23T00:00:00Z')",
        (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, run_id, updated_at) VALUES (?, 1, 'e1', 'i1', 'ACCEPTED', 'r1', "
        "'2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/executions/e1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runMetadata"]["available"] is True
    assert body["runMetadata"]["runId"] == "r1"
    assert body["runMetadata"]["engineProvider"] == "anthropic"
    assert body["runMetadata"]["outcome"] == "COMPLETED"
    assert body["runMetadata"]["budget"] == {"max_attempts_per_issue": 1}


def test_execution_detail_run_metadata_unavailable_exact_fallback_when_execution_has_no_run_id(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    _seed_generation_checkpoint_and_ready(app, repo_id)
    app.state.db.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, run_id, updated_at) VALUES (?, 1, 'e1', 'i1', 'ACCEPTED', NULL, "
        "'2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/executions/e1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["runMetadata"] == {
        "available": False, "message": "run metadata unavailable (legacy/ambiguous)",
    }


def test_execution_detail_run_metadata_unavailable_when_run_id_set_but_no_run_views_row(tmp_path):
    """A legacy/ambiguous case: the execution names a run_id, but no
    RunStarted was ever observed for it (or it belongs to a different
    generation) -- never fabricate metadata, use the exact same fallback."""
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    _seed_generation_checkpoint_and_ready(app, repo_id)
    app.state.db.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, run_id, updated_at) VALUES (?, 1, 'e1', 'i1', 'ACCEPTED', "
        "'ghost-run', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/executions/e1")
    assert resp.status_code == 200
    assert resp.json()["runMetadata"] == {
        "available": False, "message": "run metadata unavailable (legacy/ambiguous)",
    }


# --- INDEX_PREPARING gating on repository-scoped detail/topology routes ---

def test_issue_detail_returns_503_index_preparing_when_repo_not_ready(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    # No read_model_state row -- repository never got past its first tick.
    resp = client.get(f"/api/repositories/{repo_id}/issues/i1")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "INDEX_PREPARING"


def test_run_detail_returns_503_index_preparing_when_repo_not_ready(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/runs/r1")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "INDEX_PREPARING"


def test_execution_detail_returns_503_index_preparing_when_repo_not_ready(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/executions/e1")
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "INDEX_PREPARING"


def test_timeline_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, issue_id, payload_json, stored_at) VALUES (?, 1, 'c1', 'OK', 1, "
        "'IssueCreated', 'i1', '{\"secret\":true}', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/issues/i1/timeline")
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert "payload" not in item and "payloadJson" not in item


def test_topology_endpoint(tmp_path):
    client, app = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    app.state.db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (1, ?, 1, 'l', 1, 1, 1, '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, 1, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
        "VALUES (?, 1, 'i1', 'DONE', '2026-08-23T00:00:00Z')", (repo_id,),
    )
    app.state.db.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, 1, 'READY', 0, '2026-08-23T00:00:00Z', '2026-08-23T00:00:00Z', NULL)",
        (repo_id,),
    )
    resp = client.get(f"/api/repositories/{repo_id}/issues/i1/topology")
    assert resp.status_code == 200
    body = resp.json()
    assert "nodes" in body and "edges" in body and "truncated" in body


# --- existing endpoints/contracts unchanged ---

def test_existing_repositories_endpoint_shape_unchanged(tmp_path):
    client, _ = _client(tmp_path)
    _register(client, tmp_path)
    resp = client.get("/api/repositories")
    assert resp.status_code == 200
    assert "repositories" in resp.json()


def test_unknown_api_route_is_still_404(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.get("/api/totally-made-up-route")
    assert resp.status_code == 404
