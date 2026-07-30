# Session Handoff — item-9 crash harness: authored, scratch-verified, committed (real StockPhotoAgent run still gated)

## Objective
Convert `docs/15-item9-outcome-matrix.md`'s (commit `ab2e798`) five pre-committed
outcome rows (A-E, orphan-crash recovery) from INFERRED to VERIFIED by actually
building and running the fault-injection code the matrix promised — against a
**scratch** git repo only. The real fault-injection run against
`C:\Projects\StockPhotoAgent` was deliberately NOT authorized this session and stays
gated behind a separate go-ahead plus fresh precondition re-verification (the last
clearance is a dated snapshot, not re-checked this session).

## Current Status
- Completed: harness authored at `tests/crash/item9_orphan_harness.py`, all five
  rows self-tested PASS on scratch (Row A and the `/T` discriminator live, with real
  `claude -p`; Rows B/C/E as fixtures, real git, no real `claude`), committed at
  `b23d8bc` (verified this session: `git rev-parse --short HEAD` = `b23d8bc`,
  `git show --stat HEAD` shows exactly one file, `tests/crash/item9_orphan_harness.py`,
  834 insertions, no collateral). `git status --porcelain` is clean.
- In Progress: nothing mid-flight.
- Blocked: the real item-9 fault-injection run against StockPhotoAgent — blocked on
  (a) Adi's explicit go-ahead and (b) a fresh mechanical re-verification of the five
  item-9 preconditions (see Next Action) — none of that re-verification was done this
  session.

## Decisions & Rationale
- Kill method fixed to parent-only `taskkill /PID <pid> /F`, no `/T`, on every
  crash-row call site — because `loop.py:212`'s `engine.run()` is synchronous inside
  the orchestrator process; killing only the orchestrator leaves the real `claude -p`
  child running as a genuine orphan, which is exactly the state item 9 needs to
  witness. A `/T` kill collapses that to a self-dead child and would make Row D
  unwitnessable. Lives in `tests/crash/item9_orphan_harness.py`'s `taskkill()` helper
  and every call site except one.
- Exactly one isolated `/T` kill, in a dedicated `run_t_discriminator_live` function,
  to prove the negative branch of the harness's own live/self-dead discriminator
  before trusting it on a real run — labeled in-source as the sole permitted `/T`.
- Row A and Row D are reported as two independent axes, never collapsed into one
  verdict — this was a **mid-session reviewer correction**, not an original design
  choice: my first plan conflated them (treated Row A's live run as automatically
  covering Row D), and the reviewer rejected that `ExitPlanMode` attempt because a
  child that self-exits before the kill still lets Row A pass (recovery still emits
  `ExecutionCrashed`) while proving nothing about live reaping. Axis 2 (the
  live-orphan witness) is three-valued (PASS / INCONCLUSIVE / FAIL) and is never
  silently scored as a pass — an inconclusive attempt triggers a bounded retry (up to
  3 fresh scratch attempts) rather than being papered over.
- The alive-at-kill gate checks `tasklist_pid(child_pid)` showing PRESENT immediately
  before firing the kill, not just a dirty tree — a second, related mid-session
  correction: a dirty tree proves residue exists but not that the child is still
  running; the two were originally conflated in the first plan draft.
- Fixtures for Rows B, C, E use real git (`GitCliAdapter` on a scratch repo) and
  direct calls into the real production `recover()` / `bind_reconciler()` /
  `Orchestrator._commit_sequence()` / `.step()` — deliberately with NO real `claude`
  call, because none of those three rows' claims depend on live process timing; they
  are pure code paths (GC ref-scoping for B, check-2 backfill logic for C, scheduling
  + base-commit chaining for E), so a live crash-timing dry run would be strictly more
  expensive for zero additional evidence.
- `NEXT.md` item 14 corrected to RESOLVED this session, in an earlier turn than the
  harness work (commit `9d4fc32`) — its "Fix: NOT designed or implemented" line was
  stale; the fix had actually landed earlier at commit `9c071ed` (execution-scoped
  `delete_attempt_ref`) but the doc was never updated to say so. Corrected via the
  append-only pattern (struck, not deleted, with a dated correction note), not a
  silent rewrite.

## Key Files
- Plan file: `~/.claude/plans/shimmying-orbiting-scone.md` — the approved design for
  this harness, including the two reviewer-mandated fixes above (Row A/D axis
  separation, alive-at-kill gate). Read this before touching the harness again; it
  has the full per-row witness-sequence design that the code follows.
- `C:\Projects\issue-runtime\tests\crash\item9_orphan_harness.py` — the harness
  itself. `run_row_a_live` / `run_t_discriminator_live` for the two live rows;
  `fixture_row_b` / `fixture_row_c` / `fixture_row_e` for the three fixture rows;
  shared plumbing (`init_scratch_repo`, `spawn_cmd_run`, `poll_event_log`, `taskkill`,
  `tasklist_pid`, etc.) at module top.
