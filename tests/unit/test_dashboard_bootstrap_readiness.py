"""RED: browser opening requires every readiness witness."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_exact_loopback_health_readiness_contract():
    ready = getattr(_launcher_api(), "is_browser_open_ready", None)
    assert callable(ready), "RED: missing browser readiness predicate"
    ok = {"process_alive": True, "port_listening": True, "owned": True,
          "health_status": 200, "health_body": {"status": "ok"}}
    assert ready(**{**ok, "process_alive": False}) is False
    assert ready(**{**ok, "port_listening": False}) is False
    assert ready(**{**ok, "owned": False}) is False
    assert ready(**{**ok, "health_body": {"status": "degraded"}}) is False
    assert ready(**ok) is True
