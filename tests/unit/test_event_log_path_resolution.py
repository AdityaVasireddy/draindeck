"""Event-log path resolution — regression coverage for the cross-repository
isolation fix (resolve-item, 2026-08-18).

Root cause: `event_log.path` defaulted to a bare relative string
("state/events.jsonl" / now ".draindeck/state/events.jsonl") resolved
directly against `Path.cwd()` -- Draindeck's own invocation directory, not
the target repository. Every target repo run from the same CWD therefore
shared (and could replay) the same physical log. `resolve_event_log_path`
(config.py) is the fix: it anchors a relative path to
`project.repository` instead, never the CWD, and passes an absolute path
through unchanged (explicit operator overrides keep working).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import Config, resolve_event_log_path  # noqa: E402


def _cfg(repo: str, event_log_path: str | None = None) -> Config:
    data = {
        "project": {"name": "T", "repository": repo, "branch": "main",
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
    }
    if event_log_path is not None:
        data["event_log"] = {"path": event_log_path}
    return Config.model_validate(data)


# ── resolve_event_log_path: pure resolution behavior ──────────────────
def test_default_relative_path_resolves_against_repository_not_cwd(tmp_path, monkeypatch):
    repo = tmp_path / "target-repo"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)          # CWD is neither the repo nor anything related

    cfg = _cfg(str(repo))                  # no event_log section -> class default
    resolved = resolve_event_log_path(cfg)

    assert resolved == repo / ".draindeck" / "state" / "events.jsonl"
    assert Path.cwd() == elsewhere         # CWD genuinely was elsewhere throughout


def test_two_target_repos_get_isolated_default_logs(tmp_path):
    """The actual LUVZ/StockPhotoAgent incident, generalized: two different
    target repos, both left at the default event_log.path, must never
    resolve to the same physical file."""
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"

    log_a = resolve_event_log_path(_cfg(str(repo_a)))
    log_b = resolve_event_log_path(_cfg(str(repo_b)))

    assert log_a != log_b
    assert repo_a in log_a.parents
    assert repo_b in log_b.parents


def test_relative_path_is_cwd_independent(tmp_path, monkeypatch):
    repo = tmp_path / "target-repo"
    cfg = _cfg(str(repo), event_log_path="custom/log.jsonl")

    monkeypatch.chdir(tmp_path)
    resolved_1 = resolve_event_log_path(cfg)
    (tmp_path / "another-cwd").mkdir()
    monkeypatch.chdir(tmp_path / "another-cwd")
    resolved_2 = resolve_event_log_path(cfg)

    assert resolved_1 == resolved_2 == repo / "custom" / "log.jsonl"


def test_absolute_path_passes_through_unchanged(tmp_path):
    """Existing explicit configuration (an operator-pinned absolute path)
    remains fully supported -- unaffected by the repo-relative default."""
    pinned = tmp_path / "elsewhere" / "events.jsonl"
    cfg = _cfg(str(tmp_path / "target-repo"), event_log_path=str(pinned))
    assert resolve_event_log_path(cfg) == pinned


# ── systemic wiring: main.py's shared run/recover startup boundary ────
def test_cmd_recover_opens_event_log_at_repo_resolved_path_not_cwd(tmp_path, monkeypatch):
    """The one place run/recover actually open the log (main.py's
    _open_startup_recovery) must receive the repo-resolved path, not the
    raw configured string -- proving the fix isn't just the helper
    function but is actually wired into the startup boundary both
    subcommands share."""
    from runtime import main as main_mod

    repo = tmp_path / "target-repo"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    cfg = _cfg(str(repo))  # default event_log.path, no explicit override
    lease = mock.MagicMock(acquired=True, workspace_key="ws")
    lease.state.value = "ACQUIRED"
    lease.detail = "ok"

    with mock.patch.object(main_mod, "load_config", return_value=cfg), \
         mock.patch.object(main_mod, "validate_environment", return_value=[]), \
         mock.patch.object(main_mod.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main_mod, "EventLog") as event_log_cls, \
         mock.patch.object(main_mod, "resolve_startup_containment"), \
         mock.patch.object(main_mod, "ClaudeHeadlessEngine",
                            return_value=mock.MagicMock(reap_orphans=lambda: [])), \
         mock.patch.object(main_mod, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main_mod, "bind_reconciler", return_value={}), \
         mock.patch.object(main_mod, "recover",
                            return_value=(mock.MagicMock(digest=lambda: "deadbeef"),
                                          SimpleNamespace(replayed_events=0,
                                                          orphans_crashed=[],
                                                          checks_run=[], checks_skipped=[],
                                                          emitted=[]))):
        main_mod.cmd_recover(SimpleNamespace(config="unused.yaml"))

    assert event_log_cls.call_count == 1
    (opened_path,), _ = event_log_cls.call_args
    assert Path(opened_path) == repo / ".draindeck" / "state" / "events.jsonl"
    assert Path.cwd() == elsewhere
