"""Truthful, per-repository run-readiness for the cross-platform Dashboard
launcher (docs/32 L-10, review Blockers 2, 7). Extracted out of
``launcher.py`` to keep that module focused on process ownership/
orchestration -- ``launcher.py`` imports and re-exports every public name
here unchanged, so ``launcher.X`` keeps resolving exactly as it did before
the split.

Never writes anything; ``runtime.init.service.apply_target_configuration``
remains the only target-config writer. This module only ever READS a
repository's already-registered canonical ``.draindeck/config.local.yaml``
via ``runtime.config.load_config`` -- the SAME schema the runtime itself
validates against, never a reimplementation.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from runtime.config import load_config as _load_runtime_config

# ---------------------------------------------------------------------------
# Independent Dashboard-ready / Run-ready state (L-10)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadinessState:
    dashboard_ready: bool
    run_ready: bool


def readiness_state(*, dashboard_ready: bool, run_prerequisites_ready: bool) -> ReadinessState:
    """Dashboard-ready and Run-ready are independent facts (docs/32 L-10):
    the Dashboard may open with Run-ready false, and Run-ready never
    implies Dashboard-ready either.
    """
    return ReadinessState(dashboard_ready=dashboard_ready, run_ready=run_prerequisites_ready)


@dataclass(frozen=True)
class RunPrerequisiteResult:
    ready: bool
    missing: tuple[str, ...]


def check_run_prerequisites(
    *,
    claude_check: Callable[[], bool],
    ollama_check: Callable[[], bool],
    model_check: Callable[[], bool],
) -> RunPrerequisiteResult:
    """Run-readiness preflight (Claude, Ollama, configured reviewer model),
    independent of Dashboard-readiness. Every check is injected so this is
    testable without a real Claude/Ollama install.
    """
    missing = [
        name for name, check in (
            ("claude", claude_check), ("ollama", ollama_check), ("reviewer-model", model_check),
        ) if not check()
    ]
    return RunPrerequisiteResult(ready=not missing, missing=tuple(missing))


def check_reviewer_model_present(endpoint: str, model: str, *, timeout: float = 3.0) -> bool:
    """Real check: is ``model`` actually pulled in the Ollama instance at
    ``endpoint``, via ``GET /api/tags`` (Ollama's own model-listing
    endpoint) -- never assumed true."""
    try:
        with urllib.request.urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not isinstance(body, dict):
            return False
        models = body.get("models")
        if not isinstance(models, list):
            return False
        names = {entry.get("name") for entry in models if isinstance(entry, dict)}
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, OSError, TypeError, AttributeError):
        return False
    return model in names


@dataclass(frozen=True)
class RepositoryRunReadiness:
    configured: bool
    ready: bool
    missing: tuple[str, ...]
    model: Optional[str] = None


def evaluate_repository_run_readiness(
    *,
    repo_config_path: Optional[str],
    claude_check: Callable[[], bool],
    ollama_check: Callable[[], bool],
    load_repo_config: Callable[[str], object] = _load_runtime_config,
    model_present_check: Callable[[str, str], bool] = check_reviewer_model_present,
) -> RepositoryRunReadiness:
    """Truthful, per-repository run-readiness (docs/32 review Blocker 2):
    reuses ``runtime.config.load_config`` -- the SAME schema the runtime
    itself validates against, never a reimplementation -- to read the
    registered repository's canonical ``.draindeck/config.local.yaml`` and
    checks whether its configured reviewer model is actually present,
    alongside independent Claude/Ollama executable checks. Never writes
    anything; ``runtime.init.service.apply_target_configuration`` remains
    the only target-config writer.

    A deleted, unreadable, or invalid registered config file (drift after
    registration -- review Blocker 2 follow-up) is reported truthfully as
    not-ready with a specific ``config-unavailable``/``config-invalid``
    reason, never as an unhandled exception: the caller (the Dashboard API)
    must always get a normal result here, never a 500.
    """
    missing = [name for name, check in (("claude", claude_check), ("ollama", ollama_check)) if not check()]

    if repo_config_path is None:
        return RepositoryRunReadiness(
            configured=False, ready=False, missing=tuple(missing) + ("repository-not-registered",),
        )

    try:
        cfg = load_repo_config(repo_config_path)
    except Exception:
        # Config drift after registration (review Blocker 2 follow-up): the
        # file was deleted/is unreadable ("config-unavailable"), or it
        # exists but its content is malformed YAML or schema-invalid
        # ("config-invalid") -- distinguished by a real filesystem check
        # here, deliberately AFTER the injected loader has already had its
        # chance to succeed on a fake/non-filesystem path (tests inject a
        # fake ``load_repo_config`` that never touches disk at all; this
        # existence check must never run before that loader is tried, or
        # it would reject a perfectly valid injected fake). Never lets a
        # load/validation failure propagate as an unhandled 500.
        reason = "config-unavailable" if not Path(repo_config_path).exists() else "config-invalid"
        return RepositoryRunReadiness(configured=False, ready=False, missing=tuple(missing) + (reason,))

    if cfg.reviewer.provider != "qwen" or cfg.reviewer.qwen is None:
        return RepositoryRunReadiness(
            configured=False, ready=False, missing=tuple(missing) + ("reviewer-model-not-configured",),
        )

    model = cfg.reviewer.qwen.model
    if not model_present_check(cfg.reviewer.qwen.endpoint, model):
        missing.append("reviewer-model")
    return RepositoryRunReadiness(configured=True, ready=not missing, missing=tuple(missing), model=model)
