"""ReviewerProvider contract + the structured verdict (doc 03 §4, doc 09 §6.3).

A verdict approves *tree `reviewed_commit` for issue X*, not "the issue" — that
makes verdicts cacheable and replay-safe (doc 03 §4). The reviewer is a pure
function of its ReviewPack; it never touches git, the log, or the repo.

Failure taxonomy (doc 09 §6.3, reconciled with doc 03 §2 by Session 5; the
malformed-output path further reconciled by the reviewer-protocol-violation
fix after the event-733 incident):
  * A transport failure (endpoint down / HTTP error / timeout) raises
    ``ReviewerUnavailableError``. This propagates out of the orchestrator's
    review step and halts the run — doc 03 §2's REVIEWING row is authoritative
    here: the state is *re-callable* ("verdicts cacheable by (issue, tree
    hash)"), so the next startup simply re-calls the reviewer against the same
    pinned tree. Nothing about the endpoint being unreachable is evidence
    against the diff, so no verdict is fabricated.
  * A verdict that cannot be parsed into this contract after one parse-retry
    raises ``ReviewParseError``. Unlike a transport failure, this is NOT
    treated as retryable/re-callable: the orchestrator (``loop.py``'s
    ``_review``) catches it and escalates the affected issue via
    ``IssueEscalated(reason="reviewer-protocol-violation")`` — the existing
    ACTIVE→NEEDS_HUMAN transition (doc 03 §1), not a new one. The run itself
    does not halt; other independent issues keep draining. NEITHER failure
    ever maps to ReviewApproved OR ReviewRejected: a ReviewRejected requires a
    ``feedback[{category,...}]`` list that would have to be invented,
    poisoning the duplicate-category escalation rule and ADR-19 metrics. This
    overrides doc 09 §6.3's "malformed ⇒ reject" while honoring its real
    intent: never retry-until-approve, and never let malformed output read as
    approval.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Optional

_SCHEMA_VERSION = 1


class ReviewerError(RuntimeError):
    """Base for reviewer-seam failures. Nothing is swallowed."""


class ReviewerUnavailableError(ReviewerError):
    """The provider could not be reached (transport/timeout). The execution
    parks in REVIEWING; recovery re-calls on the next startup."""


class ReviewParseError(ReviewerError):
    """The provider answered but the verdict is unparseable after one
    parse-retry. Never silently downgraded to a reject."""


@dataclass(frozen=True)
class ReviewPack:
    """Exactly what a reviewer receives (doc 02 §5): diff, issue, guidelines,
    validation output. Not the repo, not the transcript, not authorship."""

    execution_id: str
    reviewed_commit: str
    issue_text: str
    diff: str
    validation_output: str = ""
    guidelines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewVerdict:
    """The structured contract (doc 03 §4). ``verdict`` is the decision;
    ``feedback`` carries taxonomy-categorized critique (doc 02 §6 review-* set)
    and is REQUIRED non-empty on REJECT (it drives retry feedback + the
    duplicate-category escalation)."""

    execution_id: str
    reviewed_commit: str
    provider: str
    verdict: Literal["APPROVE", "REJECT"]
    severity: Literal["blocking", "minor"] = "blocking"
    feedback: list[dict] = field(default_factory=list)
    schema_version: int = _SCHEMA_VERSION

    @property
    def approved(self) -> bool:
        return self.verdict == "APPROVE"


class ReviewerProvider(ABC):
    """The seam. Implementations are selected by ``config.reviewer.provider``
    and constructed once at startup."""

    #: provider label recorded in ReviewApproved/ReviewRejected.reviewer_provider
    name: str = "abstract"

    @abstractmethod
    def review(self, pack: ReviewPack) -> ReviewVerdict:
        """Single-shot structured call. Raises ReviewerUnavailableError on
        transport failure and ReviewParseError on an unparseable verdict — never
        returns a fabricated APPROVE/REJECT for either."""
