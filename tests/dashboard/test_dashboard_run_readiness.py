"""RED: Dashboard-ready and Run-ready are independent facts."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_dashboard_and_runtime_readiness_separately():
    state_for = getattr(_launcher_api(), "readiness_state", None)
    assert callable(state_for), "RED: missing independent readiness-state behavior"
    dashboard_only = state_for(dashboard_ready=True, run_prerequisites_ready=False)
    run_only = state_for(dashboard_ready=False, run_prerequisites_ready=True)
    assert dashboard_only.dashboard_ready is True
    assert dashboard_only.run_ready is False
    assert run_only.dashboard_ready is False
    assert run_only.run_ready is True
