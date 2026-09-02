#!/bin/sh
# One-click Linux launcher for the Draindeck Dashboard (docs/32).
# Minimal standard-library bootstrap: find or, with explicit per-invocation
# consent, actually install Python via the detected system package manager
# (apt/dnf/pacman/zypper -- never a silent default and never an untrusted
# fallback installer), create or reuse .venv, install the dashboard extra,
# then hand off to the shared, testable launcher implementation at
# src/draindeck_dashboard/launcher.py, which performs every remaining
# decision (further prerequisite consent, process reuse, readiness,
# browser open).
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
    MANAGER=""
    for candidate in apt dnf pacman zypper; do
        if _have "$candidate"; then
            MANAGER="$candidate"
            break
        fi
    done
    if [ -z "$MANAGER" ]; then
        _report_python_unavailable
        echo "No supported package manager (apt, dnf, pacman, zypper) was"
        echo "detected on this host either."
        echo "Install Python 3.12+ manually, then re-run this script."
        exit 1
    fi
    case "$MANAGER" in
        apt) PKG_PREVIEW="sudo apt install -y python3 python3-venv" ;;
        dnf) PKG_PREVIEW="sudo dnf install -y python3" ;;
        pacman) PKG_PREVIEW="sudo pacman -S --noconfirm python" ;;
        zypper) PKG_PREVIEW="sudo zypper install -y python3" ;;
    esac
    _report_python_unavailable
    echo "The following prerequisite is missing:"
    echo "  - python3 (>=3.12) (source: $MANAGER; may prompt for elevation; small download)"
    echo "      \$ $PKG_PREVIEW"
    if ! _consent; then
        echo "CONSENT_DECLINED"
        exit 1
    fi
    case "$MANAGER" in
        apt) sudo apt install -y python3 python3-venv ;;
        dnf) sudo dnf install -y python3 ;;
        pacman) sudo pacman -S --noconfirm python ;;
        zypper) sudo zypper install -y python3 ;;
    esac
    if ! _find_python; then
        # docs/32 review Blocker 4: the package manager may only offer an
        # older default python3 (e.g. an LTS distro's system package) --
        # fail clearly here rather than continuing into a later pip
        # install against an incompatible interpreter.
        _report_python_unavailable
        echo "Open a new terminal (PATH may need to refresh) and re-run this"
        echo "script; if the problem persists, this platform's package"
        echo "manager does not offer a compatible version and Python 3.12+"
        echo "must be installed manually."
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
