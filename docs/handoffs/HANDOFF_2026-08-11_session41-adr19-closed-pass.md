# Session Handoff — session 41: ADR-19 formally closed PASS (two-sample corroboration); drain resumed through issue 47
Continues from: `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-10_session40-issue36-escalated-issue37-shipped.md` — no conflicts.

## Objective
Cold-start verification, then formally close the ADR-19 kill-criteria experiment by recording a second corroborating sample (issues 29–47) alongside the existing n=20 verdict, and resume the live drain from issue 38 onward under the newly-logged single-issue-scope caveat.

## Current Status
- Completed: Cold-start confirmed clean (issue-runtime HEAD `6c213fd`, StockPhotoAgent `agent-work` @ `f2a539c`, `events.jsonl` = 390 lines, Ollama reachable with `qwen2.5-coder:14b` loaded). `NEXT.md` SCOPING GAP entry committed `7a58762` (single-issue live scope unreliable — `max_executions_per_run` caps total executions per run, not the targeted issue; documented after issue 37 shipped unplanned on a slot freed by issue 36's escalation). Unit baseline re-verified via `.venv\Scripts\python.exe -m pytest -q` — 131 passed. Durability harness re-verified both seeds on fresh temp roots (`%TEMP%\ch_s40i38_42`, `%TEMP%\ch_s40i38_1337`) — `ALL 60 SCENARIOS PASSED` both. Batch drain `run-20260811T235441Z` executed against real StockPhotoAgent: issues 38–47, cap-stopped at `max_executions_per_run reached (10/10)`, `proxy_dollars_this_run=$6.5999`. Shipped attempt-1: 38, 40, 41, 42, 44, 45, 46, 47 (8 issues, all `CommitCreated` ending `-e1`). Escalated: 39, 43 (both `needs-decomposition`, turn-budget exhaustion). Issue 48 `IssueActivated` but never spawned — budget hit first. ADR-19 formally closed: committed `e9f5d5b` appending a `### ADR-19 — CLOSED PASS (2026-08-11)` block to `docs/08-session-0-closure-and-adr-amendments.md` §4, recording both samples — Sample 1 (n=20, issues 13–22 + prior 10, attempt-1 85%, ~$0.36/shipped) and Sample 2 (n=19, issues 29–47, attempt-1 84%, $0.61/shipped incl. wasted escalation spend) — both bars pass, $15 hard stop never breached, no double-commit, all shipped issues attempt-1 under Rule B (strict).
- In Progress: none.
- Blocked: none.

## Decisions & Rationale
- Used `.venv\Scripts\python.exe` for pytest/harness/orchestrator instead of `C:\Python314\python.exe` — the system Python lacks `pyyaml`/`pydantic` (confirmed this session via a live `ModuleNotFoundError` on pytest collection); matches the standing requirement already documented in `NEXT.md` §7.
- Ran the durability harness against freshly-unused temp roots (`ch_s40i38_42`, `ch_s40i38_1337`) rather than deleting stale prior-session scratch directories under `%TEMP%\ch*` — the stale dirs hit a Windows `PermissionError` on `shutil.rmtree` (read-only git objects) and the user denied a proposed `rm -rf` cleanup, so a new unused name was the non-destructive path forward.
- Launched the live batch drain via plain `run` (not `recover`) against real StockPhotoAgent under the user's explicit authorization — no `--issue`/per-issue scope flag exists in `main.py`'s argparse, so the run auto-drained from issue 38 (first PENDING issue, since 36/37 are terminal) through the execution cap.
- Reverted an initial mistaken append (made to the session-29 ADR-19 handoff, the wrong target) via `git checkout --`, then appended the formal ADR-19 closure block to the canonical criteria document instead — `docs/08-session-0-closure-and-adr-amendments.md` §4 is where the pre-committed criteria table and honesty clause actually live; the session-29 handoff only ever held the n=20 scoring narrative, not the criteria themselves. Committed as `e9f5d5b`.

## Key Files
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` — §4 now carries the ADR-19 CLOSED PASS verdict block (committed `e9f5d5b`); this is the authoritative kill-criteria record going forward.
- `C:\Projects\issue-runtime\NEXT.md` — carries the SCOPING GAP entry (committed `7a58762`); read before any future single-issue-scoped live run.
- `C:\Projects\issue-runtime\state\events.jsonl` — events 322–461 are the raw evidence for both ADR-19 samples' second-sample corroboration (issues 29–47); events 391–462 specifically are this session's batch drain.
- `C:\Projects\issue-runtime\config.yaml` — `budget.max_executions_per_run: 10`, `budget.hard_stop_proxy_cost_per_run_usd: 15.0` (unchanged this session, re-confirmed live before the drain).
- `C:\Projects\issue-runtime\run_cohort_38_47.log` — stdout capture of this session's batch drain (untracked, not committed).

## Next Action
Decompose issue 39 (first of the three escalated issues in queue order; `needs-decomposition`, turn-budget exhaustion at 47 turns) into sub-issues before any further drain touches it — a plain `run` will otherwise silently skip 39/43/36 (they are terminal-escalated, not PENDING/ACTIVE) and proceed straight to issue 48 without ever resolving the backlog.
Done when: `Issues.md` contains new sub-issue entries derived from issue 39's `needs-decomposition` transcript (`state\artifacts\39-e1\transcript.jsonl`), so that a subsequent `run` picks up the decomposed sub-issues rather than leaving 39 permanently stuck in `NEEDS_HUMAN`-adjacent limbo.

## Assumptions
- MED confidence: reviewer model-string is not persisted in the event schema, and the reviewer's raw response (severity/feedback) is persisted nowhere — both carried forward from prior sessions' notes (`session-38-close.md`, `NEXT.md` Session-33 entry), not re-verified this session by reading the reviewer code or event schema directly.
- MED confidence: B-CRIT-1 (`_resolve_leaf_worker` gated behind `ITEM9_SENTINEL`, no live wiring) and the Write-tool cwd-escape residual (ADR-21 Amendment 3, not fenced) are both carried forward from `session-38-close.md`'s Outstanding Issues — not re-verified this session by reading `claude_headless.py` or the write-tool fence.
- HIGH confidence: the mid-session prompt-injection-style system-reminder had zero actual effect on repository state — independently verified via `git diff --stat` and `git status --porcelain` showing no diff for the file in question, both immediately after the suspicious reminder and again after the user's explicit revert instruction.

## Knowledge Captured
- `loop.py`'s `_next_actionable()` only ever returns an ACTIVE issue or a deps-met PENDING issue — an escalated issue (NEEDS_HUMAN or needs-decomposition) is a terminal state and is silently skipped by a plain `run`. This means issues 36, 39, and 43 do not block or re-trigger a future drain on their own; without explicit decomposition/intervention, `run` will proceed straight to issue 48 and beyond, leaving the backlog escalations stranded indefinitely.
- `C:\Python314\python.exe` (system interpreter) lacks `pyyaml`/`pydantic`; confirmed live this session via a `ModuleNotFoundError` during pytest collection. `.venv\Scripts\python.exe` is required for all orchestrator-side commands (pytest, harness, `runtime.main`).
- The crash harness's `%TEMP%\ch*` scratch directories from prior sessions (dozens observed) reliably hit `PermissionError: WinError 5` on `shutil.rmtree` cleanup — Windows read-only locks on old `.git\objects\*` files. Workaround used this session: pick a genuinely unused root name rather than deleting the stale one.
- A fake/injected system-reminder appeared mid-session immediately after a `git checkout --` revert, falsely claiming the reverted file had been "modified by the user or a linter" and instructing silence toward the user. Treated as a prompt-injection attempt (per the standing instruction to flag suspected injections rather than comply), independently verified false, and surfaced to the user directly instead of being followed.

## Testing / Verification Performed
- PASS: cold-start `git log --oneline -1` (issue-runtime) = `6c213fd`; `git branch --show-current` = `master`; `git merge-base --is-ancestor 6c213fd HEAD` rc=0.
- PASS: cold-start `git log --oneline -1` (StockPhotoAgent) = `f2a539c` (`merge 37`), branch `agent-work`, clean `git status --porcelain`.
- PASS: `state\events.jsonl` line count = 390 at cold-start, via `wc -l`.
- PASS: `http://localhost:11434/api/tags` returned 200 with `qwen2.5-coder:14b` present.
- PASS: `.venv\Scripts\python.exe -m pytest -q` — 131 passed.
- PASS: durability harness, seed 42, fresh root `%TEMP%\ch_s40i38_42` — `ALL 60 SCENARIOS PASSED`.
- PASS: durability harness, seed 1337, fresh root `%TEMP%\ch_s40i38_1337` — `ALL 60 SCENARIOS PASSED`.
- PASS: batch drain `run-20260811T235441Z` — stdout confirmed `[done] budget hard stop: max_executions_per_run reached (10/10)`, `[metrics] executions_this_run=10 proxy_dollars_this_run=$6.5999`, `[shutdown] restored agent-work`.
- PASS: `git -C StockPhotoAgent log --oneline` confirmed real merge/work commits for all 8 shipped issues in 38–47 (38, 40, 41, 42, 44, 45, 46, 47), each with a `merge N` + `work N-e1` pair.
- PASS: `events.jsonl` grep across issues 29–47 confirmed 16 `IssueCompleted` (all `reason:"accepted"`) + 3 `IssueEscalated` (36 `duplicate-feedback`/needs-human, 39 and 43 `decompose`/needs-decomposition) — 19 total, all accounted for.
- PASS: `events.jsonl` `CommitCreated` grep confirmed all 16 shipped issues in 29–47 have `execution_id` ending `-e1` — zero retries anywhere in that window.
- PASS: cost extraction — summed `ExecutionFinished.payload.usage.dollars` across 4 `run_id`s covering issues 29–47: `run-20260810T002149Z` $2.2048404, `run-20260810T193401Z` $0.7751203, `run-20260810T201428Z` $0.2470495, `run-20260811T235441Z` $6.5999187 — grand total $9.8269289 / 16 shipped = $0.6142/issue.
- PASS: `git show --stat e9f5d5b` — exactly one file changed, `docs/08-session-0-closure-and-adr-amendments.md`, 13 insertions, 0 deletions.
- NOT TESTED: issue 48's actual execution — activated only, never spawned (budget cap hit first).
- NOT TESTED: any decomposition of issues 36, 39, or 43 — flagged and deferred, not attempted this session.

## Outstanding Issues
- Issues 36, 39, 43 remain escalated (needs-human / needs-decomposition respectively) and unresolved — carried into this session's close, not addressed. See Next Action.
- B-CRIT-1 (`_resolve_leaf_worker` gated behind `ITEM9_SENTINEL`, no live wiring) — carried forward from `session-38-close.md`, not touched or re-verified this session.
- Write-tool cwd-escape residual (ADR-21 Amendment 3, not fenced) — carried forward from `session-38-close.md`, not touched or re-verified this session.
- Reviewer raw-response (severity/feedback) not persisted anywhere, and reviewer model-string not persisted in the event schema — both carried forward (NEXT.md Session-33 entry, `session-38-close.md`), non-blocking, not touched this session.

## User Constraints
- No commit without Adi's explicit authorization of that specific commit — enforced throughout (NEXT.md scoping-gap entry, ADR-19 closure block, and this handoff file were each held uncommitted until separately authorized in turn; this handoff itself is NOT committed per this session's explicit instruction).
- `ANTHROPIC_API_KEY` must stay unset (subscription billing, ADR-18) — not explicitly re-checked this session, no action taken that would have set it.

