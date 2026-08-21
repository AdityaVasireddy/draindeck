"""_config_digest determinism, allowlist-sensitivity, and exclusion (doc 03
amendment, "config_digest (exact computation)"): the digest is built by
allowlisting exactly 10 fields, never by stripping the full Config object,
so excluded fields (secrets, paths, endpoints, commands, env, ...) can
never reach the digest input."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config
from runtime.main import _config_digest, _resolve_reviewer_model


def _cfg_dict(**overrides) -> dict:
    base = {
        "project": {"name": "T", "repository": "C:/repo", "branch": "agent-work",
                    "issues_file": "Issues.md",
                    "validation": {"commands": ["exit 0"],
                                  "env": {"SECRET_TOKEN": "shh"}}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription",
                   "model": "default", "max_turns": 30, "timeout_seconds": 1800,
                   "child_env": {"ANTHROPIC_API_KEY": "should-never-appear"}},
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": "http://secret-internal-host:9999",
                             "model": "qwen2.5-coder"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0,
                   "proxy_pricing": "api_list_rates"},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
        "event_log": {"path": "C:/very/secret/path/events.jsonl"},
    }
    for dotted, value in overrides.items():
        if "." in dotted:
            section, field = dotted.split(".", 1)
            base[section] = dict(base[section])
            base[section][field] = value
        else:
            base[dotted] = value
    return base


def _cfg(**overrides) -> Config:
    return Config.model_validate(_cfg_dict(**overrides))


def _digest(cfg: Config) -> str:
    return _config_digest(cfg, _resolve_reviewer_model(cfg))


def test_digest_is_64_lowercase_hex():
    d = _digest(_cfg())
    assert re.fullmatch(r"[0-9a-f]{64}", d)


def test_digest_is_deterministic():
    assert _digest(_cfg()) == _digest(_cfg())


def test_reviewer_model_resolves_from_qwen_subsection():
    cfg = _cfg()
    assert _resolve_reviewer_model(cfg) == "qwen2.5-coder"


def test_digest_changes_when_engine_model_changes():
    assert _digest(_cfg()) != _digest(_cfg(**{"engine.model": "opus"}))


def test_digest_changes_when_engine_max_turns_changes():
    assert _digest(_cfg()) != _digest(_cfg(**{"engine.max_turns": 99}))


def test_digest_changes_when_engine_timeout_changes():
    assert _digest(_cfg()) != _digest(_cfg(**{"engine.timeout_seconds": 999}))


def test_digest_changes_when_budget_max_attempts_changes():
    assert _digest(_cfg()) != _digest(_cfg(**{"budget.max_attempts_per_issue": 7}))


def test_digest_changes_when_budget_max_executions_changes():
    assert _digest(_cfg()) != _digest(_cfg(**{"budget.max_executions_per_run": 99}))


def test_digest_changes_when_proxy_cost_changes():
    assert _digest(_cfg()) != _digest(
        _cfg(**{"budget.hard_stop_proxy_cost_per_run_usd": 999.0}))


def test_digest_changes_when_reviewer_model_changes():
    assert _digest(_cfg()) != _digest(
        _cfg(**{"reviewer.qwen": {"endpoint": "http://x", "model": "different-model"}}))


def test_digest_unaffected_by_validation_env_secret():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"project.validation": {"commands": ["exit 0"],
                                          "env": {"SECRET_TOKEN": "totally-different"}}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_engine_child_env_secret():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"engine.child_env": {"ANTHROPIC_API_KEY": "a-different-secret-value"}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_reviewer_endpoint():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"reviewer.qwen": {"endpoint": "http://totally-different-host:1",
                                     "model": "qwen2.5-coder"}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_repository_path():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"project.repository": "D:/a-totally-different-path"})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_event_log_path():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"event_log": {"path": "D:/another/secret/path.jsonl"}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_validation_commands():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"project.validation": {"commands": ["a totally different command"],
                                          "env": {"SECRET_TOKEN": "shh"}}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_unaffected_by_experiment_billing_attempts_sections():
    cfg1 = _cfg()
    cfg2 = _cfg(**{"experiment": {"sample_size": 999, "attempt1_success_min": 0.99,
                                  "cost_per_shipped_issue_max_usd": 999.0},
                   "billing": {"posture": "different", "headless_split_status": "active",
                              "verified_on": "2020-01-01", "reverify_at": "never"}})
    assert _digest(cfg1) == _digest(cfg2)


def test_digest_matches_independently_computed_fixture():
    """Hand-built per doc 03's exact 10-field spec -- NOT derived from
    _config_digest's own construction -- so a regression that silently
    changes the allowlist or its shape is caught even if it doesn't change
    which VALUES flow in. Values mirror _cfg_dict()'s base exactly."""
    cfg = _cfg()
    reviewer_model = _resolve_reviewer_model(cfg)
    expected_canon = {
        "budget": {
            "hard_stop_proxy_cost_per_run_usd": 15.0,
            "max_attempts_per_issue": 3,
            "max_executions_per_run": 10,
            "proxy_pricing": "api_list_rates",
        },
        "engine": {
            "max_turns": 30,
            "model": "default",
            "provider": "claude-headless",
            "timeout_seconds": 1800,
        },
        "reviewer": {
            "model": "qwen2.5-coder",
            "provider": "qwen",
        },
    }
    expected_raw = json.dumps(expected_canon, sort_keys=True, separators=(",", ":"))
    expected_digest = hashlib.sha256(expected_raw.encode()).hexdigest()

    assert reviewer_model == "qwen2.5-coder"
    assert _config_digest(cfg, reviewer_model) == expected_digest
