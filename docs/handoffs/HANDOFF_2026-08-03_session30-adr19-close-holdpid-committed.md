# Session Handoff — hold_pid commit landed after mechanically-verified 60/60 durability gate on both seeds

## Objective
Session 29 closed with ADR-19 PASS at n=20 but the hold_pid commit blocked: the durability harness had crashed in pre-test cleanup (PermissionError on a stale `.git` object during `shutil.rmtree`) before any scenario ran. This session's job was to clean the environment, re-run the crash durability harness fresh on both seeds (42, 1337), get evidence strong enough for a separate reviewer to authorize the commit — specifically a *mechanical* PASS/FAIL count independent of the harness's own "ALL 60 SCENARIOS PASSED" self-report string — then commit only the hold_pid change and close with a handoff. Two-role relay: this session executed commands and pasted raw output; a separate reviewer chat gated each step before the next was authorized.

## Current Status
- Completed: stale `--help/` directory removed; confirmed via live process list that nothing held the harness temp roots; harness re-run fresh and sequential on both seeds with output captured to file; mechanical `Select-String` counts confirmed 60 PASS / 0 FAIL-ERROR-SKIP on both; hold_pid change committed as `7d2f4eb` (single file, reviewed via `git show --stat` and full diff); post-commit tree confirmed to contain no unintended sweep-ins.
- In Progress: none — this handoff is the last step of the session.
- Blocked: nothing this session. The full nine-merge S-E witness sweep against StockPhotoAgent remains open but is explicitly out of this session's scope (see Deferred Work).

## Decisions & Rationale
- Ran all validation commands via `powershell.exe -NoProfile -Command` (never raw Git Bash) per project instruction, to avoid backslash-path mangling.
- First cleanup attempt double-quoted the `-Command` string; the Bash tool's own shell expanded `$env` as an (empty) bash variable before PowerShell ever saw it, mangling `$env:TEMP` into `:TEMP` and producing bogus "path not found" errors. Fixed by single-quoting the `-Command` string so PowerShell resolves `$env:TEMP` itself — a tool-invocation detail of this session, not a file change.
- Re-ran both seeds a second time (an earlier un-teed run had also shown 60/60) specifically to pipe stdout through `Tee-Object` to a log file, because the reviewer required the PASS/FAIL count via `Select-String` against captured output, not the harness's own summary line.
- Staged and committed only `src/runtime/engine/claude_headless.py` by explicit path (never `git add -A`), leaving `.gitignore`, the modified session-26 handoff, the untracked session-27 handoff, and `scratch/` untouched — reviewer was explicit that those must not be swept in.
- Used a genuinely fresh temp root per seed rather than relying on the harness's own per-scenario cleanup, since `tests\crash\harness.py`'s `fresh_scenario()` (~line 320, confirmed via Read this session) only calls `shutil.rmtree` (line 323) when the scenario subdirectory already exists — a fresh root never triggers that path, sidestepping the exact PermissionError that blocked session 29.

