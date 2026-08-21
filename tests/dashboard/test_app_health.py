"""Phase 2 acceptance: health endpoint starts; local web security headers
and loopback-only Host/Origin enforcement are wired into the app factory."""
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


def test_health_endpoint_returns_ok(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_security_headers_present_on_every_response(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/health")
    assert resp.headers["content-security-policy"].startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "access-control-allow-origin" not in resp.headers


def test_non_loopback_host_is_rejected_with_headers_still_applied(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://evil.example.com")
    resp = client.get("/api/health")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NON_LOOPBACK_HOST"
    # SecurityHeadersMiddleware must be outermost: even a rejection carries
    # the restrictive headers.
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_non_loopback_origin_is_rejected(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/health", headers={"Origin": "http://evil.example.com"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NON_LOOPBACK_ORIGIN"


def test_loopback_origin_is_accepted(tmp_path):
    app = create_app(_cfg(tmp_path))
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/health", headers={"Origin": "http://127.0.0.1:8420"})
    assert resp.status_code == 200
