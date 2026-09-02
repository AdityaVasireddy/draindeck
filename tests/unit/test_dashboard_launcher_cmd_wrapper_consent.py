"""RED -> GREEN: Start-DraindeckDashboard.cmd must actually invoke winget
(with consent), never just print manual instructions when it is available
(docs/32 review Blocker 1). Runs the real tracked script as a cmd.exe
subprocess with PATH restricted so real Python/winget are hidden and an
ordinary, plain-text Windows batch script stands in for each -- nothing
here compiles anything, downloads anything, or installs real software.

Test-double strategy (independent-review finding, third pass): a first
version of this file used `.cmd` batch stubs directly and reportedly failed
`where`-discovery on at least one host; a second version replaced them with
a C# stub compiled at test-collection time via csc.exe, which fixed that
but made every supported Windows host skip these tests outright whenever a
C# compiler wasn't present, and then a checked-in *compiled binary*
fixture, which independent review flagged as an opaque artifact with no
reproducible proof it was built from its committed source.

This version returns to plain-text `.cmd` stubs -- ordinary, fully
reviewable batch scripts written fresh inside each test's own ``tmp_path``,
with no compiler, no download, and no binary of any kind. Investigating the
earlier discoverability report surfaced a real, distinct bug in the
STRATEGY (not `where` discovery): ``Start-DraindeckDashboard.cmd`` invokes
``winget install ...`` without ``call``, and invoking one batch script from
another without ``call`` never returns control to the caller (confirmed via
a standalone repro: the caller's own trailing lines never ran, and the
overall process exit code became the *callee's* code) -- a real ``.exe``
returns control either way, so this was invisible for years until the test
double for winget itself became a batch script. The fix is the one-line,
harmless-for-a-real-.exe correction in ``Start-DraindeckDashboard.cmd``
(``call winget install ...``) alongside this rewrite; the fix has no
effect on real ``winget.exe`` (``call`` is a documented no-op for external
executables) and makes control flow correct for a batch-script double too.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CMD_SCRIPT = REPO_ROOT / "Start-DraindeckDashboard.cmd"

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Start-DraindeckDashboard.cmd is a Windows-only entry point",
)


def _winget_stub(bin_dir: Path, log_path: Path, *, exit_code: int = 0) -> None:
    """An ordinary, plain-text batch-script test double for `winget`: logs
    its own name plus every argument it received, then exits with
    ``exit_code``. Proves an invocation actually happened (not merely that
    the file exists) by requiring the log to contain real content."""
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "winget.cmd").write_text(
        "@echo off\r\n"
        f'echo winget %* >> "{log_path}"\r\n'
        f"exit /b {exit_code}\r\n",
        encoding="utf-8",
    )


def _py_launcher_stub_content(log_path: Path, *, version_ok: bool) -> str:
    """Content for a plain-text `py.cmd` test double (the `py -3` launcher,
    distinct from `python.cmd`). Recognizes the wrapper's own
    ``py -3 -c ...`` version-probe pattern (``%~1``=="-3", ``%~2``=="-c")
    and answers it with an exit code reflecting ``version_ok`` without
    logging (a version probe is not itself an install action); any other
    invocation (e.g. ``py -3 -m venv ...``) is logged, then fails on
    purpose, matching `_python_stub`'s convention.
    """
    version_exit = 0 if version_ok else 1
    return (
        "@echo off\r\n"
        'if "%~1"=="-3" (\r\n'
        '    if "%~2"=="-c" (\r\n'
        f"        exit /b {version_exit}\r\n"
        "    )\r\n"
        f'    echo py %* >> "{log_path}"\r\n'
        "    exit /b 1\r\n"
        ")\r\n"
        "exit /b 1\r\n"
    )


def _winget_stub_that_installs_py_launcher(bin_dir: Path, log_path: Path, staged_py_cmd: Path) -> None:
    """A `winget` test double that, as a side effect of "installing"
    Python, makes a compatible `py -3` launcher newly available on PATH --
    but deliberately does NOT create a `python.cmd`, simulating a fresh
    Windows install where `py` resolves immediately after install while
    `python` is not yet visible in the current CMD process's PATH."""
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "winget.cmd").write_text(
        "@echo off\r\n"
        f'echo winget %* >> "{log_path}"\r\n'
        f'copy /Y "{staged_py_cmd}" "{bin_dir / "py.cmd"}" >nul\r\n'
        "exit /b 0\r\n",
        encoding="utf-8",
    )


def _python_stub(bin_dir: Path, log_path: Path, *, version_ok: bool) -> None:
    """An ordinary, plain-text batch-script test double for `python`.
    Recognizes the wrapper's own version-probe pattern (``-c ...``, the
    first argument being exactly ``-c``) and answers it with an exit code
    reflecting ``version_ok`` -- WITHOUT logging, since a version probe is
    not itself an "install" action. Any other invocation (e.g. ``-m venv
    ...``) is logged, then fails on purpose, so the wrapper's own error
    handling for that step is what stops the script (matching this file's
    existing convention: prove the call happened, then let the wrapper's
    own failure path end the run cleanly).
    """
    bin_dir.mkdir(exist_ok=True)
    version_exit = 0 if version_ok else 1
    (bin_dir / "python.cmd").write_text(
        "@echo off\r\n"
        'if "%~1"=="-c" (\r\n'
        f"    exit /b {version_exit}\r\n"
        ")\r\n"
        f'echo python %* >> "{log_path}"\r\n'
        "exit /b 1\r\n",
        encoding="utf-8",
    )


