# Session Handoff — Issue 36 escalated to NEEDS_HUMAN; issue 37 shipped unplanned via a real scoping gap
Continues from: `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-09_session39-verdict-parser-fix-approved-halt-issue36.md` — superseded by this document (session 39 ended at "fix approved, halted at issue 36"; this session resumed exactly there, committed the fix, and drove issue 36 to a new terminal state).

## Objective
Gate the already-approved verdict-parser fix through the five-gate method, commit it, then resume the StockPhotoAgent drain at issue 36 (parked in REVIEWING since session 39's halt). The underlying problem: Qwen had returned a non-schema verdict (`'PASS'`) reviewing issue 36's diff, and the fix needed both landing safely and re-testing live before the drain could continue.

## Current Status
- Completed: verdict-parser fix committed at `6c213fd` (issue-runtime). Hardened one-liner in `qwen_ollama.py:118`: `verdict = str(obj.get("verdict") or "").strip().upper()` — non-string truthy values now raise a clean `ReviewParseError` instead of an `AttributeError`. 131 unit tests pass, durability 60/60 both seed 42 and seed 1337 — VERIFIED this session via `git show 6c213fd`, `pytest`, and the crash harness.
- Completed: issue 36 reached a terminal state, `NEEDS_HUMAN` — accepted as final for this session, no further automated retries.
- Completed (unplanned): issue 37 shipped — real `ValidationPassed`, real `ReviewApproved` from Qwen, merged to `agent-work` (merge commit `f2a539c4af3955752091428fc635d7672f5691e6`). Accepted as cleanly shipped by Adi despite being outside this session's stated single-issue scope.
- Blocked: issue 36 needs human decomposition or a different review strategy — Qwen never returned a schema-conformant verdict for its ~22K-char diff across 4 real samples (see Knowledge Captured).
- In Progress: none — session ended at a clean stopping point, config reverted, no pending runs.

## Decisions & Rationale
- Hardening pass (`str(...)` coercion) added before committing the approved one-line fix — accepted the extra line because a non-string truthy `verdict` field would otherwise crash with `AttributeError` instead of a clean parse error; this exact edge case fired for real on `36-e2` later in the session (a stringified QC-rule dict landed in the `verdict` field) and was caught cleanly, confirming the hardening was worth it. Lives at `src/runtime/reviewer/qwen_ollama.py:118`.
- Chose "force reject → retry/escalate" (manually inject `ReviewRejected` events) over two alternatives: adding a new `REVIEWING→escalated` transition (would need an ADR, touches the frozen state machine) or shrinking issue 36's payload to fit Qwen's apparent limit (unexplored, higher-risk change to context-pack building). Manual injection was lowest blast radius — no runtime code change, uses the log's own `EventLog.append()` path.
- Left issue 37 standing rather than reverting — it passed genuine validation and genuine reviewer approval, unlike issue 25's prior out-of-band hand-merge (which had neither). Judged as legitimately-shipped work, just via an unintended path.
- Accepted issue 36's `NEEDS_HUMAN` as the session's stopping point — it escalated via the duplicate-feedback guard (not the originally expected cap-hit path), but it is a real terminal state and no further runs were authorized.

## Key Files
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-09_session39-verdict-parser-fix-approved-halt-issue36.md` — prior handoff, superseded by this document for the issue-36-resume thread.
- `C:\Projects\issue-runtime\src\runtime\reviewer\qwen_ollama.py` — verdict-parser fix + hardening, line 118, confirmed this session via `git diff`/`git show 6c213fd`.
- `C:\Projects\issue-runtime\tests\unit\test_seams.py` — 8 new test cases added this session (case-normalization, reject paths, `None`, non-string verdict).
- `C:\Projects\issue-runtime\state\events.jsonl` — 390 events. Key ones this session: 376/380 (manual `ReviewRejected` for `36-e1`/`36-e2`, `run_id="manual-inject-*"`), 381 (`IssueEscalated` issue 36, reason `duplicate-feedback`, taxonomy `needs-human`), 382-389 (issue 37's full real pipeline through `IssueCompleted`), 390 (`IssueActivated` issue 38).
- `C:\Projects\issue-runtime\config.yaml` — `max_executions_per_run` reverted to 10; confirmed empty `git diff` this session (all single-issue-scope edits were working-tree-only and reverted after each run).
- `C:\Projects\StockPhotoAgent` (target repo) — `agent-work` HEAD now `f2a539c4af3955752091428fc635d7672f5691e6` ("merge 37"), confirmed via `git log --oneline -3` this session; tree clean.

## Next Action
Add the `max_executions_per_run` scoping-gap finding (below, Outstanding Issues) as a new dated item in `NEXT.md`, before attempting issue 38's drain.
Done when: `NEXT.md` contains a new entry describing this gap (config caps total executions per run, not which issue consumes the slot), distinct from the already-logged session-33 "no per-issue scope flag" item.

## Assumptions
- Root cause of Qwen's non-compliance = a model-scale/compliance limit on large diffs (~22K chars) — MED confidence. Inferred from 4 consecutive non-schema samples on the same payload (two live runs' worth, plus one throwaway probe); no controlled A/B test (e.g., re-running against a truncated or smaller diff) was performed this session to isolate size specifically from content (the diff itself contains QC-rule dict literals that may have primed the hallucinated/stringified-dict responses).
- "Prompt mandates APPROVE|REJECT exclusively, no PASS/FAIL variant" — HIGH confidence, VERIFIED verbatim this session (grepped `qwen_ollama.py`, rendered the actual `_SYSTEM` string via a live Python call).
- Reviewer raw-response is not persisted anywhere in the codebase — HIGH confidence, CONFIRMED this session via a grep sweep of the reviewer module/config/state plus a live throwaway probe showing no artifact exists for it.
- Issue 37's shipped diff content is sound — MED-HIGH confidence: real `ValidationPassed` (5/5 gate commands passed per `state/artifacts/37-e1/validation/0.log`) and real `ReviewApproved` from Qwen, both confirmed via `events.jsonl`; the diff's actual content was not manually re-read line-by-line this session.
- Reviewer model-string/provider config not persisted in some other location — INFERRED, carried from an earlier session's finding, not independently re-verified this session.

## Knowledge Captured
- The duplicate-feedback guard (`_has_duplicate_feedback` in `loop.py`) checks feedback *category*, not verdict content or message text. Two manually-injected `ReviewRejected` events sharing the same `taxonomy_category` ("review-correctness") tripped this guard before the attempts cap was ever reached, escalating issue 36 via `duplicate-feedback → needs-human` rather than the anticipated `cap-hit` path — and `36-e3` was never spawned as a result.
- `max_executions_per_run` caps total executions *per run*, not executions *for the targeted issue*. If the targeted issue leaves `ACTIVE` without consuming an execution (any form of escalation), the orchestrator's `_next_actionable()` loop moves on and the freed slot goes to the next queued issue. This is how issue 37 shipped without being explicitly authorized this session — confirmed live, not inferred, via the event log (`IssueEscalated` for 36 with `execution_id: null`, immediately followed by `IssueActivated`/full pipeline for 37, all inside one run capped at `max_executions_per_run: 1`).

## Outstanding Issues
- **Scoping gap (new, this session):** working-tree `max_executions_per_run` edits do not pin *which* issue consumes the execution slot — see Knowledge Captured above. Already manifested once (issue 37 shipped unplanned). Same class as session 33's already-logged "no per-issue scope flag" note, but a distinct, more specific mechanism (escalation-without-spawn falling through to the next queued issue). Not fixed this session — flagged for `NEXT.md` per Next Action.
- **Carried forward, not touched this session:** B-CRIT-1 (`_resolve_leaf_worker` unwired); Write-tool cwd-escape residual (ADR-21 Amendment 3) — see prior handoffs for detail, not re-verified here.

## User Constraints
- No commit without explicit, per-commit authorization (CLAUDE.md hard rule) — the verdict-parser commit only proceeded after an explicit "if and only if ALL gates green" authorization this session.
- Single-issue scoping via `config.yaml` edits must stay working-tree-only, never committed — enforced every time this session via an explicit `git diff` proof before and after each edit.
- Do not chain an authorized single-issue run into additional issues without separate authorization. This session showed the constraint can be violated *mechanically*, not just by operator choice — see Outstanding Issues. Operator discipline (careful config edits) is not sufficient on its own going forward.

## Runtime & System State
- Commit at handoff (issue-runtime): `6c213fd` — confirmed via `git rev-parse --short HEAD` this session; working tree otherwise carries only the same three pre-existing untracked docs/log files noted at session start.
- StockPhotoAgent `agent-work`: HEAD `f2a539c4af3955752091428fc635d7672f5691e6`, clean, confirmed via `git status --porcelain`/`git log` this session.
- No long-lived processes left running — every `run` invocation this session was synchronous/foreground and completed before the next command.
- No dev servers involved.
- No memory files updated this session.

## Open Questions
**Model Uncertainty**
- Whether Qwen's non-compliance on issue 36 is specifically diff *size* or diff *content* (the QC-rule dict literals inside the diff) was not isolated — no controlled smaller-diff test was run.
- Issue 38 (now `ACTIVE`, base commit `f2a539c4af395...`) has not been inspected for diff size or other characteristics that made issue 36 fail — unknown whether it's at similar risk.
