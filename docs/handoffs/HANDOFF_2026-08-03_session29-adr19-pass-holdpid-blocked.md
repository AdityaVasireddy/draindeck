# Session Handoff — session 29: ADR-19 CLOSED as PASS at n=20; hold_pid commit blocked on harness environment fault

**NOTE ON ORDERING**: This handoff was written and committed BEFORE the pending hold_pid commit on `src/runtime/engine/claude_headless.py`. That is a deliberate deviation from the normal commit→handoff→exit sequence, authorized this session: the state worth preserving right now IS the blocked commit plus an environment fault, best picked up fresh in the next session rather than carried forward in a stale context window. The hold_pid diff remains present, correct, and uncommitted — do not commit it until the durability harness gate below clears.

## Objective
Close out the ADR-19 fault-injection experiment (issues 13–22, n=20 cumulative sample) with a real orchestrator run against StockPhotoAgent, score the three ADR-19 gates from raw event-log/git evidence, and witness the S-E (real-merge) behavior needed to clear the standing hold_pid commit gate. A secondary thread this session closed a leftover config-hygiene residual (Option C) from the prior session's handoff.

## Current Status
- Completed: ADR-19 scored and closed as **PASS** at n=20 (attempt-1 85%, cost ~$0.36/shipped, no-double-commit verified — see Testing/Verification). Option A run executed end-to-end against real StockPhotoAgent. S-E witnessed on one representative merge. `config.example.yaml` em-dash residual committed.
- In Progress: none.
- Blocked: the hold_pid commit on `src/runtime/engine/claude_headless.py` is blocked — the standing gate requires 60/60 on the durability harness for both seed 42 and seed 1337, and this session's seed-42 attempt crashed before any of the 60 scenarios ran (environment fault, not an invariant failure — see Outstanding Issues).

## Decisions & Rationale
- Adopted Rule B (strict) for the ADR-19 attempt-1 numerator: an attempt-1 success is literally an `-e1` execution reaching APPROVE+merge with no prior crash or retry — a later `-e2`/`-e3` success does not count. Rationale: settles an ambiguity carried forward from prior sessions. Applied to score this run at 17/20 = 85%.
- Dropped issue-12 from the ADR-19 id-space as a byte-identical duplicate of issue-11 — both `12-e1` and `12-e2` resolved to commit `d663e32c...`, which is issue-11's own `11-e3` merge commit (confirmed via `git show --stat` on both refs in an earlier turn this session).
- Corrected the candidate `Issues.md` from `## Issue N: Title` headings to bare `## N: Title` before swapping it into StockPhotoAgent — the real parser (`C:\Projects\issue-runtime\src\runtime\queue\issues_md.py`) requires the id immediately after `## ` with no intervening word; verified this by reading the parser's regex and by an actual dry-run parse (`scratch\parse_check.py`) that showed the uncorrected form would raise `IssuesParseError` and abort the whole file.
- Kept the CLOSED historical entries (issues 7–10) in the swapped `Issues.md` rather than splitting them into a separate audit-only doc — confirmed by reading `src\runtime\main.py`'s `_ingest_issues` (~lines 127–148) that ingestion dedups purely by `spec.id` membership in `proj.issues`, never by the STATUS text in the body, so re-listing already-completed ids is a no-op, not a collision risk.
- Replaced the em-dash in `config.example.yaml`'s validation-command placeholder with a plain ASCII hyphen — byte-level inspection (hex dump) this session confirmed the true character was U+2014 (`E2 80 94` in UTF-8, no BOM) before editing. Committed as `26ce5a7` in the build repo.

## Key Files
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — the hold_pid diff (thread-based stdin delivery + `_sentinel_pause`/`_resolve_leaf_worker` leaf-worker resolution + `hold_pid` companion process + `capture_work_liveness` Layer-2 helper). **Still uncommitted** — this is what the next session commits once the harness gate clears.
- `C:\Projects\issue-runtime\src\runtime\queue\issues_md.py` — Issues.md parser; its docstring and `_ID_TITLE` regex are the ground truth for the `## <id>: <title>` format contract (no "Issue" word, no spaces in the id).
- `C:\Projects\issue-runtime\src\runtime\main.py` — `_ingest_issues` (~line 127) is the id-membership dedup logic that makes re-listing CLOSED historical issues safe.
- `C:\Projects\StockPhotoAgent\Issues.md` — swapped and committed this session (`baf8edd`); now holds CLOSED 7–10 plus 13–22 (9 shipped, 1 escalated).
- `C:\Projects\issue-runtime\tests\crash\harness.py` — durability harness; `main()` (~line 548) takes positional `<root_dir> <seed> [point_filter]`, not flags — see Knowledge Captured.
- `C:\Projects\issue-runtime\state\events.jsonl` — grew from 109 to 195 lines this session; events 110–195 belong to `run-20260803T050931Z`.

