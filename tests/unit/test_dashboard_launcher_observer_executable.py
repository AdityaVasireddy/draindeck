"""RED -> GREEN: the normal one-click launch path must never hand the
spawned Dashboard child a bare relative "draindeck" for
``--observer-executable`` (independent-review finding). The tracked
wrapper scripts invoke the venv Python directly without activating the
venv, so ``draindeck`` is commonly absent from PATH even though the
console script exists right beside that same interpreter
(``.venv/Scripts/draindeck.exe`` / ``.venv/bin/draindeck``) --
``DashboardConfig`` requires ``observer_executable`` to be absolute, so a
relative fallback here previously made the spawned child exit immediately
on a config error while the parent still waited out the full 180-second
readiness window for a process that could never become ready.
"""
from __future__ import annotations

import sys
from pathlib import Path

from draindeck_dashboard import launcher


def _sibling_name() -> str:
    return "draindeck.exe" if sys.platform == "win32" else "draindeck"


# ---------------------------------------------------------------------------
# resolve_observer_executable: pure resolution logic
# ---------------------------------------------------------------------------

def test_resolve_observer_executable_prefers_the_absolute_sibling_of_the_interpreter(tmp_path):
    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    python_exe = python_dir / "python.exe"
    python_exe.write_text("")
    sibling = python_dir / "draindeck.exe"
    sibling.write_text("")

    resolved = launcher.resolve_observer_executable(
        platform="win32", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved == str(sibling.resolve())
    assert Path(resolved).is_absolute()


def test_resolve_observer_executable_uses_the_posix_sibling_name_on_non_windows(tmp_path):
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    sibling = python_dir / "draindeck"
    sibling.write_text("")

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved == str(sibling.resolve())


def test_resolve_observer_executable_falls_back_to_which_only_when_it_is_absolute(tmp_path):
    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    python_exe = python_dir / "python.exe"
    python_exe.write_text("")
    # No sibling console script exists in this venv layout.
    found = tmp_path / "Tools" / "draindeck.exe"
    found.parent.mkdir()
    found.write_text("")

    resolved = launcher.resolve_observer_executable(
        platform="win32", python_executable=str(python_exe),
        which=lambda name: str(found),
    )

    assert resolved == str(found)


def test_resolve_observer_executable_ignores_a_relative_which_result(tmp_path):
    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    python_exe = python_dir / "python.exe"
    python_exe.write_text("")

    # A `which` implementation that returns a bare/relative name must never
    # be trusted -- DashboardConfig requires an absolute observer_executable.
    resolved = launcher.resolve_observer_executable(
        platform="win32", python_executable=str(python_exe), which=lambda name: "draindeck.exe",
    )

    assert resolved is None


def test_resolve_observer_executable_returns_none_when_nothing_resolves(tmp_path):
    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    python_exe = python_dir / "python.exe"
    python_exe.write_text("")

    resolved = launcher.resolve_observer_executable(
        platform="win32", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved is None


# ---------------------------------------------------------------------------
# resolve_observer_executable / validate_explicit_observer_executable must
# share ONE usability predicate (independent-review finding): explicit
# validation required the POSIX executable bit, but auto-resolution's
# sibling.is_file() check did not -- a non-executable .venv/bin/draindeck
# could therefore be auto-selected and only fail later, during a real spawn.
# ---------------------------------------------------------------------------

def test_resolve_observer_executable_rejects_a_non_executable_posix_sibling(tmp_path, monkeypatch):
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    sibling = python_dir / "draindeck"
    sibling.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: False)

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved is None


def test_resolve_observer_executable_accepts_an_executable_posix_sibling(tmp_path, monkeypatch):
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    sibling = python_dir / "draindeck"
    sibling.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: True)

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved == str(sibling.resolve())


def test_resolve_observer_executable_rejects_a_non_executable_which_result_on_posix(tmp_path, monkeypatch):
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    # No sibling console script exists -- resolution must fall through to
    # the which() result, and the shared predicate must reject it too.
    found = tmp_path / "draindeck-on-path"
    found.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: False)

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: str(found),
    )

    assert resolved is None


