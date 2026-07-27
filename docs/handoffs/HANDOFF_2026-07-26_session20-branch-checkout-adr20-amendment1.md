# Session Handoff — Ingest branch-check gap resolved (Option A), ADR-20 Amendment 1

## Objective
NEXT.md §5 carried an open parked decision: nothing in the runtime enforced that
`cfg.project.branch` was actually checked out before `_ingest_issues` read `Issues.md` —
correctness depended on ambient `HEAD` happening to match config. Two options were on the
table (A: explicit checkout; B: accept as scoped risk). This session designed, reviewed,
implemented, and committed Option A under a pre-committed evidence/design gate (raw
grep/read evidence required for every claim before implementation was authorized), then
closed the tracking items in NEXT.md and fixed an unrelated stale figure in CLAUDE.md
surfaced along the way.

## Current Status
- Completed: Option A implemented, harness re-verified on both seeds, all doc/tracking
  updates made, committed at `c6f2512` on `master`, tree clean, not pushed.
- In Progress: none — this checkpoint is closed.
- Blocked: live smoke remains NOT authorized (pre-existing gate, unchanged by this
  session) — see Next Action.

## Decisions & Rationale
- **Option A over Option B** — Option B (rely on Step 3 preflight Item 0) was already
  verified in a prior session as not covering this case in its scratch-workspace form;
  Option A closes the gap directly rather than deferring to a check that doesn't reach it.
- **Insertion point: step 5b, BEFORE orphan reap/recovery/baseline — not immediately
  before ingest.** The naive read of the gap ("add checkout before `_ingest_issues`") was
  identified as under-scoped during design: `recover()`'s `bind_reconciler(adapter,
  cfg.project.branch)` binds recovery's seams to the configured branch, and the baseline
  health check's `Validator.validate` runs commands against the physical working tree at
  `cfg.project.repository`. Both would be meaningless — recovery reconciling the wrong
  branch's state, baseline-green asserting nothing about the configured branch — if
  enforcement happened only at the ingest call site, after both already ran against
  whatever was on disk. Lives in `C:\Projects\issue-runtime\src\runtime\main.py`
  (`cmd_run`, new step "5b" between adapter construction and orphan reap).
- **Reuse existing `checkout_branch(branch, *, create_from=None)`, no new adapter method.**
  The task's initial premise ("`checkout_branch` does not exist") was checked and found
  false — it already exists on `GitCliAdapter` (`src/runtime/repo/git_adapter.py:165-174`,
  abstract at `src/runtime/repo/adapter.py:100`) and is already used once in production for
  per-issue branches (`src/runtime/loop.py:204`). Called with no `create_from`, since that
  parameter force-creates/resets a branch at a pinned commit — correct for disposable
  per-issue branches, wrong for the target repo's long-lived branch, which must only be
  switched to, never force-reset.
- **One `except RepoError` arm covers both dirty-tree and missing-local-branch cases.**
  Verified by reading `_git` (`src/runtime/repo/git_adapter.py:52-75`): its default
  `check=True` re-raises any nonzero git exit as `RepoError`, same exception class the
  existing dirty-tree check already raises — so a single new `except RepoError` arm in
  `cmd_run`, matching the existing `except ConfigError`/`except EngineError` pattern,
  handles both failure modes fail-loud (print to stderr, `return 1`).
- **Detached HEAD and already-on-branch are not special-cased.** Plain `git checkout
  <branch>` corrects a detached HEAD identically to switching from another named branch,
  and is an idempotent no-op (exit 0) when already on the target branch — the same
  `[startup] checked out {branch}` log line fires truthfully either way, so nothing is
  silently skipped.
- **Gated by ADR-20 Amendment 1**, not a new ADR — this closes a gap in enforcing ADR-20's
  existing decision (which already names the working branch as part of what it froze), not
  a new architectural mechanism. Amendment text appended to
  `docs/08-session-0-closure-and-adr-amendments.md` after ADR-20's Rationale, following the
  existing ADR-21-Amendment-1 precedent's format in the same file.
- **CLAUDE.md's harness verify-command comment was stale** (said "expect 46 pass," no seed
  mentioned) relative to `docs/14-session6-phase2-gate.md`'s recorded current state (60
  scenarios, both seed 42 and seed 1337) — corrected as a scoped one-line fix, not part of
  the Option A design itself, with a "(see docs/14 for current harness state)" pointer
  added so the figure can't silently drift again unnoticed.

## Key Files
- `C:\Users\adity\.claude\plans\gentle-waddling-swing.md` — the design document produced
  under plan mode before implementation was authorized; contains the full evidence-backed
  design (insertion point, adapter reuse, failure modes, blast radius, harness/ADR gating)
  that this session's implementation followed exactly.
- `C:\Projects\issue-runtime\src\runtime\main.py` — new step 5b in `cmd_run` (added
  `from .repo.adapter import RepoError` import; ~13 lines added between adapter
  construction and orphan reap).
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` — ADR-20
  Amendment 1, the full rationale/gate for this change (~45 lines added after ADR-20's
  Rationale paragraph, before the ADR-21 section).
