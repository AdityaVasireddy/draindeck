"""Context-pack builder (doc 02 §5). Pure function: projection + config → the
prompt a fresh engine session receives. Under-stuffs by design (issue + feedback
+ constraints; no file contents, no repo map) — the engine's own tools discover
what it needs (ADR-10 fresh-process, feedback-over-conversation)."""
from .pack import build_prompt, prompt_hash

__all__ = ["build_prompt", "prompt_hash"]
