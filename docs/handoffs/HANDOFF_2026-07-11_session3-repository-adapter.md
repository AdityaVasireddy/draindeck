# Session Handoff — RepositoryAdapter, reconciler seam binding, and git-world crash harness (Session 3)

## Objective
Make the git boundary of the autonomous issue-resolution runtime real. Sessions 1-2
built the durable event log, projections, and a reconciler whose two repo-dependent
checks (unwitnessed commit, dirty workspace) were injectable seams reported SKIPPED.
This session designed (in Plan Mode, user-approved) and then implemented a
`RepositoryAdapter` over the git CLI, bound all three reconciler seams to it, and
rebuilt the kill-9 crash harness on a real temp git repository instead of filesystem
stubs — closing the gap between "durability proven against a stub" and "durability
proven against real git."

## Current Status
- Completed: `RepositoryAdapter`/`GitCliAdapter`, all three reconciler seam bindings,
  the git-world crash harness rewrite, the design doc (docs/11), NEXT.md update, and
  a checkpoint commit. Working tree is clean at commit `f2142b9`.
- Blocked: nothing. Session 4 (engine wrapper) can start immediately.

## Decisions & Rationale
- `merge_to` computes the CommitIntent→CommitCreated merge entirely in the object
  database (`git merge-tree --write-tree` → `commit-tree` → atomic `update-ref`),
  never touching the worktree — implemented in `src/runtime/repo/git_adapter.py`.
  Rationale: this collapses the merge's crash surface to exactly two post-crash
  states ("ref moved" or "ref didn't"), distinguishable by `is_ancestor`, which
  matches doc 02 §4.2's witness exactly, and guarantees a crashed merge can never
  be the cause of a dirty-workspace (check 3) finding.
- `preserve_residue` (check 1) now takes the whole `ExecutionView`, not just an
  execution id — it needs `issue_id` (for the attempt-ref name) and `base_commit`
  (to detect "nothing happened yet"). Parsing an issue id back out of an execution
  id would have been a hidden format coupling. Lives in `src/runtime/recovery/bindings.py`.
- Check 2 (unwitnessed commit) raises `ReconcilerTamperError` if `end_commit` is
  found to be an ancestor of the target branch but no merge commit's second parent
  matches it (i.e., a human fast-forwarded or squashed outside the runtime).
  Rationale: forging the `merge_commit` join key would corrupt ADR-11's
  authoritative-log invariant; a tampered world must be surfaced loudly, not guessed
  through.
- Check 3 (dirty workspace) emits no event — doc 03's frozen event vocabulary has
  none for it, and doc 02 §4.3 only prescribes ref+reset. Its evidence trail is the
  attempt ref plus a new `RecoveryReport.workspace_repairs` list, so recovery still
  never silently claims work it didn't record.
- The projection (`src/runtime/events/projections.py`) was widened with
  `base_commit`, `end_commit`, and the `CommitIntent` payload fields — derived
  entirely from existing doc 03 §3 event payloads, so this is not a schema change
  and required no ADR.
- Added a no-op `_checkpoint(name)` instrumentation seam inside `GitCliAdapter`'s
  `snapshot_commit` and `merge_to`. Rationale: a timed external process kill cannot
  reliably land *inside* a single git subprocess call, so the harness needs a hook
  between git's own internal steps (mid-merge, mid-snapshot) to exercise those
  crash windows deterministically. Production behavior is unchanged (no-op); the
  harness overrides it in a `GitCliAdapter` subclass.

## Key Files
- Plan file: `~/.claude/plans/you-are-starting-session-dapper-lemur.md` — the
  approved Session 3 design (RepositoryAdapter interface, seam-binding crash-window
  tables b1-b7/c1-c4, harness invariants, model handoff tiers). Read this first for
  the full design reasoning; docs/11 below is the as-built summary of the same work.
- `docs/11-session3-repository-adapter-design.md` — as-built record: what was
  designed vs. what changed under contact with real git (e.g., mutation M2 ended up
  caught by a unit test rather than the harness, as designed for M1).
