"""Runtime CLI — foundation commands only (Session 2 scope).

  python -m runtime.main verify-log [--log PATH]   replay, enforce contract
  python -m runtime.main show-state [--log PATH]   print projection summary
  python -m runtime.main recover    [--log PATH]   run recovery, print report
  python -m runtime.main check-config CONFIG       structural + env validation

Orchestration commands arrive in later sessions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, load_config, validate_environment
from .events.log import CorruptionError, EventLog
from .events.projections import StateProjection
from .recovery.reconciler import recover


def _load(path: str) -> EventLog:
    return EventLog(Path(path))


def cmd_verify_log(args) -> int:
    try:
        log = _load(args.log)
        n = sum(1 for _ in log.replay())
    except CorruptionError as e:
        print(f"CORRUPT: {e}", file=sys.stderr)
        return 1
    print(f"OK: {n} events, last_event_id={log.last_event_id}")
    return 0


def cmd_show_state(args) -> int:
    log = _load(args.log)
    proj = StateProjection().rebuild(log.replay())
    out = {
        "last_event_id": proj.last_event_id,
        "digest": proj.digest(),
        "issues": {k: v.value for k, v in sorted(proj.issues.items())},
        "executions": {
            k: {"issue": v.issue_id, "state": v.state.value,
                "commit_intended": v.commit_intended,
                "commit_created": v.commit_created}
            for k, v in sorted(proj.executions.items())
        },
        "event_counts": dict(sorted(proj.counts.items())),
    }
    print(json.dumps(out, indent=2))
    return 0


def cmd_recover(args) -> int:
    log = _load(args.log)
    proj, rep = recover(log)
    print(json.dumps({
        "replayed_events": rep.replayed_events,
        "orphans_crashed": rep.orphans_crashed,
        "emitted": rep.emitted,
        "checks_run": rep.checks_run,
        "checks_skipped": rep.checks_skipped,
        "digest": proj.digest(),
    }, indent=2))
    return 0


def cmd_check_config(args) -> int:
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1
    problems = validate_environment(cfg)
    if problems:
        print("STRUCTURE OK; ENVIRONMENT PROBLEMS:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: structure and environment valid")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("verify-log", cmd_verify_log),
                     ("show-state", cmd_show_state),
                     ("recover", cmd_recover)]:
        s = sub.add_parser(name)
        s.add_argument("--log", default="state/events.jsonl")
        s.set_defaults(fn=fn)
    s = sub.add_parser("check-config")
    s.add_argument("config")
    s.set_defaults(fn=cmd_check_config)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
