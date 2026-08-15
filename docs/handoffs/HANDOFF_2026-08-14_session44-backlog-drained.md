# Session Handoff — Full StockPhotoAgent backlog drain to terminal state
Continues from: C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-14_session43-first-live-drain.md — no conflicts (this session continues the live drain that session 43 started; no architecture or contract changes)

## Objective
Continue the live drain of the StockPhotoAgent issue backlog (started session 43) to completion, under a strict verify-before-and-after-every-action protocol driven by the user: every drain pass, recovery, and manual log edit was gated by raw command output pasted back before proceeding. Goal was to run the backlog to a terminal state (no PENDING, no ACTIVE) while proving durability behavior (crash recovery, orphan handling) along the way.

## Current Status
- Completed: Backlog drained to terminal state — 0 PENDING, 0 ACTIVE, 74 DONE, 7 NEEDS_HUMAN, 21 NEEDS_DECOMPOSITION (102 issues total). state/events.jsonl at last_event_id 843, verify-log OK.
- Completed: Orphaned execution 62-e1 (created when a Bash-tool 10-minute timeout SIGTERM'd the orchestrator mid-run) reconciled via `python -m runtime.main recover` → `ExecutionCrashed` at event 547.
- Completed: Issue 88 manually retired ACTIVE→NEEDS_HUMAN via a hand-appended `IssueEscalated` event (733, reason `reviewer-contract-violation`) after the orchestrator hit the same reviewer-parser halt twice in a row on it.
- Blocked: None remaining in the drain itself. The 21 NEEDS_DECOMPOSITION and 7 NEEDS_HUMAN issues are terminal states requiring separate follow-up work (decomposition, manual disposition), not further drain passes.

## Decisions & Rationale
- Switched from foreground `python -m runtime.main run` to non-blocking background execution (Bash `run_in_background: true`, output to `run.out`/`run.err`) after the first pass — HIGH confidence, directly observed: a foreground run with a 10-minute Bash-tool timeout got SIGTERM'd (exit 143) mid-execution on issue 62, leaving `62-e1` spawned but never finished. Background execution avoided any further tool-induced kills for the rest of the session.
- Recovered the orphan via `python -m runtime.main recover` rather than manually editing the log — HIGH confidence: this is exactly the reconciler's designed job (orphaned_execution check), verified by output showing `orphans_crashed: ["62-e1"]` → `ExecutionCrashed` emitted at event 547, then issue 62 correctly went back through the normal retry flow (`62-e2`) on the next drain pass.
- Issue 88 was manually escalated to NEEDS_HUMAN rather than retried further — HIGH confidence this was the right call given the evidence: the orchestrator hard-halted the *entire run* (exit 2, no new events at all) twice in a row with the identical error (`verdict must be APPROVE|REJECT, got '<prose>'`), on an execution (`88-e1`) whose diff had already passed validation (`ValidationPassed` at event 732, both pytest gates green). The defect is in the reviewer-verdict parser, not in issue 88's fix, so retrying issue 88 again would just re-trigger the same halt. Escalation event 733 payload uses `reason: "reviewer-contract-violation"` (a new reason string, not previously used) — the transition table (`src/runtime/state/transitions.py:22-27`) routes any `reason != "decompose"` to NEEDS_HUMAN, confirmed against the same code this session.
- Proved the manual event-733 append on a scratch copy of events.jsonl before touching the real log, and took a full pre-edit backup (`scratch/events_prebackup_732.jsonl`) — HIGH confidence, per explicit user instruction; this is the standing pattern for any hand-authored event going forward.

## Key Files
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-14_session43-first-live-drain.md` — prior handoff, drain context that led into this session
- `C:\Projects\issue-runtime\docs\03-state-machine-and-event-schema.md` — frozen event/state contract; referenced this session to confirm `IssueEscalated` transition legality before the manual append
- `C:\Projects\issue-runtime\src\runtime\state\transitions.py` — read this session (lines 22-27) to confirm `(ACTIVE, IssueEscalated)` → NEEDS_HUMAN when `payload.reason != "decompose"`, before authoring event 733
- `C:\Projects\issue-runtime\src\runtime\events\log.py` — read this session to confirm the log has no cross-line hash chaining (only per-line schema validity + contiguous event_id), which is why a manually appended, correctly-shaped line passes `verify-log`
- `C:\Projects\issue-runtime\state\events.jsonl` — the real event log, now at last_event_id 843
- `C:\Projects\issue-runtime\scratch\events_prebackup_732.jsonl` — full backup of the real log taken immediately before the event-733 manual append (at 732 events)
- `C:\Projects\issue-runtime\config.yaml` — `budget.max_executions_per_run: 10` (line ~66), confirmed this session; governs the per-pass cap referenced throughout

## Next Action
Fix the reviewer-verdict parser defect (Carry #1 below) in `src/runtime/` so a non-APPROVE|REJECT verdict string triggers a bounded reject-or-retry instead of a hard `sys.exit`-style run halt, then run the full five-gate process plus both durability-harness seeds before considering it shippable.
Done when: `python tests\crash\harness.py %TEMP%\ch` passes 60/60 on both seed 42 and seed 1337, AND a targeted unit/integration test reproduces the old halt input (a prose string instead of APPROVE/REJECT) and asserts the run continues (reject-and-retry, capped) instead of exiting.

## Assumptions
- MED confidence: the reviewer-parser defect is a code bug (unbounded hard-halt on unparseable verdict) rather than a qwen/reviewer-prompt issue — inferred from two identical failures on the same execution with no prompt change between them, but the reviewer's exact prompt/output-format contract was not re-read this session to rule out a prompt-side fix instead.
- HIGH confidence: no other issue in the 7 NEEDS_HUMAN or 21 NEEDS_DECOMPOSITION sets is blocked by this same parser defect — verified by checking each escalation's `reason` field this session (`superseded-context`, `superseded`, `decompose`, `cap-hit`, `reviewer-contract-violation`); only issue 88 carries the new reason.

## Testing / Verification Performed
- PASS: `python -m runtime.main verify-log` — final check this session returned `OK: 843 events, last_event_id=843`.
- PASS: `python -m runtime.main show-state` — final check returned issue-state counts {DONE: 74, NEEDS_HUMAN: 7, NEEDS_DECOMPOSITION: 21}, 0 PENDING/ACTIVE.
- PASS: `grep -i 0143486` over every `run.out`/`run.err` produced this session and over the full `state/events.jsonl` after each pass — zero new occurrences each time (only the two pre-existing lines from event 460/462, predating this session).
- PASS: scratch-copy proof of event 733 — `verify-log --log <scratch>` returned `OK: 733 events, last_event_id=733`; `show-state --log <scratch>` showed issue 88 → NEEDS_HUMAN, execution `88-e1` unchanged at REVIEWING — matched exactly after the real append.
- NOT TESTED: the reviewer-parser fix itself (not attempted this session — pure drain-and-verify session, no src/ changes made).
- NOT TESTED: durability harness (`tests\crash\harness.py`) was not re-run this session; last known-good state is from an earlier session per prior handoffs, unconfirmed as of this session's HEAD.

## Outstanding Issues
1. **Reviewer-parser hard-halt (HIGH severity).** The orchestrator hard-halts the *entire run* (process exit 2, zero new events logged) when the reviewer (qwen2.5-coder:14b via Ollama) returns a full prose explanation instead of the literal string `APPROVE` or `REJECT`. Observed twice this session, both on issue 88's `88-e1` execution — identical error text both times: `verdict must be APPROVE|REJECT, got '<prose>'`. This halts drain progress for the *whole queue*, not just the offending issue, until a human intervenes (which is why issue 88 was manually retired rather than left to block future passes). Needs a src/ fix: on unparseable verdict, treat as REJECT-and-retry (capped, same as other rejection paths), not as a fatal halt. This is a high-blast-radius change (runtime behavior) — per CLAUDE.md it needs full five gates, an ADR, and both durability-harness seeds green before shipping.
2. **21 issues in NEEDS_DECOMPOSITION** (includes 19, 25, 39, 43, 51, 52, 53, 56, 57, 58, 60, 62, 65, 72, 74, 86, 87, 91, 92, 93, 96 — full list not re-verified in this handoff, confirm against `show-state` before acting). Each needs to be broken into sub-issues with fresh IDs above the current ceiling (104) before it can re-enter the queue; the original issue IDs are terminal and will not be retried.
3. **7 issues in NEEDS_HUMAN** (12, 36, 48, 54, 82, 88, 94) need manual disposition. Six of these were escalated in prior sessions (per event history, not re-investigated this session). Issue 88 is the one exception fully diagnosed this session: it is blocked on Outstanding Issue #1 (the reviewer parser), not on its own content — its diff already passed both validation gates (`ValidationPassed`, event 732, `validated_commit: ea644ced2a7b...`). Recommend re-issuing it under a fresh ID once the parser fix ships, rather than trying to resume execution `88-e1` directly.

## User Constraints
- No commit without explicit authorization — never commit or push until the user explicitly authorizes that specific commit. (Note: an automated `history(auto)` git hook committed the working tree independently during this session, moving HEAD from `616de71` to `d378004` — this was not an agent-initiated commit and was not separately authorized within this session; flag to the user if unexpected.)
- Kill criteria (ADR-19) are frozen and must not be tuned to dodge a verdict.
- Every drain pass and log mutation this session required raw command output pasted back to the user before the next action — this was a per-session working style, not a standing repo rule, but continuing it is likely expected if this thread of work resumes with the same user.

## Runtime & System State
- Commit at handoff: `d378004` (issue-runtime repo; moved from `616de71` at session start via an automated `history(auto)` commit hook, not a manual commit this session)
- state/events.jsonl: last_event_id 843, verify-log OK (confirmed at end of session)
- StockPhotoAgent (external target repo): branch `agent-work`, working tree clean, HEAD left wherever the last `[shutdown] restored agent-work` line landed it — not re-verified after the final drain pass in this session; confirm with `git -C <StockPhotoAgent-path> status --porcelain` and `git rev-parse HEAD` before any further action.
- Long-lived processes: none — all drain passes were background Bash commands (`run_in_background: true`) that completed and were confirmed via task-completion notifications; no process left running.
- Untracked files in issue-runtime working tree at handoff: `run.out`, `run.err` (last drain pass's output — queue-drained pass, both empty/informational, safe to leave or clean up), `scratch/` (contains `events_prebackup_732.jsonl`), several prior-session handoff files not yet committed.

## Open Questions

**Needs User Input**
- [non-blocking] Should the six pre-existing NEEDS_HUMAN issues (12, 36, 48, 54, 82, 94) be worked in this same session thread, or is a separate session/owner expected? Not investigated this session beyond confirming their escalation reasons.
- [non-blocking] Priority order for the three carries — fix the reviewer parser first (unblocks re-running issue 88 content), or start decomposing the 21 NEEDS_DECOMPOSITION issues in parallel? Both are independent of each other.

**Model Uncertainty**
- Whether the reviewer-parser defect is reproducible with a different prompt/temperature setting on the qwen reviewer, or is inherent to how the model formats verdicts under certain diff shapes — not tested against multiple inputs this session, only observed on issue 88's two attempts.