def test_resolve_observer_executable_and_validate_explicit_agree_on_a_non_executable_file(
    tmp_path, monkeypatch,
):
    # Same non-executable file: auto-resolution's sibling path and explicit
    # validation must reach the SAME verdict -- proving both routes share
    # one predicate instead of diverging POSIX-executable-bit logic.
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    sibling = python_dir / "draindeck"
    sibling.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: False)

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: None,
    )
    explicit_valid = launcher.validate_explicit_observer_executable(
        str(sibling.resolve()), platform="linux",
    )

    assert resolved is None
    assert explicit_valid is False


def test_resolve_observer_executable_and_validate_explicit_agree_on_an_executable_file(
    tmp_path, monkeypatch,
):
    python_dir = tmp_path / "bin"
    python_dir.mkdir()
    python_exe = python_dir / "python"
    python_exe.write_text("")
    sibling = python_dir / "draindeck"
    sibling.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: True)

    resolved = launcher.resolve_observer_executable(
        platform="linux", python_executable=str(python_exe), which=lambda name: None,
    )
    explicit_valid = launcher.validate_explicit_observer_executable(
        str(sibling.resolve()), platform="linux",
    )

    assert resolved == str(sibling.resolve())
    assert explicit_valid is True


def test_resolve_observer_executable_still_accepts_a_valid_windows_sibling(tmp_path):
    # Windows has no POSIX executable bit to check -- current valid Windows
    # behavior must remain accepted exactly as before this change.
    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    python_exe = python_dir / "python.exe"
    python_exe.write_text("")
    sibling = python_dir / "draindeck.exe"
    sibling.write_text("")

    resolved = launcher.resolve_observer_executable(
        platform="win32", python_executable=str(python_exe), which=lambda name: None,
    )

    assert resolved == str(sibling.resolve())


# ---------------------------------------------------------------------------
# main(): the resolver is actually wired into the real spawn path
# ---------------------------------------------------------------------------

def test_main_uses_the_absolute_sibling_executable_when_draindeck_is_absent_from_path(
    tmp_path, monkeypatch,
):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    # `draindeck` is NOT on PATH.
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)

    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    fake_python = python_dir / "python.exe"
    fake_python.write_text("")
    sibling = python_dir / _sibling_name()
    sibling.write_text("")
    monkeypatch.setattr(launcher.sys, "executable", str(fake_python))

    spawned = []

    class _FakeProc:
        pid = 999

    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=True, elapsed_seconds=0.1),
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 0
    assert len(spawned) == 1
    argv = spawned[0]
    idx = argv.index("--observer-executable")
    observer_value = argv[idx + 1]
    assert observer_value == str(sibling.resolve())
    assert Path(observer_value).is_absolute()
    assert observer_value != "draindeck", "must never pass a bare relative 'draindeck' to the child"


def test_main_fails_before_popen_when_no_observer_executable_can_be_resolved(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)

    python_dir = tmp_path / "Scripts"
    python_dir.mkdir()
    fake_python = python_dir / "python.exe"
    fake_python.write_text("")
    # No sibling console script created -- nothing resolves.
    monkeypatch.setattr(launcher.sys, "executable", str(fake_python))

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    waited = []
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: waited.append(1) or launcher.WaitResult(ready=True, elapsed_seconds=0.0),
    )

    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420"])

    assert rc == 1
    assert spawned == [], "must never spawn the Dashboard child with no resolvable observer executable"
    assert waited == [], "must fail before ever entering the 180s readiness wait"


def test_main_respects_an_explicit_observer_executable_flag_over_resolution(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)

    def _boom(*a, **k):
        raise AssertionError("resolve_observer_executable must not run when --observer-executable is given")

    monkeypatch.setattr(launcher, "resolve_observer_executable", _boom)

    spawned = []

    class _FakeProc:
        pid = 999

    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda argv, **k: spawned.append(argv) or _FakeProc(),
    )
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: launcher.WaitResult(ready=True, elapsed_seconds=0.1),
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: None)

    explicit = tmp_path / "custom-draindeck.exe"
    explicit.write_text("")
    explicit = str(explicit)
    rc = launcher.main(["--host", "127.0.0.1", "--port", "8420", "--observer-executable", explicit])

    assert rc == 0
    argv = spawned[0]
    assert argv[argv.index("--observer-executable") + 1] == explicit


