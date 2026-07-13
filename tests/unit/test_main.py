"""main.py startup helpers: Issues.md ingest idempotency (a second startup over
the same file must emit zero new events) and fail-loud on a malformed file."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config                                    # noqa: E402
from runtime.events.log import EventLog                              # noqa: E402
from runtime.events.projections import StateProjection              # noqa: E402
from runtime.main import _ingest_issues                              # noqa: E402
from runtime.queue.issues_md import IssuesParseError                 # noqa: E402


def _cfg(repo: Path) -> Config:
    return Config.model_validate({
        "project": {"name": "T", "repository": str(repo), "branch": "agent-work",
                    "issues_file": "Issues.md",
                    "validation": {"commands": ["exit 0"]}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription"},
        "reviewer": {"provider": "qwen",
                     "qwen": {"endpoint": "http://x", "model": "q"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })


def test_ingest_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Issues.md").write_text(
        "## 001: First\nbody\n## 002: Second\nDepends-On: 001\n", encoding="utf-8")
    cfg = _cfg(repo)
    log = EventLog(tmp_path / "events.jsonl")
    proj = StateProjection()

    first = _ingest_issues(cfg, log, proj, "run-1")
    assert first == 2
    assert set(proj.issues) == {"001", "002"}
    assert proj.issue_depends_on["002"] == ["001"]

    # a second startup over the SAME file emits nothing new
    second = _ingest_issues(cfg, log, proj, "run-2")
    assert second == 0
    assert sum(1 for _ in log.replay()) == 2  # no duplicate IssueCreated


def test_ingest_malformed_aborts(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Issues.md").write_text("## bad heading no colon\nbody\n", encoding="utf-8")
    cfg = _cfg(repo)
    log = EventLog(tmp_path / "events.jsonl")
    with pytest.raises(IssuesParseError):
        _ingest_issues(cfg, log, StateProjection(), "run-1")
