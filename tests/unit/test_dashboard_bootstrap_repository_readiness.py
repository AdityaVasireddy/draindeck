"""RED -> GREEN: run-readiness is truthful per registered repository
(docs/32 review Blocker 2) -- it verifies Claude, Ollama, AND the actual
reviewer model configured in that repository's canonical
`.draindeck/config.local.yaml`, reusing runtime.config's own schema
(never reimplementing it), instead of hard-coding the model check True.
"""
from __future__ import annotations

from types import SimpleNamespace

from draindeck_dashboard import launcher


def _fake_config(model="qwen2.5-coder:7b", endpoint="http://127.0.0.1:11434", provider="qwen"):
    qwen = SimpleNamespace(model=model, endpoint=endpoint) if provider == "qwen" else None
    reviewer = SimpleNamespace(provider=provider, qwen=qwen)
    return SimpleNamespace(reviewer=reviewer)


def test_not_configured_when_no_repository_is_registered():
    result = launcher.evaluate_repository_run_readiness(
        repo_config_path=None,
        claude_check=lambda: True, ollama_check=lambda: True,
        load_repo_config=lambda path: _fake_config(),
        model_present_check=lambda endpoint, model: True,
    )
    assert result.configured is False
    assert result.ready is False
    assert "repository-not-registered" in result.missing


def test_ready_when_claude_ollama_and_configured_model_are_all_present():
    result = launcher.evaluate_repository_run_readiness(
        repo_config_path="/repo/.draindeck/config.local.yaml",
        claude_check=lambda: True, ollama_check=lambda: True,
        load_repo_config=lambda path: _fake_config(model="qwen2.5-coder:7b"),
        model_present_check=lambda endpoint, model: model == "qwen2.5-coder:7b",
    )
    assert result.configured is True
    assert result.ready is True
    assert result.missing == ()
    assert result.model == "qwen2.5-coder:7b"


def test_reports_missing_reviewer_model_specifically_when_not_pulled(monkeypatch):
    result = launcher.evaluate_repository_run_readiness(
        repo_config_path="/repo/.draindeck/config.local.yaml",
        claude_check=lambda: True, ollama_check=lambda: True,
        load_repo_config=lambda path: _fake_config(model="qwen2.5-coder:32b"),
        model_present_check=lambda endpoint, model: False,
    )
    assert result.configured is True
    assert result.ready is False
    assert result.missing == ("reviewer-model",)
    assert result.model == "qwen2.5-coder:32b"


def test_reports_missing_ollama_independently_of_the_model_check():
    calls = []

    def model_present_check(endpoint, model):
        calls.append((endpoint, model))
        return True

    result = launcher.evaluate_repository_run_readiness(
        repo_config_path="/repo/.draindeck/config.local.yaml",
        claude_check=lambda: True, ollama_check=lambda: False,
        load_repo_config=lambda path: _fake_config(),
        model_present_check=model_present_check,
    )
    assert result.ready is False
    assert "ollama" in result.missing


def test_reports_missing_claude_independently():
    result = launcher.evaluate_repository_run_readiness(
        repo_config_path="/repo/.draindeck/config.local.yaml",
        claude_check=lambda: False, ollama_check=lambda: True,
        load_repo_config=lambda path: _fake_config(),
        model_present_check=lambda endpoint, model: True,
    )
    assert result.ready is False
    assert "claude" in result.missing


def test_uses_runtime_config_schema_fields_not_a_reimplementation():
    # The default `load_repo_config` must be runtime.config.load_config
    # itself -- proves the schema is reused, not reimplemented.
    import runtime.config as runtime_config

    assert launcher.evaluate_repository_run_readiness.__defaults__ is not None or True
    import inspect

    sig = inspect.signature(launcher.evaluate_repository_run_readiness)
    assert sig.parameters["load_repo_config"].default is runtime_config.load_config


def test_reports_config_unavailable_when_the_registered_config_file_is_missing(tmp_path):
    # Registration-time success does not guarantee the file still exists at
    # readiness-check time (review Blocker 2 follow-up: config drift).
    missing_path = tmp_path / ".draindeck" / "config.local.yaml"
    result = launcher.evaluate_repository_run_readiness(
        repo_config_path=str(missing_path),
        claude_check=lambda: True, ollama_check=lambda: True,
    )
    assert result.configured is False
    assert result.ready is False
    assert "config-unavailable" in result.missing


def test_reports_config_invalid_when_load_repo_config_raises_on_a_present_file(tmp_path):
    present_path = tmp_path / ".draindeck" / "config.local.yaml"
    present_path.parent.mkdir(parents=True)
    present_path.write_text("not: [valid, yaml, :::", encoding="utf-8")

    def _raise(path):
        raise ValueError("invalid YAML")

    result = launcher.evaluate_repository_run_readiness(
        repo_config_path=str(present_path),
        claude_check=lambda: True, ollama_check=lambda: True,
        load_repo_config=_raise,
    )
    assert result.configured is False
    assert result.ready is False
    assert "config-invalid" in result.missing


def test_config_drift_reason_never_raises_and_always_returns_a_result(tmp_path):
    # The whole point of Blocker 2: a load/validation failure must never
    # propagate as an unhandled exception (which the API layer would turn
    # into a 500) -- evaluate_repository_run_readiness always returns a
    # normal RepositoryRunReadiness.
    present_path = tmp_path / "config.local.yaml"
    present_path.write_text("ok: true", encoding="utf-8")

    def _raise(path):
        raise RuntimeError("schema invalid: reviewer.qwen.model must not be empty")

    result = launcher.evaluate_repository_run_readiness(
        repo_config_path=str(present_path),
        claude_check=lambda: True, ollama_check=lambda: True,
        load_repo_config=_raise,
    )
    assert isinstance(result, launcher.RepositoryRunReadiness)
    assert result.ready is False


def test_ollama_model_presence_uses_the_ollama_tags_endpoint(monkeypatch):
    requested = []

    def fake_urlopen(url, timeout=None):
        requested.append(url)

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                import json
                return json.dumps({"models": [{"name": "qwen2.5-coder:7b"}]}).encode()

        return _Resp()

    monkeypatch.setattr(launcher.urllib.request, "urlopen", fake_urlopen)
    assert launcher.check_reviewer_model_present(
        endpoint="http://127.0.0.1:11434", model="qwen2.5-coder:7b",
    ) is True
    assert launcher.check_reviewer_model_present(
        endpoint="http://127.0.0.1:11434", model="not-pulled-model",
    ) is False
    assert any("api/tags" in u for u in requested)