# ---------------------------------------------------------------------------
# validate_explicit_observer_executable: pure validation logic
# (independent-review finding: an explicit --observer-executable value
# used to bypass resolution entirely and be handed straight to the child,
# even when relative or pointing at nothing -- DashboardConfig requires an
# absolute, real observer_executable, so that failure mode made the child
# exit immediately while the parent still waited out the full 180s.)
# ---------------------------------------------------------------------------

def test_validate_explicit_observer_executable_accepts_an_absolute_existing_file(tmp_path):
    exe = tmp_path / "draindeck.exe"
    exe.write_text("")
    assert launcher.validate_explicit_observer_executable(str(exe), platform="win32") is True


def test_validate_explicit_observer_executable_rejects_a_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("draindeck.exe").write_text("")
    assert launcher.validate_explicit_observer_executable("draindeck.exe", platform="win32") is False


def test_validate_explicit_observer_executable_rejects_an_absolute_missing_path(tmp_path):
    missing = tmp_path / "does-not-exist.exe"
    assert launcher.validate_explicit_observer_executable(str(missing), platform="win32") is False


def test_validate_explicit_observer_executable_rejects_an_absolute_directory(tmp_path):
    assert launcher.validate_explicit_observer_executable(str(tmp_path), platform="win32") is False


def test_validate_explicit_observer_executable_requires_executable_permission_on_posix(tmp_path, monkeypatch):
    exe = tmp_path / "draindeck"
    exe.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: False)
    assert launcher.validate_explicit_observer_executable(str(exe), platform="linux") is False


def test_validate_explicit_observer_executable_accepts_an_executable_file_on_posix(tmp_path, monkeypatch):
    exe = tmp_path / "draindeck"
    exe.write_text("")
    monkeypatch.setattr(launcher.os, "access", lambda path, mode: True)
    assert launcher.validate_explicit_observer_executable(str(exe), platform="linux") is True


def test_validate_explicit_observer_executable_never_checks_executable_bit_on_windows(tmp_path, monkeypatch):
    exe = tmp_path / "draindeck.exe"
    exe.write_text("")

    def _boom(path, mode):
        raise AssertionError("os.access must not be consulted on win32")

    monkeypatch.setattr(launcher.os, "access", _boom)
    assert launcher.validate_explicit_observer_executable(str(exe), platform="win32") is True


# ---------------------------------------------------------------------------
# main(): an invalid explicit --observer-executable fails before Popen
# ---------------------------------------------------------------------------

def test_main_fails_before_popen_when_explicit_observer_executable_is_relative(tmp_path, monkeypatch):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    waited = []
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: waited.append(1) or launcher.WaitResult(ready=True, elapsed_seconds=0.0),
    )

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", "draindeck",
    ])

    assert rc == 1
    assert spawned == [], "a relative --observer-executable must never reach Popen"
    assert waited == [], "must fail before ever entering the 180s readiness wait"


def test_main_fails_before_popen_when_explicit_observer_executable_is_absolute_but_missing(
    tmp_path, monkeypatch,
):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)

    spawned = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: spawned.append(a) or None)
    waited = []
    monkeypatch.setattr(
        launcher, "wait_for_readiness",
        lambda **k: waited.append(1) or launcher.WaitResult(ready=True, elapsed_seconds=0.0),
    )

    missing = str(tmp_path / "does-not-exist-draindeck.exe")
    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", missing,
    ])

    assert rc == 1
    assert spawned == [], "an absolute but non-existent --observer-executable must never reach Popen"
    assert waited == [], "must fail before ever entering the 180s readiness wait"


def test_main_never_rewrites_an_invalid_explicit_observer_executable(tmp_path, monkeypatch, capsys):
    state_path = tmp_path / "launcher-state.json"
    monkeypatch.setattr(launcher, "default_state_path", lambda: state_path)
    monkeypatch.setattr(launcher, "_ensure_prerequisites", lambda args: True)
    monkeypatch.setattr(launcher, "is_port_listening", lambda host, port: False)

    def _boom(*a, **k):
        raise AssertionError("must never spawn with an invalid explicit observer executable")

    monkeypatch.setattr(launcher.subprocess, "Popen", _boom)

    rc = launcher.main([
        "--host", "127.0.0.1", "--port", "8420",
        "--observer-executable", "draindeck",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "OBSERVER_EXECUTABLE_INVALID" in err
    assert "draindeck" in err, "must report the operator's own value, never a silently rewritten one"
