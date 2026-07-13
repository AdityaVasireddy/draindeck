"""Budget seam (ADR-09): per-run caps + proxy-cost accounting. In subscription
mode dollar cost is not directly billed, so cost is a PROXY — engine-reported
token usage priced at API list rates (doc 08 §3), summed per run. Runaway-loop
protection is a correctness feature, not only a cost feature."""
from .manager import BudgetDecision, BudgetManager, ExperimentMetrics

__all__ = ["BudgetManager", "BudgetDecision", "ExperimentMetrics"]
