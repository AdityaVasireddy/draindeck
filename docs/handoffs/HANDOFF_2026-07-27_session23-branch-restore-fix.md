# Session Handoff — Surface-3 branch-restore fix (NEXT.md item 8) implemented and gated

## Objective
Implement NEXT.md §2 item 8: `cmd_run` left the target repo checked out on the last
issue/N attempt branch instead of `cfg.project.branch` on exit. This is a `src/`
exit-path change (high-blast-radius per CLAUDE.md), so it was gated on a fix-shape
proposal, then a full durability harness re-run (60/60, both seeds) and reviewer
approval before any commit — no commit without explicit reviewer gate + user
authorization, per the session's own opening instruction.

## Current Status
- Completed: fix implemented, tested, harness-verified, and committed in two gated
  steps. Item 8 is RESOLVED. NEXT.md updated to record the resolution and a defect
  reclassification, and committed.
- In Progress: none — item 8 is fully closed this session.
- Blocked: none.

## Decisions & Rationale
- Fix lives in `cmd_run` (`src/runtime/main.py`), not in `loop.py`'s `Orchestrator.run()`
  — `loop.py` is the frozen state-machine core per doc 03; workspace/git teardown is a
  session-lifecycle concern `main.py` already owns (symmetric with the existing startup
  checkout at `main.py:189`). No touch to `loop.py`, schema, or transitions.
- Restructured `cmd_run`'s existing single try/except (around `orch.run()`) into an
  `exit_code` variable pattern with one `finally` attached to that same `try`, so the
  restore checkout fires on every exit path: clean drain, budget hard stop,
  `OrchestratorHalt`/`ReviewerError`, `KeyboardInterrupt`, and uncaught-exception
  fall-through (verified via raw `git diff` that no bare `return 2`/`return 0` survived
  inside the try/except — both were fully replaced by `exit_code = ...`).
- The restore call is wrapped in its own inner `except RepoError` inside the `finally`
  (log-and-continue, no re-raise) — a failed shutdown checkout must not supersede an
  in-flight `OrchestratorHalt`'s exit code (Python's finally-supersedes-return/exception
  semantics would otherwise let a shutdown git failure mask a real halt). Proven with a
  dedicated test, not just asserted from the shape.
- Defect reclassified in NEXT.md: originally filed as "dirty tree" (uncommitted
  changes). Live `git status` (full form, not `--porcelain`) on `StockPhotoAgent` this
  session showed `nothing to commit, working tree clean` while `On branch issue/5` —
  the actual defect is narrower: wrong branch checked out, tree otherwise clean. Same
  fix class and root cause; recorded so the next session doesn't have to re-derive this
  correction.

## Key Files
- `~/Projects/issue-runtime/src/runtime/main.py` — `cmd_run`'s try/except/finally
  restructure (the fix itself).
- `~/Projects/issue-runtime/tests/unit/test_main_exit_paths.py` — new file, 5 tests:
  one per exit path (clean drain, `OrchestratorHalt`, `ReviewerError`,
  `KeyboardInterrupt`) plus the restore-failure-survives-halt guard test. All mock
  `Orchestrator`/`GitCliAdapter`/etc. at the `runtime.main` module level rather than
  driving a real `cmd_run` end-to-end.
- `~/Projects/issue-runtime/NEXT.md` — item 8 marked RESOLVED with an appended
  resolution + defect-reclassification note (original filing left untouched, per doc 12
  append-only discipline); item 12 added (housekeeping: stray `--help/` dir).

