"""The launcher's in-memory config path through the `draindeck-dashboard`
CLI (docs/32 "Dashboard process settings are in-memory only"): explicit
--host/--port/--db-path/--observer-executable/--instance-token flags build
a DashboardConfig directly, with no YAML file ever read or written, and the
instance token reaches the running app's identity endpoint."""
from __future__ import annotations

from draindeck_dashboard import cli


def test_in_memory_flags_start_the_app_without_any_config_file(tmp_path, monkeypatch):
    captured = {}

    def fake_run(app, *, host, port):
        captured["host"] = host
        captured["port"] = port
        captured["instance_token"] = app.state.instance_token
        captured["db_path"] = app.state.config.db_path

    import uvicorn
    monkeypatch.setattr(uvicorn, "run", fake_run)

    rc = cli.main([
        "--host", "127.0.0.1",
        "--port", "8531",
        "--db-path", str(tmp_path / "dashboard.sqlite3"),
        "--observer-executable", str(tmp_path / "draindeck.exe"),
        "--instance-token", "launcher-tok-1",
    ])
    assert rc == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8531
    assert captured["instance_token"] == "launcher-tok-1"
    assert captured["db_path"] == str(tmp_path / "dashboard.sqlite3")


def test_missing_both_config_and_in_memory_flags_is_a_clean_config_error(capsys):
    rc = cli.main([])
    captured = capsys.readouterr()
    assert rc == 1
    assert "CONFIG INVALID" in captured.err


def test_relative_db_path_is_rejected_as_a_clean_config_error(capsys):
    rc = cli.main([
        "--db-path", "relative/dashboard.sqlite3",
        "--observer-executable", "relative/draindeck.exe",
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "CONFIG INVALID" in captured.err
