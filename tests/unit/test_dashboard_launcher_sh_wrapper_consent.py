"""RED -> GREEN: start-draindeck-dashboard.sh must actually invoke the
detected package manager (with consent), never just print manual
instructions when one is available (docs/32 review Blocker 1). Runs the
real tracked script as a subprocess with PATH manipulated so Python is
hidden and the package manager is a recording stub -- nothing here
installs real software.
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
SH_SCRIPT = REPO_ROOT / "start-draindeck-dashboard.sh"

# Resolved explicitly (never bare "bash"): on Windows, plain "bash" can
# resolve to the WSL launcher shim at C:\Windows\System32\bash.exe instead
# of a real POSIX shell, which then fails to find a Windows-style path at
# all -- this must be the actual git-bash/MSYS bash that can run the script.
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
    # bin_dir first (our stubs), then git-bash's own coreutils (dirname,
    # cat, ...) so the script itself can run -- deliberately WITHOUT the
    # rest of the real PATH, so no real python/apt/winget/brew is exposed.
    env["PATH"] = f"{bin_dir}:/usr/bin"
    env["HOME"] = str(bin_dir.parent)
    # Bytes, not text=True: Python's text-mode stdin write on Windows
    # translates "\n" to "\r\n", which bash's `read -r` then captures as a
    # trailing "\r" that no case pattern matches -- send exactly "\n".
    result = subprocess.run(
        [_BASH, SH_SCRIPT.as_posix(), *extra_args],
        cwd=bin_dir.parent, env=env, input=stdin_text.encode("utf-8"),
        capture_output=True, timeout=20,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def test_declining_consent_makes_zero_calls_to_the_detected_package_manager(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub(bin_dir, "apt", log)
    _make_stub(bin_dir, "sudo", log)

    result = _run(bin_dir, stdin_text="n\n")

    assert result.returncode != 0
    assert not log.exists(), f"apt/sudo must never be invoked on decline; stderr={result.stderr!r}"
    assert "CONSENT_DECLINED" in result.stdout


def test_affirmative_consent_actually_invokes_the_detected_package_manager(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    # The stub "fails" on purpose so the script stops right after invoking
    # it -- this test only needs to prove the real call happened, not
    # exercise the rest of the (real pip install) bootstrap.
    _make_stub(bin_dir, "apt", log, exit_code=1)
    _make_stub(bin_dir, "sudo", log)

    result = _run(bin_dir, stdin_text="y\n")

    assert log.is_file(), f"apt was never invoked; stdout={result.stdout!r} stderr={result.stderr!r}"
    logged = log.read_text()
    assert "apt install" in logged or "sudo" in logged


def test_yes_flag_bypasses_the_interactive_prompt_entirely(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_stub(bin_dir, "apt", log, exit_code=1)
    _make_stub(bin_dir, "sudo", log)

    # No stdin provided at all -- if the script were still prompting
    # interactively, it would hang or fail to read; --yes must skip that.
    result = _run(bin_dir, stdin_text="", extra_args=["--yes"])

    assert log.is_file()


def _make_python_stub(bin_dir: Path, name: str, log_path: Path, *, version_ok: bool) -> None:
    # Responds to a `-c "..."` version-check invocation with the requested
    # exit code; any OTHER invocation (e.g. `-m venv`) is logged then fails
    # on purpose, so a test only needs to prove how far the script got
    # (mirrors the existing _make_stub "fail right after being invoked"
    # convention used for the package-manager stubs above).
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
    # docs/32 review Blocker 4: a Python interpreter that IS on PATH but is
    # older than 3.12 must reach the exact same consent-gated install
    # manifest as no Python at all -- never silently accepted.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_python_stub(bin_dir, "python3", log, version_ok=False)
    _make_stub(bin_dir, "apt", log)
    _make_stub(bin_dir, "sudo", log)

    result = _run(bin_dir, stdin_text="n\n")

    assert result.returncode != 0
    assert "3.12" in result.stdout, f"must name the required version; stdout={result.stdout!r}"
    assert "CONSENT_DECLINED" in result.stdout
    logged = log.read_text() if log.exists() else ""
    assert "apt" not in logged and "sudo" not in logged, (
        "a too-old python must reach the same consent gate as a missing one, and "
        "declining it must invoke zero package-manager calls"
    )


def test_compliant_python_skips_the_install_prompt_entirely(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _make_python_stub(bin_dir, "python3", log, version_ok=True)

    result = _run(bin_dir, stdin_text="")

    assert "missing" not in result.stdout.lower()
    assert "CONSENT_DECLINED" not in result.stdout
    assert log.is_file(), (
        f"a compatible python must proceed straight to venv creation with no "
        f"install prompt; stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_no_supported_package_manager_reports_an_actionable_failure_not_a_silent_default(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Nothing on PATH at all: no python, no apt/dnf/pacman/zypper.
    result = _run(bin_dir, stdin_text="")

    assert result.returncode != 0
    assert "package manager" in result.stdout.lower() or "package manager" in result.stderr.lower()
