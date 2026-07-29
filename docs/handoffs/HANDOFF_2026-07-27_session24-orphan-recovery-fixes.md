# Session Handoff — Item-9 fault injection surfaced and fixed two gating defects (items 13, 14)

## Objective
Gate NEXT.md §2 item 9 (orphan-crash recovery, previously UNWITNESSED) via
deliberate fault injection: kill the real `cmd_run` orchestrator mid-execution
against a disposable scratch repo, resume, and prove from event-log + git refs
that recovery reaps the orphan without repeating or double-committing work.
The first real attempt didn't reach a verdict on item 9 at all — it exposed a
standing startup deadlock (item 13) that blocked recovery from ever running on
genuine crash residue, and fixing that then exposed a second, independent
evidence-integrity defect (item 14) in how crash residue is garbage-collected.
Both were root-caused, designed, gated, and committed this session before item
9 itself could be positively witnessed.

## Current Status
- Completed: item 13 (ADR-20 Amendment 2, startup-ordering deadlock) fixed,
  gated, committed. Item 14 (ADR-15 Amendment 1, residue-ref false witness)
  fixed, gated, committed. Item 9 witnessed against a scratch repo, including
  residue durability, for the first time. Two housekeeping commits (session-23
  handoff doc added; stale test counts corrected).
- In Progress: nothing mid-flight.
- Blocked: item 9's standing caveat — "never exercised against real
  StockPhotoAgent `cmd_run`" — remains open. Not blocked on anything technical;
  blocked on a deliberate, separate authorization decision (see Next Action).

## Decisions & Rationale
- Item 13 fix: reorder `reap_orphans` + `recover()` ahead of `checkout_branch`
  in `cmd_run` — because Amendment 1's checkout-before-recovery placement
  refused (dirty-tree guard) before recovery ever got a chance to clean a
  genuine crash's residue, a standing deadlock, not a transient race. Written
  up as `ADR-20 — Amendment 2`, `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md:134`.
- Item 14 fix: replace issue-scoped `delete_attempt_refs(issue_id)` with
  execution-scoped `delete_attempt_ref(issue_id, execution_id)` — because the
  issue-scoped delete collaterally destroyed a crashed sibling execution's
  residue ref the moment a *different* execution of the same issue completed,
  leaving the residue commit dangling while the event log still asserted it
  was preserved. Old method removed entirely (its sole caller was
  `loop.py:339` per a session grep), not left dormant, to avoid a future call
  site reintroducing the same defect. Written up as `ADR-15 — Amendment 1`,
  same file, `docs/08-session-0-closure-and-adr-amendments.md:358`.
- Safety of item 14's narrower scope rests on the completing execution's ref
  being redundant *at delete time*: `loop.py`'s `_commit_sequence` is a strict
  three-step ladder (`CommitIntent` → `merge_to`/`CommitCreated` →
  `IssueCompleted`+delete), each step returning immediately after emitting its
  fact, so the delete step is only ever reached on a later invocation than the
  merge step. Witnessed, not assumed: `git merge-base --is-ancestor
  <completing execution's end_commit> agent-work` returned exit 0 against the
  actual scratch run before this was approved.
- Crashed/failed sibling executions' residue refs are retained **indefinitely**
  by design under the item-14 fix — no event in doc 03's frozen vocabulary
  marks residue as safe to discard, and ADR-15 already names crash residue as
  evidence worth preserving. If ref/object growth from accumulated crash
  residue ever becomes a real concern, a dedicated periodic reap mechanism
  (decoupled from `IssueCompleted`) is a candidate future, separate ADR — not
  built this session.
- Items 13 and 14 were committed **separately** (`5e63341`, then `9c071ed`),
  not bundled — 14 was surfaced by 13's own re-test but is an independent
  defect on a different code path (issue-completion GC vs. startup ordering);
  bundling a verified fix with a not-yet-fixed defect would have made the
  commit history misrepresent what each fix actually proves.
- All fault-injection was run against disposable scratch git repos under the
  session's Temp scratchpad directory (outside the project tree), never
  StockPhotoAgent — StockPhotoAgent is high-blast-radius and was explicitly
  not authorized this session.

## Key Files
- Plan file: `%USERPROFILE%\.claude\plans\enumerated-jumping-yeti.md` — the
  item-14 fix design (Direction A/B analysis, option comparison, ADR impact,
  pre-committed re-test spec), gated and approved before implementation.
