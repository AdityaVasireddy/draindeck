"""RED -> GREEN: "dashboard-deps" must be a real, consent-gated PIP install
path -- not routed through the OS package manager (independent-review
finding). Before this fix, `detect_missing_prerequisites` could emit
"dashboard-deps", but `_ensure_prerequisites` always built its installer
via `real_package_manager_adapter`, whose `install_command_for` has no
case for "dashboard-deps" and raises `ValueError` -- so an affirmative,
explicit consent to install the missing dashboard extra always reported
INSTALL_FAILED without ever actually running pip.
"""
from __future__ import annotations

import argparse

import pytest

from draindeck_dashboard import launcher


def test_real_package_manager_adapter_has_no_case_for_dashboard_deps(monkeypatch):
    # Guards the ORIGINAL bug directly: the OS package-manager adapter must
    # still fail closed for "dashboard-deps" -- production code must route
    # around it via combined_prerequisite_adapter, never "fix" this adapter
    # itself to secretly know about a PyPI package.
    installer = launcher.PlatformInstaller("win32", "winget", "note")
    adapter = launcher.real_package_manager_adapter(installer)
    with pytest.raises(ValueError):
        adapter("dashboard-deps")


def test_combined_prerequisite_adapter_routes_dashboard_deps_to_pip_and_everything_else_to_the_package_manager(
    monkeypatch,
):
    installer = launcher.PlatformInstaller("win32", "winget", "note")
    pm_calls = []
    monkeypatch.setattr(launcher, "real_package_manager_adapter", lambda inst: pm_calls.append)
    pip_calls = []
    monkeypatch.setattr(launcher, "default_dashboard_deps_installer", lambda: pip_calls.append)

    adapter = launcher.combined_prerequisite_adapter(installer)
    adapter("git")
    adapter("dashboard-deps")

    assert pm_calls == ["git"]
    assert pip_calls == ["dashboard-deps"]


def test_default_dashboard_deps_installer_installs_editable_dashboard_extra_into_the_active_interpreter(
    monkeypatch, tmp_path,
):
    calls = []
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda argv, **k: calls.append((argv, k)) or launcher.subprocess.CompletedProcess(argv, 0),
    )
    install = launcher.default_dashboard_deps_installer(
        project_root=tmp_path, python_executable=r"C:\venv\Scripts\python.exe",
    )
    install("dashboard-deps")

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [r"C:\venv\Scripts\python.exe", "-m", "pip", "install", "-e", f"{tmp_path}[dashboard]"]
    assert kwargs.get("shell", False) is False
    assert kwargs.get("check") is True


def test_declining_consent_with_only_dashboard_deps_missing_makes_zero_pip_or_package_manager_calls(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher, "dashboard_deps_present", lambda: False)
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: False)
    run_calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: run_calls.append(a))

    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is False
    assert run_calls == []


def test_consenting_with_only_dashboard_deps_missing_runs_a_real_pip_action_never_the_package_manager(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher, "dashboard_deps_present", lambda: False)
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: True)

    run_calls = []
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda argv, **k: run_calls.append((argv, k)) or launcher.subprocess.CompletedProcess(argv, 0),
    )

    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is True
    assert len(run_calls) == 1
    argv, kwargs = run_calls[0]
    assert argv[1:4] == ["-m", "pip", "install"]
    assert "-e" in argv
    assert argv[-1].endswith("[dashboard]")
    assert kwargs.get("shell", False) is False
    assert "winget" not in " ".join(argv)


def test_a_prior_dashboard_deps_failure_is_persisted_and_resumes_through_the_pip_adapter(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher, "dashboard_deps_present", lambda: False)
    state_path = tmp_path / "install-state.json"
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: True)

    fail_calls = []

    def flaky_run(argv, **k):
        fail_calls.append(argv)
        raise RuntimeError("pip network error")

    monkeypatch.setattr(launcher.subprocess, "run", flaky_run)

    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is False
    state = launcher.load_install_state(state_path)
    assert state["remaining"] == ["dashboard-deps"]
    assert len(fail_calls) == 1

    ok_calls = []
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda argv, **k: ok_calls.append(argv) or launcher.subprocess.CompletedProcess(argv, 0),
    )
    assert launcher._ensure_prerequisites(args) is True
    assert len(ok_calls) == 1
    assert ok_calls[0][1:4] == ["-m", "pip", "install"]
    assert not state_path.exists()
