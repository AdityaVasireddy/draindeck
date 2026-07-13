"""QwenOllamaReviewer — the default v1 reviewer (ADR-05), Ollama-hosted.

Stdlib ``urllib`` only (deps frozen: pyyaml/pydantic/pytest). POSTs the review
pack to ``{endpoint}/api/chat`` (``stream:false``) and parses a single strict
JSON verdict. Two independent retries, distinct by design:
  * ONE transport retry after a short backoff (endpoint flaps / cold model)
    before ``ReviewerUnavailableError``.
  * ONE parse-retry (re-ask with the parse error appended) before
    ``ReviewParseError`` — doc 03 §4's "parse-retry enforced by orchestrator".
Neither failure is ever downgraded to a verdict (see base.py).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from .base import (
    ReviewerProvider,
    ReviewerUnavailableError,
    ReviewParseError,
    ReviewPack,
    ReviewVerdict,
)

# doc 02 §6 review-* taxonomy (closed set; extend only by ADR).
_REVIEW_CATEGORIES = ("review-correctness", "review-style")

_SYSTEM = (
    "You are a strict, single-shot code reviewer. You are given a unified diff, "
    "the issue it is meant to resolve, optional guidelines, and the validation "
    "output. Decide whether the diff correctly and cleanly resolves the issue.\n\n"
    "Respond with EXACTLY ONE JSON object and NOTHING else — no prose, no "
    "markdown, no code fence. Schema:\n"
    '{"verdict": "APPROVE" | "REJECT", '
    '"severity": "blocking" | "minor", '
    '"feedback": [{"category": <one of ' + ", ".join(_REVIEW_CATEGORIES) + ">, "
    '"message": <string>}]}\n\n'
    "On APPROVE, feedback may be an empty list. On REJECT, feedback MUST be "
    "non-empty and every item MUST have a non-empty category and message."
)


class QwenOllamaReviewer(ReviewerProvider):
    name = "qwen"

    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        timeout_seconds: float = 120.0,
        transport_backoff_seconds: float = 5.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds
        self.backoff = transport_backoff_seconds

    # ── the seam ──────────────────────────────────────────────────────
    def review(self, pack: ReviewPack) -> ReviewVerdict:
        user = self._render(pack)
        raw = self._call([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ])
        try:
            return self._parse(pack, raw)
        except ReviewParseError as first_err:
            # ONE parse-retry: re-ask, quoting the exact failure.
            retry_user = (
                user
                + "\n\nYour previous answer could not be parsed: "
                + str(first_err)
                + "\nReturn ONLY the single JSON object described above."
            )
            raw2 = self._call([
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": retry_user},
            ])
            return self._parse(pack, raw2)

    # ── transport (one retry, then unavailable) ───────────────────────
    def _call(self, messages: list[dict]) -> str:
        body = json.dumps({
            "model": self.model, "messages": messages, "stream": False,
        }).encode("utf-8")
        last: Exception | None = None
        for attempt in range(2):  # initial + one retry
            try:
                req = urllib.request.Request(
                    f"{self.endpoint}/api/chat", data=body,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                # Ollama /api/chat: {"message": {"role","content"}, ...}
                return (payload.get("message") or {}).get("content") or ""
            except (urllib.error.URLError, TimeoutError, OSError,
                    json.JSONDecodeError) as e:
                last = e
                if attempt == 0:
                    time.sleep(self.backoff)
        raise ReviewerUnavailableError(
            f"qwen reviewer at {self.endpoint} unreachable after retry: {last}"
        ) from last

    # ── strict parse (unparseable => ReviewParseError) ────────────────
    def _parse(self, pack: ReviewPack, raw: str) -> ReviewVerdict:
        text = _strip_fence(raw.strip())
        try:
            obj = json.loads(text)
        except (json.JSONDecodeError, ValueError) as e:
            raise ReviewParseError(f"verdict is not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise ReviewParseError("verdict is not a JSON object")
        verdict = obj.get("verdict")
        if verdict not in ("APPROVE", "REJECT"):
            raise ReviewParseError(f"verdict must be APPROVE|REJECT, got {verdict!r}")
        severity = obj.get("severity", "blocking")
        if severity not in ("blocking", "minor"):
            severity = "blocking"
        feedback = obj.get("feedback") or []
        if not isinstance(feedback, list):
            raise ReviewParseError("feedback must be a list")
        clean: list[dict] = []
        for item in feedback:
            if not isinstance(item, dict):
                raise ReviewParseError("feedback item must be an object")
            cat = item.get("category")
            msg = item.get("message")
            if not cat or not isinstance(cat, str):
                raise ReviewParseError("feedback item missing a non-empty category")
            entry = {"category": cat, "message": msg or ""}
            if item.get("location"):
                entry["location"] = item["location"]
            clean.append(entry)
        if verdict == "REJECT" and not clean:
            raise ReviewParseError("REJECT requires non-empty feedback")
        return ReviewVerdict(
            execution_id=pack.execution_id,
            reviewed_commit=pack.reviewed_commit,
            provider=self.name,
            verdict=verdict,
            severity=severity,
            feedback=clean,
        )

    @staticmethod
    def _render(pack: ReviewPack) -> str:
        parts = [f"ISSUE:\n{pack.issue_text}\n"]
        if pack.guidelines:
            parts.append("GUIDELINES:\n" + "\n".join(f"- {g}" for g in pack.guidelines) + "\n")
        if pack.validation_output:
            parts.append(f"VALIDATION OUTPUT:\n{pack.validation_output}\n")
        parts.append(f"DIFF:\n{pack.diff}")
        return "\n".join(parts)


def _strip_fence(text: str) -> str:
    """Remove a single optional ```json ... ``` fence, tolerating a stray
    leading language tag. Only the outermost fence is stripped."""
    if text.startswith("```"):
        text = text[3:]
        if text[:4].lower() == "json":
            text = text[4:]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
