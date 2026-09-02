"""Installer policy for the cross-platform Dashboard launcher (docs/32,
review Blockers 1, 6, 7). Extracted out of ``launcher.py`` to keep that
module focused on process ownership/orchestration (docs/32 review Blocker
7) -- this module owns detection, the consent-gated manifest, and the
per-platform install adapters; ``launcher.py`` imports and re-exports
every public name here unchanged, so ``launcher.X`` keeps resolving
exactly as it did before the split (existing tests monkeypatch through
that namespace and must keep working unmodified).

Every side-effecting operation (package manager, model puller) is
injected as a callable so the decision logic here is exercised in unit
tests without ever touching a real OS package manager or network socket.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Consent-gated install (L-03, L-04, L-05, L-06)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstallResult:
    status: str  # "CONSENT_DECLINED" | "INSTALLED" | "INSTALL_FAILED"
    completed: tuple[str, ...] = ()
    failed_step: Optional[str] = None


def install_missing_prerequisites(
    *,
    missing: Sequence[str],
    consent: bool,
    package_manager: Callable[[str], None],
    model_puller: Callable[[str], None],
    server_starter: Callable[[str], None],
) -> InstallResult:
    """Per-invocation consent gate. Declining consent (``consent=False``)
    makes ZERO calls to any of the three side-effecting callables and
    returns CONSENT_DECLINED (L-03) -- the caller is responsible for having
    already shown the exact missing-prerequisite manifest before calling
    this with ``consent=True``.

    On consent, each missing item is routed to its adapter and installed
    in order. A failure partway through stops immediately, retains the
    steps already completed, and reports exactly which step failed (L-06)
    -- nothing here ever auto-uninstalls a completed step.
    """
    if not consent:
        return InstallResult(status="CONSENT_DECLINED")

    completed: list[str] = []
    for item in missing:
        installer = _installer_for(item, package_manager, model_puller, server_starter)
        try:
            installer(item)
        except Exception:
            return InstallResult(
                status="INSTALL_FAILED", completed=tuple(completed), failed_step=item
            )
        completed.append(item)
    return InstallResult(status="INSTALLED", completed=tuple(completed))


def _installer_for(item, package_manager, model_puller, server_starter):
    if item == "reviewer-model":
        return model_puller
    if item == "dashboard-server":
        return server_starter
    return package_manager


# ---------------------------------------------------------------------------
# Platform installer adapters (L-04, L-05)
# ---------------------------------------------------------------------------

class UnsupportedPlatformError(RuntimeError):
    """Raised only for a truly unrecognized ``sys.platform`` value. Never
    used to fall back to an untrusted installer (docs/32 L-05)."""


@dataclass(frozen=True)
class PlatformInstaller:
    platform: str
    package_manager: str
    elevation_note: str


_LINUX_MANAGERS: tuple[str, ...] = ("apt", "dnf", "pacman", "zypper")


def select_platform_installer(
    platform: str, *, which: Callable[[str], Optional[str]] = shutil.which,
) -> PlatformInstaller:
    """Selects exactly one supported adapter for ``platform``.

    Windows always selects winget (current user; per-package UAC prompts
    only after consent). macOS always selects Homebrew (terminal sudo only
    after consent). Linux detects the first present manager among apt/dnf/
    pacman/zypper via the injected ``which``, in that priority order; when
    NONE is detectable on the current host, this raises an actionable
    ``UnsupportedPlatformError`` immediately -- it never silently guesses
    "apt" or any other untrusted fallback (review correction: an earlier
    version defaulted to apt, which could show or run apt's install command
    on a host that doesn't actually have apt).
    """
    if platform == "win32":
        return PlatformInstaller("win32", "winget", "package-specific UAC only after consent")
    if platform == "darwin":
        return PlatformInstaller("darwin", "brew", "terminal sudo only after consent")
    if platform.startswith("linux"):
        for manager in _LINUX_MANAGERS:
            if which(manager):
                return PlatformInstaller("linux", manager, "interactive sudo only after consent")
        raise UnsupportedPlatformError(
            "no supported Linux package manager found on this host (checked: "
            + ", ".join(_LINUX_MANAGERS) + "); install one of these first"
        )
    raise UnsupportedPlatformError(f"unsupported platform: {platform!r}")


# ---------------------------------------------------------------------------
# Real detection -> manifest -> consent -> install (review Blocker 1).
#
# Package identifiers below are verified against official vendor docs, not
# invented:
#   - Claude Code: winget id "Anthropic.ClaudeCode", Homebrew cask
#     "claude-code" (https://code.claude.com/docs/en/setup, "Install Claude
#     Code" tabs).
#   - Ollama: winget id "Ollama.Ollama" (microsoft/winget-pkgs manifests;
#     docs.ollama.com/windows), Homebrew formula "ollama"
#     (formulae.brew.sh/formula/ollama).
#
# Linux security posture (review Blocker 6): neither vendor publishes an
# apt/dnf/pacman/zypper package, and this launcher no longer treats their
# documented `curl | bash` one-liner as installable -- that pattern
# downloads a MUTABLE script from a URL this launcher does not control and
# would execute it with no version pin and no integrity check, merely
# because it arrived over HTTPS. Ollama's GitHub releases do publish
# per-version binary tarballs with vendor-computed checksums (see
# https://github.com/ollama/ollama/releases), which would be a legitimate
# future pinned+verified path; Claude Code's native Linux installer has no
# equivalent published artifact this code could verify with confidence.
# Until a genuinely verifiable artifact is wired in, both fail closed on
# Linux: `install_command_for` returns None for them, and the manifest and
# the real adapter both report a manual-install action instead of ever
# downloading and executing anything.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Prerequisite:
    name: str
    source: str
    command: tuple[str, ...]
    may_prompt_elevation: bool
    large_download: bool
    manual_instructions: Optional[str] = None


_GIT_PACKAGE_NAMES: dict[str, str] = {
    "winget": "Git.Git", "brew": "git", "apt": "git", "dnf": "git",
    "pacman": "git", "zypper": "git",
}

_LINUX_MANUAL_INSTALL_DOCS: dict[str, str] = {
    "claude": "https://code.claude.com/docs/en/setup",
    "ollama": "https://ollama.com/download/linux",
}


def _generic_package_command(installer: PlatformInstaller, package_name: str) -> tuple[str, ...]:
    if installer.package_manager == "winget":
        return (
            "winget", "install", "--id", package_name, "-e",
            "--accept-source-agreements", "--accept-package-agreements",
        )
    if installer.package_manager == "brew":
        return ("brew", "install", package_name)
    if installer.package_manager in ("apt", "dnf"):
        return ("sudo", installer.package_manager, "install", "-y", package_name)
    if installer.package_manager == "pacman":
        return ("sudo", "pacman", "-S", "--noconfirm", package_name)
    if installer.package_manager == "zypper":
        return ("sudo", "zypper", "install", "-y", package_name)
    raise UnsupportedPlatformError(f"no generic package command for manager {installer.package_manager!r}")


def _claude_install_command(installer: PlatformInstaller) -> Optional[tuple[str, ...]]:
    if installer.platform == "win32":
        return (
            "winget", "install", "--id", "Anthropic.ClaudeCode", "-e",
            "--accept-source-agreements", "--accept-package-agreements",
        )
    if installer.platform == "darwin":
        return ("brew", "install", "--cask", "claude-code")
    return None  # Linux: no vendor-verifiable automatic install path (Blocker 6)


def _ollama_install_command(installer: PlatformInstaller) -> Optional[tuple[str, ...]]:
    if installer.platform == "win32":
        return (
            "winget", "install", "--id", "Ollama.Ollama", "-e",
            "--accept-source-agreements", "--accept-package-agreements",
        )
    if installer.platform == "darwin":
        return ("brew", "install", "ollama")
    return None  # Linux: no vendor-verifiable automatic install path (Blocker 6)


def install_command_for(item: str, installer: PlatformInstaller) -> Optional[tuple[str, ...]]:
    """The DISPLAY/execution command for ``item``, or None when no
    automatic install is offered on this platform (Linux claude/ollama --
    Blocker 6). A None here must never be papered over with a fabricated
    command; callers show a manual-install instruction instead."""
    if item == "git":
        return _generic_package_command(installer, _GIT_PACKAGE_NAMES[installer.package_manager])
    if item == "claude":
        return _claude_install_command(installer)
    if item == "ollama":
        return _ollama_install_command(installer)
    raise ValueError(f"no install command known for prerequisite {item!r}")


_PREREQUISITE_SOURCES: dict[str, str] = {
    "git": "the detected system package manager",
    "claude": "Anthropic (official)",
    "ollama": "Ollama (official)",
}


def detect_missing_prerequisites(
    *,
    installer: PlatformInstaller,
    git_present: bool,
    claude_present: bool,
    ollama_present: bool,
    dashboard_deps_present: bool,
) -> tuple[Prerequisite, ...]:
    """Builds the exact manifest of what is missing -- name, source, the
    real install command (or manual instructions when none exists),
    whether it may prompt for elevation, and whether it's a large
    download. Nothing here installs anything; it only reports.
    """
    candidates: list[Prerequisite] = []
    for name, present in (
        ("git", git_present), ("claude", claude_present), ("ollama", ollama_present),
    ):
        if present:
            continue
        command = install_command_for(name, installer)
        manual = None if command else (
            f"no vendor-published, checksum-verifiable automatic install path on "
            f"{installer.platform}; install manually: "
            f"{_LINUX_MANUAL_INSTALL_DOCS.get(name, 'see vendor documentation')}"
        )
        candidates.append(Prerequisite(
            name=name, source=_PREREQUISITE_SOURCES[name],
            command=command or (),
            may_prompt_elevation=installer.package_manager != "brew" or name != "claude",
            large_download=(name == "ollama"),
            manual_instructions=manual,
        ))
    if not dashboard_deps_present:
        candidates.append(Prerequisite(
            name="dashboard-deps", source="PyPI via pip",
            command=("pip", "install", "-e", ".[dashboard]"),
            may_prompt_elevation=False, large_download=False,
        ))
    return tuple(candidates)


def render_prerequisite_manifest(missing: Sequence[Prerequisite]) -> str:
    lines = ["The following prerequisites are missing:"]
    for p in missing:
        elevation = "may prompt for elevation" if p.may_prompt_elevation else "no elevation expected"
        size = "large download" if p.large_download else "small download"
        lines.append(f"  - {p.name} (source: {p.source}; {elevation}; {size})")
        if p.command:
            lines.append(f"      $ {' '.join(p.command)}")
        else:
            lines.append(f"      MANUAL INSTALL REQUIRED: {p.manual_instructions}")
    return "\n".join(lines)


def prompt_consent(manifest_text: str, *, input_fn: Callable[[str], str] = input) -> bool:
    """Default is No (L-03/Blocker 1): only an explicit y/yes proceeds."""
    print(manifest_text)
    reply = input_fn("Install the above now? [y/N] ")
    return reply.strip().lower() in ("y", "yes")


def prompt_model_pull_consent(model: str, *, input_fn: Callable[[str], str] = input) -> bool:
    """Separate, explicit consent for the Ollama model pull specifically --
    never folded into the general prerequisite consent, because a model
    pull can be a multi-gigabyte download."""
    print(
        f"The reviewer model '{model}' is not present locally. Pulling it via "
        f"`ollama pull {model}` may download several gigabytes."
    )
    reply = input_fn(f"Pull '{model}' now? [y/N] ")
    return reply.strip().lower() in ("y", "yes")


def _run_argv(argv: Sequence[str]) -> None:
    subprocess.run(list(argv), shell=False, check=True)


class ManualLinuxInstallRequiredError(RuntimeError):
    """Raised when asked to auto-install an item that has no vendor-
    verifiable install path on this platform (Blocker 6). This launcher
    NEVER downloads and executes a mutable, unsigned remote installer
    script merely because it arrived over HTTPS -- it fails closed here
    instead, every time, with the official manual-install location."""


def real_package_manager_adapter(installer: PlatformInstaller) -> Callable[[str], None]:
    """The real (argv-only, shell=False) package-manager callable to inject
    into ``install_missing_prerequisites``/``resume_partial_install``. Raises
    ``ManualLinuxInstallRequiredError`` -- never runs anything -- for an item
    with no vendor-verifiable Linux install path (Blocker 6)."""
    def _install(item: str) -> None:
        command = install_command_for(item, installer)
        if command is None:
            raise ManualLinuxInstallRequiredError(
                f"{item} has no vendor-published, checksum-verifiable automatic "
                f"install path on {installer.platform}; install it manually: "
                f"{_LINUX_MANUAL_INSTALL_DOCS.get(item, 'see vendor documentation')}"
            )
        _run_argv(command)
    return _install


def pull_ollama_model(model: str) -> None:
    """Argv-only, shell=False (L-12); requires its own separate consent
    via ``prompt_model_pull_consent`` before being called."""
    _run_argv(["ollama", "pull", model])


# ---------------------------------------------------------------------------
# Dashboard-deps: a distinct local-environment/pip adapter (independent
# review finding), never a fake OS package-manager item.
#
# `detect_missing_prerequisites` can emit "dashboard-deps", but it has no
# vendor package identifier for any OS package manager -- routing it
# through `real_package_manager_adapter` makes `install_command_for` raise
# `ValueError`. This installs the optional `dashboard` extra via pip,
# argv-only and shell=False, into the ACTIVE interpreter running this
# launcher (the same venv the tracked wrapper scripts themselves
# bootstrap), never a system Python and never an OS package manager.
# ---------------------------------------------------------------------------

def default_dashboard_deps_installer(
    *, project_root: Optional[Path] = None, python_executable: Optional[str] = None,
) -> Callable[[str], None]:
    """Real pip adapter for the "dashboard-deps" prerequisite. The editable
    project root defaults to this module's own on-disk location (three
    parents up from ``src/draindeck_dashboard/launcher_install.py``) rather
    than trusting any caller-supplied path -- in an editable install this
    reliably resolves to the real checkout, since editable mode keeps
    ``__file__`` pointing at the source tree, not a site-packages copy.
    """
    root = project_root if project_root is not None else Path(__file__).resolve().parents[2]
    python = python_executable if python_executable is not None else sys.executable

    def _install(item: str) -> None:
        _run_argv([python, "-m", "pip", "install", "-e", f"{root}[dashboard]"])

    return _install


def dashboard_deps_present() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True


def default_install_state_path() -> Path:
    home = Path(os.environ.get("DRAINDECK_DASHBOARD_HOME", Path.home() / ".draindeck-dashboard"))
    return home / "install-state.json"


def load_install_state(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or "completed" not in raw or "remaining" not in raw:
            return None
        return {"completed": list(raw["completed"]), "remaining": list(raw["remaining"])}
    except (OSError, ValueError):
        return None


def save_install_state(path: Path, *, completed: Sequence[str], remaining: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"completed": list(completed), "remaining": list(remaining)}), encoding="utf-8",
    )


def clear_install_state(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Partial-install recovery (L-06)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResumeResult:
    completed: tuple[str, ...]
    failed_step: Optional[str] = None


def resume_partial_install(
    *, state: Mapping[str, Sequence[str]], installer: Callable[[str], None],
) -> ResumeResult:
    """Resumes ONLY the remaining work from a retained partial-install
    state -- previously completed steps are never re-run or uninstalled. A
    failure partway through stops immediately (the still-untried remaining
    steps are never attempted) and reports exactly which step failed,
    mirroring ``install_missing_prerequisites``'s failure shape.
    """
    completed = list(state.get("completed", ()))
    for item in state.get("remaining", ()):
        try:
            installer(item)
        except Exception:
            return ResumeResult(completed=tuple(completed), failed_step=item)
        completed.append(item)
    return ResumeResult(completed=tuple(completed))
