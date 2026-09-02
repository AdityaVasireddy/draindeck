"""The launcher's ownership-proof endpoint (docs/32 L-08/L-13): a Dashboard
process started with an instance token reports it back verbatim, and a
Dashboard started without one (e.g. a plain `--config` run, not through the
launcher) reports no token -- so nothing can be mistaken for launcher-owned
by default."""
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


def test_identity_endpoint_reports_the_token_the_process_was_started_with(tmp_path):
    app = create_app(_cfg(tmp_path), instance_token="tok-abc123")
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/launcher/identity")
    assert resp.status_code == 200
    assert resp.json() == {"instanceToken": "tok-abc123"}


def test_identity_endpoint_reports_no_token_when_not_launcher_started(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/launcher/identity")
    assert resp.status_code == 200
    assert resp.json() == {"instanceToken": None}