def _isolated_env(bin_dir: Path) -> dict:
    env = dict(os.environ)
    # Windows-style, semicolon-separated PATH, with the stub directory
    # FIRST, then the system directory (needed for cmd.exe's own
    # builtins/where/findstr) -- deliberately WITHOUT the rest of the real
    # PATH so no real python or winget is exposed.
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    env["PATH"] = f"{bin_dir};{system32}"
    # Pinned explicitly (defense in depth) rather than inherited: ".CMD" is
    # always in cmd.exe's own built-in PATHEXT default, so a plain `.cmd`
    # test double is found regardless, but some hosts/shells narrow or
    # clear PATHEXT -- pinning it removes that as a variable entirely.
    env["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
    return env


def _run(bin_dir: Path, stdin_text: str, extra_args=()):
    env = _isolated_env(bin_dir)
    result = subprocess.run(
        ["cmd.exe", "/c", str(CMD_SCRIPT), *extra_args],
        cwd=bin_dir.parent, env=env, input=stdin_text.encode("utf-8"),
        capture_output=True, timeout=30,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def test_declining_consent_makes_zero_calls_to_winget(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _winget_stub(bin_dir, log)

    result = _run(bin_dir, stdin_text="n\r\n")

    assert result.returncode != 0
    assert not log.exists(), f"winget must never be invoked on decline; stdout={result.stdout!r}"
    assert "CONSENT_DECLINED" in result.stdout


def test_affirmative_consent_actually_invokes_winget(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _winget_stub(bin_dir, log, exit_code=1)

    result = _run(bin_dir, stdin_text="y\r\n")

    assert log.is_file(), f"winget was never invoked; stdout={result.stdout!r}"
    assert "install" in log.read_text()


def test_yes_flag_bypasses_the_interactive_prompt(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _winget_stub(bin_dir, log, exit_code=1)

    result = _run(bin_dir, stdin_text="", extra_args=["--yes"])

    assert log.is_file()


def _run_isolated(bin_dir: Path, stdin_text: str, extra_args=()):
    # `%~dp0` inside the .cmd always resolves to the directory containing
    # the SCRIPT FILE itself, never the process cwd -- so running the
    # tracked script in place would compute VENV_DIR as THIS repository's
    # own real .venv, which already exists here, skipping straight past
    # any python-stub interception into a REAL pip install against the
    # developer's actual environment. Running an isolated COPY of the
    # script from tmp_path gives it a VENV_DIR with no existing venv, so
    # the python stub is actually reached, exactly like the POSIX wrapper
    # tests (only Windows needs this: those scripts' own venv-exists check
    # already misses this repo's Windows-layout .venv, so they don't need
    # a copy).
    isolated_script = bin_dir.parent / CMD_SCRIPT.name
    isolated_script.write_bytes(CMD_SCRIPT.read_bytes())
    env = _isolated_env(bin_dir)
    result = subprocess.run(
        ["cmd.exe", "/c", str(isolated_script), *extra_args],
        cwd=bin_dir.parent, env=env, input=stdin_text.encode("utf-8"),
        capture_output=True, timeout=30,
    )
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    return result


def test_cold_install_falls_back_to_compatible_py_launcher_after_winget_install(tmp_path):
    """docs/32 review: after a successful winget install, `python` may
    still be absent from the current CMD process's PATH while `py -3` is
    already usable. The wrapper must fall back to `py -3` instead of
    printing the "open a new terminal and re-run" failure -- proceeding
    all the way into venv creation via `py -3 -m venv`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    staged_py = tmp_path / "staged_py.cmd"
    staged_py.write_text(_py_launcher_stub_content(log, version_ok=True), encoding="utf-8")
    _winget_stub_that_installs_py_launcher(bin_dir, log, staged_py)

    result = _run_isolated(bin_dir, stdin_text="y\r\n")

    assert "CONSENT_DECLINED" not in result.stdout
    assert "re-run this script" not in result.stdout.lower(), (
        f"must fall back to the newly-available `py -3` instead of giving up; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert log.is_file(), f"winget was never invoked; stdout={result.stdout!r}"
    log_text = log.read_text()
    assert "winget" in log_text, f"winget must have been invoked; log={log_text!r}"
    assert "py -3 -m venv" in log_text, (
        f"must proceed past Python discovery into venv creation via `py -3 -m venv`; "
        f"log={log_text!r} stdout={result.stdout!r}"
    )


def test_too_old_python_is_treated_exactly_like_missing_python(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _python_stub(bin_dir, log, version_ok=False)
    _winget_stub(bin_dir, log)

    result = _run(bin_dir, stdin_text="n\r\n")

    assert result.returncode != 0
    assert "3.12" in result.stdout, f"must name the required version; stdout={result.stdout!r}"
    assert "CONSENT_DECLINED" in result.stdout
    assert not log.exists(), "winget must never be invoked when consent is declined"


def test_compliant_python_skips_the_install_prompt_entirely(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    _python_stub(bin_dir, log, version_ok=True)

    result = _run_isolated(bin_dir, stdin_text="")

    assert "CONSENT_DECLINED" not in result.stdout
    assert log.is_file(), (
        f"a compatible python must proceed straight to venv creation with no "
        f"install prompt; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "python -m venv" in log.read_text()


def test_missing_winget_reports_an_actionable_failure(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    result = _run(bin_dir, stdin_text="")

    assert result.returncode != 0
    assert "winget" in result.stdout.lower() or "python" in result.stdout.lower()