- `src/runtime/repo/adapter.py`, `git_adapter.py` — the adapter contract and its git
  CLI implementation; every method's idempotency guarantee is documented inline.
- `src/runtime/recovery/bindings.py` — the seam-binding logic joining the adapter to
  the reconciler; this is the only module that knows both git and the event log.
- `src/runtime/recovery/reconciler.py` — signature changes: `preserve_residue` now
  takes an `ExecutionView`; new `recover_workspace` seam and `workspace_repairs`
  report field.
- `tests/crash/worker.py`, `harness.py` — rewritten to drive a real temp git repo
  (branch `trunk` for the target, `work` for in-progress issue branches) instead of
  filesystem `.done` artifacts; new invariants I-i through I-m are documented at the
  top of `harness.py`.
- `NEXT.md` — updated resume pointer; points at Session 4 (engine wrapper).

## Next Action
Session 4 per doc 07 ordering: implement the engine wrapper
(`src/runtime/engine/claude_headless.py`) as the concrete `ClaudeHeadlessEngine`
class (ADR-08) — spawn `claude -p` in the workspace, enforce `max_turns`/timeout,
and implement ADR-18 env hygiene (strip `ANTHROPIC_API_KEY` from the spawned child
process when `auth_mode=subscription`). A provisional interface sketch is in
docs/11 §4, marked explicitly not-frozen.

