"""Execution engine seam (ADR-08: one concrete engine, no abstraction layer).

The engine spawns ``claude -p`` in the target workspace and returns an ADVISORY
result; the load-bearing output is the workspace mutation observed through
RepositoryAdapter (ADR-02/07). See ``claude_headless`` for the full contract.
"""
from .claude_headless import (
    ClaudeHeadlessEngine,
    EngineEnvError,
    EngineError,
    EngineResult,
)

__all__ = [
    "ClaudeHeadlessEngine",
    "EngineEnvError",
    "EngineError",
    "EngineResult",
]
