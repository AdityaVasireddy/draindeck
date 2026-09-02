"""RED: fast path has a measurable, strict browser-readiness budget."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_dependency_present_fast_path_contract():
    contract = getattr(_launcher_api(), "fast_path_contract", None)
    assert callable(contract), "RED: missing fast-path timing contract"
    target = contract()
    assert target.deadline_seconds == 180
    assert target.browser_open_required is True
    assert target.within_budget(179.9) is True
    assert target.within_budget(180.1) is False