- `C:\Projects\issue-runtime\NEXT.md` — §2 item 2 marked CLOSED (struck through, matching
  the existing item-3 precedent style); §5's "Ingest branch-check gap" entry rewritten to
  a RESOLVED note that preserves the original problem statement and adds a dated
  Resolution paragraph. §2 item 1 (live-smoke sequencing) was explicitly left untouched —
  confirmed unchanged by diff during the session.
- `C:\Projects\issue-runtime\CLAUDE.md` — verify-command harness figure corrected
  (46 → 60, both seeds noted, docs/14 pointer added).

## Next Action
NEXT.md §2 item 1 is the single remaining open decision: how to sequence live-smoke design
against the 3 carried-forward-unwitnessed surfaces (witness one first vs. carry all three
labeled into live-smoke design) — a decision only, no precondition blocking it. Live smoke
itself remains NOT authorized regardless of that decision.

## Testing / Verification Performed
- PASS: `tests/crash/harness.py` re-run in full after the `main.py` change, seed 42 —
  `ALL 60 SCENARIOS PASSED`, no non-PASS line, output captured raw this session.
- PASS: same harness, seed 1337 — `ALL 60 SCENARIOS PASSED`, no non-PASS line, output
  captured raw this session.
- PASS: `git diff` reviewed raw (not summarized) for all four touched files
  (`src/runtime/main.py`, `docs/08-session-0-closure-and-adr-amendments.md`, `NEXT.md`,
  `CLAUDE.md`) before staging; `git diff --cached --stat` + `git status --porcelain=v1`
  confirmed exactly those four staged, nothing else, before commit.
- PASS: `python -c "import ast; ast.parse(...)"` syntax check on the edited `main.py`.
- NOT TESTED: `cmd_run` was not actually executed end-to-end this session — the harness
  exercises the crash/recovery machinery, not `cmd_run`'s own startup sequencing or the
  new step 5b in a live process. See Carried-forward / Unwitnessed below.
- NOT TESTED: `python -m pytest tests\unit -q` (the unit suite) was not re-run this
  session — only the durability harness was rerun, per the task's explicit gate.

## Outstanding Issues
None newly introduced this session.

## Carried-forward / Unwitnessed
- **Step 5b itself is UNWITNESSED as running code.** This session verified: (1) it was
  added correctly (diff reviewed raw), (2) it does not regress the durability harness
  (60/60 both seeds). It was NOT verified to actually run correctly against a real
  checked-out-branch mismatch, a real missing-branch case, or a real dirty tree in a live
  `cmd_run` invocation — the harness does not exercise `cmd_run`'s startup path at all.
  This is witnessed only when live smoke runs `cmd_run` against StockPhotoAgent.
- **Three pre-existing carried-forward-unwitnessed surfaces, unchanged by this session**
  (per `docs/14-session6-phase2-gate.md` § "Carried-forward note (Session 16-17,
  2026-07-26)", L1129 as of last session's pointer check): (1) `main.py`'s end-to-end
  startup composition under the real CLI entrypoint (Dry-run A bypassed it by constructing
  `Orchestrator` directly); (2) the orphan-crash recovery path (an accidental crash was not
  resumed through, so it's not evidence); (3) real-tree behavior itself (every prior run
  used a scratch workspace or clone, never StockPhotoAgent's actual tree). Step 5b now
  makes surface (1) slightly larger in scope (one more startup step unwitnessed against
  the real entrypoint) but does not change the fundamental gate status.

## User Constraints
- No commit or push without explicit per-commit authorization (repeated and honored
  throughout this session — design, implementation, and doc-fix phases were each gated
  separately before the final commit authorization).
- Kill criteria (ADR-19) frozen, not touched this session.
- Architecture frozen; changes go through ADR — honored via ADR-20 Amendment 1 rather than
  an ad hoc `main.py` change.

## Runtime & System State
- Commit at handoff: `c6f2512` (short SHA, confirmed via `git rev-parse --short HEAD` this
  session), on `master`, working tree clean (`git status --porcelain=v1` empty), not
  pushed.
- No background processes started this session.
- No dev servers/ports involved.
- No memory files updated this session.

## Open Questions
**Needs User Input**
- §2 item 1's sequencing decision (witness one surface first vs. carry all three labeled)
  — pre-existing open item, not raised or resolved this session; still needs the user's
  call before live-smoke design can proceed.
