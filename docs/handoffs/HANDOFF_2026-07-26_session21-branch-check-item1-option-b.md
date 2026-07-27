# Session Handoff — NEXT.md §2 item 1 resolved: Option B (carry all three surfaces labeled) ratified

## Objective
NEXT.md §2 item 1 was the last open decision from the Session-20 handoff: how to sequence
live-smoke design against the 3 carried-forward-unwitnessed surfaces (main.py startup
composition, orphan-crash recovery through `cmd_run`, real-tree behavior) — witness one/some
first (Option A) vs. carry all three labeled into live-smoke design (Option B). This session
gathered the feasibility fact the decision turned on, built a pre-committed outcome matrix
on that fact, had the reviewer recommend Option B, and got it ratified by Adi. The session
then executed the decision-record edits: the NEXT.md §2 item 1 resolution note, this
handoff, and an historian capture — no witnessing, no `src/` change, nothing committed.

## Current Status
- Completed: feasibility investigation, pre-committed matrix, Option B ratified, NEXT.md §2
  item 1 edited to record the resolution (uncommitted), historian case captured under a
  correctly-labeled Session 21 header.
- In Progress: none — this decision-record step is closed.
- Blocked: live-smoke design itself has not started — it is the next action and re-enters
  the full review apparatus fresh (high-blast-radius, per CLAUDE.md's tiering rule). Live
  smoke remains NOT authorized; Step-3 §3 preconditions remain unsatisfied (unchanged by
  this session).

## Decisions & Rationale
- **Option B (carry all three surfaces labeled into live-smoke design), with an
  A-deferred escape hatch** — ratified by Adi over Option A (witness surfaces 1 & 2 via a
  standalone probe before live-smoke design) and over an immediate A-deferred. Recorded in
  `C:\Projects\issue-runtime\NEXT.md` §2 item 1 (struck through, RESOLVED/Option B note,
  matching the existing item-2/item-3 strikethrough convention).
- **Why B, not A**: the pre-committed matrix's own branch condition fired for B. Reading
  the raw `cmd_run` body (`src/runtime/main.py:151-264`, read this session) showed it
  hard-requires `claude` on PATH (step 4: `ClaudeHeadlessEngine` init fails fast otherwise),
  a reachable reviewer/Ollama endpoint (step 8: refuses to start if unreachable), and
  baseline-green-or-`--skip-baseline` — i.e. most of the live-smoke precondition stack
  already. Reading `tests/crash/harness.py`'s `run_worker`/`verify` (lines 158-205) plus a
  `grep` for `-m runtime` across the file (zero matches) confirmed `run_worker` drives a
  separate `WORKER` script via `subprocess.Popen`, never the real `cmd_run` entrypoint — no
  existing harness scaffolding can plant a crash AND drive `cmd_run` at the same time. A
  standalone witness probe for surfaces 1 & 2 would therefore need new harness code plus the
  same live-service stack live smoke itself needs, making it strictly more costly than just
  running live smoke for those two surfaces — the matrix's pre-committed condition for
  choosing B ("witnessing 1 & 2 standalone would require new production/harness code or a
  new production seam") fired as written, before any probe was designed.
- **A-deferred escape hatch retained, not dropped**: a dedicated scratch probe can still be
  reopened later as its own separately-gated item, but only if live-smoke design itself
  surfaces a specific real-tree risk that warrants pre-witnessing ahead of authorization —
  it is not scheduled or assumed now.
- **Surface 3 (real-tree behavior) is untouched by this decision** — it was already
  established as irreducible (per `docs/14-session6-phase2-gate.md`, the carried-forward
  note's item 3: every prior run used a scratch workspace, never a real target tree) and
  stays carried labeled regardless of A or B.
- **NEXT.md §1 and the three-surface tracking language were left factually unchanged.**
  This was a sequencing decision, not a witnessing event — all three surfaces remain
  UNWITNESSED / carried-forward exactly as previously worded; only §2 item 1's own entry was
  edited.
- **No VERIFIED/INFERRED evidence tags added to the §2 item 1 note** — NEXT.md's own rule
  (stated in its header) exempts only §3 from the zero-evidence-label policy; the resolution
  note states the fact and evidence basis in prose and points to this session's record for
  the full reasoning, rather than tagging it.

## Key Files
- `C:\Projects\issue-runtime\NEXT.md` — §2 item 1 edited (struck through + RESOLVED/Option-B
  note with evidence basis); §1 and items 2-3 confirmed unchanged by this session's own diff
  review. Edit is in the working tree only, not staged, not committed.
- `C:\Projects\issue-runtime\src\runtime\main.py` (lines 151-264, `cmd_run`) — read this
  session (not modified) to establish the live-service precondition stack (`claude` on PATH,
  reviewer/Ollama reachability, baseline-green) that a standalone probe would also need.
- `C:\Projects\issue-runtime\tests\crash\harness.py` (lines 158-205, `run_worker`/`verify`,
  plus a full-file `grep` for `-m runtime`) — read this session (not modified) to establish
  that no existing harness scaffolding drives the real `cmd_run` entrypoint.
- `C:\Projects\issue-runtime\docs\14-session6-phase2-gate.md` (the Session 16-17
  carried-forward note, around L1129-1147, per the prior session's pointer) — source of the
  three-surface definitions and surface 3's irreducibility; not re-verified line-by-line
  this session, relied on the prior session's confirmed pointer.
- `C:\Projects\issue-runtime\knowledge\issue-runtime\2026-07-26.md` — historian day file;
  this session's cases captured under a "## Session 21" header (gitignored, not committed
  regardless).

## Next Action
Live-smoke design is the next real work item (per NEXT.md §1/§2 as they now read) — it is
high-blast-radius (real repository mutation, runtime behavior against a live target) per
CLAUDE.md's process-depth-scales-to-blast-radius rule, so it must re-enter the full
apparatus (pre-committed outcome matrices, evidence-backed design review) fresh rather than
inherit this session's lighter decision-record process. Live smoke itself remains NOT
authorized regardless of design progress, and Step-3 §3's preconditions remain unsatisfied.

## Testing / Verification Performed
- PASS: `git status --porcelain=v1` — confirmed only `NEXT.md` modified, working tree
  otherwise clean, before and after the edit.
- PASS: `git diff --stat` — confirmed exactly one file (`NEXT.md`), +14/-5 lines, matching
  the intended single-item edit.
- NOT TESTED / NOT APPLICABLE: no `src/` change occurred this session, so the durability
  harness (`tests/crash/harness.py`) was correctly not re-run; the unit suite was not re-run
  for the same reason.

## User Constraints
- No commit or push without explicit per-commit authorization — the `NEXT.md` edit and this
  handoff file are both left uncommitted, staged nowhere, pending a separate authorization
  the user explicitly withheld for this step.
- Live smoke remains NOT authorized — unchanged, not addressed or challenged this session.
- Architecture frozen; this session recorded a sequencing/process decision, not an
  architectural or `src/` change, so no ADR was needed or written.

## Runtime & System State
- Commit at handoff: `98fa063` (short SHA, unchanged from session start — no commit made
  this session).
- Working tree: `NEXT.md` modified (uncommitted); no other files changed by this session's
  edits.
- No background processes started this session.
- No dev servers/ports involved.
- Memory files updated: none (historian vault `knowledge/` was updated per its own separate
  mechanism, not the project's `~/.claude` memory system).

## Open Questions
**Needs User Input**
- None new — live-smoke design's own sequencing/approach is the next substantive question,
  but it was not raised or scoped this session beyond "re-enters the full apparatus."
