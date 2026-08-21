"""Phase 2 acceptance: dashboard config validation."""
from __future__ import annotations

import pytest
import yaml

from draindeck_dashboard.config import (
    DashboardConfig,
    DashboardConfigError,
    load_dashboard_config,
)


def test_host_must_be_the_loopback_literal():
    with pytest.raises(Exception):
        DashboardConfig(host="0.0.0.0", db_path="C:/x/db.sqlite3",
                        observer_executable="C:/x/draindeck.exe")


def test_db_path_must_be_absolute():
    with pytest.raises(Exception):
        DashboardConfig(db_path="relative/db.sqlite3",
                        observer_executable="C:/x/draindeck.exe")


def test_observer_executable_must_be_absolute():
    with pytest.raises(Exception):
        DashboardConfig(db_path="C:/x/db.sqlite3",
                        observer_executable="relative/draindeck.exe")


def test_unknown_field_is_rejected():
    with pytest.raises(Exception):
        DashboardConfig(db_path="C:/x/db.sqlite3",
                        observer_executable="C:/x/draindeck.exe",
                        unexpected_field=True)


def test_valid_config_round_trips_from_yaml(tmp_path):
    cfg_path = tmp_path / "dashboard.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "db_path": str(tmp_path / "dashboard.sqlite3"),
        "observer_executable": str(tmp_path / "draindeck.exe"),
    }))
    cfg = load_dashboard_config(cfg_path)
    assert cfg.host == "127.0.0.1"
    assert cfg.db_path == str(tmp_path / "dashboard.sqlite3")


def test_missing_file_raises_dashboard_config_error(tmp_path):
    with pytest.raises(DashboardConfigError):
        load_dashboard_config(tmp_path / "missing.yaml")


def test_non_mapping_yaml_raises_dashboard_config_error(tmp_path):
    cfg_path = tmp_path / "dashboard.yaml"
    cfg_path.write_text("- just\n- a\n- list\n")
    with pytest.raises(DashboardConfigError):
        load_dashboard_config(cfg_path)
