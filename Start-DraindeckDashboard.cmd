@echo off
setlocal enabledelayedexpansion

rem One-click Windows launcher for the Draindeck Dashboard (docs/32).
rem Minimal standard-library bootstrap: find or, with explicit per-
rem invocation consent, actually install Python via winget (never
rem silently), create or reuse .venv, install the dashboard extra, then
rem hand off to the shared, testable launcher implementation at
rem src\draindeck_dashboard\launcher.py, which performs every remaining
rem decision (further prerequisite consent, process reuse, readiness,
rem browser open).
rem
rem NOTE: control flow below deliberately avoids nesting `if errorlevel`
rem blocks inside one another -- cmd.exe has a well-documented quirk where
rem `exit /b N` from inside a nested if-block can be swallowed, silently
rem returning exit code 0 to the caller. Flat goto/label structure avoids
rem this entirely; every `if errorlevel` here is single-level.

set "REPO_DIR=%~dp0"
set "VENV_DIR=%REPO_DIR%.venv"
set "PY=python"
set "DRAINDECK_YES=0"

for %%A in (%*) do (
    if /I "%%~A"=="--yes" set "DRAINDECK_YES=1"
)

set "PY_OK=0"
where python >nul 2>nul
if errorlevel 1 goto :try_py_launcher
set "PY=python"
call :check_py_version
if "!PY_OK!"=="1" goto :have_python

:try_py_launcher
where py >nul 2>nul
if errorlevel 1 goto :need_python
set "PY=py -3"
call :check_py_version
if "!PY_OK!"=="1" goto :have_python

:need_python
where winget >nul 2>nul
if errorlevel 1 goto :no_winget

echo The following prerequisite is missing:
echo   - Python.Python.3.12 (source: winget; may prompt for per-package UAC; small download)
echo       $ winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
if "!DRAINDECK_YES!"=="1" goto :install_python
set /p REPLY="Install the above now? [y/N] "
if /I "!REPLY!"=="y" goto :install_python
if /I "!REPLY!"=="yes" goto :install_python
echo CONSENT_DECLINED
exit /b 1

:install_python
rem `call` is required here even though winget is a real executable, which
rem is unaffected by it either way. Without `call`, a batch-file winget
rem test double would never return control to this script after it exits --
rem invoking one .cmd/.bat from another without `call` permanently
rem transfers execution instead of returning.
call winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
where python >nul 2>nul
if errorlevel 1 goto :post_install_try_py
set "PY=python"
call :check_py_version
if "!PY_OK!"=="1" goto :have_python

:post_install_try_py
rem docs/32 review Blocker 8: a fresh Windows install commonly resolves
rem `py` through the `py` launcher immediately after a winget install
rem while `python` is not yet visible in the current CMD process's PATH.
rem Try the same compatible-interpreter fallback used before install --
rem exactly once, never looping back into a second install prompt.
where py >nul 2>nul
if errorlevel 1 goto :py_still_unavailable
set "PY=py -3"
call :check_py_version
if "!PY_OK!"=="1" goto :have_python

:py_still_unavailable
rem docs/32 review Blocker 4: winget may only offer a version older than
rem 3.12 on some hosts -- fail clearly here rather than continuing into a
rem later pip install against an incompatible interpreter.
echo Python 3.12+ still not available on PATH after installation. Open a
echo new terminal ^(PATH may need to refresh^) and re-run this script; if
echo the problem persists, install Python 3.12+ manually from
echo https://www.python.org/downloads/
exit /b 1

:no_winget
echo Python 3.12+ was not found on PATH, and winget was not found either.
echo Install Python 3.12+ manually from https://www.python.org/downloads/
echo then re-run this script.
exit /b 1

:have_python
if exist "%VENV_DIR%\Scripts\python.exe" goto :venv_ready
echo Creating virtual environment at "%VENV_DIR%" ...
call %PY% -m venv "%VENV_DIR%"
if errorlevel 1 (
    echo Failed to create the virtual environment.
    exit /b 1
)

:venv_ready
echo Installing/updating draindeck[dashboard] ...
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade -e "%REPO_DIR%.[dashboard]"
if errorlevel 1 (
    echo Failed to install draindeck[dashboard] into the virtual environment.
    exit /b 1
)
echo draindeck[dashboard] installed.

"%VENV_DIR%\Scripts\python.exe" -m draindeck_dashboard.launcher %*
exit /b %errorlevel%

goto :eof

rem docs/32 review Blocker 4: a Python that IS on PATH but is older than
rem 3.12 must be treated exactly like a missing Python -- never silently
rem accepted, since the Dashboard requires 3.12+. Sets PY_OK to 1/0; kept
rem as a `call`ed subroutine (never `exit /b` inside it) so it composes
rem with the flat goto/label discipline above rather than nesting.
:check_py_version
call %PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :py_version_bad
set "PY_OK=1"
goto :eof

:py_version_bad
set "PY_OK=0"
goto :eof
