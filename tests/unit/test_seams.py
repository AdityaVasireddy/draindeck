"""Session-5 seam unit tests: Issues.md parser, Validator, BudgetManager, and
the QwenOllamaReviewer parse contract + transport retry. No live Ollama and no
real `claude` — the reviewer's HTTP is monkeypatched; the validator runs trivial
shell commands."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.budget.manager import BudgetManager                     # noqa: E402
from runtime.queue.issues_md import IssuesParseError, parse          # noqa: E402
from runtime.reviewer.base import ReviewPack, ReviewParseError, \
    ReviewerUnavailableError                                          # noqa: E402
from runtime.reviewer.qwen_ollama import QwenOllamaReviewer          # noqa: E402
from runtime.validation.runner import Validator                      # noqa: E402


# ── Issues.md parser ─────────────────────────────────────────────────
def test_parse_basic_with_deps_and_acceptance():
    text = (
        "# preamble ignored\n"
        "## 001: First issue\n"
        "Do the thing.\n"
        "Depends-On: 000, 002\n"
        "### Acceptance\n"
        "- it works\n"
        "- it is tested\n"
        "## 002: Second\n"
        "Body two.\n"
    )
    specs = parse(text)
    assert [s.id for s in specs] == ["001", "002"]  # file order preserved
    assert specs[0].title == "First issue"
    assert specs[0].depends_on == ["000", "002"]
    assert specs[0].acceptance_criteria == ["it works", "it is tested"]
    assert "Do the thing." in specs[0].body
    assert "Depends-On" not in specs[0].body  # dep line consumed, not body


def test_parse_malformed_heading_aborts():
    with pytest.raises(IssuesParseError):
        parse("## not-an-id-title-without-colon\nbody\n")


def test_parse_duplicate_id_aborts():
    with pytest.raises(IssuesParseError):
        parse("## 001: A\n## 001: B\n")


# ── Validator ────────────────────────────────────────────────────────
def test_validator_passes_all_commands(tmp_path):
    v = Validator(["exit 0", "exit 0"], timeout_seconds=30, artifacts_dir=tmp_path / "art")
    res = v.validate(tmp_path, "deadbeef", "042-e1")
    assert res.passed is True
    assert len(res.per_command) == 2
    assert res.validated_commit == "deadbeef"
    assert res.taxonomy_category is None


def test_validator_short_circuits_on_failure(tmp_path):
    v = Validator(["exit 1", "exit 0"], timeout_seconds=30, artifacts_dir=tmp_path / "art")
    res = v.validate(tmp_path, "deadbeef", "042-e1")
    assert res.passed is False
    assert len(res.per_command) == 1          # second command never ran
    assert res.taxonomy_category == "validation-test"
    assert res.flake_retries == 1             # the failing command was retried once


# ── BudgetManager ────────────────────────────────────────────────────
def test_budget_denies_at_execution_cap():
    b = BudgetManager(max_executions_per_run=2, hard_stop_proxy_cost_per_run_usd=100.0)
    assert b.check().allowed
    b.note_execution_started()
    assert b.check().allowed
    b.note_execution_started()
    assert not b.check().allowed  # 2/2 reached


def test_budget_denies_at_cost_ceiling():
    b = BudgetManager(max_executions_per_run=100, hard_stop_proxy_cost_per_run_usd=1.0)
    b.record_usage("e1", {"dollars": 0.6})
    assert b.check().allowed
    b.record_usage("e2", {"dollars": 0.6})     # cumulative 1.2 ≥ 1.0
    d = b.check()
    assert not d.allowed and "hard_stop" in d.reason
    assert b.record_usage("e3", None) is None  # tolerates missing usage


# ── QwenOllamaReviewer parse contract ────────────────────────────────
def _reviewer() -> QwenOllamaReviewer:
    return QwenOllamaReviewer("http://localhost:11434", "qwen2.5-coder")


def _pack() -> ReviewPack:
    return ReviewPack(execution_id="042-e1", reviewed_commit="cafe",
                      issue_text="do it", diff="--- a\n+++ b\n")


def test_reviewer_parses_approve_with_fence():
    r = _reviewer()
    v = r._parse(_pack(), '```json\n{"verdict":"APPROVE","feedback":[]}\n```')
    assert v.approved and v.provider == "qwen"
    assert v.reviewed_commit == "cafe" and v.execution_id == "042-e1"


def test_reviewer_parses_reject_with_feedback():
    r = _reviewer()
    v = r._parse(_pack(), '{"verdict":"REJECT","severity":"blocking",'
                 '"feedback":[{"category":"review-correctness","message":"bug"}]}')
    assert not v.approved
    assert v.feedback[0]["category"] == "review-correctness"


def test_reviewer_rejects_empty_feedback_as_unparseable():
    r = _reviewer()
    with pytest.raises(ReviewParseError):
        r._parse(_pack(), '{"verdict":"REJECT","feedback":[]}')


def test_reviewer_bad_json_is_unparseable():
    r = _reviewer()
    with pytest.raises(ReviewParseError):
        r._parse(_pack(), "I think this looks fine, approve it")


def test_reviewer_unknown_verdict_is_unparseable():
    r = _reviewer()
    with pytest.raises(ReviewParseError):
        r._parse(_pack(), '{"verdict":"MAYBE","feedback":[]}')


def test_reviewer_transport_failure_retries_then_unavailable(monkeypatch):
    """Two transport failures (initial + retry) → ReviewerUnavailableError,
    never a fabricated verdict. Backoff is zeroed so the test is fast."""
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise OSError("connection refused")

    r = QwenOllamaReviewer("http://localhost:11434", "qwen2.5-coder",
                           transport_backoff_seconds=0)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(ReviewerUnavailableError):
        r.review(_pack())
    assert calls["n"] == 2  # initial + one retry
