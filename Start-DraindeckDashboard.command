#!/bin/sh
# One-click macOS launcher for the Draindeck Dashboard (docs/32).
# Minimal standard-library bootstrap: find or, with explicit per-invocation
# consent, actually install Python via Homebrew (never silently), create
# or reuse .venv, install the dashboard extra, then hand off to the
# shared, testable launcher implementation at
# src/draindeck_dashboard/launcher.py, which performs every remaining
# decision (further prerequisite consent, process reuse, readiness,
# browser open). Double-clickable from Finder (.command).
set -eu

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$REPO_DIR/.venv"

_have() { command -v "$1" >/dev/null 2>&1; }

DRAINDECK_YES=0
for _arg in "$@"; do
    case "$_arg" in
        --yes) DRAINDECK_YES=1 ;;
    esac
done

_consent() {
    if [ "$DRAINDECK_YES" = "1" ]; then
        return 0
    fi
    printf "Install the above now? [y/N] "
    read -r reply
    case "$reply" in
        y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

# docs/32 review Blocker 4: a Python that IS on PATH but is older than
# 3.12 must be treated exactly like a missing Python -- never silently
# accepted, since the Dashboard requires 3.12+.
_python_is_compatible() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 12) else 1)' >/dev/null 2>&1
}

_find_python() {
    PY=""
    for candidate in python3.12 python3 python; do
        if _have "$candidate" && _python_is_compatible "$candidate"; then
            PY="$candidate"
            return 0
        fi
    done
    return 1
}

_report_python_unavailable() {
    if _have python3.12 || _have python3 || _have python; then
        echo "A Python interpreter is on PATH, but none found is version 3.12 or newer."
    else
        echo "Python 3 was not found on PATH."
    fi
}

if ! _find_python; then
    if ! _have brew; then
        _report_python_unavailable
        echo "Homebrew was not found either."
        echo "Install Homebrew from https://brew.sh, then re-run this script."
        exit 1
    fi
    _report_python_unavailable
    echo "The following prerequisite is missing:"
    echo "  - python@3.12 (source: Homebrew; may prompt for elevation; small download)"
    echo "      \$ brew install python@3.12"
    if ! _consent; then
        echo "CONSENT_DECLINED"
        exit 1
    fi
    brew install python@3.12
    if ! _find_python; then
        # docs/32 review Blocker 4: fail clearly here rather than
        # continuing into a later pip install against an incompatible
        # interpreter.
        _report_python_unavailable
        echo "Open a new terminal (PATH may need to refresh) and re-run this script."
        exit 1
    fi
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating virtual environment at $VENV_DIR ..."
    "$PY" -m venv "$VENV_DIR"
fi

echo "Installing/updating draindeck[dashboard] ..."
"$VENV_DIR/bin/python" -m pip install --upgrade -e "$REPO_DIR/.[dashboard]"
echo "draindeck[dashboard] installed."

exec "$VENV_DIR/bin/python" -m draindeck_dashboard.launcher "$@"
