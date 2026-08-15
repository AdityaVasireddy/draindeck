"""B7 command-boundary tests: safe recovery and observational diagnostics."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.events.log import EventLog
from runtime.events.schema import Event, EventType
from runtime.recovery.reconciler import RecoveryReport


def _created_log(path: Path, *, torn: bool = False) -> bytes:
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
    if torn:
        with open(path, "ab") as fh:
            fh.write(b'{"event_id":2')
    return path.read_bytes()


@pytest.mark.parametrize("command_name", ["cmd_verify_log", "cmd_show_state"])
def test_diagnostics_read_complete_log_without_mutation(tmp_path, capsys, command_name):
    from runtime import main

    path = tmp_path / "state" / "events.jsonl"
    before = _created_log(path)
    entries = sorted(item.name for item in path.parent.iterdir())

    assert getattr(main, command_name)(SimpleNamespace(log=str(path))) == 0
    assert path.read_bytes() == before
    assert sorted(item.name for item in path.parent.iterdir()) == entries
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("command_name", ["cmd_verify_log", "cmd_show_state"])
def test_diagnostics_report_torn_log_without_mutation(tmp_path, capsys, command_name):
    from runtime import main

    path = tmp_path / "state" / "events.jsonl"
    before = _created_log(path, torn=True)
    entries = sorted(item.name for item in path.parent.iterdir())

    assert getattr(main, command_name)(SimpleNamespace(log=str(path))) == 1
    assert "INCOMPLETE" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert sorted(item.name for item in path.parent.iterdir()) == entries
    assert not list(path.parent.glob("events.jsonl.torn.*"))


@pytest.mark.parametrize("command_name", ["cmd_verify_log", "cmd_show_state"])
def test_diagnostics_do_not_create_missing_log(tmp_path, capsys, command_name):
    from runtime import main

    path = tmp_path / "missing" / "events.jsonl"

    assert getattr(main, command_name)(SimpleNamespace(log=str(path))) == 1
    assert "MISSING" in capsys.readouterr().err
    assert not path.exists()
    assert not path.parent.exists()


def _recovery_cfg(path: Path):
    cfg = mock.MagicMock()
    cfg.project.repository = "C:/b7-unit-workspace"
    cfg.project.branch = "agent-work"
    cfg.event_log.path = str(path)
    cfg.attempts.ref_namespace = "refs/attempts"
    return cfg


def _lease(*, acquired: bool = True):
    lease = mock.MagicMock(acquired=acquired, workspace_key="ws-b7")
    lease.state.value = "ACQUIRED" if acquired else "UNAVAILABLE"
    lease.detail = "ok" if acquired else "held"
    return lease


def test_configured_recover_stops_before_log_when_workspace_is_owned(capsys):
    from runtime import main

    cfg = _recovery_cfg(Path("C:/b7-unit/events.jsonl"))
    lease = _lease(acquired=False)
    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main, "EventLog") as event_log, \
         mock.patch.object(main, "resolve_startup_containment") as containment, \
         mock.patch.object(main, "recover") as recovery:
        assert main.cmd_recover(SimpleNamespace(config="runtime.yaml")) == 1

    assert "WORKSPACE OWNERSHIP UNAVAILABLE" in capsys.readouterr().err
    assert not event_log.called
    assert not containment.called
    assert not recovery.called


def test_configured_recover_uses_normal_safety_boundary_and_closes_resources():
    from runtime import main

    cfg = _recovery_cfg(Path("C:/b7-unit/events.jsonl"))
    lease = _lease()
    log = mock.MagicMock()
    engine = mock.MagicMock()
    engine.is_execution_alive = lambda _execution_id: True
    calls = []
    report = RecoveryReport(replayed_events=1)
    projection = mock.MagicMock()
    projection.digest.return_value = "digest"

    def make_log(_path):
        calls.append("log")
        return log

    def make_engine(*_args):
        calls.append("engine")
        return engine

    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main.WorkspaceLease, "acquire", side_effect=lambda _path: calls.append("lease") or lease), \
         mock.patch.object(main, "EventLog", side_effect=make_log), \
         mock.patch.object(main, "resolve_startup_containment", side_effect=lambda *_a, **_k: calls.append("containment")), \
         mock.patch.object(main.Path, "mkdir"), \
         mock.patch.object(main, "ClaudeHeadlessEngine", side_effect=make_engine), \
         mock.patch.object(main, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main, "bind_reconciler", return_value={}), \
         mock.patch.object(main, "recover", side_effect=lambda *_a, **kw: (calls.append("recover") or (projection, report))) as recovery:
        engine.reap_orphans.side_effect = lambda: calls.append("reap") or []
        assert main.cmd_recover(SimpleNamespace(config="runtime.yaml")) == 0

    assert calls == ["lease", "log", "containment", "engine", "reap", "recover"]
    assert recovery.call_args.kwargs["is_execution_alive"] is engine.is_execution_alive
    assert recovery.call_args.kwargs["workspace_key"] == "ws-b7"
    log.close.assert_called_once()
    lease.release_and_close.assert_called_once()


@pytest.mark.parametrize("is_alive, expected_crashes", [(True, []), (False, ["042-e1"])])
def test_configured_recover_supplies_liveness_and_releases_writer(tmp_path, is_alive, expected_crashes):
    from runtime import main

    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.append(Event(EventType.ISSUE_CREATED, issue_id="042"))
        log.append(Event(EventType.ISSUE_ACTIVATED, issue_id="042"))
        log.append(Event(EventType.EXECUTION_SPAWNED, issue_id="042", execution_id="042-e1"))
    cfg = _recovery_cfg(path)
    lease = _lease()
    engine = mock.MagicMock()
    engine.is_execution_alive = lambda _execution_id: is_alive
    engine.reap_orphans.return_value = []

    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main, "resolve_startup_containment"), \
         mock.patch.object(main.Path, "mkdir"), \
         mock.patch.object(main, "ClaudeHeadlessEngine", return_value=engine), \
         mock.patch.object(main, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main, "bind_reconciler", return_value={}):
        assert main.cmd_recover(SimpleNamespace(config="runtime.yaml")) == 0

    with EventLog(path) as successor:
        crashed = [event.execution_id for event in successor.replay()
                   if event.type is EventType.EXECUTION_CRASHED]
    assert crashed == expected_crashes
    lease.release_and_close.assert_called_once()


def test_configured_recover_releases_writer_when_bound_recovery_fails(tmp_path):
    from runtime import main

    path = tmp_path / "events.jsonl"
    with EventLog(path):
        pass
    cfg = _recovery_cfg(path)
    lease = _lease()
    engine = mock.MagicMock(reap_orphans=lambda: [])

    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main, "resolve_startup_containment"), \
         mock.patch.object(main.Path, "mkdir"), \
         mock.patch.object(main, "ClaudeHeadlessEngine", return_value=engine), \
         mock.patch.object(main, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main, "bind_reconciler", return_value={}), \
         mock.patch.object(main, "recover", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            main.cmd_recover(SimpleNamespace(config="runtime.yaml"))

    with EventLog(path):
        pass
    lease.release_and_close.assert_called_once()


def test_startup_failure_releases_workspace_lease_when_log_close_fails():
    """A failed log cleanup must not strand workspace ownership."""
    from runtime import main

    cfg = _recovery_cfg(Path("C:/b7-unit/events.jsonl"))
    lease = _lease()
    log = mock.MagicMock()
    cleanup_calls = []

    def fail_log_close():
        cleanup_calls.append("log.close")
        raise RuntimeError("log close failed")

    def release_lease():
        cleanup_calls.append("lease.release")

    log.close.side_effect = fail_log_close
    lease.release_and_close.side_effect = release_lease

    with mock.patch.object(main.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main, "EventLog", return_value=log), \
         mock.patch.object(main, "resolve_startup_containment",
                           side_effect=RuntimeError("startup failed")):
        with pytest.raises(RuntimeError, match="startup failed"):
            main._open_startup_recovery(cfg)

    log.close.assert_called_once()
    lease.release_and_close.assert_called_once()
    assert cleanup_calls == ["log.close", "lease.release"]


@pytest.mark.parametrize("outcome", [0, RuntimeError("boom")])
def test_run_releases_startup_resources_on_success_and_exception(outcome):
    from runtime import main

    cfg = _recovery_cfg(Path("C:/b7-unit/events.jsonl"))
    startup = mock.MagicMock()
    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main, "_open_startup_recovery", return_value=startup), \
         mock.patch.object(main, "_run_after_startup",
                           side_effect=outcome if isinstance(outcome, Exception) else None,
                           return_value=outcome if not isinstance(outcome, Exception) else mock.DEFAULT):
        if isinstance(outcome, Exception):
            with pytest.raises(RuntimeError, match="boom"):
                main.cmd_run(SimpleNamespace(config="runtime.yaml", skip_baseline=True))
        else:
            assert main.cmd_run(SimpleNamespace(config="runtime.yaml", skip_baseline=True)) == 0
    startup.close.assert_called_once()


@pytest.mark.parametrize("outcome", [0, RuntimeError("boom")])
def test_run_releases_real_event_log_writer_on_success_and_exception(tmp_path, outcome):
    from runtime import main

    path = tmp_path / "events.jsonl"
    cfg = _recovery_cfg(path)
    lease = _lease()
    engine = mock.MagicMock(reap_orphans=lambda: [],
                            is_execution_alive=lambda _execution_id: False)
    projection = mock.MagicMock()
    report = RecoveryReport(replayed_events=1)
    with mock.patch.object(main, "load_config", return_value=cfg), \
         mock.patch.object(main, "validate_environment", return_value=[]), \
         mock.patch.object(main.WorkspaceLease, "acquire", return_value=lease), \
         mock.patch.object(main, "resolve_startup_containment"), \
         mock.patch.object(main, "ClaudeHeadlessEngine", return_value=engine), \
         mock.patch.object(main, "GitCliAdapter", return_value=mock.MagicMock()), \
         mock.patch.object(main, "bind_reconciler", return_value={}), \
         mock.patch.object(main, "recover", return_value=(projection, report)), \
         mock.patch.object(main, "_run_after_startup",
                           side_effect=outcome if isinstance(outcome, Exception) else None,
                           return_value=outcome if not isinstance(outcome, Exception) else mock.DEFAULT):
        if isinstance(outcome, Exception):
            with pytest.raises(RuntimeError, match="boom"):
                main.cmd_run(SimpleNamespace(config="runtime.yaml", skip_baseline=True))
        else:
            assert main.cmd_run(SimpleNamespace(config="runtime.yaml", skip_baseline=True)) == 0

    with EventLog(path):
        pass
    lease.release_and_close.assert_called_once()
