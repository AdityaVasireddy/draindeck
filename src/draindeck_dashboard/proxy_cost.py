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
