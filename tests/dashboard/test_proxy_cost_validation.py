"""Unit 1: pure proxy-cost/token validation (spec §2.2/§2.3).

usage.dollars -> integer micro-USD (Decimal(str())*1e6, ROUND_HALF_UP);
bool/negative/non-finite rejected; finite >= 0 accepted; a valid 0 is metered.
Tokens: non-negative int only, never bool; cost and token coverage independent.
Dollars never inferred from tokens or vice versa.
"""
from __future__ import annotations

import math

import pytest

from draindeck_dashboard.proxy_cost import validate_dollars, validate_tokens


# --- validate_dollars ---

@pytest.mark.parametrize("value", [True, False])
def test_dollars_bool_rejected(value):
    assert validate_dollars(value) is None


@pytest.mark.parametrize("value", [-0.01, -1, -1e-9, -1000000])
def test_dollars_negative_rejected(value):
    assert validate_dollars(value) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_dollars_non_finite_rejected(value):
    assert validate_dollars(value) is None


@pytest.mark.parametrize("value", ["1.84", None, [], {}, object()])
def test_dollars_non_numeric_rejected(value):
    assert validate_dollars(value) is None


def test_dollars_zero_is_metered_not_none():
    # A valid zero is metered: 0 micro-USD, not "missing".
    assert validate_dollars(0) == 0
    assert validate_dollars(0.0) == 0


def test_dollars_basic_conversion():
    assert validate_dollars(1.84) == 1_840_000
    assert validate_dollars(1) == 1_000_000


def test_dollars_round_half_up_at_micro_boundary():
    # 0.0000005 USD = 0.5 micro-USD -> ROUND_HALF_UP -> 1 micro-USD.
    assert validate_dollars(0.0000005) == 1
    # 1.8400005 USD = 1_840_000.5 micro-USD -> 1_840_001.
    assert validate_dollars(1.8400005) == 1_840_001


def test_dollars_uses_decimal_str_not_binary_float():
    # 2.675 as a binary float is slightly below 2.675; Decimal(str(x))
    # captures the intended decimal. 2.675 USD = 2_675_000 micro-USD exactly.
    assert validate_dollars(2.675) == 2_675_000


def test_dollars_large_value():
    assert validate_dollars(12345.678901) == 12_345_678_901


# --- validate_tokens ---

@pytest.mark.parametrize("value", [True, False])
def test_tokens_bool_rejected(value):
    assert validate_tokens(value) is None


@pytest.mark.parametrize("value", [-1, -100])
def test_tokens_negative_rejected(value):
    assert validate_tokens(value) is None


@pytest.mark.parametrize("value", [1.0, 1.5, "5", None, [], {}])
def test_tokens_non_int_rejected(value):
    assert validate_tokens(value) is None


def test_tokens_zero_and_positive_accepted():
    assert validate_tokens(0) == 0
    assert validate_tokens(41200) == 41200
