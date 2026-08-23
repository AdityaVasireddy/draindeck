"""Unit 5 (docs/27 SS7): the additive REST route surface over Units 3/4's
attention/query layer. Thin routes only -- no business SQL here; behavior
is already covered by test_api_queries.py/test_attention.py/test_search.py.
This file proves the routes are wired, return the right shapes/status
codes, and don't disturb existing endpoints.
"""
from __future__ import annotations

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
    resp = client.get(f"/api/repositories/{repo_id}/issues/i1")
    assert resp.status_code == 200
    assert resp.json()["issueId"] == "i1"

    missing = client.get(f"/api/repositories/{repo_id}/issues/does-not-exist")
    assert missing.status_code == 404

    bad_repo = client.get("/api/repositories/notanint/issues/i1")
    assert bad_repo.status_code == 422


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