## Key Files
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — file committed this session (`7d2f4eb`); contains the hold_pid gate on the stdin-write/wait path, LAYER 1 (`_resolve_leaf_worker`, `_sentinel_pause`, the hold_pid companion process), and LAYER 2 (`capture_work_liveness`, built but not yet called against StockPhotoAgent).
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-03_session29-adr19-pass-holdpid-blocked.md` — prior handoff; full context on why the commit was blocked going into this session.
- `C:\Projects\issue-runtime\tests\crash\harness.py` — durability gate; `main()` at line 548 takes positional `root` (sys.argv[1]), `seed` (sys.argv[2]), optional `point_filter` (sys.argv[3]); no documented flag to skip/force pre-test cleanup.

## Next Action
Read this handoff and `NEXT.md`, then decide with the user/reviewer whether to start the full nine-merge S-E witness sweep against StockPhotoAgent (1 of 9 merges witnessed so far — see Deferred Work) or the issue-19 decomposition follow-up. The durability gate itself is closed for this cycle (60/60 both seeds, mechanically confirmed) — do not re-run it as a first step unless something changes that specifically calls it into question.

## Knowledge Captured
- The Bash tool's underlying Git Bash shell mangles PowerShell `$env:VAR` syntax when it appears inside a double-quoted `-Command` string (bash expands `$env` itself, as empty, leaving `:VAR`). Single-quoting the `-Command` argument avoids this, since PowerShell then resolves `$env:VAR` on its own side.
- `tests\crash\harness.py` has no CLI flag to skip or force pre-test cleanup. Its only pre-scenario cleanup is inside `fresh_scenario()` (~line 320): `if base.exists(): shutil.rmtree(base)` (line 323) — this only fires on a *reused* root whose scenario subdirectory already exists, not on a fresh one.
- Grepping raw `git diff` output for lines matching `^\+` overcounts insertions by exactly 1 relative to `git diff --stat`, because the `+++ b/<file>` diff header line also matches `^\+`. Confirmed this session: raw count 275 vs. `--stat`-reported 274 insertions on the identical diff.

## Assumptions
- ADR-19 PASS at n=20 — this is the message text of commit `cf8fe56`, which was confirmed as HEAD at the start of this session via `git rev-parse HEAD`. The underlying kill-criteria evaluation was not re-run or re-verified this session. MED confidence (HEAD match is confirmed; the PASS determination itself is trusted from the commit message, not re-derived).
- "S-E witnessed on run-20260803T050931Z merge 779fb3e (issue 22)" — this exact claim was supplied by the reviewer as the required commit-message text; it was not independently verified against a run log or the merge commit this session. LOW-MED confidence — treat as reviewer-asserted.
- "Full nine-merge witness sweep still open," "issue-19 decomposition not yet started," and "`config.example.yaml` line 11 `<StockAgent>` placeholder scoped out" — all supplied by the user for this handoff; not independently verified this session (did not read `config.example.yaml` or an issue tracker).

## Testing / Verification Performed
- PASS: crash durability harness, seed 42, fresh root — `ALL 60 SCENARIOS PASSED`, `EXITCODE:0`; independently confirmed via `Select-String -Pattern '^PASS '` count = 60 and `^(FAIL|ERROR|SKIP)` count = 0 against a `Tee-Object`-captured log file.
- PASS: same for seed 1337, fresh separate root — mechanical counts 60 / 0, `EXITCODE:0`.
- PASS: `git show --stat 7d2f4eb` and the full `git diff 7d2f4eb~1 7d2f4eb` reviewed directly — confirms exactly one file changed, 274 insertions / 9 deletions, and that the content is the hold_pid/LAYER1/LAYER2 logic described above, not a reformat or duplication artifact.
- NOT TESTED: unit test suite (`python -m pytest tests\unit -q`) was not run this session — only the durability harness was in the reviewer's turn scope.
- NOT TESTED: no interaction with StockPhotoAgent this session (explicitly out of scope, per direct instruction).

## Risks
- The hold_pid companion-process logic (LAYER 1 / `_sentinel_pause`) has so far only run under the crash harness's `ITEM9_SENTINEL` fixture and against one real merge (779fb3e / issue 22). The remaining 8 of 9 planned witness-sweep merges have not yet exercised this code against real StockPhotoAgent conditions.

## User Constraints
- No commit without explicit, per-commit authorization (project CLAUDE.md rule; reaffirmed turn-by-turn this session).
- PowerShell only for validation commands, never Git Bash directly.
- Do not touch StockPhotoAgent this session.
- Fixed order: commit → handoff → exit; handoff not to start until the commit is confirmed clean.
- Stage files explicitly by path — never `git add -A` or `git add .`.

## Runtime & System State
- Commit at handoff: `7d2f4eb` (full: `7d2f4eb52c86b85bc8ebf9536d3b572bb3736fca`)
- Background processes: none started this session — all harness runs were foreground/synchronous.
- Dev servers / ports: none.
- Open branches / worktrees: none created; all work done directly on `master`.
- Memory files updated: none this session.

## Deferred Work
- Full nine-merge S-E witness sweep against StockPhotoAgent — 1 of 9 merges witnessed so far (779fb3e / issue 22, per commit message). Explicitly out of scope this session ("do not touch StockPhotoAgent").
- Issue-19 decomposition — not started, per user note; not independently investigated this session.
- `config.example.yaml` line 11 `<StockAgent>` placeholder — explicitly scoped out of this session's work, per user note; file not read this session to confirm current state.

## Open Questions

**Needs User Input**
- When should the nine-merge S-E witness sweep against StockPhotoAgent begin, and does it require the same stepwise, raw-output-per-turn authorization protocol used this session?

**Model Uncertainty**
- The ADR-19 n=20 kill-criteria evaluation itself (the actual pass/fail arithmetic) was not re-run this session — only the fact that HEAD matched the commit asserting it. If that evaluation needs re-confirming, re-derive it from the ADR-19 doc and underlying run data rather than trusting the commit message alone.
