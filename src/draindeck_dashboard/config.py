"""Dashboard configuration (ADR-26 decision 1/3; docs/19 "Purpose and
dependency boundary" / "Registration and polling").

Structural validation only, mirroring ``runtime.config``'s discipline:
loaded once, fully validated, immutable. Dashboard never loads a target
repo's ``config.yaml`` or reproduces ``resolve_event_log_path`` — the
observer executable path and the SQLite database location are the only
filesystem facts this config owns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DashboardConfigError(ValueError):
    pass


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DashboardConfig(_Frozen):
    # Local web security (docs/19 "Local web security"): the unauthenticated
    # server binds only to 127.0.0.1 — this is not a default, it is the only
    # accepted value, enforced structurally rather than left to the deployer.
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(gt=0, le=65535, default=8420)
    # Dashboard-owned SQLite database (ADR-26 decision 2). Absolute so its
    # location never depends on the process's invocation cwd.
    db_path: str
    # Operator-configured absolute path to the draindeck executable this
    # Dashboard invokes for `observe events`/`observe status` (docs/19
    # "Purpose and dependency boundary").
    observer_executable: str

    @field_validator("db_path")
    @classmethod
    def _db_path_absolute(cls, v: str) -> str:
        if not Path(v).is_absolute():
            raise ValueError(f"db_path must be an absolute path, got {v!r}")
        return v

    @field_validator("observer_executable")
    @classmethod
    def _observer_executable_absolute(cls, v: str) -> str:
        if not Path(v).is_absolute():
            raise ValueError(
                f"observer_executable must be an absolute path, got {v!r}"
            )
        return v


def load_dashboard_config(path: Path | str) -> DashboardConfig:
    """Structural load. Raises DashboardConfigError with a pointed message."""
    p = Path(path)
    if not p.exists():
        raise DashboardConfigError(f"dashboard config file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DashboardConfigError(f"invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise DashboardConfigError(f"{p}: top level must be a mapping")
    try:
        return DashboardConfig.model_validate(raw)
    except Exception as e:  # pydantic ValidationError
        raise DashboardConfigError(f"{p}: {e}") from e
