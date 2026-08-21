"""Phase 2 acceptance: observer subprocess uses shell=False and a minimal
allowlisted, credential-free child environment (docs/19)."""
from __future__ import annotations

from draindeck_dashboard.observer_client import (
    _ALLOWED_ENV_KEY_NAMES,
    _CREDENTIAL_DENYLIST,
    build_observer_env,
    invoke_observer_status,
)


def test_credential_vars_never_reach_the_child():
    base_env = {
        "PATH": r"C:\Windows",
        "SystemRoot": r"C:\Windows",
        "ANTHROPIC_API_KEY": "sk-secret",
        "ANTHROPIC_AUTH_TOKEN": "tok-secret",
        "ANTHROPIC_BASE_URL": "https://evil.example.com",
        "SOME_OTHER_SECRET": "unrelated-but-not-allowlisted",
    }
    env = build_observer_env(base_env)
    for credential_key in _CREDENTIAL_DENYLIST:
        assert credential_key not in env
    assert "SOME_OTHER_SECRET" not in env  # allowlist, not a strip-after-inherit
    assert env.get("PATH") == r"C:\Windows"


def test_allowlist_is_the_only_source_of_keys():
    base_env = {name: f"value-{name}" for name in _ALLOWED_ENV_KEY_NAMES}
    base_env["RANDOM_UNRELATED"] = "should-not-appear"
    env = build_observer_env(base_env)
    assert set(env.keys()) == set(_ALLOWED_ENV_KEY_NAMES)


def test_invoke_uses_shell_false_and_the_hygienic_env(monkeypatch):
    calls = {}

    class FakeCompleted:
        returncode = 0
        stdout = b'{"ok": true}'

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return FakeCompleted()

    monkeypatch.setattr("draindeck_dashboard.observer_client.subprocess.run", fake_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")

    result = invoke_observer_status("C:/x/draindeck.exe", "C:/x/events.jsonl")

    assert result == {"ok": True}
    assert calls["kwargs"]["shell"] is False
    assert "ANTHROPIC_API_KEY" not in calls["kwargs"]["env"]
    assert calls["argv"] == [
        "C:/x/draindeck.exe", "observe", "status",
        "--log", "C:/x/events.jsonl", "--format", "json",
    ]
