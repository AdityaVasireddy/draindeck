"""Unit 15 (docs/27 SS13.2/SS14): dedicated security-acceptance tests not
already covered by test_app_health.py (Host/Origin/CSP headers),
test_app_repositories_api.py (body-size limit), test_api_queries.py
(sort/filter allowlists, offset caps), or test_artifacts.py (transcript
path containment) -- encoded/traversal-like path segments on ID-lookup
routes, and free-text content (never a filesystem path, so not already
covered by artifact containment) round-tripping safely as JSON rather
than being reflected into any HTML/templated response.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig
from draindeck_dashboard.db import connect_and_init


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1")


def _register(client: TestClient, tmp_path: Path, name: str = "repo") -> int:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    resp = client.post("/api/repositories", json={"projectPath": str(repo)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- encoded/traversal-like path segments on ID-lookup routes ---
# `execution_id`/`issue_id`/`evidence_id` are always DB lookup keys, never
# concatenated into a filesystem path (the actual artifact path comes from
# a DB-stored value that already goes through artifacts.py's containment
# check) -- a traversal-shaped id must therefore just miss the lookup and
# 404, never 500 or leak filesystem state.

def test_traversal_shaped_execution_id_on_transcript_route_is_404_not_500(tmp_path):
    client = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    for evil_id in ["..%2F..%2Fetc%2Fpasswd", "../../etc/passwd", "..\\..\\windows\\system32"]:
        resp = client.get(f"/api/repositories/{repo_id}/executions/{evil_id}/transcript")
        assert resp.status_code == 404, f"{evil_id!r} -> {resp.status_code}: {resp.text[:200]}"


def test_traversal_shaped_execution_id_on_diff_route_is_404_not_500(tmp_path):
    client = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    resp = client.get(f"/api/repositories/{repo_id}/executions/..%2F..%2Fetc%2Fpasswd/diff")
    assert resp.status_code == 404


def test_traversal_shaped_issue_id_on_detail_route_is_404_not_500(tmp_path):
    client = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    resp = client.get(f"/api/repositories/{repo_id}/issues/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code == 404


def test_traversal_shaped_evidence_id_on_detail_route_is_422_or_404_not_500(tmp_path):
    client = _client(tmp_path)
    repo_id = _register(client, tmp_path)
    resp = client.get(f"/api/repositories/{repo_id}/evidence/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (404, 422), resp.text


# --- free-text content (issue titles, project paths) round-trips as JSON,
# never reflected into an HTML/templated response ---

def test_issue_title_with_script_tag_round_trips_as_escaped_json_not_html(tmp_path):
    db_path = tmp_path / "dashboard.sqlite3"
    conn = connect_and_init(db_path)
    cur = conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES ('C:/repo', 'C:/repo/events.jsonl', 'c:/repo/events.jsonl', '2026-08-23T00:00:00Z')"
    )
    repo_id = cur.lastrowid
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 1, 'lineage', 1, 1, 1, '2026-08-23T00:00:00Z')",
        (repo_id,),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', '2026-08-23T00:00:00Z')",
        (repo_id, gen_id),
    )
    evil_title = "<script>alert(document.cookie)</script>"
    conn.execute(
        "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, title, "
        "updated_at) VALUES (?, ?, 'i1', 'OPEN', ?, '2026-08-23T00:00:00Z')",
        (repo_id, gen_id, evil_title),
    )
    conn.commit()
    conn.close()

    client = TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1")
    resp = client.get("/api/issues", params={"limit": 50})
    # A JSON response is safe against this content by construction as long
    # as (a) the Content-Type is application/json -- browsers never
    # execute a JSON body as HTML/script regardless of its contents -- and
    # (b) the value round-trips through proper JSON string quoting rather
    # than being truncated, corrupted, or used to break out of the string
    # literal. Stripping/escaping "<script>" itself inside a JSON string
    # would be non-standard and is not what makes a JSON API safe; the
    # frontend's own textContent-only rendering (verified in Units 7-14)
    # is the actual XSS boundary once this value reaches the browser.
    assert "application/json" in resp.headers["content-type"]
    assert resp.json()["items"][0]["title"] == evil_title

    search_resp = client.get("/api/search", params={"q": "alert", "limit": 10})
    assert search_resp.status_code == 200
    assert "application/json" in search_resp.headers["content-type"]
