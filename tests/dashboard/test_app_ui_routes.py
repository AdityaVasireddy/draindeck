"""Unit 6 (docs/27 SS9.1): stable UI routing and security preservation.

API routes register first; static assets mount only at /assets; an
explicit allowlist of approved UI route patterns returns the semantic app
shell (index.html) so a direct reload/deep-link works; everything else
retains FastAPI's normal 404. Legacy /styles.css and /app.js stay
reachable for backward compatibility. No existing security header/
middleware coverage regresses.
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
    return TestClient(create_app(_cfg(tmp_path)), base_url="http://127.0.0.1")


_APPROVED_UI_ROUTES = [
    "/",
    "/repositories",
    "/repositories/new",
    "/repositories/new-target",
    "/repositories/5/configuration",
    "/repositories/5",
    "/attention",
    "/runs",
    "/repositories/5/runs",
    "/repositories/5/runs/run-1",
    "/issues",
    "/repositories/5/issues",
    "/repositories/5/issues/42",
    "/executions",
    "/repositories/5/executions",
    "/repositories/5/executions/42-e1",
    "/evidence",
    "/repositories/5/evidence",
    "/repositories/5/evidence/7",
    "/about",
]


def test_every_approved_ui_route_returns_the_app_shell_directly(tmp_path):
    client = _client(tmp_path)
    for route in _APPROVED_UI_ROUTES:
        resp = client.get(route)
        assert resp.status_code == 200, f"{route} -> {resp.status_code}"
        assert "text/html" in resp.headers["content-type"]
        assert "<main" in resp.text  # real semantic landmark, not an empty stub


def test_unknown_ui_route_is_a_real_404_not_the_app_shell(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404


def test_api_routes_are_never_swallowed_by_the_ui_shell(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_unknown_api_route_still_gets_normal_404_not_html(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/api/nonexistent-endpoint")
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


def test_assets_mount_serves_static_files(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/assets/index.html")
    assert resp.status_code == 200
    assert "<main" in resp.text


def test_legacy_styles_css_still_reachable(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/styles.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_legacy_app_js_still_reachable(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_nested_route_reload_still_gets_security_headers(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/repositories/5/issues/42")
    assert resp.status_code == 200
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in resp.headers["content-security-policy"]


def test_hostile_host_still_rejected_on_a_ui_route(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/repositories", headers={"Host": "evil.example.com"})
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "NON_LOOPBACK_HOST"


def test_no_js_fallback_present_in_shell(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert "<noscript" in resp.text
