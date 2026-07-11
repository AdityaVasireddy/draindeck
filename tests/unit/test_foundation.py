"""Unit tests for the runtime foundation — reconciled against doc 03."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import ConfigError, load_config, validate_environment
from runtime.events.log import CorruptionError, EventLog
from runtime.events.projections import StateProjection
from runtime.events.schema import Event, EventType, SchemaError
from runtime.recovery.reconciler import recover
from runtime.state.model import ExecutionState, IssueState
from runtime.state.transitions import TransitionError


# ── event log ────────────────────────────────────────────────────
def test_append_replay_roundtrip(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    e1 = log.append(Event(EventType.ISSUE_CREATED, issue_id="042",
                          payload={"source": "t", "title": "t"}))
    e2 = log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042",
                          payload={"base_commit": "c0"}))
    assert (e1, e2) == (1, 2)
    back = list(log.replay())
    assert [e.event_id for e in back] == [1, 2]
    assert back[0].type is EventType.ISSUE_CREATED
    assert back[0].schema_version == 1
    assert back[1].kind.value == "fact"


def test_event_id_persists_across_reopen(tmp_path):
    p = tmp_path / "e.jsonl"
    EventLog(p).append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    log2 = EventLog(p)
    assert log2.last_event_id == 1
    assert log2.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042")) == 2


def test_torn_tail_quarantined(tmp_path):
    p = tmp_path / "e.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    log.close()
    with open(p, "ab") as fh:  # crash mid-append: partial line, no \n
        fh.write(b'{"event_id":"torn-garbage')
    log2 = EventLog(p)
    events = list(log2.replay())
    assert len(events) == 1 and events[0].event_id == 1
    sidecars = list(tmp_path.glob("e.jsonl.torn.*"))
    assert len(sidecars) == 1
    assert b"torn-garbage" in sidecars[0].read_bytes()
    assert log2.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042")) == 2


def test_midfile_corruption_refuses_to_load(tmp_path):
    p = tmp_path / "e.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042"))
    log.close()
    data = p.read_bytes().splitlines(keepends=True)
    data[0] = b"not json at all\n"
    p.write_bytes(b"".join(data))
    with pytest.raises(CorruptionError):
        EventLog(p)


def test_event_id_gap_detected(tmp_path):
    p = tmp_path / "e.jsonl"
    log = EventLog(p)
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042"))
    log.close()
    lines = p.read_bytes().splitlines(keepends=True)
    p.write_bytes(lines[1])  # drop event 1 → replay sees 2 first
    with pytest.raises(CorruptionError):
        EventLog(p)


def test_unsupported_schema_version_rejected():
    line = (b'{"event_id":1,"schema_version":2,"ts":"t","run_id":null,'
            b'"type":"IssueCreated","issue_id":"042","execution_id":null,'
            b'"payload":{}}')
    with pytest.raises(SchemaError):
        Event.from_line(line)


# ── projections / transitions (doc 03 tables) ────────────────────
def _happy(issue="042", xid="042-e1"):
    mk = lambda i, t, **kw: Event(t, event_id=i, issue_id=issue, **kw)
    return [
        mk(1, EventType.ISSUE_CREATED),
        mk(2, EventType.ISSUE_ACTIVATED),
        mk(3, EventType.EXECUTION_SPAWNED, execution_id=xid,
           payload={"spawn_reason": "initial"}),
        mk(4, EventType.EXECUTION_FINISHED, execution_id=xid,
           payload={"end_commit": "d4", "exit_status": 0}),
        mk(5, EventType.VALIDATION_PASSED, execution_id=xid,
           payload={"validated_commit": "d4"}),
        mk(6, EventType.REVIEW_APPROVED, execution_id=xid,
           payload={"reviewed_commit": "d4", "verdict": "APPROVE"}),
        mk(7, EventType.COMMIT_INTENT, execution_id=xid,
           payload={"end_commit": "d4", "target_branch": "agent-work"}),
        mk(8, EventType.COMMIT_CREATED, execution_id=xid,
           payload={"merge_commit": "m1", "backfilled": False}),
        mk(9, EventType.ISSUE_COMPLETED),
    ]


def test_happy_path_projection():
    p = StateProjection().rebuild(iter(_happy()))
    assert p.issues["042"] is IssueState.DONE
    x = p.executions["042-e1"]
    assert x.state is ExecutionState.ACCEPTED
    assert x.commit_intended and x.commit_created
    assert p.digest() == StateProjection().rebuild(iter(_happy())).digest()


def test_finish_outcome_rejected_and_validation_failed():
    evs = _happy()[:3] + [
        Event(EventType.EXECUTION_FINISHED, event_id=4, issue_id="042",
              execution_id="042-e1",
              payload={"outcome": "REJECTED", "taxonomy_category": "timeout"})]
    p = StateProjection().rebuild(iter(evs))
    assert p.executions["042-e1"].state is ExecutionState.REJECTED

    evs = _happy()[:4] + [
        Event(EventType.VALIDATION_FAILED, event_id=5, issue_id="042",
              execution_id="042-e1", payload={"taxonomy_category": "validation-tests"})]
    p = StateProjection().rebuild(iter(evs))
    assert p.executions["042-e1"].state is ExecutionState.REJECTED


def test_review_rejected():
    evs = _happy()[:5] + [
        Event(EventType.REVIEW_REJECTED, event_id=6, issue_id="042",
              execution_id="042-e1",
              payload={"verdict": "REJECT", "severity": "blocking"})]
    p = StateProjection().rebuild(iter(evs))
    assert p.executions["042-e1"].state is ExecutionState.REJECTED


def test_escalation_reasons():
    base = _happy()[:2]
    p = StateProjection().rebuild(iter(base + [
        Event(EventType.ISSUE_ESCALATED, event_id=3, issue_id="042",
              payload={"reason": "cap"})]))
    assert p.issues["042"] is IssueState.NEEDS_HUMAN
    p = StateProjection().rebuild(iter(base + [
        Event(EventType.ISSUE_ESCALATED, event_id=3, issue_id="042",
              payload={"reason": "decompose"})]))
    assert p.issues["042"] is IssueState.NEEDS_DECOMPOSITION


def test_commit_created_without_intent_is_illegal():
    evs = _happy()[:6] + [
        Event(EventType.COMMIT_CREATED, event_id=7, issue_id="042",
              execution_id="042-e1", payload={"merge_commit": "m1"})]
    with pytest.raises(TransitionError):
        StateProjection().rebuild(iter(evs))


def test_illegal_transitions_raise():
    # finish for an execution that was never spawned
    evs = _happy()[:2] + [
        Event(EventType.EXECUTION_FINISHED, event_id=3, issue_id="042",
              execution_id="ghost")]
    with pytest.raises(TransitionError):
        StateProjection().rebuild(iter(evs))
    # spawn while previous execution is mid-flight
    evs = _happy()[:4] + [
        Event(EventType.EXECUTION_SPAWNED, event_id=5, issue_id="042",
              execution_id="042-e2")]
    with pytest.raises(TransitionError):
        StateProjection().rebuild(iter(evs))
    # spawn against a non-ACTIVE issue
    evs = [_happy()[0],
           Event(EventType.EXECUTION_SPAWNED, event_id=2, issue_id="042",
                 execution_id="042-e1")]
    with pytest.raises(TransitionError):
        StateProjection().rebuild(iter(evs))
    # duplicate IssueCreated
    evs = [_happy()[0],
           Event(EventType.ISSUE_CREATED, event_id=2, issue_id="042")]
    with pytest.raises(TransitionError):
        StateProjection().rebuild(iter(evs))


# ── recovery (doc 03: crashed, never witnessed) ──────────────────
def _spawned_log(tmp_path) -> EventLog:
    log = EventLog(tmp_path / "e.jsonl")
    log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042"))
    log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="042",
                     execution_id="042-e1", payload={"spawn_reason": "initial"}))
    return log


def test_recovery_crashes_orphan_with_residue(tmp_path):
    log = _spawned_log(tmp_path)
    proj, rep = recover(
        log, preserve_residue=lambda v: f"refs/attempts/042/{v.execution_id}")
    assert rep.orphans_crashed == ["042-e1"]
    x = proj.executions["042-e1"]
    assert x.state is ExecutionState.CRASHED
    crashed = [e for e in log.replay() if e.type is EventType.EXECUTION_CRASHED]
    assert crashed[0].payload["residue_ref"] == "refs/attempts/042/042-e1"
    assert crashed[0].payload["last_known_state"] == "EXECUTING"
    # idempotent: second recovery finds nothing
    proj2, rep2 = recover(EventLog(tmp_path / "e.jsonl"))
    assert rep2.orphans_crashed == [] and rep2.emitted == []
    assert proj2.digest() == proj.digest()


def test_recovery_never_witnesses_finished(tmp_path):
    """Doc 03: EXECUTING is abandonable, never resumed — even when world
    evidence of completion exists, the orphan is CRASHED, not finished."""
    log = _spawned_log(tmp_path)
    _, rep = recover(log, preserve_residue=lambda v: "refs/attempts/x")
    assert rep.emitted == [EventType.EXECUTION_CRASHED.value]
    assert EventType.EXECUTION_FINISHED.value not in rep.emitted


def test_recovery_respects_live_execution(tmp_path):
    log = _spawned_log(tmp_path)
    proj, rep = recover(log, is_execution_alive=lambda xid: True)
    assert proj.executions["042-e1"].state is ExecutionState.EXECUTING
    assert rep.emitted == []


def test_recovery_reports_skipped_repo_checks(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    _, rep = recover(log)
    assert set(rep.checks_skipped) == {"unwitnessed_commit", "dirty_workspace"}


# ── config loader (unchanged by reconciliation) ──────────────────
GOOD_YAML = """
project:
  name: StockAgent
  repository: '{repo}'
  branch: agent-work
  issues_file: Issues.md
  validation:
    commands: ['pytest -q']
    timeout_seconds: 600
