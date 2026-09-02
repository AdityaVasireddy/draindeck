"""RED: target configuration must retain its existing shared writer."""
import importlib
from types import SimpleNamespace

from runtime.init.service import apply_target_configuration


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_has_a_config_boundary_without_a_parallel_target_config_writer():
    launcher = _launcher_api()
    assert getattr(launcher, "target_configuration_writer", None) is apply_target_configuration, (
        "RED: launcher must expose the shared service writer, not a local config writer"
    )