## Knowledge Captured
- The Windows console's default code page (cp1252) cannot encode the `→`/`—`
  characters the crash harness printed in diagnostic messages; this crashed the
  harness with a `UnicodeEncodeError` that would have masked the real failure text
  if it had fired inside an assertion path. Fixed by forcing `sys.stdout`/`stderr`
  to UTF-8 via `reconfigure()` at the top of `harness.py`. This is a genuine
  cross-platform gap the stub-era harness never hit (it printed no such characters
  until this session's diagnostic strings), not a preexisting bug that had gone
  unnoticed — confirmed by reproducing the crash on the pre-Session-3 harness
  before any git-world changes were made.
- `git reset --hard` does not remove untracked files; `GitCliAdapter.reset_hard`
  therefore always pairs it with `git clean -fd` (verified via the M2 mutation:
  removing `clean -fd` made `test_reset_hard_removes_untracked` fail immediately).
- A killed `git add`/`commit` can leave a stale `.git/index.lock` that blocks every
  subsequent git mutation; `recover_workspace()` clears it defensively before any
  other recovery step runs, gated on the precondition that v1 is single-writer
  (ADR-04) so no legitimate process can be holding it concurrently.

## Assumptions
- Power-loss (not process-crash) durability of git's own ref/object writes is
  `core.fsync`-config-dependent and out of scope for this harness — the same
  caveat the Session 2 handoff already recorded for the event log's fsync calls
  (kill-9 proves process-crash durability, not power-loss durability). HIGH
  confidence this is the correct scope boundary, since it mirrors an already-
  accepted precedent rather than introducing a new one.
- Git ≥ 2.38 is required for `merge-tree --write-tree`; `GitCliAdapter` checks this
  at construction and raises a pointed error below that version. Verified present
  on this machine (git 2.53.0) this session; not verified on any other environment.
- `delete_attempt_refs` (ADR-15 garbage collection) is implemented on the adapter
  but deliberately not called from anywhere yet — GC is orchestrator policy
  (post-`IssueCompleted`), which doesn't exist until Session 4+. MED confidence this
  is the right sequencing rather than a gap, since the orchestrator loop is the
  only thing that knows when an issue is truly done with its evidence.

## Testing / Verification Performed
- PASS: unit suite. Verified twice this session — once mid-session after all
  implementation was complete (58/58), and again just now during wrap-up as a
  fresh re-check (`.venv/Scripts/python.exe -m pytest tests/unit -q` → `58 passed`
  in 9.41s, observed directly this turn).
- PASS: full crash harness on seed 42 and seed 1337 — 50/50 scenarios each,
  observed directly in tool output earlier this session (16 deterministic crash
  points × 2 occurrences, 15 random-timing rounds each landing ≥1 kill, 2 planted
  fixtures, 1 control run). Each run took several minutes given real git
  subprocesses per scenario; not re-run in full during wrap-up. Instead, re-verified
  the harness is still functional just now with a single-crash-point smoke check
  (`... %TEMP%\hoff_check 42 "engine:post-edit"` → `PASS det[engine:post-edit:1]`,
  `PASS det[engine:post-edit:2]`, `ALL 2 SCENARIOS PASSED`, observed this turn).
- PASS: mutation M1 (made `preserve_residue` unconditionally return `None`) —
  confirmed the harness fails on invariant I-m with the message "killed at
  engine:post-edit ... but no ExecutionCrashed carried a residue_ref", observed in
  tool output earlier this session, then reverted.
- PASS: mutation M2 (removed `clean -fd` from `reset_hard`) — confirmed
  `test_reset_hard_removes_untracked` fails with `assert True is False` (dirty
  workspace after reset), observed in tool output earlier this session, then
  reverted.
- Verified this wrap-up turn only, via `grep -rn "MUTATION" src/ tests/`: no
  mutation-marker text remains in the tree (grep found zero matches) — confirming
  both mutations were fully reverted before the checkpoint commit.
- NOT TESTED: the real `claude -p` engine, reviewer, budget manager, queue,
  context pack, and orchestrator loop (all out of scope through Session 3, per the
  existing project scope). Power-loss durability (see Assumptions). Any platform
  other than this Windows machine with git 2.53.0.

## Technical Debt
- `delete_attempt_refs` is implemented and unit-tested but has no caller anywhere
  in the codebase yet (intentional — see Assumptions; will be wired when the
  orchestrator's issue-completion step exists in a later session).

## User Constraints
- Architecture is FROZEN; doc 03 (state machine & event schema) wins any conflict
  with other docs or with the implementation; changes require an ADR, not ad hoc
  edits. (No architecture changes were made this session — only the previously
  -SKIPPED reconciler seams were bound, which was explicitly in-scope per NEXT.md.)
- Honesty discipline: every session summary must separate what was verified (ran
  it, saw it pass) from what is assumed; never report a test as passing without
  running it. Applied throughout this handoff.
- Target repo path, branch, and test commands are CONFIG ONLY — nothing under
  `src/` may hardcode them. The new adapter code takes `repo_path` and
  `ref_namespace` at construction and every branch name as a method argument;
  verified by inspection of `git_adapter.py` and `bindings.py` (no path/branch
  literals found).
- ANTHROPIC_API_KEY must stay unset in this development environment (both for the
  target runtime's subscription billing and for Claude Code sessions themselves).
  Not touched this session; no engine wrapper exists yet to enforce it.

## Runtime & System State
- Commit at handoff: `f2142b9` (working tree clean, confirmed via `git status
  --short` this turn — no output, i.e. nothing pending).
- Diff from the prior Session 2 checkpoint (`8523ad9`) to this commit, confirmed
  via `git diff --stat 8523ad9 f2142b9` this turn: 14 files changed, 1683
  insertions, 219 deletions — new files `src/runtime/repo/{__init__,adapter,
  git_adapter}.py`, `src/runtime/recovery/bindings.py`,
  `tests/unit/{test_git_adapter,test_bindings}.py`,
  `docs/11-session3-repository-adapter-design.md`; modified
  `events/projections.py`, `recovery/reconciler.py`, `tests/crash/{worker,
  harness}.py`, `tests/unit/test_foundation.py`, `NEXT.md`. The `.gitattributes`
  addition visible in this diff range is from the intermediate `40a33d8 Normalize
  line endings to LF` commit (between Session 2 and this one), not from this
  session's work — confirmed via `git diff 8523ad9 f2142b9 -- .gitattributes`.
- No background processes, dev servers, or open worktrees.
- No memory files were written or updated this session.

## Open Questions
**Needs User Input**
- ~~StockAgent vs. StockPhotoAgent directory-name mismatch~~ — resolved:
  name/path are separate fields by design, no mismatch existed.
- ~~project.validation.commands placeholder~~ — resolved in commit `efad497`
  (config.yaml created with real values, package properly installed).
  Both closed before Session 4 began.