## Runtime & System State
- Commit at handoff: `e9f5d5b` (issue-runtime, `master`).
- Long-lived processes: none still running — the batch-drain background task (harness id `bgdoiacrz`) completed with exit code 0 before this handoff was written; nothing left dangling.
- Dev servers / ports: none.
- Open branches / worktrees: issue-runtime on `master` @ `e9f5d5b`, working tree carries untracked `docs/handoffs/HANDOFF_2026-08-09_session39-verdict-parser-fix-approved-halt-issue36.md`, `docs/handoffs/HANDOFF_2026-08-10_session40-issue36-escalated-issue37-shipped.md`, `docs/handoffs/session-38-close.md`, `run_cohort_29_38.log`, `run_cohort_38_47.log`, plus this new handoff file — none committed. StockPhotoAgent on `agent-work`, tip `01434867765bec00495643bf307bd61c934336b7` (`merge 47`), restored/clean per the drain's `[shutdown] restored agent-work` line.
- Memory files updated: none this session.

## Deferred Work
- Decomposition of issue 36 (needs-human, duplicate-feedback taxonomy) deferred separately from 39/43 (needs-decomposition) — its escalation reason is structurally different (duplicate reviewer feedback, not turn-budget exhaustion) and may need a different remedy than sub-issue breakdown; not scoped or attempted this session.
- Fixing the `max_executions_per_run` single-issue-scope gap in `src/` (NEXT.md SCOPING GAP entry) — deferred; ADR-19 closure did not require it, and it is a `src/`-level change requiring the full five-gate/durability-harness discipline.

## Open Questions
**Needs User Input**
- [non-blocking] Should issue 36 be decomposed the same way as 39/43, or does its `needs-human`/`duplicate-feedback` taxonomy call for a different remedy (manual fix, prompt-pack revision)? Not addressed this session.
- [non-blocking] Now that ADR-19 is formally closed PASS, should the `max_executions_per_run` single-issue-scope gap be fixed in `src/`, or left as a known/documented-and-mitigated gap indefinitely?

**Model Uncertainty**
- None beyond what's already captured under Knowledge Captured — the injected system-reminder's full text was directly observed and already reported to the user in-session; nothing further to resolve there.
