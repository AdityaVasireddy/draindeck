"""RED: a partial install must resume only the remaining work."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_idempotent_partial_install_recovery():
    resume = getattr(_launcher_api(), "resume_partial_install", None)
    assert callable(resume), "RED: missing partial-install recovery behavior"
    installed: list[str] = []
    result = resume(
        state={"completed": ("python",), "remaining": ("dashboard",)},
        installer=installed.append,
    )
    assert installed == ["dashboard"]
    assert result.completed == ("python", "dashboard")
    assert result.failed_step is None


def test_resume_partial_install_stops_at_the_failing_step_without_losing_progress():
    resume = _launcher_api().resume_partial_install
    attempted: list[str] = []

    def flaky_installer(item: str) -> None:
        attempted.append(item)
        if item == "ollama":
            raise RuntimeError("network unreachable")

    result = resume(
        state={"completed": ("python", "git"), "remaining": ("ollama", "claude")},
        installer=flaky_installer,
    )
    # Only the failing step (and nothing after it) was attempted -- "claude"
    # must never be touched once "ollama" fails.
    assert attempted == ["ollama"]
    assert result.completed == ("python", "git")
    assert result.failed_step == "ollama"
