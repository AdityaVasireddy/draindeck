"""BudgetManager — per-run caps + proxy-cost meter (ADR-09, doc 09 §6.4).

Two run-level hard stops (ADR-19 kill-criteria plumbing): a cap on executions
per run and a cumulative proxy-dollar ceiling. Per-*issue* attempt caps are a
projection query (``proj.attempts`` vs ``max_attempts_per_issue``) owned by the
loop's retry guard, not here — this object owns only run-global state, which is
per-``run_id`` and resets on restart (the experiment-total cost is a log
projection, computed separately).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = ""


@dataclass
class ExperimentMetrics:
    executions_this_run: int
    proxy_dollars_this_run: float


@dataclass
class BudgetManager:
    max_executions_per_run: int
    hard_stop_proxy_cost_per_run_usd: float

    _executions_started: int = field(default=0, init=False)
    _proxy_dollars: float = field(default=0.0, init=False)

    def check(self) -> BudgetDecision:
        """Called before starting a new execution. Denies (stops the run) when a
        run-level hard stop is hit — never tuned to dodge a verdict (ADR-19)."""
        if self._executions_started >= self.max_executions_per_run:
            return BudgetDecision(
                False,
                f"max_executions_per_run reached "
                f"({self._executions_started}/{self.max_executions_per_run})",
            )
        if self._proxy_dollars >= self.hard_stop_proxy_cost_per_run_usd:
            return BudgetDecision(
                False,
                f"hard_stop_proxy_cost reached "
                f"(${self._proxy_dollars:.2f} ≥ "
                f"${self.hard_stop_proxy_cost_per_run_usd:.2f})",
            )
        return BudgetDecision(True)

    def note_execution_started(self) -> None:
        self._executions_started += 1

    def record_usage(self, execution_id: str, usage: dict | None) -> None:
        """Add an execution's proxy dollars (engine ``usage['dollars']`` ←
        total_cost_usd). Tolerant of a missing/None value — advisory data may be
        absent from a malformed transcript, and the meter must not crash the
        run over it."""
        if not usage:
            return
        dollars = usage.get("dollars")
        if isinstance(dollars, (int, float)):
            self._proxy_dollars += float(dollars)

    def metrics(self) -> ExperimentMetrics:
        return ExperimentMetrics(
            executions_this_run=self._executions_started,
            proxy_dollars_this_run=round(self._proxy_dollars, 6),
        )
