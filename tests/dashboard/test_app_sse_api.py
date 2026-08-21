"""Phase 5 acceptance: /api/events endpoint wiring -- headers, Last-Event-ID
resume precedence, and a resync response (which terminates after one
event, so it is safe to read as a normal finite response body)."""
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


def test_events_endpoint_has_sse_headers_and_resyncs_over_limit_cursor(tmp_path, monkeypatch):
    app = create_app(_cfg(tmp_path))
    from draindeck_dashboard import sse
    monkeypatch.setattr(sse, "REPLAY_CAP", 1)
    conn = app.state.db
    for i in range(5):
        conn.execute(
            "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
            "VALUES (1, 'evidence', ?, '2026-08-20T00:00:00Z')",
            (str(i),),
        )

    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/events?after=0")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert "CHANGE_RESYNC_REQUIRED" in resp.text


def test_last_event_id_header_takes_precedence_over_query_param(tmp_path, monkeypatch):
    app = create_app(_cfg(tmp_path))
    from draindeck_dashboard import sse
    monkeypatch.setattr(sse, "REPLAY_CAP", 1)
    conn = app.state.db
    for i in range(5):
        conn.execute(
            "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) "
            "VALUES (1, 'evidence', ?, '2026-08-20T00:00:00Z')",
            (str(i),),
        )

    client = TestClient(app, base_url="http://127.0.0.1")
    # after=5 (query) would NOT need resync (nothing left to replay), but
    # Last-Event-ID=0 (header) DOES -- the header must win.
    resp = client.get("/api/events?after=5", headers={"Last-Event-ID": "0"})

    assert "CHANGE_RESYNC_REQUIRED" in resp.text
