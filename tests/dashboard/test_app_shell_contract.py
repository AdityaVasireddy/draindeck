"""Unit 7 (docs/27 SS9, SS11, DESIGN.md): the app shell's served assets
and CSP-safety contract. Live browser verification (rail active state,
theme persistence, deep-link reload, zero console errors) was performed
separately and is recorded in docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md;
this file locks the static-asset/markup contract into the regular suite.
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


_NEW_STYLESHEETS = ["tokens.css", "base.css", "shell.css", "components.css", "pages.css"]
_NEW_JS_MODULES = [
    "app.js", "dom.js", "format.js", "state.js", "components/shell.js", "api.js", "stream.js",
    "router.js", "pages/home.js", "pages/repositories.js", "pages/repository-detail.js",
    "pages/attention.js", "components/search.js", "pages/runs.js", "pages/issues.js",
    "components/timeline-topology.js", "pages/executions.js", "pages/evidence.js",
    "components/chart.js",
]


def test_every_new_stylesheet_is_served_with_css_content_type(tmp_path):
    client = _client(tmp_path)
    for name in _NEW_STYLESHEETS:
        resp = client.get(f"/assets/styles/{name}")
        assert resp.status_code == 200, name
        assert "text/css" in resp.headers["content-type"]


def test_every_new_js_module_is_served_reachable(tmp_path):
    client = _client(tmp_path)
    for name in _NEW_JS_MODULES:
        resp = client.get(f"/assets/js/{name}")
        assert resp.status_code == 200, name


def test_index_html_links_every_new_stylesheet(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    for name in _NEW_STYLESHEETS:
        assert f"/assets/styles/{name}" in body, name


def test_index_html_has_no_inline_style_or_script_csp_violation(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    assert "<style" not in body
    assert 'style="' not in body
    # The only <script> tags allowed are external src references (module
    # boot + legacy compat) -- never an inline script body.
    import re
    for match in re.finditer(r"<script[^>]*>(.*?)</script>", body, re.DOTALL):
        assert match.group(1).strip() == "", "inline script body found"


def test_index_html_has_skip_link_and_main_landmark(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    assert 'class="skip-link"' in body
    assert 'href="#main-content"' in body
    assert 'id="main-content"' in body


def test_index_html_has_eight_rail_destinations_mount_point(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    assert 'id="rail-nav-list"' in body


def test_response_still_has_self_only_csp_on_the_shell_page(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    csp = resp.headers["content-security-policy"]
    assert "default-src 'self'" in csp
