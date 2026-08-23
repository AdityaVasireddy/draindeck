"""Unit 14 (docs/27 SS6.9): the About & Safety page's live facts endpoint.
Everything else on the page (mutation-boundary/safety disclosure text,
update-stream meaning, theme storage) is static content owned by the
frontend page module -- this endpoint supplies only what's genuinely
config- or build-dependent: host, port, database path, and version."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig


def _cfg(tmp_path: Path, port: int = 8420) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
        port=port,
    )


def test_about_returns_host_port_db_path_and_version(tmp_path):
    app = create_app(_cfg(tmp_path, port=8433))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/about")
    assert resp.status_code == 200
    body = resp.json()
    assert body["host"] == "127.0.0.1"
    assert body["port"] == 8433
    assert body["dbPath"] == str(tmp_path / "dashboard.sqlite3")
    assert isinstance(body["version"], str) and body["version"]
