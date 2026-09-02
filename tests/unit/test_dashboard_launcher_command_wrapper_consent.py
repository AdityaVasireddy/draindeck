"""RED -> GREEN: Start-DraindeckDashboard.command must actually invoke
Homebrew (with consent), never just print manual instructions when it is
available (docs/32 review Blocker 1). Same execution approach as the
Linux .sh wrapper test -- see that file's comments for the Windows
bash-resolution and stdin-newline notes that apply here too.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND_SCRIPT = REPO_ROOT / "Start-DraindeckDashboard.command"

_BASH = None
for _candidate in (
    r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe",
):
    if Path(_candidate).is_file():
        _BASH = _candidate
        break
if _BASH is None and sys.platform != "win32":
    _BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(_BASH is None, reason="requires a real POSIX bash (git-bash/MSYS)")


def _make_stub(bin_dir: Path, name: str, log_path: Path, exit_code: int = 0) -> None:
    script = bin_dir / name
    script.write_text(
        "#!/bin/sh\n"
        f'echo "{name} $*" >> "{log_path.as_posix()}"\n'
        f"exit {exit_code}\n",
    )
    st = script.stat()
    script.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(bin_dir: Path, stdin_text: str, extra_args=()):
    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:/usr/bin"
    env["HOME"] = str(bin_dir.parent)
    result = subprocess.run(
        [_BASH, COMMAND_SCRIPT.as_posix(), *extra_args],
        cwd=bin_dir.parent, env=env, input=stdin_text.encode("utf-8"),
        capture_output=True, timeout=20,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def test_declining_consent_makes_zero_calls_to_homebrew(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub(bin_dir, "brew", log)

    result = _run(bin_dir, stdin_text="n\n")

    assert result.returncode != 0
    assert not log.exists(), f"brew must never be invoked on decline; stdout={result.stdout!r}"
    assert "CONSENT_DECLINED" in result.stdout


def test_affirmative_consent_actually_invokes_homebrew(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub(bin_dir, "brew", log, exit_code=1)

    result = _run(bin_dir, stdin_text="y\n")

    assert log.is_file(), f"brew was never invoked; stdout={result.stdout!r}"
    assert "install" in log.read_text()


def test_yes_flag_bypasses_the_interactive_prompt(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub(bin_dir, "brew", log, exit_code=1)

    result = _run(bin_dir, stdin_text="", extra_args=["--yes"])

    assert log.is_file()


def _make_python_stub(bin_dir: Path, name: str, log_path: Path, *, version_ok: bool) -> None:
    script = bin_dir / name
    version_exit = 0 if version_ok else 1
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then\n'
        f"    exit {version_exit}\n"
        "fi\n"
        f'echo "{name} $*" >> "{log_path.as_posix()}"\n'
        "exit 1\n",
    )
    st = script.stat()
    script.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def test_too_old_python_is_treated_exactly_like_missing_python(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_python_stub(bin_dir, "python3", log, version_ok=False)
    _make_stub(bin_dir, "brew", log)

    result = _run(bin_dir, stdin_text="n\n")

    assert result.returncode != 0
    assert "3.12" in result.stdout, f"must name the required version; stdout={result.stdout!r}"
    assert "CONSENT_DECLINED" in result.stdout
    assert not log.exists(), "brew must never be invoked when consent is declined"


def test_compliant_python_skips_the_install_prompt_entirely(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_python_stub(bin_dir, "python3", log, version_ok=True)

    result = _run(bin_dir, stdin_text="")

    assert "CONSENT_DECLINED" not in result.stdout
    assert log.is_file(), (
        f"a compatible python must proceed straight to venv creation with no "
        f"install prompt; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_missing_homebrew_reports_an_actionable_failure(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    result = _run(bin_dir, stdin_text="")

    assert result.returncode != 0
    assert "brew" in result.stdout.lower() or "homebrew" in result.stdout.lower()
