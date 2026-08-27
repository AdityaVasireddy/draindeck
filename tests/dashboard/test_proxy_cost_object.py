"""Unit 3: pure proxyCost / average object builders and completeness
(spec §2.5/§2.6/§3.1/§3.2)."""
from __future__ import annotations

from draindeck_dashboard.proxy_cost import (
    BASIS,
    build_average_object,
    build_proxy_cost_object,
    micro_to_usd_str,
)


def test_micro_to_usd_str():
    assert micro_to_usd_str(1_840_000) == "1.840000"
    assert micro_to_usd_str(0) == "0.000000"
    assert micro_to_usd_str(500_000) == "0.500000"
    assert micro_to_usd_str(12_345_678_901) == "12345.678901"
    assert micro_to_usd_str(None) is None


def test_complete_object():
    obj = build_proxy_cost_object(total=2, metered=2, observed_micro=1_840_000,
                                  token_metered=2, input_tokens=41200, output_tokens=9800)
    assert obj == {
        "basis": BASIS,
        "observedMicroUsd": 1_840_000,
        "observedUsd": "1.840000",
        "completeness": "COMPLETE",
        "meteredExecutions": 2,
        "totalExecutions": 2,
        "missingCostExecutions": 0,
        "inputTokensObserved": 41200,
        "outputTokensObserved": 9800,
        "tokenMeteredExecutions": 2,
    }


def test_partial_object():
    obj = build_proxy_cost_object(total=3, metered=2, observed_micro=1_840_000,
                                  token_metered=2, input_tokens=41200, output_tokens=9800)
    assert obj["completeness"] == "PARTIAL"
    assert obj["missingCostExecutions"] == 1
    assert obj["observedMicroUsd"] == 1_840_000


def test_unavailable_object_empty_scope():
    obj = build_proxy_cost_object(total=0, metered=0, observed_micro=None,
                                  token_metered=0, input_tokens=None, output_tokens=None)
    assert obj["completeness"] == "UNAVAILABLE"
    assert obj["observedMicroUsd"] is None
    assert obj["observedUsd"] is None
    assert obj["totalExecutions"] == 0
    assert obj["missingCostExecutions"] == 0
    assert obj["inputTokensObserved"] is None
    assert obj["outputTokensObserved"] is None


def test_unavailable_object_no_metered_but_has_executions():
    obj = build_proxy_cost_object(total=3, metered=0, observed_micro=None,
                                  token_metered=0, input_tokens=None, output_tokens=None)
    assert obj["completeness"] == "UNAVAILABLE"
    assert obj["observedMicroUsd"] is None
    assert obj["missingCostExecutions"] == 3


def test_metered_zero_is_complete_not_unavailable():
    # A valid $0.00 across all executions is COMPLETE and observed, not missing.
    obj = build_proxy_cost_object(total=1, metered=1, observed_micro=0,
                                  token_metered=0, input_tokens=None, output_tokens=None)
    assert obj["completeness"] == "COMPLETE"
    assert obj["observedMicroUsd"] == 0
    assert obj["observedUsd"] == "0.000000"


# --- average per completed issue ---

def test_average_null_when_no_completed_issues():
    obj = build_average_object(completed_issues=0, total_executions=0,
                               cost_metered_executions=0, observed_micro=None)
    assert obj["observedMicroUsd"] is None
    assert obj["observedUsd"] is None
    assert obj["observed"] is False
    assert obj["completedIssues"] == 0


def test_average_complete_not_observed_label():
    # 2 DONE issues, both fully metered, total 4_000_000 micro -> avg 2_000_000.
    obj = build_average_object(completed_issues=2, total_executions=2,
                               cost_metered_executions=2, observed_micro=4_000_000)
    assert obj["observedMicroUsd"] == 2_000_000
    assert obj["observedUsd"] == "2.000000"
    assert obj["observed"] is False  # COMPLETE -> plain average


def test_average_partial_uses_observed_label():
    # 2 DONE issues, only 1 execution metered -> "Observed average".
    obj = build_average_object(completed_issues=2, total_executions=2,
                               cost_metered_executions=1, observed_micro=2_000_000)
    assert obj["observedMicroUsd"] == 1_000_000
    assert obj["observed"] is True


def test_average_null_when_completed_issues_but_no_metered_cost():
    # DONE issues exist but none have valid cost -> unknown, never $0.00.
    obj = build_average_object(completed_issues=2, total_executions=3,
                               cost_metered_executions=0, observed_micro=None)
    assert obj["observedMicroUsd"] is None
    assert obj["observed"] is True  # partial (nothing observed of something expected)
    assert obj["completedIssues"] == 2


def test_average_rounds_half_up():
    # sum 1 micro over 2 issues = 0.5 -> ROUND_HALF_UP -> 1 micro.
    obj = build_average_object(completed_issues=2, total_executions=2,
                               cost_metered_executions=2, observed_micro=1)
    assert obj["observedMicroUsd"] == 1
