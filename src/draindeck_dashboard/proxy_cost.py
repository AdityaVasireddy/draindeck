"""Pure proxy-cost/token validation and conversion (spec
`spec/coding-engine-proxy-cost.md` §2.2/§2.3).

The coding engine's ``ExecutionFinished.payload.usage`` carries ``dollars``
(list-rate proxy, from ``total_cost_usd``) and ``input_tokens``/``output_tokens``.
These helpers are the single, deterministic gate that turns those advisory,
possibly-malformed values into stored read-model fields. They never raise and
never infer one field from another: missing/invalid cost is ``None`` (unknown,
never zero), and a valid ``0`` is a metered zero (``0`` micro-USD), distinct from
missing.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

_MICRO = Decimal(1_000_000)

# The permanent statement of what this figure is: engine-reported token usage
# priced at API list rates -- a proxy, never an invoice (spec §1.1/§3.1).
BASIS = "ENGINE_REPORTED_API_LIST_RATE_PROXY"


def validate_dollars(value: object) -> Optional[int]:
    """``usage.dollars`` -> integer micro-USD, or ``None`` when invalid.

    Rejects ``bool`` (``isinstance(True, int)`` is ``True`` under Python's
    int/bool subtyping, so bool must be excluded first and explicitly),
    negatives, non-finite (NaN/±Inf), and non-numeric values. Accepts any
    finite ``int``/``float`` ``>= 0``. Conversion is ``Decimal(str(value)) *
    1_000_000`` quantized to an integer with ``ROUND_HALF_UP`` -- the string
    constructor avoids binary-float artifacts and the rounding is deterministic.
    A valid ``0`` returns ``0`` (metered), never ``None``.
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if value < 0:
        return None
    micro = (Decimal(str(value)) * _MICRO).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(micro)


def validate_tokens(value: object) -> Optional[int]:
    """``usage.input_tokens``/``output_tokens`` -> non-negative int, or ``None``.

    Accepts only ``int`` (never ``bool``) ``>= 0``. Floats, strings, and
    negatives are rejected. Independent of cost validity -- token coverage is
    tracked separately from cost coverage (spec §2.3).
    """
    if isinstance(value, bool):
        return None
    if not isinstance(value, int):
        return None
    if value < 0:
        return None
    return value


def micro_to_usd_str(micro: Optional[int]) -> Optional[str]:
    """Integer micro-USD -> fixed 6-decimal-place USD string, or None.

    Derived only from the integer micro-USD (never re-derived from a float),
    so the displayed dollars are exact for whatever was metered."""
    if micro is None:
        return None
    return str((Decimal(micro) / _MICRO).quantize(Decimal("0.000001")))


def _completeness(total: int, metered: int) -> str:
    if metered == 0:
        return "UNAVAILABLE"
    if metered == total:
        return "COMPLETE"
    return "PARTIAL"


def build_proxy_cost_object(*, total: int, metered: int, observed_micro: Optional[int],
                            token_metered: int, input_tokens: Optional[int],
                            output_tokens: Optional[int]) -> dict:
    """Assemble the additive ``proxyCost`` object (spec §3.1) from a scope's
    aggregate counts. ``observed_micro`` is the SUM of ``proxy_micro_usd`` over
    the metered executions (None/absent when none are metered -- unknown, never
    zero). Token coverage is independent of cost coverage.

    Invariants: ``missingCostExecutions == total - metered``; completeness is
    UNAVAILABLE iff ``metered == 0``, COMPLETE iff ``metered == total > 0``,
    else PARTIAL; ``observedMicroUsd``/``observedUsd`` are None iff UNAVAILABLE.
    """
    completeness = _completeness(total, metered)
    micro = observed_micro if completeness != "UNAVAILABLE" else None
    return {
        "basis": BASIS,
        "observedMicroUsd": micro,
        "observedUsd": micro_to_usd_str(micro),
        "completeness": completeness,
        "meteredExecutions": metered,
        "totalExecutions": total,
        "missingCostExecutions": total - metered,
        "inputTokensObserved": input_tokens if token_metered > 0 else None,
        "outputTokensObserved": output_tokens if token_metered > 0 else None,
        "tokenMeteredExecutions": token_metered,
    }


def build_average_object(*, completed_issues: int, total_executions: int,
                         cost_metered_executions: int,
                         observed_micro: Optional[int]) -> dict:
    """Assemble the ``averageProxyCostPerCompletedIssue`` object (spec §3.2).

    Denominator is the count of DONE issues; numerator is the summed proxy cost
    of those issues' executions. Returns a null amount when there are no
    completed issues (spec §2.6) OR when none of their executions carry valid
    cost (missing cost is unknown, never $0.00). ``observed`` is True -- the
    "Observed average" label -- whenever any included cost is partial (not every
    included execution is metered). Both coverage figures are disclosed so issue
    coverage and usage coverage stay distinct.
    """
    partial = completed_issues > 0 and cost_metered_executions < total_executions
    if completed_issues == 0 or cost_metered_executions == 0 or observed_micro is None:
        micro: Optional[int] = None
    else:
        micro = int((Decimal(observed_micro) / Decimal(completed_issues)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP))
    return {
        "basis": BASIS,
        "observedMicroUsd": micro,
        "observedUsd": micro_to_usd_str(micro),
        "observed": bool(partial),
        "completedIssues": completed_issues,
        "costMeteredExecutions": cost_metered_executions,
        "totalExecutions": total_executions,
    }
