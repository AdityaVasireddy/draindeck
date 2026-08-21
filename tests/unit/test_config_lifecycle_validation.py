"""Config-layer guards preventing a config from ever producing an
invalid Doc-03 RunStarted (review finding, 2026-08-21): empty required
models, booleans in numeric budget fields (pydantic silently coerces
True/False to 1/0 for int/float fields, which erases the bool-ness before
any downstream event validator could ever see it -- this can only be
caught here, at the raw-input layer, via a `mode="before"` validator),
and non-finite proxy cost. These are config input-hygiene fixes, not a
second implementation of the doc 03 closed-schema rules -- the payload
shape itself is still validated exactly once, downstream, by the same
canonical `_run_started`/`_run_finished` functions StateProjection uses."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config
from pydantic import ValidationError


def _base_cfg_dict(**overrides) -> dict:
    base = {
        "project": {"name": "T", "repository": "C:/repo", "branch": "agent-work",
                    "issues_file": "Issues.md", "validation": {"commands": ["exit 0"]}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription"},
        "reviewer": {"provider": "qwen", "qwen": {"endpoint": "http://x", "model": "q"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0, "proxy_pricing": "api_list_rates"},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    }
    for dotted, value in overrides.items():
        section, field = dotted.split(".", 1)
        base[section] = dict(base[section])
        base[section][field] = value
    return base


def test_empty_engine_model_is_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(_base_cfg_dict(**{"engine.model": ""}))


def test_empty_reviewer_qwen_model_is_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(_base_cfg_dict(**{
            "reviewer.qwen": {"endpoint": "http://x", "model": ""},
        }))


def test_budget_max_attempts_per_issue_boolean_is_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(_base_cfg_dict(**{"budget.max_attempts_per_issue": True}))


def test_budget_max_executions_per_run_boolean_is_rejected():
    # True coerces to 1, which passes gt=0 -- unlike False (coerces to 0,
    # already rejected by gt=0 today), this is the genuine bool-coercion gap.
    with pytest.raises(ValidationError):
        Config.model_validate(_base_cfg_dict(**{"budget.max_executions_per_run": True}))


def test_budget_hard_stop_cost_boolean_is_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(_base_cfg_dict(**{"budget.hard_stop_proxy_cost_per_run_usd": True}))


def test_budget_hard_stop_cost_infinity_is_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(
            _base_cfg_dict(**{"budget.hard_stop_proxy_cost_per_run_usd": math.inf}))


def test_budget_hard_stop_cost_nan_is_rejected():
    # Already rejected today: `nan > 0` is False under IEEE 754, so
    # Field(gt=0) alone happens to catch it. Kept as a regression guard,
    # not evidence of the gap the isfinite fix specifically closes.
    with pytest.raises(ValidationError):
        Config.model_validate(
            _base_cfg_dict(**{"budget.hard_stop_proxy_cost_per_run_usd": math.nan}))


def test_budget_hard_stop_cost_negative_infinity_is_rejected():
    # Already rejected today for the same gt=0 reason as NaN above
    # (`-inf > 0` is False) -- +inf is the only value gt=0 alone misses.
    with pytest.raises(ValidationError):
        Config.model_validate(
            _base_cfg_dict(**{"budget.hard_stop_proxy_cost_per_run_usd": -math.inf}))


# ── still-valid configs must keep loading (no over-tightening) ──────────
def test_ordinary_valid_config_still_loads():
    cfg = Config.model_validate(_base_cfg_dict())
    assert cfg.engine.model == "default"
    assert cfg.budget.max_attempts_per_issue == 3


def test_default_engine_model_still_loads():
    # engine.model omitted entirely -- must keep using the "default" literal,
    # never rejected as "empty".
    d = _base_cfg_dict()
    cfg = Config.model_validate(d)
    assert cfg.engine.model == "default"
