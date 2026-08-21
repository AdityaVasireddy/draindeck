"""Subprocess wrapper around the ADR-25 ``draindeck observe`` CLI (docs/19
"Purpose and dependency boundary" / "Registration and polling").

Dashboard never parses ``events.jsonl`` directly, opens a Draindeck
workspace/log mutex, repairs a log, or invokes Git — this module is the
only place Dashboard reaches outside its own process, and it does so by
invoking the operator-configured observer executable as a subprocess with
``shell=False`` and a minimal allowlisted environment.
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

TIMEOUT_SECONDS = 10

# Minimal allowlist: only the OS-required keys a Windows subprocess needs to
# start and resolve DLLs/sockets. Everything else — including any credential
# the parent process happens to carry — is excluded by construction (an
# allowlist, not a strip-after-inherit), so the explicit denylist below is
# defense in depth, not the primary mechanism.
_ALLOWED_ENV_KEY_NAMES = frozenset({
    "PATH", "SYSTEMROOT", "PATHEXT", "TEMP", "TMP", "WINDIR", "COMSPEC",
})

# Redundant, explicit exclusion (docs/19): even if one of these somehow used
# an allowlisted key name, it must never reach the child.
_CREDENTIAL_DENYLIST = frozenset({
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
})


def build_observer_env(base_env: dict) -> dict:
    env: dict[str, str] = {
        key: value
        for key, value in base_env.items()
        if key.upper() in _ALLOWED_ENV_KEY_NAMES
    }
    for credential_key in _CREDENTIAL_DENYLIST:
        env.pop(credential_key, None)
    return env


class ObserverError(RuntimeError):
    """Dashboard-facing error from invoking the observer CLI. Never carries
    raw stderr or the child environment — only a stable code/message the
    API can surface to a browser."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_response(self) -> dict:
        error: dict = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"error": error}


def invoke_observer_events(executable: str, log_path: str, *,
                            after: Optional[str], limit: int) -> dict:
    argv = [executable, "observe", "events", "--log", log_path,
            "--limit", str(limit), "--format", "json"]
    if after is not None:
        argv += ["--after", after]
    return _invoke(argv)


def invoke_observer_status(executable: str, log_path: str) -> dict:
    argv = [executable, "observe", "status", "--log", log_path, "--format", "json"]
    return _invoke(argv)


def _invoke(argv: list[str]) -> dict:
    env = build_observer_env(os.environ)
    try:
        result = subprocess.run(
            argv, shell=False, capture_output=True,
            timeout=TIMEOUT_SECONDS, env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise ObserverError(
            "OBSERVER_TIMEOUT",
            f"observer did not respond within {TIMEOUT_SECONDS}s",
        ) from e
    except FileNotFoundError as e:
        raise ObserverError(
            "OBSERVER_EXECUTABLE_NOT_FOUND",
            "configured observer executable was not found",
        ) from e

    try:
        text = result.stdout.decode("utf-8")
    except UnicodeDecodeError as e:
        raise ObserverError(
            "OBSERVER_OUTPUT_NOT_UTF8", "observer produced non-UTF8 output",
        ) from e

    if result.returncode == 0:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise ObserverError(
                "OBSERVER_OUTPUT_NOT_JSON",
                "observer produced non-JSON stdout on success",
            ) from e

    if result.returncode == 1:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ObserverError(
                "OBSERVER_OUTPUT_NOT_JSON",
                "observer exit-1 stdout was not JSON",
            ) from e
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and "code" in error:
            raise ObserverError(
                str(error.get("code", "OBSERVER_ERROR")),
                str(error.get("message", "observer reported an error")),
                error.get("details"),
            )
        raise ObserverError(
            "OBSERVER_ERROR", "observer exit-1 output missing error.code",
        )

    # exit-2 argparse text, or any other exit code: never expose raw stderr.
    raise ObserverError(
        "OBSERVER_INVOCATION_FAILED", f"observer exited {result.returncode}",
    )