## Next Action
Clear the environment fault (lingering processes / stale temp dirs — see Outstanding Issues), then re-run the durability harness fresh and sequentially: seed 42 to completion, then seed 1337. Only once both show a literal 60/60 is the hold_pid commit authorized.

## Knowledge Captured
- `src/runtime/queue/issues_md.py`'s heading regex requires the bare id immediately after `## ` (charset `[A-Za-z0-9][A-Za-z0-9_-]*`, no spaces permitted). A heading like `## Issue 7: Title` fails to match and raises `IssuesParseError`, which aborts parsing of the **entire file**, not just that heading.
- `src/runtime/main.py`'s `_ingest_issues` dedups purely by `spec.id in proj.issues` — the STATUS text in an issue's body (`OPEN`/`CLOSED`) is never inspected by the ingestion path.
- The real orchestrator entrypoint is `python -m runtime.main run --config CONFIG`, and it must be invoked with `C:\Projects\issue-runtime\.venv\Scripts\python.exe` — that venv has `pyyaml`/`pydantic` installed; `C:\Python314\python.exe` does not (confirmed via `pip show pyyaml` failing there) and is only StockPhotoAgent's target test interpreter (used inside the validation gate command, not for running the orchestrator itself).
- `tests\crash\harness.py`'s CLI is positional (`harness.py <root_dir> <seed> [point_filter]`), not flag-based — passing `--help` is silently accepted as a literal root-directory value (not recognized as a help flag) and the harness actually starts running against that bogus path.
- Issue 19's `ExecutionFinished` this run carried `outcome:"REJECTED"` and `taxonomy_category:"needs-decomposition"` with **no** `ValidationPassed`/`ReviewRejected` event anywhere between its spawn and its `IssueEscalated` — a pre-gate self-classification escalation path, structurally distinct from issue-12's earlier post-gate `ReviewRejected` path seen in prior sessions.
- The Bash tool wrapper used to invoke PowerShell this session repeatedly stripped `$_`/`$env:`/`$LASTEXITCODE` tokens when passed inline via `-Command "..."` (bash's own variable expansion consumes them before PowerShell sees them). Writing the command to a `.ps1` file and invoking it with `-File` reliably avoided this; inline `-Command` with PowerShell-native `$`-syntax should be avoided going forward.

## Assumptions
- MED confidence: the seed-42 harness `PermissionError` (WinError 5, during `shutil.rmtree` at `harness.py:323`, cleaning up a stale `$env:TEMP\ch-seed42\_calibration` directory) is an environment/leftover-state fault rather than a real invariant regression — inferred from the failure occurring during pre-test cleanup, before `_calibration` or any of the 60 scenarios ran, not from any assertion. Not independently proven by inspecting file handles — no handle-inspection tool was available this session, so the two lingering `python.exe` processes observed (PIDs 37052, 40224) are a plausible but unconfirmed cause.
- HIGH confidence: the hold_pid diff itself is unchanged in shape from what prior sessions' handoffs describe (thread-based stdin feed, sentinel pause, leaf-worker resolution) — confirmed by reading the full diff this session.

## Testing / Verification Performed
- PASS: dry-run parse of the corrected candidate `Issues.md` through the real parser (`scratch\parse_check.py`) — 14 headings parsed cleanly, no `IssuesParseError`; active ids exactly `13`–`22`, no duplicates; zero collision with existing ids `1`–`12`.
- PASS: post-swap heading grep on the live `C:\Projects\StockPhotoAgent\Issues.md` — exactly 14 bare `## N:` headings, no `## Issue N:` form survived.
- PASS: Option A orchestrator run completed (exit code 0) against real StockPhotoAgent — baseline `baf8edd` → final tip `779fb3edba9d9beecc38cc3fc034b06de7d87811`; event log grew 109 → 195 lines (86 new events, `run-20260803T050931Z`).
- PASS: merge-parent structure check across the run range — all 9 merges (issues 13–18, 20–22) have exactly two parents; parent-1 forms the unbroken `baf8edd → 779fb3e` chain; all 9 second-parent commit hashes are pairwise distinct (no work commit merged twice).
- PASS: S-E witness on merge `779fb3e` (issue 22) — its diff against parent-1 is byte-identical (`review_manager.py`, 25+/9−) to its second parent's own diff; no extra content rode the merge.
- PASS: full-log cost extraction — 22 `ExecutionFinished` records across the whole event log (all runs), total `$6.1476478`; 17 of the 22 correspond to shipped/accepted issues.
- NOT TESTED: durability harness, seed 42 — crashed in pre-test cleanup before any of the 60 scenarios executed (see Outstanding Issues). Seed 1337 was never attempted, since the gate requires stopping on any seed's failure before trying the next. This is **unwitnessed** durability this session, not a pass or a fail tally.

## Outstanding Issues
- Two `python.exe` processes were observed still running at the time of the seed-42 harness failure: PID `37052` (`C:\Projects\issue-runtime\.venv\Scripts\python.exe`) and PID `40224` (`C:\Python314\python.exe`). Their exact role was not conclusively determined this session (no handle-inspection tool available). A stale `$env:TEMP\ch-seed42\_calibration\repo\.git\objects\...` file caused a `PermissionError` during the harness's pre-test `shutil.rmtree` cleanup, crashing the run before any of the 60 scenarios executed. A parallel `$env:TEMP\ch-seed1337` directory was never touched this session (seed 1337 was never run) — whether it exists from an earlier session is unconfirmed.
- A stray `--help` directory was created directly under the build repo root (`C:\Projects\issue-runtime\--help\`), confirmed via `git status` this session as an untracked entry. Root cause: an earlier mistaken invocation of `tests\crash\harness.py --help` (run from cwd `C:\Projects\issue-runtime`) was silently accepted as a literal root-directory argument rather than a help flag (see Knowledge Captured), and the harness began creating its "world" there before being backgrounded/abandoned. Not cleaned up this turn per this turn's explicit "no temp-dir deletion" scope — this is a newly-discovered item, not one the reviewer had already flagged; next session should confirm nothing valuable is inside before removing it.

## Technical Debt
- `config.example.yaml` line 11's `<StockAgent test command — REQUIRED before first run>` placeholder (inside the ADR-23 validation-command block) remains untouched — intentionally scoped out again this session; Option C this session only fixed the em-dash on the other placeholder line (now line 10). Deliberate, low-blast-radius, deferred.
- S-E is witnessed on exactly one representative merge (`779fb3e`, issue 22) out of the nine produced this run, not all nine. Deliberate scope choice this session; flagged as an open follow-up if a stronger full-set witness is wanted later.

## User Constraints
- No commit without Adi's explicit authorization of that specific commit — enforced throughout this session (the config.example.yaml commit, the Issues.md swap commit, and this handoff's own commit were each separately authorized in turn; the hold_pid commit remains unauthorized/blocked).
- `src/` changes require literal 60/60 on both seeds (42 and 1337) before commit — the standing gate currently blocking the hold_pid commit.
- Git Bash is inadmissible for validation on this project — all commands this session ran through `powershell.exe` (via the Bash tool wrapper, generally as `.ps1` files — see Knowledge Captured) or a direct Python interpreter call, never Git Bash.
- `ANTHROPIC_API_KEY` must stay unset (subscription billing, ADR-18) — confirmed unset immediately before the Option A run.
- Do not blanket-kill `python.exe` processes when clearing the environment fault — identify each by command line first (explicit instruction this session, given two live PIDs of unconfirmed origin).

## Runtime & System State
- Commit at handoff (build repo, immediately before this handoff's own commit): `26ce5a7`.
- Background processes: none believed still running that this session started and left dangling — the Option A run and both harness invocations (the mistaken `--help` one and the deliberate seed-42 one) each reported a terminal status (completed/exit code) by the time this handoff was written. The two `python.exe` PIDs above (37052, 40224) were observed via `Get-Process`, not via a tool-tracked background shell id, so there is no kill command recorded for them from this session — identify by command line before acting.
- Dev servers / ports: none.
- Open branches / worktrees: build repo (`C:\Projects\issue-runtime`) on `master`, at `26ce5a7` before this handoff's commit; working tree carries the uncommitted hold_pid diff on `src/runtime/engine/claude_headless.py` plus pre-existing modified/untracked items from earlier sessions (`.gitignore`, the session-26 handoff, the session-27 handoff, `scratch/`), plus the newly-discovered stray `--help/` directory. StockPhotoAgent (`C:\Projects\StockPhotoAgent`) on branch `agent-work`, tip `779fb3edba9d9beecc38cc3fc034b06de7d87811`, clean working tree.
- Memory files updated: none this session.

## Deferred Work
- Re-run the durability harness fresh, sequentially, seed 42 then seed 1337 — deferred to next session per this session's explicit "no harness run" scope this turn; required before the hold_pid commit can proceed.
- Full nine-merge S-E witness (currently only `779fb3e`/issue-22 witnessed) — deferred, optional, only pursue if a stronger guarantee is wanted.
- Issue 19 (three-way country-derivation divergence) remains unshipped, escalated `needs-decomposition` — retrying it requires breaking it into smaller sub-issues first; deferred as its own follow-up.

## Open Questions
**Needs User Input**
- Should the stray `C:\Projects\issue-runtime\--help\` directory be deleted, and should `$env:TEMP\ch-seed42` (and `ch-seed1337` if it exists) be cleared before the next harness attempt — or does Adi want to inspect their contents first?
- Should the two lingering `python.exe` processes (PID 37052, PID 40224) be identified and/or terminated before the next harness run, or does Adi want their command lines identified first?

**Model Uncertainty**
- Whether the seed-42 `PermissionError` was actually caused by either of the two observed `python.exe` processes, or by something else entirely (antivirus, a third unenumerated process) — not conclusively determined this session; no handle-inspection tool was available.
- Whether `$env:TEMP\ch-seed1337` already exists from an earlier session — not checked this session, since seed 1337 was never attempted.
