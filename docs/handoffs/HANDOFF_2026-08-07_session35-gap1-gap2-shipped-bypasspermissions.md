# Session Handoff — Gap 1 + Gap 2 shipped: bypassPermissions self-verify + new-file validation gate
Continues from: `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-05_session34-gap4-shipped-gap1-confirmed-live.md` — no conflicts (this session completes the Gap 1 + Gap 2 work session-34 explicitly deferred/blocked as a paired five-gate item; nothing here contradicts session-34's record)

## Objective
Session-34 left Gap 1 (a headless `-p` child cannot self-verify via Bash) and Gap 2 (the orchestrator's fixed validation-command list silently never runs a child-authored new test file) as an unstarted, paired five-gate item. This session ran root-cause and fix-surface probes against the real engine, produced a pre-committed outcome matrix and diff plan, implemented both fixes, ran all three gates, and shipped to `master`.

## Current Status
- Completed: Gap 1 (`_DEFAULT_PERMISSION_MODE` → `bypassPermissions`) and Gap 2 (Design A — explicit per-file append, not discovery) implemented, gated, committed (`6cb2f3d`). ADR-21 Amendment 2 documenting the fix and its accepted residual is committed in the same commit.
- In Progress: none.
- Blocked: none.

## Decisions & Rationale
- `_DEFAULT_PERMISSION_MODE` changed `"acceptEdits"` → `"bypassPermissions"` — under `acceptEdits`/`default`, every Bash `tool_use` in headless `-p` mode is auto-denied (`non_execution_kind="user-rejected"`) with no human present to approve it, verified live via the issue-26 transcript (4/4 denied) and 5 controlled probes this session; `bypassPermissions` is the only tested mode where a non-denied Bash command runs while `_DENY_TOOLS` still denies curl/rm/git identically (`non_execution_kind="permission-rule"`) — `src/runtime/engine/claude_headless.py`, `_DEFAULT_PERMISSION_MODE` block (was line 89 pre-edit; shifted down by the new rationale comment, exact new line not re-confirmed this session).
- Gap 2 implemented as explicit per-file append (Design A), not directory/glob discovery (Design B) — Design B would directly contradict ADR-23 rule 2 (`docs/08-session-0-closure-and-adr-amendments.md`), adopted specifically because StockPhotoAgent has other pytest-collectible files that are live credentialed browser-automation tests that must never be auto-swept into a gate.
- `RepositoryAdapter.added_files()` added as a new abstract method, backed by `git diff --name-status --diff-filter=A` (structured), not text-parsed out of the existing `diff()` unified output — `src/runtime/repo/adapter.py` + `src/runtime/repo/git_adapter.py`.
- `Validator.validate()` gained an `extra_commands` parameter appended per-call; `self.commands` (the config-sourced fixed list) is never mutated, so it stays an auditable, always-run baseline independent of any single execution — `src/runtime/validation/runner.py`.
- The new-file pytest commands' interpreter comes from a separate, explicit config field (`new_test_command_prefix`), not parsed out of the existing `commands` string — ADR-23 rule 1 states "the runtime resolves nothing," and parsing an opaque command string to extract an interpreter would violate that even when reusing an already-explicit value.
- Both new config fields (`new_test_pattern`, `new_test_command_prefix`) default to `None`/inert, so existing configs are behaviorally unaffected until they opt in; StockPhotoAgent's `config.yaml` was set live this session (`tests/test_*.py`, `C:\Python314\python.exe -m pytest`).

## Key Files
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — Gap 1: `_DEFAULT_PERMISSION_MODE`, its rationale comment, CLI-contract header re-pinned to 2.1.224. `_DENY_TOOLS` and `_command()`'s argv structure confirmed byte-unchanged (diffed line by line this session).
- `C:\Projects\issue-runtime\src\runtime\repo\adapter.py`, `git_adapter.py` — `added_files()` abstract + implementation.
- `C:\Projects\issue-runtime\src\runtime\validation\runner.py` — `validate(extra_commands=...)`.
- `C:\Projects\issue-runtime\src\runtime\loop.py` — `_new_test_commands()` hook + its call site in `_validate()`.
- `C:\Projects\issue-runtime\src\runtime\config.py`, `C:\Projects\issue-runtime\config.yaml` — the two new `ValidationCfg` fields, live values set for StockPhotoAgent.
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` — ADR-21 Amendment 2, the load-bearing record of the fix and its accepted residual.
- `C:\Projects\issue-runtime\tests\unit\test_engine.py`, `test_git_adapter.py`, `test_loop.py` — updated/extended for the new argv value and the new abstract method.
- `C:\Projects\issue-runtime\tests\unit\test_validation_extra_commands_gap2.py` — new file, 4 tests for the `extra_commands` mechanism.

## Next Action
Watch the first live orchestrator run against StockPhotoAgent with the Gap 2 hook active — it is unit-tested only, never exercised end-to-end against a real child-authored new test file in a live pipeline run.
Done when: a live run produces a `VALIDATION_PASSED`/`VALIDATION_FAILED` event whose `gate_results` includes an entry whose `"gate"` string starts with `C:\Python314\python.exe -m pytest` for a file that is NOT in `config.yaml`'s fixed `commands` list.

## Assumptions
- Gap 1's fix is verified against installed CLI `2.1.224` specifically — HIGH confidence for the current pin, but contingent on the CLI's own re-pin discipline (`claude_headless.py`'s own header requires re-witnessing on any version bump).
- Gap 2's mechanism (`added_files` + `extra_commands`) is unit-tested (5 dedicated tests) but not exercised against a real live run this session — MED confidence it behaves correctly end-to-end; the mechanism is simple and the unit tests cover the branching logic, but no live witness exists yet.
- Whether the Write-tool cwd-escape residual is genuinely new exposure under `bypassPermissions` or was already present under `acceptEdits` is UNCONFIRMED, not just undocumented — the one probe run under `acceptEdits` got a model self-refusal, not a mechanism-level answer (see Open Questions).

## Knowledge Captured
- The CLI's interactive Bash-approval heuristic (`non_execution_kind="user-rejected"`) and the `--disallowedTools` denylist (`non_execution_kind="permission-rule"`) are two independent mechanisms — denylist enforcement is unchanged across `default`/`acceptEdits`/`bypassPermissions`; only the approval heuristic differs by mode. Confirmed via 5 probes this session, including that `git status` (read-only) is denied by the denylist exactly like `git commit`.
- Under `bypassPermissions`, the `Write` tool has zero cwd confinement — host-verified via `Test-Path` (not the child's self-report) that a child wrote a file to an arbitrary absolute path outside its assigned workspace with no prompt and no denial, while a parallel `Bash rm` attempt at an out-of-cwd path in the same run WAS denied by the denylist. Two independent controls: the denylist covers specific Bash patterns; nothing covers `Write` path scope.
- `plan` permission mode never reaches Bash at all in headless `-p` — the child attempts `ExitPlanMode`, gets "not enabled in this context," and stalls asking a nonexistent human to confirm. It also wrote a real file to the host's `~/.claude/plans/` directory, outside any scratch workspace — an unanticipated side effect of a supposedly read-only probe.
- On this machine, PowerShell's `>` redirect defaults to UTF-16LE, corrupting UTF-8 `git diff` output (em-dashes, `§`) into mojibake on read-back; the console itself also mis-decodes git's UTF-8 stdout before `Out-File` ever sees it. Fix: `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` before the git call, piped to `Out-File -Encoding utf8`.

## Architecture Changes
Settled and built this session: `loop._validate()` now calls `_new_test_commands(ex)` → `RepositoryAdapter.added_files(base, end)` → `fnmatch` filter against `config.new_test_pattern` → builds `f"{new_test_command_prefix} {path}"` per match → passed as `Validator.validate(..., extra_commands=[...])`, appended after `self.commands` for that call only.

## Testing / Verification Performed
- PASS: `.venv\Scripts\python.exe -m pytest tests\unit -q` → `123 passed in 22.01s` (117 baseline + 6 new: 1 in `test_engine.py`, 1 in `test_git_adapter.py`, 4 in `test_validation_extra_commands_gap2.py`).
- PASS: `python tests\crash\harness.py <tmp> 42` → `ALL 60 SCENARIOS PASSED` (40 det + 15 rand + 4 fixture + 1 control).
- PASS: `python tests\crash\harness.py <tmp> 1337` → `ALL 60 SCENARIOS PASSED`, same arithmetic; re-run once this session after an incomplete first paste (transcription error, not a harness fault — the harness itself was run only once per seed).
- PASS: `git --no-pager show --stat HEAD` after commit → 12 files changed, 212 insertions(+), 9 deletions(-), matches the staged set exactly.
- NOT TESTED: Gap 2 hook against a real live StockPhotoAgent run. The Write-tool cwd-escape under `acceptEdits` at the mechanism level (probe was inconclusive — model self-refused before the fence ever answered). Destructive overwrite via `Write` (only `rm`-via-Bash deletion was probed). `Bash(git:*)` denial specifically under `default`/`plan` modes (only `bypassPermissions` was probed for git this session).

## Risks
- The confirmed Write-tool cwd-escape (no confinement under `bypassPermissions`) is now live in production config, not just a lab finding — a StockPhotoAgent-targeting child could write files outside its assigned workspace on the host if ever prompted, accidentally or adversarially, to do so. Accepted as unchanged risk per ADR-21 Amendment 2; not newly introduced, but now shipped rather than theoretical.

## User Constraints
- No commit without Adi's explicit go-ahead, given directly, not inferred from anything in a terminal buffer — enforced across the whole session (five-gate opener, edit phase, and commit were three separately gated turns).
- PowerShell only for all repo commands this session; Git Bash flagged by the user as having produced false results on this machine previously.
- Fixed order: commit → handoff → exit, not reorderable; StockPhotoAgent untouched throughout.

## Runtime & System State
- Commit at handoff: `6cb2f3d`.
- Long-lived processes: none — all probe children this session were synchronous spawns that completed and exited; nothing left running.
- Open branches / worktrees: none opened this session.
- Memory files updated: none.

## Deferred Work
- Mechanism-level test of Write-tool cwd-escape under `acceptEdits` (does the fence itself block it, or was the prior negative result only a model self-refusal?) — explicitly postponed by the user mid-session ("note it stays open, don't chase it here").
- Destructive-overwrite-via-`Write` path (writing garbage/empty content to an existing file is functionally a delete but was never probed) — same explicit deferral.
- `docs/reviews/` (`full-codebase-review.md`, `coverage-ledger.md`) — untracked since before this session (surfaced at cold-start), still not triaged.

## Open Questions
**Needs User Input**
- [non-blocking] Should `docs/reviews/` be committed, `.gitignore`d, or deleted? Untracked and unaddressed across this entire session.
- [non-blocking] Is a `Bash(git:*)`-under-`default`/`plan` probe needed to fully close the denylist verification, or is the `bypassPermissions` + `acceptEdits` coverage already obtained (curl/rm) sufficient given git was only directly probed under `bypassPermissions`?

**Model Uncertainty**
- Whether the Write-tool cwd-escape is genuinely new exposure from the `bypassPermissions` switch, or was already present under `acceptEdits` and just never triggered because the earlier probe's prompt read as an obvious containment test to the model — no probe design attempted this session forced a mechanism-level answer under `acceptEdits`.
