"""Deterministic validation seam (doc 02 §1, doc 09 §6.5). Pure code — it runs
config-supplied commands against the workspace and reports pass/fail per
command. It NEVER asks an LLM whether tests passed (ADR-01)."""
from .runner import ValidationResult, Validator

__all__ = ["Validator", "ValidationResult"]