- `C:\Projects\issue-runtime\docs\15-item9-outcome-matrix.md` (commit `ab2e798`,
  confirmed 425 lines via `wc -l` earlier this session) — the pre-committed
  predictions this harness exists to verify. Two premise corrections already recorded
  in its own §0 (item-14 status, and Row D's real discriminator location) — read
  those before re-deriving them.
- `C:\Projects\issue-runtime\NEXT.md` — item 14's corrected note (append-only,
  commit `9d4fc32`), and §3's item-9 precondition list (the five preconditions the
  Next Action below re-verifies; not re-read in full this session, so treat its
  current wording as a starting point, not a settled reference).

## Next Action
Mechanically re-verify the five item-9 preconditions and bring back raw results (not
prose) for the go/no-go decision on the first real StockPhotoAgent run: (1)
StockPhotoAgent branch/HEAD/clean state, (2) Ollama serving the configured reviewer
model, (3) `Issues.md` on `agent-work` still lists issues 7/8/9 witnessed-unfixed,
(4) the configured validation command still returns a clean, non-vacuous result (not
just exit 0), (5) the event log / ingest id-keyed dedup guard is still intact (no
collision risk from reused issue ids). Nothing destructive runs until Adi gives
explicit go-ahead on top of that re-verification.

## Knowledge Captured
- The event log alone cannot distinguish "reap_orphans killed a genuinely live
  orphan" from "the child had already self-exited" — both paths still emit
  `ExecutionCrashed` (check 1 doesn't care why `is_execution_alive` came back false).
  The only discriminators are a `tasklist` snapshot taken BEFORE the kill (must show
  the child PRESENT) and the `"[startup] reaped orphan engine ..."` stdout line on
  resume — and both must be captured pre-resume, since resume's own reap step
  destroys the evidence either way. Verified live this session on both branches (Row
  A: present pre/post-kill, reaped line present; `/T` run: present pre-kill, absent
  post-kill, no reaped line).
- A dirty tree does not imply a live child — a child can finish editing and exit
  while the tree stays dirty. The harness's alive-at-kill gate re-checks `tasklist`
  immediately before the kill, separately from the dirty-tree poll, for this reason.
- Fixture commit SHAs can come out byte-identical across two independently-built
  scratch repos in the same harness run (observed in `fixture_row_c`'s two
  sub-cases). Confirmed via source read this session: `git_adapter.py`'s `_git()`
  sets no `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`/`SOURCE_DATE_EPOCH` — with identical
  tree content, identical fixed identity (`-c user.name=t -c user.email=t@t`), and
  identical commit messages, two commits landing in the same wall-clock second
  (very plausible for fast, network-free, back-to-back local git ops) hash
  identically. Not a code bug; each sub-case builds its own repo/log/adapter with no
  shared state.
- A scratch repo's own `.gitignore` can silently swallow a fault-injection harness's
  own residue markers if the glob overlaps (hit this in `fixture_row_b`: a `*.tmp`
  marker file collided with the repo's own `*.tmp` gitignore entry, making
  `preserve_residue` correctly — but unhelpfully — conclude "nothing happened").
  Fixed by naming residue markers outside the ignored globs.

## Assumptions
- MED confidence: the five item-9 preconditions (Next Action) still hold as they did
  when last cleared in an earlier session — not re-checked this session, and they are
  known to drift (branch state, Ollama model availability, Issues.md contents have
  all changed at least once across prior sessions this project).
- LOW confidence: a real StockPhotoAgent run will reproduce the same clean,
  single-attempt witness sequence the scratch runs showed (both live rows passed on
  their first attempt, no retries needed) — scratch is a much simpler repo/workload
  than StockPhotoAgent, and the harness's bounded-retry logic exists specifically
  because INCONCLUSIVE attempts are expected to be possible, just not observed this
  session.

## Testing / Verification Performed
- PASS — Row A live: real `claude -p` scratch dry-run, 1 attempt, no retries. Child
  pid present in `tasklist` both before and after the parent-only kill; resume stdout
  contained `"[startup] reaped orphan engine 1-e1 (pid ...)"`; `ExecutionCrashed`
  emitted with a `residue_ref` that resolved via `git rev-parse` to a real commit
  (`git log -1 --format=%s` = `"crash residue 1-e1"`).
- PASS — `/T` discriminator live: 1 attempt, no retries. Child pid present in
  `tasklist` immediately before the `/T` kill (proves the subsequent absence is the
  kill's doing), absent after; resume stdout had no reaped-orphan line but still
  showed `"[recovery] crashed orphans: ['1-e1']"`; `ExecutionCrashed` still emitted.
- PASS — `fixture_row_b`: real git, `refs/attempts/1/1-e1` (crashed sibling's residue)
  survived a later `IssueCompleted` GC while `refs/attempts/1/1-e2` (the completing
  execution) was correctly GC'd; `git fsck --unreachable` showed the residue commit
  not dangling.
- PASS — `fixture_row_c`: both sub-cases (merge pre-landed / not-landed) produced
  exactly one `CommitCreated` each, with `backfilled` `true`/`false` matching setup.
- PASS — `fixture_row_e`: sequential-scheduling claim held (issue 9's first
  post-activation event strictly after issue 8's terminal event); `git merge-base
  --is-ancestor` confirmed issue 8's merge is an ancestor of issue 9's base commit;
  `git show` confirmed issue 9's base has `bug_a` fixed and `bug_b` still unfixed.
- NOT TESTED — anything against real StockPhotoAgent. Every scenario this session ran
  under `%TEMP%\item9-harness*`; StockPhotoAgent was touched by zero commands.
- NOT RE-RUN — the unit suite (117/117) and durability harness (60/60, both seeds).
  Not required this session: `git diff --stat -- src/` was confirmed empty both at
  harness-authoring time and at commit time, so nothing durability-gated changed.
  The 117/117 and 60/60 figures associated with commit `9c071ed` (the item-14 fix)
  are that commit's own self-report, not independently reproduced by me at any point
  this session.

## Technical Debt
- `fixture_row_e`'s `_FakeEngineRowE` / `_FakeValidatorRowE` / `_FakeReviewerRowE`
  duplicate the shape of `tests/unit/test_loop.py`'s `FakeEngine`/`FakeValidator`/
  `FakeReviewer` rather than importing them — intentional (test_loop.py is a test
  module, not a library, and `_FakeEngineRowE` needed an extra real-file-edit side
  effect the original doesn't have), stated in-source as a comment at the class
  definition.
- The live rows' bounded retry (3 attempts) has never actually had to retry (both
  passed on attempt 1) — the INCONCLUSIVE-retry path is authored and reasoned about
  but not exercised by any run this session. Intentional acceptance, not an oversight:
  forcing an INCONCLUSIVE on a real scratch run isn't something the harness tries to
  engineer.

## User Constraints
- No StockPhotoAgent write or run of any kind without Adi's explicit, separate
  go-ahead — held for every scenario this session (all scratch-only).
- No commit without explicit authorization — the harness commit (`b23d8bc`) was
  explicitly authorized turn-by-turn, as was the earlier matrix commit (`ab2e798`)
  and the `NEXT.md` correction (`9d4fc32`).
- No `src/` edits during this authoring/self-test work — would reopen the
  60/60-both-seeds durability gate; confirmed not needed (`git diff --stat -- src/`
  empty at every checkpoint).
- Subscription billing only: `ANTHROPIC_API_KEY` explicitly popped from every spawned
  `cmd_run` child's environment in `spawn_cmd_run()`.
- Kill method fixed: `tree=False` on every crash-row `taskkill` call site; the sole
  `tree=True` isolated to the discriminator function and labeled in-source.

## Runtime & System State
- Commit at handoff: `b23d8bc` (issue-runtime). StockPhotoAgent unchanged, re-verified
  this session: `45e545acb3ef15c9970b1668731ca710e3a50381`, branch `agent-work`,
  `git status --porcelain` empty (clean).
- Background processes: none left running. Two were started this session with
  `run_in_background` (shell IDs `bjri30vud` for Row A live, `br0cfpanu` for the `/T`
  discriminator live) — both completed normally within the session and their output
  was read; nothing to kill.
- Dev servers / ports: none started or stopped this session. The Ollama reviewer
  endpoint (`http://localhost:11434`) was used read-only by the live scratch runs
  (real HTTP calls as part of `cmd_run`'s own health check), not modified.
- Open branches / worktrees: none opened in either repo this session beyond the
  scratch repos under `%TEMP%\item9-harness*` (transient, git-repo-per-scenario,
  safe to delete — not part of either tracked repo).
- Memory files updated: none this session.

## Deferred Work
- The real item-9 fault-injection run against StockPhotoAgent — deferred pending
  Adi's go-ahead and the precondition re-verification in Next Action.
- ADR-19's kill-criteria verdict — out of scope regardless of item 9's outcome; that
  needs a 20-issue sample (`experiment.sample_size` in `config.yaml`) and the
  project's only real-issue run to date was n=5 (Session 22's live smoke).

## Open Questions
**Needs User Input**
- Go/no-go on the first real item-9 fault-injection run against StockPhotoAgent, once
  the five preconditions are re-verified and brought back — this is Adi's call, not
  something to infer from the scratch results being clean.

**Model Uncertainty**
- Whether all five item-9 preconditions still hold: unverified this session, and they
  are known to drift session-to-session (see Assumptions).
