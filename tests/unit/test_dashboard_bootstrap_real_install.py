"""RED -> GREEN: install_missing_prerequisites/select_platform_installer are
wired into a real detection -> manifest -> consent -> install flow, using
verified vendor package identifiers (docs/32 review Blocker 1), not merely
existing as unused pure functions.
"""
from __future__ import annotations

import pytest

from draindeck_dashboard import launcher


def _installer(platform, package_manager):
    return launcher.PlatformInstaller(platform, package_manager, "test elevation note")


# ---------------------------------------------------------------------------
# Detection -> manifest
# ---------------------------------------------------------------------------

def test_detect_missing_prerequisites_reports_only_absent_items():
    missing = launcher.detect_missing_prerequisites(
        installer=_installer("win32", "winget"),
        git_present=True, claude_present=False, ollama_present=False,
        dashboard_deps_present=True,
    )
    names = {p.name for p in missing}
    assert names == {"claude", "ollama"}


def test_detect_missing_prerequisites_reports_nothing_when_all_present():
    missing = launcher.detect_missing_prerequisites(
        installer=_installer("win32", "winget"),
        git_present=True, claude_present=True, ollama_present=True,
        dashboard_deps_present=True,
    )
    assert missing == ()


def test_render_prerequisite_manifest_shows_item_source_command_and_flags():
    missing = launcher.detect_missing_prerequisites(
        installer=_installer("darwin", "brew"),
        git_present=False, claude_present=True, ollama_present=True,
        dashboard_deps_present=True,
    )
    text = launcher.render_prerequisite_manifest(missing)
    assert "git" in text
    assert "brew install git" in text
    assert "elevation" in text.lower()


# ---------------------------------------------------------------------------
# Verified vendor package identifiers (not invented)
# ---------------------------------------------------------------------------

def test_claude_code_install_command_uses_the_verified_winget_id():
    cmd = launcher.install_command_for("claude", _installer("win32", "winget"))
    assert cmd[:2] == ("winget", "install")
    assert "Anthropic.ClaudeCode" in cmd


def test_claude_code_install_command_uses_the_verified_homebrew_cask():
    cmd = launcher.install_command_for("claude", _installer("darwin", "brew"))
    assert cmd == ("brew", "install", "--cask", "claude-code")


def test_ollama_install_command_uses_the_verified_winget_id():
    cmd = launcher.install_command_for("ollama", _installer("win32", "winget"))
    assert cmd[:2] == ("winget", "install")
    assert "Ollama.Ollama" in cmd


def test_ollama_install_command_uses_the_verified_homebrew_formula():
    cmd = launcher.install_command_for("ollama", _installer("darwin", "brew"))
    assert cmd == ("brew", "install", "ollama")


def test_linux_claude_and_ollama_have_no_automatic_install_command(monkeypatch):
    # Review Blocker 6: neither tool has an official apt/dnf/pacman/zypper
    # package, and this launcher no longer treats their documented
    # `curl | bash` one-liner as something it will download and execute --
    # that is a mutable, unsigned remote script with no version pin or
    # integrity check. install_command_for must return None (never a
    # fabricated package name, and never the curl/bash pipeline) so callers
    # fail closed instead of silently claiming automatic installation.
    for manager in ("apt", "dnf", "pacman", "zypper"):
        assert launcher.install_command_for("claude", _installer("linux", manager)) is None
        assert launcher.install_command_for("ollama", _installer("linux", manager)) is None


def test_linux_manifest_shows_manual_install_instructions_for_claude_and_ollama():
    missing = launcher.detect_missing_prerequisites(
        installer=_installer("linux", "apt"),
        git_present=True, claude_present=False, ollama_present=False,
        dashboard_deps_present=True,
    )
    text = launcher.render_prerequisite_manifest(missing)
    assert "MANUAL INSTALL REQUIRED" in text
    assert "code.claude.com" in text
    assert "ollama.com" in text
    # No mutable install-then-pipe-to-bash instruction is ever displayed as
    # something this launcher will run automatically.
    assert "| bash" not in text
    assert "curl" not in text


def test_git_install_command_uses_the_detected_manager_generically():
    assert launcher.install_command_for("git", _installer("win32", "winget"))[:2] == ("winget", "install")
    assert launcher.install_command_for("git", _installer("darwin", "brew")) == ("brew", "install", "git")
    assert launcher.install_command_for("git", _installer("linux", "apt"))[:1] == ("sudo",)


# ---------------------------------------------------------------------------
# Consent prompts
# ---------------------------------------------------------------------------

def test_prompt_consent_requires_affirmative_yes_default_is_no():
    assert launcher.prompt_consent("manifest text", input_fn=lambda _: "") is False
    assert launcher.prompt_consent("manifest text", input_fn=lambda _: "n") is False
    assert launcher.prompt_consent("manifest text", input_fn=lambda _: "no") is False
    assert launcher.prompt_consent("manifest text", input_fn=lambda _: "y") is True
    assert launcher.prompt_consent("manifest text", input_fn=lambda _: "YES") is True


def test_prompt_model_pull_consent_is_a_separate_gate_from_general_install_consent():
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return "y"

    assert launcher.prompt_model_pull_consent("qwen2.5-coder:7b", input_fn=fake_input) is True
    assert any("qwen2.5-coder:7b" in p for p in prompts)


# ---------------------------------------------------------------------------
# Real argv-only execution (shell=False everywhere) for winget/brew; Linux
# claude/ollama fail closed instead of ever downloading+executing a remote
# script (review Blocker 6).
# ---------------------------------------------------------------------------

def test_real_package_manager_adapter_runs_argv_only_never_a_shell_string(monkeypatch):
    calls = []
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or launcher.subprocess.CompletedProcess(argv, 0),
    )
    adapter = launcher.real_package_manager_adapter(_installer("win32", "winget"))
    adapter("git")
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert isinstance(argv, list)
    assert kwargs.get("shell", False) is False
    assert kwargs.get("check") is True


def test_real_package_manager_adapter_never_downloads_or_executes_anything_for_linux_claude_or_ollama(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        launcher.subprocess, "run",
        lambda argv, **kwargs: calls.append((list(argv), kwargs)) or launcher.subprocess.CompletedProcess(argv, 0),
    )
    adapter = launcher.real_package_manager_adapter(_installer("linux", "apt"))

    with pytest.raises(launcher.ManualLinuxInstallRequiredError):
        adapter("ollama")
    with pytest.raises(launcher.ManualLinuxInstallRequiredError):
        adapter("claude")

    # Zero subprocess calls of any kind -- never a curl download, never an
    # execution of a downloaded file, on this platform for these items.
    assert calls == []


# ---------------------------------------------------------------------------
# Install-state persistence (operational state, never target config)
# ---------------------------------------------------------------------------

def test_install_state_round_trips_completed_and_remaining(tmp_path):
    path = tmp_path / "install-state.json"
    assert launcher.load_install_state(path) is None
    launcher.save_install_state(path, completed=("git",), remaining=("claude", "ollama"))
    state = launcher.load_install_state(path)
    assert state == {"completed": ["git"], "remaining": ["claude", "ollama"]}
    launcher.clear_install_state(path)
    assert launcher.load_install_state(path) is None
