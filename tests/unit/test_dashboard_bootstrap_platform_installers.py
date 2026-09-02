"""RED: supported operating systems select exactly their adapter."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_windows_macos_and_linux_install_adapters():
    select = getattr(_launcher_api(), "select_platform_installer", None)
    assert callable(select), "RED: missing platform installer selection behavior"
    assert select("win32").package_manager == "winget"
    assert select("darwin").package_manager == "brew"
    # Linux detection is injected (never relies on this test host's real
    # environment) and must pick exactly the first present manager, in the
    # documented priority order.
    assert select("linux", which=lambda cmd: "/usr/bin/apt" if cmd == "apt" else None).package_manager == "apt"
    assert select("linux", which=lambda cmd: "/usr/bin/dnf" if cmd == "dnf" else None).package_manager == "dnf"
    assert select(
        "linux", which=lambda cmd: "/usr/bin/pacman" if cmd == "pacman" else None,
    ).package_manager == "pacman"
    assert select(
        "linux", which=lambda cmd: "/usr/bin/zypper" if cmd == "zypper" else None,
    ).package_manager == "zypper"


def test_select_platform_installer_never_silently_defaults_to_apt_on_linux():
    select = _launcher_api().select_platform_installer
    unsupported_error = _launcher_api().UnsupportedPlatformError
    # RED: a host with none of apt/dnf/pacman/zypper detectable must get an
    # actionable failure, never a silent, unverified "apt" guess.
    try:
        select("linux", which=lambda cmd: None)
    except unsupported_error as exc:
        assert "apt" in str(exc) and "dnf" in str(exc) and "pacman" in str(exc) and "zypper" in str(exc)
    else:
        raise AssertionError("expected UnsupportedPlatformError when no Linux package manager is detected")