- `C:\Projects\issue-runtime\NEXT.md` — items 9, 13, 14 all fully written up
  here with symptom/root-cause/evidence/fix detail; item 13's entry also
  carries item 9's Session-24 follow-up (the residue-with-no-event-trace
  finding that item 14 later confirmed in production).
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` —
  `ADR-20 — Amendment 2` (line 134) and `ADR-15 — Amendment 1` (line 358).
- `C:\Projects\issue-runtime\src\runtime\main.py` — the `cmd_run` startup
  reorder (item 13).
- `C:\Projects\issue-runtime\src\runtime\loop.py`,
  `C:\Projects\issue-runtime\src\runtime\repo\adapter.py`,
  `C:\Projects\issue-runtime\src\runtime\repo\git_adapter.py` — the
  execution-scoped attempt-ref GC (item 14).

## Next Action
Open the item-9 StockPhotoAgent-repeat authorization: a fresh session, held to
the same full evidence bar already proven on scratch this session (pre-kill
capture, GAP-1 live-child witness against the *real* StockPhotoAgent `claude
-p` child, the full item-9 outcome matrix including residue-ref survival) —
this is the run that would actually discharge the standing caveat. Requires
explicit user go-ahead before it starts; do not run it opportunistically.

## Knowledge Captured
- A real orphan requires killing the **orchestrator**, not the child —
  `ClaudeHeadlessEngine.run()` is synchronous (`Popen` then `communicate()`
  block in the same process), so killing only the child just returns a
  nonzero exit inside a still-live orchestrator; nothing is ever orphaned or
  reaped.
- `taskkill /PID <orch_pid> /F` **without** `/T` leaves the child alive on this
  Windows machine (no job-object binding tying their lifetimes) — this is the
  actual mechanism that produces a genuine orphan. The GAP-1 live-child
  witness (`tasklist` immediately after the parent kill, before resume) is the
  only discriminator between reaping a real orphan and reaping a child that
  already died with its parent — without it, a "reaped" claim is unwitnessed.
- Item 14 confirmed in production a risk item 9's Session-24 follow-up had
  already predicted: residue can exist on disk/in git with no reliable
  event-log or ref trace. Any future no-double-commit check that keys only on
  event or ref cardinality is insufficient by construction — the merge
  second-parent / commit-content check (comparing actual SHAs, not trusting a
  ref name) is load-bearing, not redundant.

## Assumptions
- MED confidence: `taskkill /F` without `/T` orphaning the child is a
  Windows-specific, and possibly machine-specific, behavior (no job-object
  binding on process spawn) — verified on this machine this session, not
  re-verified against a different Windows configuration.
- LOW confidence / design bet: item 14's "retain crashed residue refs
  indefinitely" is justified on the assumption that crash rate stays low in
  practice (bounded ref/object growth). Not load-bearing for correctness, but
  worth revisiting if a much higher crash rate is ever observed in real usage.

## Architecture Changes
- `cmd_run` startup order changed: `checkout_branch(cfg.project.branch)` now
  runs *after* `reap_orphans()` + `recover()`, not before. Baseline
  health-check and issue ingest are unaffected — both still run strictly after
  checkout, unchanged.
- Attempt-ref garbage collection on `IssueCompleted` changed from
  issue-scoped (deleted every execution's ref under that issue) to
  execution-scoped (deletes only the completing execution's own ref).

## Testing / Verification Performed
- PASS — item 13: durability harness 60/60 both seed 42 and seed 1337 (raw
  `ALL 60 SCENARIOS PASSED` both runs, observed this session); scratch
  fault-injection re-test reached `recover()` (no `CHECKOUT FAILED`), and the
  full item-9 outcome matrix (orphan reaped / no work repeated / no
  double-commit) passed.
- PASS — item 14: unit suite 117/117 (observed this session); durability
  harness 60/60 both seeds; inverse re-test on a fresh scratch repo —
  `refs/attempts/1/1-e1` (crashed) resolved after issue completion,
  `refs/attempts/1/1-e2` (completing) was correctly gone, `git fsck
  --unreachable` showed no dangling commits.
- NOT TESTED — item 9 against the real StockPhotoAgent `cmd_run`. Every
  witness this session (item 13's re-test, item 14's inverse re-test) ran
  against disposable scratch repos only. This is the load-bearing gap the
  standing caveat names.

## Outstanding Issues
- NEXT.md item 10 (cosmetic): `Issues.md` STATUS text is never written back
  after issues complete — confirmed by prior hand-verification (per NEXT.md,
  not re-verified this session), not touched this session.

## Risks
- NEXT.md item 11: ingest idempotency depends on `state/events.jsonl`
  surviving between runs; if that log is ever deleted, moved, or repointed
  while `Issues.md` still lists issues, ingest would re-emit them as new work
  — real duplicate executions/commits. A tracked invariant, not yet a failure.
  Not touched this session.
- Gate (a), the ADR-22 vacuity-guard positive control, remains permanently
  unproven per standing record (carried from prior sessions, not re-touched
  this session) — the mechanism has never been shown to actually detect
  contamination, only to not observe it in three independent attempts.

## User Constraints
- No commit without explicit authorization — every commit this session (four:
  `5e63341`, `9c071ed`, `ecc3c5d`, `4d52d64`) was staged and shown for review
  before being made, on the user's explicit go-ahead each time.
- Scratch fault-injection artifacts (`orphan-report*`, scratch repo copies,
  scratch configs) must live outside the project tree under the session's Temp
  scratchpad directory and stay untracked — verified via `git status` at
  multiple points this session that none leaked into the repo.
- StockPhotoAgent is high-blast-radius: no runs against it without explicit
  go-ahead. Not touched this session.

## Runtime & System State
- Commit at handoff: `4d52d64` (verified this turn via `git rev-parse --short
  HEAD`; `git status --porcelain` clean, no untracked or modified files).
- Background processes: none running at handoff — all harness runs and
  fault-injection scripts launched with `run_in_background` this session
  completed and were read out before this handoff.
- Open branches / worktrees: none beyond `master` in the main project repo.
  Scratch repos (`orphan-scratch-repo-v2`, `orphan-scratch-repo-v3`, and the
  original `orphan-scratch-repo`) exist under the Temp scratchpad, each with
  their own local `agent-work`/`issue/N` branches — disposable, outside the
  project tree, not tracked by this repo's git.
- Memory files updated: none this session.

## Deferred Work
- Item 9's StockPhotoAgent repeat (see Next Action) — deliberately deferred to
  a fresh session by explicit user choice: high-blast-radius, wants its own
  outcome-matrix gate rather than being folded into this session's scratch
  work.
- ADR-19's kill-criteria verdict remains un-reached — the only live smoke to
  date is n=5 (5/5 attempt-1, ~$0.31/issue per a prior session's live run, not
  re-verified this session), not the 20-issue sample ADR-19's verdict needs.
  Not actioned this session.

## Open Questions
**Needs User Input**
- When to schedule the item-9 StockPhotoAgent-repeat run (see Next Action) —
  timing and final go-ahead are the user's call.