## Next Action
Session 24 target (per reviewer's stated direction this session): witness NEXT.md item
9 — the orphan-crash recovery path has never been positively exercised (every run to
date, including Session 22's live smoke, is happy-path only). Needs deliberate
fault-injection (kill `claude -p` mid-execution, then resume) before the reconciler's
reap/no-double-commit behavior can be trusted unsupervised.

## Knowledge Captured
- `tests/crash/harness.py` has no `argparse`/`--help` handling — `sys.argv[1]` is taken
  literally as the run root directory. Invoking it as `python tests/crash/harness.py
  --help` does NOT print usage; it creates a literal directory named `--help` and runs
  the full harness into it. Correct invocation is strictly positional:
  `python tests/crash/harness.py <root-dir> <seed> [point-filter]`.
- Python `finally` semantics were load-bearing for this fix's correctness: a `finally`
  attached to a `try` runs before `return` completes on every path out of that
  try — normal return, a caught exception's `except` branch, or `KeyboardInterrupt` —
  which is why placing the restore in `cmd_run`'s one existing try/except (as a single
  `finally`) covers all exit paths without any change to `loop.py`.

## Testing / Verification Performed
- PASS: `tests/unit/test_main_exit_paths.py` — 5/5 (raw pytest output captured this
  session: clean drain, `OrchestratorHalt`, `ReviewerError`, `KeyboardInterrupt`, and the
  restore-failure-survives-halt guard).
- PASS: full unit suite — `python -m pytest tests/unit -q` — 117 passed.
- PASS: durability harness, seed 42 — `ALL 60 SCENARIOS PASSED` (raw output captured).
- PASS: durability harness, seed 1337 — `ALL 60 SCENARIOS PASSED` (raw output captured).
- PASS: raw `git diff`/`git show --stat` witnessed multiple times per reviewer's explicit
  demand, confirming no early `return` survived inside the try/except and that each
  commit contains exactly the intended files.
- NOT TESTED: no live end-to-end `cmd_run` run against the real `StockPhotoAgent` target
  was performed this session. The exit-path tests mock `Orchestrator`/`GitCliAdapter`/
  `ClaudeHeadlessEngine` entirely — the fix's real-world effect (the workspace actually
  landing back on `agent-work` after a genuine run) has not yet been observed live.

## Outstanding Issues
- `StockPhotoAgent` (the target repo) is still checked out on `issue/5` as of this
  session's end — this session's fix was verified only via mocked unit tests and the
  durability harness, not by re-running the real `cmd_run` against that repo. The next
  live run will be the first real exercise of this fix.
- NEXT.md item 9 — orphan-crash recovery path never positively witnessed (open, likely
  next session's target — see Next Action).
- NEXT.md item 10 — `Issues.md` STATUS text drift, cosmetic, open, untouched this
  session.
- NEXT.md item 11 — event-log durability invariant, named latent dependency, open,
  untouched this session.
- NEXT.md item 12 (new, this session) — stray `--help/` directory at the repo root,
  untracked harness-fixture scratch from an accidental `--help` invocation (see Knowledge
  Captured), deliberately left in place per reviewer instruction; needs manual delete or
  a `.gitignore` line next session.
- Stale unit-test-count references: `CLAUDE.md`'s verify-commands section says "expect
  19 pass"; `NEXT.md` §7 says "expect 106"; this session's actual observed count was 117.
  Named as a cleanup item this session per explicit reviewer instruction; not corrected.

## User Constraints
- No commit without explicit reviewer gate + user authorization — followed throughout;
  two commits this session, each only after a raw-evidence gate was explicitly passed.
- Kill criteria (ADR-19) are frozen and were not touched. Standing reminder carried
  forward per this session's explicit instruction: the n=5 live smoke from Session 22 is
  NOT an ADR-19 20-issue verdict — it's a positive smoke signal consistent with the
  kill-criteria thresholds, nothing more.
- Process depth scales to blast radius (CLAUDE.md) — this change was treated as
  high-blast-radius (src/ exit-path logic) and gated with the full five-gate-style
  discipline (fix-shape proposal → implementation → test proof → durability harness →
  reviewer sign-off → commit), consistent with that rule.

## Runtime & System State
- Commit at handoff: `9b84067` (docs: NEXT.md item 8 resolution + item 12), directly on
  top of `86e2476` (fix: cmd_run branch-restore), directly on top of `bf975a0` (Session
  22 close) — all three confirmed via `git log --oneline -3` this session.
- Background processes: none left running. An earlier mis-invocation of the harness
  (`... harness.py --help`) was backgrounded automatically on a 120s timeout and was
  explicitly stopped via `TaskStop` this session once the `--help` argument-parsing
  issue was understood.
- Dev servers / ports: none.
- Open branches / worktrees: `issue-runtime` repo on `master`, clean except the
  untracked `--help/` directory (see Outstanding Issues). Target repo
  `C:\Projects\StockPhotoAgent` on branch `issue/5`, working tree clean (not yet restored
  to `agent-work` — no live run has exercised the new fix yet).
- Memory files updated: none this session.

## Deferred Work
- Stale test-count documentation cleanup (`CLAUDE.md` "expect 19", `NEXT.md` §7 "expect
  106" vs. the 117 actually observed this session) — named this session per explicit
  reviewer instruction, not actioned; carry to next session.
- `--help/` directory cleanup (manual delete or `.gitignore` line) — deliberately left
  untouched this session per reviewer instruction (containment condition on the commit
  gate); next session's call.
