"""ADR-30 RED 5: run-request API is strict, exact, and race-safe.

See docs/plans/dashboard-issue-run-control-failing-tests.md RED 5 and
docs/31-dashboard-issue-run-control-outcome-matrix.md "API, UI, and
security".
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig

_VALID_CONFIG_YAML = """
project:
  name: T
  repository: {repository!r}
  branch: agent-work
  issues_file: Issues.md
  validation:
    commands: ["echo ok"]
engine:
  provider: claude-headless
  auth_mode: subscription
  model: default
  max_turns: 30
  timeout_seconds: 1800
reviewer:
  provider: qwen
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
budget:
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  hard_stop_proxy_cost_per_run_usd: 15.0
  proxy_pricing: api_list_rates
experiment:
  sample_size: 20
  attempt1_success_min: 0.3
  cost_per_shipped_issue_max_usd: 3.0
billing:
  posture: p
  headless_split_status: paused
  verified_on: '2026-07-10'
  reverify_at: x
"""


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1")


def _git(cwd, *args):
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"git {args} failed: {p.stderr}")


def _git_worktree(tmp_path, name="repo"):
    # doc 33 Part A: launching requires a clean git worktree, so the fixture is
    # a real (initially empty) git repo; _register_ready commits its files so
    # the target is clean when the run-request worktree preflight runs.
    repo = tmp_path / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "agent-work")
    _git(repo, "config", "core.autocrlf", "false")
    return repo


def _register_ready(client, tmp_path, *, issues_text="## a: A\nbody\n\n## b: B\nbody\n",
                    name="repo", issue_states=None):
    """Registers a repository with a valid config + issues file (committed so
    the worktree is clean), and publishes a READY read model with the given
    issue states (default: both non-terminal PENDING) so run-plan admission is
    exercisable end to end."""
    repo = _git_worktree(tmp_path, name)
    (repo / "Issues.md").write_text(issues_text, encoding="utf-8", newline="")
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")

    created = client.post(
        "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
    )
    assert created.status_code == 201, created.text
    repo_id = created.json()["id"]

    conn = client.app.state.db
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status) "
        "VALUES (?, 1, 'READY')", (repo_id,),
    )
    for iid, state in (issue_states or {}).items():
        conn.execute(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, updated_at) "
            "VALUES (?, 1, ?, ?, '2026-08-30T00:00:00Z')", (repo_id, iid, state),
        )

    digest = client.get(f"/api/repositories/{repo_id}/configured-issues").json()["issuesFileRevision"]
    return repo_id, digest


def test_run_selected_requires_nonempty_unique_issue_ids_and_revision(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": [], "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert resp.json()["emptySelection"] is True


def test_run_all_rejects_client_supplied_issue_ids(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "issueIds": ["a"], "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "RUN_ALL_REJECTS_ISSUE_IDS"


def test_unknown_request_fields_are_422(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "expectedIssuesDigest": digest, "executable": "evil.exe"},
    )
    assert resp.status_code == 422


def test_oversized_issue_count_id_and_body_are_rejected_before_planning(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)

    too_many = [f"id{i}" for i in range(501)]
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": too_many, "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TOO_MANY_ISSUE_IDS"

    resp2 = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": ["x" * 201], "expectedIssuesDigest": digest},
    )
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "ISSUE_ID_TOO_LONG"


def test_issue_revision_conflict_queues_nothing(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    stale = "0" * 64
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": stale},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "ISSUES_REVISION_CONFLICT"
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []


def test_selected_refusal_returns_all_blockers_in_typed_envelope(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(
        client, tmp_path, issues_text="## a: A\nDepends-On: missing1, missing2\nbody\n",
    )
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": ["a"], "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    reported = {b["missingDependencyId"] for b in body["blockers"]}
    assert reported == {"missing1", "missing2"}


def test_selected_terminal_refusal_queues_nothing(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(
        client, tmp_path, issue_states={"a": "DONE"},
    )
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "SELECTED", "issueIds": ["a"], "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "SELECTION_REFUSED"
    assert any(t["issueId"] == "a" for t in resp.json()["error"]["details"]["terminalSelected"])
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []


def test_run_all_returns_terminal_exclusion_summary(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path, issue_states={"a": "DONE"})
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 200
    excluded = resp.json()["excluded"]
    assert {(e["issueId"], e["state"]) for e in excluded} == {("a", "DONE")}


def test_run_all_zero_result_returns_noop_without_queue_or_process(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(
        client, tmp_path, issues_text="## a: A\nbody\n",
        issue_states={"a": "DONE"},
    )
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 201
    assert resp.json().get("noop") is True
    assert client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []


def test_api_rechecks_current_event_state_not_source_status(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(
        client, tmp_path, issues_text="## a: A\nSTATUS: DONE\nbody\n",
    )  # no event state at all for 'a' -> NOT_INGESTED, still runnable
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": ["a"], "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True  # STATUS: DONE text never makes it terminal


def test_api_never_accepts_executable_config_or_issue_path_from_run_body(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "expectedIssuesDigest": digest,
              "configPath": "C:/evil/config.yaml", "executable": "evil.exe",
              "issuesPath": "C:/evil/Issues.md"},
    )
    assert resp.status_code == 422  # extra=forbid rejects all of them


def test_non_loopback_host_and_origin_cannot_enqueue_run(tmp_path):
    app_client = _client(tmp_path)
    repo_id, digest = _register_ready(app_client, tmp_path)

    evil_host_client = TestClient(app_client.app, base_url="http://evil.example.com")
    resp = evil_host_client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 403

    resp2 = app_client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "k2", "Origin": "http://evil.example.com"},
    )
    assert resp2.status_code == 403
    assert app_client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"] == []


def test_cors_remains_disabled_for_run_routes(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert "access-control-allow-origin" not in resp.headers


def test_security_headers_wrap_success_and_failure_responses(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    ok = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
    )
    assert ok.headers["x-content-type-options"] == "nosniff"
    bad = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "BOGUS", "expectedIssuesDigest": digest},
    )
    assert bad.status_code == 422
    assert bad.headers["x-content-type-options"] == "nosniff"


def test_injection_shaped_issue_id_remains_data(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    evil_id = "a'; DROP TABLE repositories; --"
    resp = client.post(
        f"/api/repositories/{repo_id}/run-plans",
        json={"mode": "SELECTED", "issueIds": [evil_id], "expectedIssuesDigest": digest},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert evil_id in resp.json()["unknownIds"]
    # the repositories table must still exist and be queryable
    assert client.get(f"/api/repositories/{repo_id}").status_code == 200


def test_html_shaped_issue_text_is_escaped_in_api_consumer_contract(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(
        client, tmp_path, issues_text="## a: <script>alert(1)</script>\nbody\n",
    )
    resp = client.get(f"/api/repositories/{repo_id}/configured-issues")
    assert resp.status_code == 200
    # JSON is not HTML -- the raw text is returned as data; the UI (RED 8) is
    # responsible for rendering it as text, never innerHTML.
    assert resp.json()["issues"][0]["title"] == "<script>alert(1)</script>"
    assert resp.headers["content-type"].startswith("application/json")


def test_run_api_does_not_persist_environment_or_secrets(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    resp = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 201
    conn = client.app.state.db
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_commands)")}
    assert "environment" not in columns and "env" not in columns and "secret" not in columns


# ── idempotency ──────────────────────────────────────────────────────────

def test_idempotency_key_repeat_returns_existing_command(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    first = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "same-key"},
    )
    second = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "ALL", "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "same-key"},
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get(f"/api/repositories/{repo_id}/run-commands").json()["commands"]) == 1


def test_idempotency_key_reused_with_different_content_is_rejected(tmp_path):
    client = _client(tmp_path)
    repo_id, digest = _register_ready(client, tmp_path)
    first = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "SELECTED", "issueIds": ["a"], "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "same-key"},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/repositories/{repo_id}/run-commands",
        json={"mode": "SELECTED", "issueIds": ["b"], "expectedIssuesDigest": digest},
        headers={"Idempotency-Key": "same-key"},
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
