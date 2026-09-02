"""Dashboard-local background reviewer-model pull (docs/32 review Blocker 1
follow-up: "clone -> launch Dashboard -> register target -> select issues ->
run" must not require a manual terminal command). This is a Dashboard
operational action only -- it never writes target config, events.jsonl,
leases, or run state. The model to pull is resolved EXCLUSIVELY from the
repository's own registered canonical ``.draindeck/config.local.yaml`` via
``runtime.config.load_config``; there is no parameter anywhere in this
module that accepts a client-supplied model or config path.

State is in-memory, per-Dashboard-process only -- a restart simply loses
in-flight status, which is safe: the operator can re-trigger the pull, and
nothing durable was ever promised or lost.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from runtime.config import load_config as _load_runtime_config

from .launcher import pull_ollama_model as _default_model_puller


@dataclass(frozen=True)
class PullState:
    status: str  # "in_progress" | "success" | "failed"
    model: str
    error: Optional[str] = None


class ModelPullTracker:
    """One instance lives on ``app.state`` for the process's lifetime."""

    def __init__(
        self,
        *,
        model_puller: Callable[[str], None] = _default_model_puller,
        load_repo_config: Callable[[str], object] = _load_runtime_config,
    ) -> None:
        self._model_puller = model_puller
        self._load_repo_config = load_repo_config
        self._lock = threading.Lock()
        self._state: Dict[int, PullState] = {}

    def resolve_model(self, config_path: str) -> str:
        """Resolves the model to pull EXCLUSIVELY from the repository's own
        registered config -- reuses ``runtime.config.load_config``'s schema,
        never reimplements it, and never accepts a caller-supplied model."""
        cfg = self._load_repo_config(config_path)
        if cfg.reviewer.provider != "qwen" or cfg.reviewer.qwen is None:
            raise ValueError("no reviewer model is configured for this repository")
        return cfg.reviewer.qwen.model

    def status(self, repo_id: int) -> Optional[PullState]:
        with self._lock:
            return self._state.get(repo_id)

    def start(self, repo_id: int, config_path: str) -> PullState:
        """Idempotent: a pull already in progress for this repository is
        returned as-is rather than started a second time. Resolving the
        model happens synchronously (and can raise) BEFORE anything is
        started in the background, so a misconfigured repository never
        spawns a thread or an ``ollama pull`` call at all."""
        with self._lock:
            existing = self._state.get(repo_id)
            if existing is not None and existing.status == "in_progress":
                return existing
            model = self.resolve_model(config_path)
            state = PullState(status="in_progress", model=model)
            self._state[repo_id] = state

        def _run() -> None:
            try:
                self._model_puller(model)
            except Exception as exc:
                with self._lock:
                    self._state[repo_id] = PullState(status="failed", model=model, error=str(exc))
                return
            with self._lock:
                self._state[repo_id] = PullState(status="success", model=model)

        threading.Thread(target=_run, daemon=True).start()
        return state
