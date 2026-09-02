"""RED: port reuse must distinguish owned and foreign processes."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_owned_process_reuse_collision_and_stop_rules():
    resolve = getattr(_launcher_api(), "resolve_dashboard_process", None)
    assert callable(resolve), "RED: missing owned-process resolution behavior"
    terminated: list[int] = []
    owned = resolve(
        recorded_pid=41, port_pid=41, process_alive=lambda _: True,
        health_ok=lambda: True, terminate=terminated.append,
    )
    foreign = resolve(
        recorded_pid=41, port_pid=99, process_alive=lambda _: False,
        health_ok=lambda: False, terminate=terminated.append,
    )
    assert owned.action == "REUSE"
    assert foreign.action == "REFUSE_PORT_COLLISION"
    assert terminated == []