engine: {{provider: claude-headless, auth_mode: subscription, model: default,
         max_turns: 30, timeout_seconds: 1800}}
reviewer:
  provider: qwen
  qwen: {{endpoint: 'http://localhost:11434', model: qwen2.5-coder}}
budget: {{max_attempts_per_issue: 3, max_executions_per_run: 10,
         proxy_pricing: api_list_rates, hard_stop_proxy_cost_per_run_usd: 15.0}}
experiment: {{sample_size: 20, attempt1_success_min: 0.30,
             cost_per_shipped_issue_max_usd: 3.0}}
billing: {{posture: pro_subscription_headless, headless_split_status: paused,
          verified_on: '2026-07-10', reverify_at: phase-2-gate}}
event_log: {{path: state/events.jsonl}}
attempts: {{ref_namespace: refs/attempts}}
"""


def _write_cfg(tmp_path, repo="/nonexistent") -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(GOOD_YAML.format(repo=repo))
    return p


def test_config_loads_and_is_frozen(tmp_path):
    cfg = load_config(_write_cfg(tmp_path))
    assert cfg.engine.auth_mode == "subscription"
    assert cfg.experiment.cost_per_shipped_issue_max_usd == 3.0
    with pytest.raises(Exception):
        cfg.engine.auth_mode = "api_key"


def test_config_rejects_bad_shapes(tmp_path):
    p = _write_cfg(tmp_path)
    for breakage in [
        ("auth_mode: subscription", "auth_mode: magic"),
        ("provider: qwen", "provider: gpt"),
        ("sample_size: 20", "sample_size: 0"),
    ]:
        broken = tmp_path / "bad.yaml"
        broken.write_text(p.read_text().replace(*breakage))
        with pytest.raises(ConfigError):
            load_config(broken)
    broken = tmp_path / "bad2.yaml"
    broken.write_text(p.read_text().replace("provider: qwen", "provider: claude"))
    with pytest.raises(ConfigError):
        load_config(broken)


def test_environment_validation(tmp_path):
    repo = tmp_path / "target"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "agent-work", str(repo)], check=True)
    (repo / "x").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "init"], check=True)
    cfg = load_config(_write_cfg(tmp_path, repo=str(repo)))
    assert validate_environment(cfg, env={}) == []
    probs = validate_environment(cfg, env={"ANTHROPIC_API_KEY": "sk-x"})
    assert any("subscription" in p for p in probs)
    cfg2 = load_config(_write_cfg(tmp_path, repo="/nope"))
    assert any("does not exist" in p for p in validate_environment(cfg2, env={}))
