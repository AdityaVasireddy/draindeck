# Session Handoff — first live drain of the StockPhotoAgent backlog
Continues from: C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-12_session42-decompose-36-39-43-collision-recovery.md — no conflicts

## Objective
Went live: ran the first real drain of the StockPhotoAgent issue backlog through the orchestrator, after a read-only design phase (Phase Q) established that a naive ingest would silently load two footguns — a WONT-FIX issue (99) and two SUPERSEDED issues (54, 82) with stale bodies that the ingest's id-only dedup would never catch. The session's work was to neutralize both footguns and the ACTIVE-issue-48 recovery hazard before authorizing the drain, then execute and verify it.

## Current Status
- Completed: StockPhotoAgent/Issues.md edited to remove issues 54, 82, 99 (committed `7e18da1`, StockPhotoAgent, branch agent-work). Real event log retired issues 48/54/82 to NEEDS_HUMAN via a 5-event append (event_ids 463-467). Live drain executed: ingested issues 100-104, ran 10 executions, hard-stopped cleanly at the budget cap. issue-runtime `state\events.jsonl` verified at 521 events (`verify-log`: `OK: 521 events, last_event_id=521`). StockPhotoAgent agent-work HEAD carries merge commits for issues 49, 50, 55 (`ee99da7`, `90e7710`, `8fc6560`, merging work commits `e7d83a7`, `6c6b64b`, `0dde88e` respectively).
- In Progress: backlog drain itself — only 10 of the remaining actionable issues were processed this pass; PENDING queue still has 44 issues.
- Not yet built: nothing — this session only operated the existing runtime, no code changes.

## Decisions & Rationale
- Deleted the `## 54:`, `## 82:`, `## 99:` headings from `StockPhotoAgent\Issues.md` — issue 99 (WONT-FIX) would have been ingested as a live PENDING issue and executed against a premise the author had already marked false; issues 54/82 (SUPERSEDED by 104) would still be drained against their stale pre-supersession bodies because ingest dedups by id only, never re-reads STATUS. Committed separately as `7e18da1` before any live drain, so the drain's ingest step never saw these three ids. — `C:\Projects\StockPhotoAgent\Issues.md`
- Retired issues 48 (ACTIVE, interrupted from a prior session), 54, and 82 to NEEDS_HUMAN by appending 5 events directly to the real log (`IssueEscalated` for 48; `IssueActivated`+`IssueEscalated` for 54; `IssueActivated`+`IssueEscalated` for 82), landing as event_ids 463-467 with resulting digest `e479e2eaa77bfc0f875d7d59b9a97a3da024a7c6e23cc324f683d6bca36773c8`. Proven byte-identical on a scratch copy of the log first (`scratch\design-2026-08-13\events_scratch.jsonl`) so the real-log append's resulting last_event_id and digest were known in advance rather than discovered after the fact. Used only the existing legal `(ACTIVE, IssueEscalated)` transition already present in `ISSUE_TRANSITIONS` — no new event type, no src/ state-machine change. — `C:\Projects\issue-runtime\state\events.jsonl`
- Retiring ACTIVE-issue-48 also eliminated a live recovery hazard, as a side effect rather than the primary goal: with 48 ACTIVE and no execution yet spawned for it, the reconciler's `check_dirty_workspace` would have computed `expected = issue_base_commit['48']` (a commit ref beginning `0143486...`) and called `adapter.reset_hard(expected)` on the next recovery pass. With 48 now terminal (NEEDS_HUMAN), no issue is ACTIVE going into recovery, so `_expected_commit` falls through to `adapter.head_of(target_branch)` instead. Confirmed this session: zero `reset workspace to 0143486` lines anywhere in the live run's captured stdout. — `C:\Projects\issue-runtime\src\runtime\recovery\bindings.py`

## Key Files
- `C:\Projects\issue-runtime\state\events.jsonl` — the real event log, now at 521 events, verified clean
- `C:\Projects\issue-runtime\scratch\design-2026-08-13\` — this session's scratch workspace. Contains: `FINDINGS-Q-ingest.md` (the only one of three planned findings docs actually written and verified intact this session — 853 lines, 0 replacement characters on byte check); `FINDINGS-P-scope.md` and `FINDINGS-R-order.md` were never produced despite writer scripts `_write_p.py`/`_write_r.py` existing on disk targeting those exact paths — most likely never executed, no partial/tmp artifact found either; `retire_scratch_probe.py` (the dry-run proof script, run against `events_scratch.jsonl`); `retire_real_append.py` (the script that performed the real-log append); `events_prebackup_467.jsonl` (pre-mutation backup of the real log at 462 events, taken immediately before the real append)
- `C:\Projects\StockPhotoAgent\Issues.md` — issues 54/82/99 removed, committed as `7e18da1`

## Next Action
From `C:\Projects\issue-runtime`, re-run `.venv\Scripts\python.exe -m runtime.main run --config config.yaml` to continue draining the backlog (self-resumes from event 521; hard-stops at the 10-execution budget cap, ~$6-7/pass — this pass cost $6.7113).
Done when: post-run, `.venv\Scripts\python.exe -m runtime.main verify-log --log state\events.jsonl` reports `last_event_id` greater than 521 with no error, and no issue's execution state is CRASHED in an unexpected way (an execution reaching CRASHED without a matching orphan/timeout explanation would fail this check; REJECTED with a normal retry is expected and passes).

## Testing / Verification Performed
- PASS: `verify-log --log state\events.jsonl` → `OK: 521 events, last_event_id=521`, run after the live drain completed.
- PASS: `StateProjection` rebuild from the real log this session → counts `{'PENDING': 44, 'DONE': 43, 'NEEDS_DECOMPOSITION': 9, 'NEEDS_HUMAN': 5, 'ACTIVE': 1}`; issues 100-104 all `PENDING`; issues 48/54/82 all `NEEDS_HUMAN`.
- PASS: `git -C C:\Projects\StockPhotoAgent log --oneline -8` → confirmed merge commits `8fc6560`/`90e7710`/`ee99da7` for issues 55/50/49 sit directly above `7e18da1` (the Issues.md removal commit) and `749aea6`.
- PASS: `Select-String` over the captured drain stdout for pattern `reset|0143486` → zero matches, confirming the retired-hazard reset never fired.
- PASS: event_ids for the 5 newly-ingested issues confirmed via direct log read: `468 IssueCreated 100`, `469 IssueCreated 101`, `470 IssueCreated 102`, `471 IssueCreated 103`, `472 IssueCreated 104`.
- NOT TESTED: the unit test suite (`pytest tests\unit`) and the crash harness were not re-run this session; this session only exercised the live `run` command end-to-end.

## Risks
- ~50% of issues touched by this drain pass landed as NEEDS_DECOMPOSITION (9 of the roughly 19 issues activated). Not a runtime defect — no code is implicated — but worth investigating as a backlog-quality/throughput concern (issues possibly too large or underspecified for a single execution) before assuming future passes will convert PENDING to DONE at a similar rate.

## User Constraints
- Do not treat a future drain's recovery-pass `reset_hard` call as a regression of the hazard flagged this session: the NEXT drain's recovery will legitimately reset to whatever issue is ACTIVE at that time, against its real recent base_commit — that is normal reconciler behavior (docs/11 A2.3), not a reappearance of the retired `0143486...` hazard.

## Runtime & System State
- Commit at handoff (issue-runtime): `616de71`
- StockPhotoAgent branch: agent-work, HEAD `8fc6560`
- No long-lived processes left running; the live drain (`runtime.main run`) exited cleanly (exit code 0) and is not still active.
