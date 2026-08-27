"""Unit 4: proxyCost is attached additively to every placement endpoint
(spec §3.3) and is absent from the excluded endpoints (Evidence/Search/
Attention). Existing response fields are unchanged (backward compatibility).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _client(tmp_path: Path):
    cfg = DashboardConfig(db_path=str(tmp_path / "d.sqlite3"),
                          observer_executable=str(tmp_path / "draindeck.exe"))
    app = create_app(cfg)
    return TestClient(app, base_url="http://127.0.0.1"), app


def _seed(app):
    db = app.state.db
    repo = str(Path(app.state.config.db_path).parent / "repo")
    db.execute(
        "INSERT INTO repositories (id, project_path, log_path, canonical_log_path, created_at) "
        "VALUES (1, ?, NULL, NULL, '2026-08-26T00:00:00Z')", (repo,))
    db.execute(
        "INSERT INTO identity_generations (id, repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (7, 1, 1, 'l', 1, 1, 1, '2026-08-26T00:00:00Z')")
    db.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, availability, updated_at) "
        "VALUES (1, 7, 'AVAILABLE', '2026-08-26T00:00:00Z')")
    db.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (1, 7, 'READY', 9, '2026-08-26T00:00:00Z', '2026-08-26T00:00:01Z', NULL)")
    # Issue 42 DONE with two attempts: one metered ($1.00), one missing cost.
    db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, title, "
        "inconsistent, last_event_id, updated_at) "
        "VALUES (1, 7, '42', 'DONE', 'fix', 0, 5, '2026-08-26T00:00:00Z')")
    _exec(db, "42-e1", issue_id="42", run_id="run-1", micro=1_000_000, cost_valid=1,
          in_tok=100, out_tok=50, tokens_valid=1)
    _exec(db, "42-e2", issue_id="42", run_id="run-1", micro=None, cost_valid=0)
    db.execute(
        "INSERT INTO run_views (repository_id, identity_generation_id, run_id, engine_provider, "
        "engine_model, reviewer_provider, reviewer_model, budget_json, config_digest, outcome, "
        "inconsistent, last_event_id, observed_started_at, observed_finished_at, updated_at) "
        "VALUES (1, 7, 'run-1', 'claude', 'm', 'qwen', NULL, NULL, NULL, 'COMPLETED', 0, 5, "
        "'2026-08-26T00:00:00Z', '2026-08-26T00:00:01Z', '2026-08-26T00:00:01Z')")


def _exec(db, execution_id, *, issue_id=None, run_id=None, micro=None, cost_valid=0,
          in_tok=None, out_tok=None, tokens_valid=0):
    db.execute(
        "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
        "issue_id, state, inconsistent, last_event_id, run_id, proxy_micro_usd, cost_valid, "
        "input_tokens, output_tokens, tokens_valid, updated_at) "
        "VALUES (1, 7, ?, ?, 'DONE', 0, 5, ?, ?, ?, ?, ?, ?, '2026-08-26T00:00:00Z')",
        (execution_id, issue_id, run_id, micro, cost_valid, in_tok, out_tok, tokens_valid))


def _assert_proxy_shape(pc):
    assert pc["basis"] == "ENGINE_REPORTED_API_LIST_RATE_PROXY"
    for k in ("observedMicroUsd", "observedUsd", "completeness", "meteredExecutions",
              "totalExecutions", "missingCostExecutions", "inputTokensObserved",
              "outputTokensObserved", "tokenMeteredExecutions"):
        assert k in pc


def test_overview_has_global_cost_average_and_top(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    body = client.get("/api/overview").json()
    _assert_proxy_shape(body["proxyCost"])
    assert body["proxyCost"]["observedMicroUsd"] == 1_000_000
    assert body["proxyCost"]["completeness"] == "PARTIAL"
    avg = body["averageProxyCostPerCompletedIssue"]
    assert avg["completedIssues"] == 1
    assert avg["observedMicroUsd"] == 1_000_000
    assert avg["observed"] is True  # partial -> Observed average
    assert body["topCostIssues"][0]["issueId"] == "42"


def test_repository_overview_has_cost_and_average(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    body = client.get("/api/repositories/1/overview").json()
    _assert_proxy_shape(body["proxyCost"])
    assert body["proxyCost"]["totalExecutions"] == 2
    assert body["averageProxyCostPerCompletedIssue"]["completedIssues"] == 1


def test_cross_repo_issues_have_per_issue_cost(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    body = client.get("/api/issues").json()
    item = next(i for i in body["items"] if i["issueId"] == "42")
    _assert_proxy_shape(item["proxyCost"])
    assert item["proxyCost"]["observedMicroUsd"] == 1_000_000
    assert item["proxyCost"]["completeness"] == "PARTIAL"


def test_issues_cost_sort_places_unavailable_last(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    # add a second issue with no metered cost
    app.state.db.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, title, "
        "inconsistent, last_event_id, updated_at) "
        "VALUES (1, 7, '99', 'ACTIVE', 't', 0, 1, '2026-08-26T00:00:00Z')")
    _exec(app.state.db, "99-e1", issue_id="99", micro=None, cost_valid=0)
    body = client.get("/api/issues?sort=cost&direction=desc").json()
    ids = [i["issueId"] for i in body["items"]]
    assert ids[0] == "42"      # highest observed cost first
    assert ids[-1] == "99"     # UNAVAILABLE last


def test_issue_detail_has_cost_and_attempt_breakdown(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    body = client.get("/api/repositories/1/issues/42").json()
    _assert_proxy_shape(body["proxyCost"])
    assert body["proxyCost"]["totalExecutions"] == 2
    attempts = {a["executionId"]: a for a in body["executionAttempts"]}
    assert attempts["42-e1"]["proxyCost"]["observedMicroUsd"] == 1_000_000
    assert attempts["42-e2"]["proxyCost"]["completeness"] == "UNAVAILABLE"


def test_cross_repo_runs_and_run_detail_have_cost(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    listing = client.get("/api/runs").json()
    run_item = next(i for i in listing["items"] if i["runId"] == "run-1")
    _assert_proxy_shape(run_item["proxyCost"])
    assert run_item["proxyCost"]["observedMicroUsd"] == 1_000_000

    detail = client.get("/api/repositories/1/runs/run-1").json()
    _assert_proxy_shape(detail["proxyCost"])
    assert detail["proxyCost"]["totalExecutions"] == 2


def test_cross_repo_executions_and_detail_have_cost(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    listing = client.get("/api/executions").json()
    e1 = next(i for i in listing["items"] if i["executionId"] == "42-e1")
    assert e1["proxyCost"]["observedMicroUsd"] == 1_000_000
    e2 = next(i for i in listing["items"] if i["executionId"] == "42-e2")
    assert e2["proxyCost"]["completeness"] == "UNAVAILABLE"

    detail = client.get("/api/repositories/1/executions/42-e1").json()
    assert detail["proxyCost"]["observedMicroUsd"] == 1_000_000


def test_executions_cost_sort_unavailable_last(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    body = client.get("/api/executions?sort=cost&direction=desc").json()
    ids = [i["executionId"] for i in body["items"]]
    assert ids[0] == "42-e1"
    assert ids[-1] == "42-e2"


def _ev(db, event_id, event_type, *, issue_id=None, execution_id=None, run_id=None, payload=None):
    import json
    db.execute(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, schema_version, issue_id, execution_id, run_id, event_ts, "
        "payload_json, record_hash, length_bytes, stored_at) "
        "VALUES (1, 7, ?, 'OK', ?, ?, 1, ?, ?, ?, '2026-08-26T00:00:00Z', ?, 'h', 1, "
        "'2026-08-26T00:00:00Z')",
        (f"c{event_id}", event_id, event_type, issue_id, execution_id, run_id,
         json.dumps(payload) if payload is not None else None))


def test_repo_scoped_lists_have_cost(tmp_path):
    # The repo-scoped list endpoints project from OK EVIDENCE (build_projection),
    # not the read-model tables, so seed evidence for issue 42's attempts.
    client, app = _client(tmp_path)
    _seed(app)
    db = app.state.db
    _ev(db, 1, "IssueCreated", issue_id="42", payload={"title": "fix"})
    _ev(db, 2, "ExecutionSpawned", issue_id="42", execution_id="x1", run_id="run-1")
    _ev(db, 3, "ExecutionFinished", execution_id="x1",
        payload={"usage": {"input_tokens": 100, "output_tokens": 50, "dollars": 1.0}})
    _ev(db, 4, "ExecutionSpawned", issue_id="42", execution_id="x2", run_id="run-1")
    _ev(db, 5, "ExecutionFinished", execution_id="x2", payload={})
    _ev(db, 6, "RunStarted", run_id="run-1", payload={})  # surfaces the run in list_runs

    issues = client.get("/api/repositories/1/issues").json()
    assert issues["items"][0]["proxyCost"]["observedMicroUsd"] == 1_000_000
    assert issues["items"][0]["proxyCost"]["completeness"] == "PARTIAL"
    execs = client.get("/api/repositories/1/executions").json()
    assert any(i["proxyCost"]["completeness"] == "UNAVAILABLE" for i in execs["items"])
    runs = client.get("/api/repositories/1/runs").json()
    assert runs["items"][0]["proxyCost"]["observedMicroUsd"] == 1_000_000


def test_excluded_endpoints_have_no_proxy_cost(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    for url in ("/api/evidence", "/api/repositories/1/evidence", "/api/attention",
                "/api/search?q=42"):
        body = client.get(url).json()
        assert "proxyCost" not in body
        for item in body.get("items", []):
            assert "proxyCost" not in item


def test_existing_fields_unchanged_backward_compat(tmp_path):
    client, app = _client(tmp_path)
    _seed(app)
    issue = client.get("/api/repositories/1/issues/42").json()
    # pre-existing keys still present and unchanged
    assert issue["issueId"] == "42"
    assert issue["state"] == "DONE"
    assert issue["title"] == "fix"
    assert issue["inconsistent"] is False
