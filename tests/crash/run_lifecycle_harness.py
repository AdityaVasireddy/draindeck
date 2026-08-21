"""Crash-harness scenario for the doc 03 amendment's "Never-fabricated
abrupt death" rule: if a process dies after RunStarted was appended but
before any controlled exit, no RunFinished is ever written -- not by the
dying process, and not retroactively by a later process's recovery pass.
RunStarted is deliberately excluded from RESOLUTION_OF (schema.py), so
the production recover() entrypoint must never attempt to resolve it.

Fixture-style (real git repo, real EventLog, real recover()/bind_reconciler
entrypoints -- same production code path tests/crash/item9_orphan_harness.py's
Row B/C/E fixtures use), not a live subprocess kill: this is a pure
reconciler-logic claim (RunStarted has no RESOLUTION_OF entry, so recover()
never looks for a fact to backfill for it), not a live-timing claim, so no
real process kill is needed to exercise it -- matching the same scoping
precedent item9_orphan_harness.py's docstring states for its own fixture
rows. "Abrupt death" is simulated the same way item9's fixture_row_b
simulates a crash: the log simply never receives the fact event, then a
real recover() pass runs against it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.log import EventLog                       # noqa: E402
from runtime.events.projections import StateProjection        # noqa: E402
from runtime.events.schema import Event, EventType             # noqa: E402
from runtime.recovery.bindings import bind_reconciler          # noqa: E402
from runtime.recovery.reconciler import recover                # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter              # noqa: E402

RUN_ID = "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6"


def _rmtree_readonly_safe(path: Path) -> None:
    def _on_error(func, p, exc_info):
        os.chmod(p, 0o700)
        func(p)
    shutil.rmtree(path, onexc=_on_error)


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"harness git {args} failed: {p.stderr}")
    return p.stdout.strip()


def _init_repo(root: Path, name: str) -> Path:
    base = root / name
    if base.exists():
        _rmtree_readonly_safe(base)
    base.mkdir(parents=True)
    repo = base / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "agent-work")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    return base


def _run_started_payload() -> dict:
    return {
        "engine": {"provider": "claude-headless", "model": "default"},
        "reviewer": {"provider": "qwen", "model": "qwen2.5-coder"},
        "budget": {
            "max_attempts_per_issue": 3,
            "max_executions_per_run": 10,
            "hard_stop_proxy_cost_per_run_usd": 15.0,
            "proxy_pricing": "api_list_rates",
        },
        "config_digest": "a" * 64,
    }


def fixture_run_started_never_backfilled(root: Path) -> dict:
    report: dict = {"witnesses": {}}
    base = _init_repo(root, "run_started_never_backfilled")
    repo = base / "repo"
    adapter = GitCliAdapter(repo)
    log = EventLog(base / "events.jsonl")

    # RunStarted is the run's only event on this log -- no issue/execution
    # activity at all -- to isolate the claim from every other reconciler
    # check. Then the process "dies": nothing else is ever appended.
    started_eid = log.append(Event(
        EventType.RUN_STARTED, run_id=RUN_ID, payload=_run_started_payload()))
    report["witnesses"]["run_started_event_id"] = started_eid
    log.close()

    # First recovery pass after the "crash" -- same production entrypoint
    # every other crash scenario in this suite uses.
    log = EventLog(base / "events.jsonl")
    proj, rec_report = recover(
        log, is_execution_alive=lambda _xid: False,
        **bind_reconciler(adapter, "agent-work"),
    )
    report["witnesses"]["first_recovery_checks_run"] = rec_report.checks_run
    report["witnesses"]["first_recovery_orphans_crashed"] = rec_report.orphans_crashed
    report["witnesses"]["first_recovery_emitted"] = rec_report.emitted
    log.close()

    events_after_first_recovery = list(EventLog(base / "events.jsonl").replay())
    report["witnesses"]["events_after_first_recovery"] = [
        ev.type.value for ev in events_after_first_recovery
    ]
    run_finished_1 = [ev for ev in events_after_first_recovery
                      if ev.type is EventType.RUN_FINISHED]
    run_started_1 = [ev for ev in events_after_first_recovery
                     if ev.type is EventType.RUN_STARTED]

    # Second recovery pass (simulating yet another restart against the same
    # still-unresolved RunStarted) -- proves the exemption holds on repeat,
    # not just once.
    log = EventLog(base / "events.jsonl")
    proj2, rec_report2 = recover(
        log, is_execution_alive=lambda _xid: False,
        **bind_reconciler(adapter, "agent-work"),
    )
    report["witnesses"]["second_recovery_emitted"] = rec_report2.emitted
    log.close()

    events_after_second_recovery = list(EventLog(base / "events.jsonl").replay())
    run_finished_2 = [ev for ev in events_after_second_recovery
                      if ev.type is EventType.RUN_FINISHED]
    run_started_2 = [ev for ev in events_after_second_recovery
                     if ev.type is EventType.RUN_STARTED]

    report["assertions"] = {
        "run_started_survives_first_recovery": len(run_started_1) == 1,
        "no_run_finished_after_first_recovery": len(run_finished_1) == 0,
        "run_started_survives_second_recovery": len(run_started_2) == 1,
        "no_run_finished_after_second_recovery": len(run_finished_2) == 0,
        "log_grew_by_exactly_recovery_facts_not_run_finished": (
            len(events_after_second_recovery) == len(events_after_first_recovery)
        ),
    }
    assert len(run_started_1) == 1, (
        "fixture_run_started_never_backfilled FAILED: RunStarted lost across recovery")
    assert len(run_finished_1) == 0, (
        "fixture_run_started_never_backfilled FAILED: recover() fabricated a "
        "RunFinished for an orphaned RunStarted")
    assert len(run_started_2) == 1, (
        "fixture_run_started_never_backfilled FAILED: RunStarted lost across a "
        "second recovery pass")
    assert len(run_finished_2) == 0, (
        "fixture_run_started_never_backfilled FAILED: a second recovery pass "
        "fabricated a RunFinished for the still-orphaned RunStarted")

    report["status"] = "PASS"
    return report


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "run-lifecycle-harness"
    root.mkdir(parents=True, exist_ok=True)

    print("=== fixture_run_started_never_backfilled ===")
    print(json.dumps(fixture_run_started_never_backfilled(root), indent=2, default=str))

    print("\nALL REQUESTED SCENARIOS COMPLETED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
