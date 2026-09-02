"""RED -> GREEN: install_missing_prerequisites/select_platform_installer are
actually wired into main()'s real bootstrap flow (docs/32 review Blocker
1), not dead helpers no caller reaches. Every side-effecting call is
mocked -- these tests never touch a real package manager or network.
"""
from __future__ import annotations

from draindeck_dashboard import launcher


def _stub_all_present(monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher, "dashboard_deps_present", lambda: True)


def _stub_missing(monkeypatch, missing_names):
    def which(cmd):
        if cmd in missing_names:
            return None
        return f"/usr/bin/{cmd}"
    monkeypatch.setattr(launcher.shutil, "which", which)
    monkeypatch.setattr(launcher, "dashboard_deps_present", lambda: "dashboard-deps" not in missing_names)


def test_ensure_prerequisites_is_a_noop_when_everything_is_already_present(monkeypatch, tmp_path):
    _stub_all_present(monkeypatch)
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    prompted = []
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: prompted.append(text) or True)

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is True
    assert prompted == [], "the fast path must never show a consent prompt when nothing is missing"


def test_ensure_prerequisites_declined_consent_makes_zero_install_calls(monkeypatch, tmp_path):
    _stub_missing(monkeypatch, {"git"})
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: False)
    calls = []
    monkeypatch.setattr(
        launcher, "real_package_manager_adapter", lambda installer: (lambda item: calls.append(item)),
    )

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is False
    assert calls == []
    assert not (tmp_path / "install-state.json").exists()


def test_ensure_prerequisites_yes_flag_bypasses_the_interactive_prompt(monkeypatch, tmp_path):
    _stub_missing(monkeypatch, {"git"})
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    prompted = []
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: prompted.append(text) or True)
    installed = []
    monkeypatch.setattr(
        launcher, "real_package_manager_adapter", lambda installer: (lambda item: installed.append(item)),
    )

    import argparse
    args = argparse.Namespace(yes=True)
    assert launcher._ensure_prerequisites(args) is True
    assert prompted == [], "--yes must bypass the interactive prompt entirely"
    assert installed == ["git"]


def test_ensure_prerequisites_installs_each_missing_item_on_consent(monkeypatch, tmp_path):
    _stub_missing(monkeypatch, {"git", "claude"})
    state_path = tmp_path / "install-state.json"
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: True)
    installed = []
    monkeypatch.setattr(
        launcher, "real_package_manager_adapter", lambda installer: (lambda item: installed.append(item)),
    )

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is True
    assert sorted(installed) == ["claude", "git"]
    assert not state_path.exists(), "a fully successful install must clear any prior partial state"


def test_ensure_prerequisites_persists_partial_state_and_never_retries_completed_steps(monkeypatch, tmp_path):
    _stub_missing(monkeypatch, {"git", "claude", "ollama"})
    state_path = tmp_path / "install-state.json"
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: True)

    def flaky_adapter(installer):
        def _install(item):
            if item == "claude":
                raise RuntimeError("network unreachable")
        return _install

    monkeypatch.setattr(launcher, "real_package_manager_adapter", flaky_adapter)

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is False
    state = launcher.load_install_state(state_path)
    assert state["completed"] == ["git"]
    assert "claude" in state["remaining"]
    assert "ollama" in state["remaining"]


def test_ensure_prerequisites_resumes_only_remaining_steps_from_persisted_state(monkeypatch, tmp_path):
    _stub_missing(monkeypatch, {"claude", "ollama"})
    state_path = tmp_path / "install-state.json"
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: state_path)
    launcher.save_install_state(state_path, completed=("git",), remaining=("claude", "ollama"))
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: True)
    installed = []
    monkeypatch.setattr(
        launcher, "real_package_manager_adapter", lambda installer: (lambda item: installed.append(item)),
    )

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is True
    assert installed == ["claude", "ollama"], "git was already completed and must never be re-installed"
    assert not state_path.exists()


def test_ensure_prerequisites_never_calls_pip_or_model_puller_when_consent_declined(monkeypatch, tmp_path):
    # Blocker 1: consent=False must make zero package-manager, model-puller,
    # server-starter, OR pip-install calls.
    _stub_missing(monkeypatch, {"dashboard-deps"})
    monkeypatch.setattr(launcher, "default_install_state_path", lambda: tmp_path / "install-state.json")
    monkeypatch.setattr(launcher, "prompt_consent", lambda text: False)
    run_calls = []
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: run_calls.append(a))

    import argparse
    args = argparse.Namespace(yes=False)
    assert launcher._ensure_prerequisites(args) is False
    assert run_calls == []
