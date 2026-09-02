"""RED: declining installation consent must invoke no side-effecting adapter."""
import importlib
from types import SimpleNamespace


def _launcher_api():
    try:
        return importlib.import_module("draindeck_dashboard.launcher")
    except ModuleNotFoundError as exc:
        if exc.name == "draindeck_dashboard.launcher":
            return SimpleNamespace()
        raise


def test_launcher_exposes_per_invocation_install_consent_gate():
    install = getattr(_launcher_api(), "install_missing_prerequisites", None)
    assert callable(install), "RED: missing install_missing_prerequisites behavior"
    calls: list[str] = []
    result = install(
        missing=("python", "reviewer-model"),
        consent=False,
        package_manager=lambda *_: calls.append("package-manager"),
        model_puller=lambda *_: calls.append("model-puller"),
        server_starter=lambda *_: calls.append("server-starter"),
    )
    assert calls == []
    assert result.status == "CONSENT_DECLINED"
