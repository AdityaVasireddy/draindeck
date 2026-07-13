"""End-to-end loop against a REAL temp git repo (GitCliAdapter), with only the
engine and reviewer faked. Proves the git choreography the FakeAdapter cannot:
checkout -B from a pinned base, snapshot_commit → end_commit, attempt refs,
reset_hard, object-DB merge_to, the I3 pin gate, and attempt-ref GC. The fake
engine actually writes a file into the workspace, so validation runs against a
genuinely mutated tree — the workspace-is-the-contract path (ADR-07).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.budget.manager import BudgetManager                     # noqa: E402
from runtime.config import Config                                    # noqa: E402
from runtime.engine.claude_headless import EngineResult             # noqa: E402
from runtime.events.log import EventLog                              # noqa: E402
from runtime.events.projections import StateProjection              # noqa: E402
from runtime.events.schema import Event, EventType                  # noqa: E402
from runtime.loop import Orchestrator                                # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter                   # noqa: E402
from runtime.reviewer.base import ReviewVerdict                      # noqa: E402
from runtime.state.model import IssueState                           # noqa: E402

_BRANCH = "agent-work"


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=repo, capture_output=True, text=True, encoding="utf-8")
    if p.returncode != 0:
        raise RuntimeError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def _init_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", _BRANCH)
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "README").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return repo


class _WritingEngine:
    """Simulates the real engine: writes a unique file into the workspace so the
    snapshot is a genuine commit and validation sees a mutated tree."""

    def __init__(self, artifacts_dir):
        self.artifacts_dir = Path(artifacts_dir)

    def run(self, xid, prompt_file, workspace):
        (Path(workspace) / f"work-{xid}.txt").write_text(f"done by {xid}\n")
        return EngineResult(exit_status=0, timed_out=False, duration_s=0.1,
                            usage={"dollars": 0.01}, num_turns=2,
                            transcript_path=Path("t.jsonl"), stderr_tail="")


class _ApproveReviewer:
    name = "fake"

    def review(self, pack):
        return ReviewVerdict(execution_id=pack.execution_id,
                             reviewed_commit=pack.reviewed_commit,
                             provider="fake", verdict="APPROVE")


def _cfg(repo: Path) -> Config:
    # validation passes only if the engine actually wrote its file → proves the
    # workspace mutation is what's being validated.
    check = ('python -c "import glob,sys; '
             'sys.exit(0 if glob.glob(\'work-*.txt\') else 1)"')
    return Config.model_validate({
        "project": {"name": "T", "repository": str(repo), "branch": _BRANCH,
                    "validation": {"commands": [check]}},
        "engine": {"provider": "claude-headless", "auth_mode": "subscription"},
        "reviewer": {"provider": "qwen", "qwen": {"endpoint": "http://x", "model": "q"}},
        "budget": {"max_attempts_per_issue": 3, "max_executions_per_run": 10,
                   "hard_stop_proxy_cost_per_run_usd": 15.0},
        "experiment": {"sample_size": 20, "attempt1_success_min": 0.3,
                       "cost_per_shipped_issue_max_usd": 3.0},
        "billing": {"posture": "p", "headless_split_status": "paused",
                    "verified_on": "2026-07-10", "reverify_at": "x"},
    })


def test_two_issues_ship_end_to_end_on_real_git(tmp_path):
    repo = _init_repo(tmp_path)
    cfg = _cfg(repo)
    art = tmp_path / "art"
    from runtime.validation.runner import Validator
    log = EventLog(tmp_path / "events.jsonl")
    proj = StateProjection()
    for iid in ("001", "002"):
        ev = Event(EventType.ISSUE_CREATED, issue_id=iid,
                   payload={"title": f"I{iid}", "body": "b", "depends_on": []})
        eid = log.append(ev)
        proj.apply(Event(type=ev.type, payload=ev.payload, issue_id=ev.issue_id,
                         event_id=eid))

    adapter = GitCliAdapter(repo, cfg.attempts.ref_namespace)
    orch = Orchestrator(
        cfg=cfg, log=log, proj=proj, adapter=adapter,
        engine=_WritingEngine(art),
        validator=Validator(cfg.project.validation.commands, timeout_seconds=60,
                            artifacts_dir=art),
        reviewer=_ApproveReviewer(),
        budget=BudgetManager(10, 15.0), artifacts_dir=art, run_id="run-test",
    )
    orch.run()

    assert proj.issues["001"] is IssueState.DONE
    assert proj.issues["002"] is IssueState.DONE
    # two merges landed on agent-work's first-parent chain
    merges = _git(repo, "rev-list", "--first-parent", "--merges", "--count", _BRANCH)
    assert merges == "2"
    # attempt refs GC'd on completion (ADR-15)
    assert adapter.list_attempt_refs() == {}
    # exactly one CommitCreated per issue (I-d)
    assert proj.counts.get("CommitCreated") == 2
    # both issues' work is on the trunk tree
    _git(repo, "checkout", _BRANCH)
    assert (repo / "work-001-e1.txt").exists()
    assert (repo / "work-002-e1.txt").exists()
