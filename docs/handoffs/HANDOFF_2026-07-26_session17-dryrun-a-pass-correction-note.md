# Session Handoff — Dry-run A PASS + Witness-1 correction note

## Objective
Close the sequencing gap between Step-3's five-precondition wall (all MET/CLOSED as of Session 16) and live smoke. Session 16 left two open items: gate (a) the parked vacuity-guard question (permanently UNPROVEN) and gate (b) the scratch-vs-real-repo step (every prior Item-0 probe used a scratch workspace, never StockPhotoAgent, and never ran through `main.py`'s full orchestrator). This session's job was to witness the real-vs-scratch delta, determine it was too large to jump straight to live smoke, and design + run a bounded dry-run that collapses the composition half of that delta on a disposable clone before live smoke touches the real tree.

## Current Status
- **Completed: Dry-run A PASS.** Three cycles (VALIDATION_FAILED, REVIEW_REJECTED, clean-APPROVE→commit-on-approval) run against a real `git clone` of StockPhotoAgent, adjudicated from mechanical git + event-log evidence against a pre-committed outcome matrix. Full detail in `NEXT.md`'s Session 17 entry.
- **Completed: Witness-1 correction note appended to NEXT.md** (doc-12 pattern) — the Session-16 "correction pass across three artifacts" claim was a same-session in-draft self-edit with no witnessable before-state, not an appended correction note; recorded so future sessions don't cite it as one.
- **Blocked (unchanged): live smoke still not authorized.** Gate (b) is now reduced to one variable (clone → real tree) instead of two (composition + real tree). Gate (a) (vacuity-guard detectability) remains permanently UNPROVEN, carried into smoke as a labeled limitation per standing ruling — this session did not touch it.

## Decisions & Rationale
- **Real-vs-scratch delta enumerated from code, not memory, before any dry-run design.** `config.yaml → project.repository` points at StockPhotoAgent's real working tree (validated at config-load, `config.py:157-166`); `checkout_branch`'s `git checkout -B` (`git_adapter.py:165-174`) operates on that **primary tree** — no worktree isolation (`git_adapter.py:37`) — and its safety is conditional on orchestrator sequencing (`set_attempt_ref` at `loop.py:217` always landing before any `reset_hard` at `loop.py:243/257/275/301`, verified from code). No `dry_run`/`DRY_RUN` flag exists anywhere in `src/` (grepped, zero hits).
- **A naive "stub spawn+commit, let everything else run against the real tree" dry-run was rejected.** It would let `checkout_branch` fire against the primary tree without the sequencing that makes its force-reset safe — more dangerous than live smoke, not less. Split into "Dry-run A" (composition, on a faithful clone) with no "Dry-run B" (real-tree behavior has no lower-risk substitute — that's what live smoke itself is).
- **Stub matrix required to drive real reject paths, not one clean pass.** A stub that only ever clean-approves would leave the `set_attempt_ref`-before-`reset_hard` ordering unexercised on real residue — the exact false-confidence failure mode this whole exercise exists to avoid. Sequenced three issues (from StockPhotoAgent's own real, committed `Issues.md`) to force VALIDATION_FAILED, REVIEW_REJECTED, and clean-APPROVE respectively.
- **Cycle-3 pre-commit: a real REJECT on the on-target patch would still count as PASS**, with commit-on-approval carried forward explicitly labeled unwitnessed — decided *before* running, specifically to prevent post-hoc rationalization toward whatever the reviewer happened to say. (Turned out unnecessary — Cycle 3 drew a real APPROVE — but the pre-commit stands as the record of how a REJECT would have been handled.)
- **Scope boundary recorded in the harness file itself, not just in conversation:** Dry-run A witnesses the loop transition-table composition only, not `main.py`'s end-to-end startup composition (health checks → ingest → loop under the real CLI entrypoint). This was flagged as a required fix mid-session — the initial matrix draft under-stated this narrowing.
- **Commit ruling departed from the default no-commit-without-authorization reflex.** NEXT.md had been sitting modified since Session 16, four handoffs were untracked with no other copy, and this session added two more durable artifacts (correction note + Dry-run A entry) on top. The user explicitly authorized a scoped commit this session — NEXT.md + the four untracked handoffs + the sweep-log line (confirmed as a normal historian artifact, not an anomaly) — while explicitly excluding the scratch clone/harness (outside the repo entirely, under `%TEMP%`, never at risk of being staged).

## Key Files
- `C:\Projects\issue-runtime\NEXT.md` — Session 17 entry (Dry-run A PASS, full cycle-by-cycle evidence, carried-unwitnessed list, vacuity-guard label) + the Witness-1 correction note, both appended this session.
- `C:\Users\adity\.claude\plans\twinkling-twirling-crane.md` — the approved plan for Dry-run A (context, approach, scope fences).
- Scratchpad (uncommitted, outside the repo, abandoned per plan): `dryrun_a_clone` (the StockPhotoAgent clone, HEAD `5e4018d2`, now at `agent-work` tip `5b76887e` after Cycle 3's real merge), `dryrun_a_harness.py` (StubEngine + canned patches + scope-boundary/Cycle-3 pre-commit notes in its docstring), `dryrun_a_run.py` (the three-cycle driver + raw capture).
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-07-26_step3-precondition4-mutation-leg-closure.md` — prior session's handoff (Session 16), the baseline this session started from.

## Next Action
Live smoke design. Gate (b) is down to one variable (real tree vs. the now-verified-faithful clone). Before designing live smoke itself: decide how to handle the two items Dry-run A explicitly left unwitnessed (main.py startup composition, orphan-crash recovery path) — whether either needs its own bounded witness first, or whether both are acceptable to carry into live smoke labeled. Gate (a) (vacuity-guard detectability, permanently UNPROVEN) is carried into smoke as a labeled limitation per standing ruling, not a blocker to resolve first.

## Testing / Verification Performed
- Clone fidelity: `git rev-parse HEAD` matched source exactly before and after a wipe-and-reclone (post stub-crash); `git branch -a` topology confirmed present (as remote-tracking refs per single-branch-checkout convention, not a content divergence).
- Dry-run A: all three cycles' PASS verdicts are from raw `git for-each-ref`/`rev-parse`/`status --porcelain` output and event-log JSON rows pasted in full in-conversation this session (not summarized before evidence was shown) — see `NEXT.md` Session 17 entry for the retained summary.
- `git status --porcelain` on the clone checked between every cycle (stop condition: dirty tree) — clean at all four checkpoints (post-build, post-cycle1, post-cycle2, post-cycle3).
- Witness 1 (correction-pass claim): `grep` for the doc-12 "Correction note" marker across NEXT.md/day-file/handoff found only the pre-existing, unrelated Session-14 note; `git log --oneline` on the day file and the Session-16 handoff both returned zero commits.
- Witness 2 (precondition #4 revert-clean): `git diff -- src/qc/rules/resolution.py` via `subprocess.run(shell=True)` through `C:\Python314\python.exe` (not the Bash tool) — empty, rc=0.
- Witness 3 (git status both trees): issue-runtime dirty exactly as Session 16 left it; StockPhotoAgent's real tree fully clean (`git status --porcelain` empty).

## Assumptions
None outstanding for the work performed. The one genuinely non-deterministic element (the real Qwen reviewer's verdicts in Cycles 2/3) was treated as "real verdict as-found" per explicit pre-commit, not assumed toward a desired outcome — both verdicts happened to land as hoped, but the harness and matrix were built to accept the opposite result too.

## Technical Debt
None introduced in `src/` — no `src/` change this session. The scratch harness and clone are abandoned per plan, not cleaned up as of this handoff (not required — outside the repo, disposable).

## User Constraints
- Bash-tool results remain inadmissible for any `Validator`-shaped command witness (standing from Session 16) — all git/pytest facts this session went through `subprocess.run(shell=True)` via the target interpreter, or through the Grep/Read/Bash tools only for non-`Validator`-shaped reads.
- No live smoke, no spawn against the real `claude` CLI, no touch to the real StockPhotoAgent tree, no doc 14 edit — all held this session.
- Commit this session is explicitly scoped by the user to NEXT.md + four untracked handoffs + the sweep-log line only — not a general "commit everything" authorization.

## Runtime & System State
- Commit at handoff (issue-runtime): pending the scoped commit described above — staged-file list to be confirmed with the user before it lands (final gate, per explicit instruction).
- Commit at handoff (StockPhotoAgent, real tree): unchanged — untouched this session, confirmed clean.
- Scratch clone (StockPhotoAgent copy, outside both repos): `agent-work` at `5b76887e` (post-Cycle-3 merge), abandoned, never to be pushed or referenced as StockPhotoAgent's real state.
- Background processes: none running. Ollama (`localhost:11434`, real, not stubbed) was called live during this session for Cycles 2 and 3's reviewer verdicts.
- Open branches / worktrees: none opened in either real repo.

## Deferred Work
- Live smoke itself — not designed, not started.
- The orphan-crash recovery path against a real-tree-shaped composition — flagged as unwitnessed by this session, not scheduled.
- `main.py` end-to-end startup composition (health checks + ingest + loop under the real CLI) — flagged as unwitnessed by this session, not scheduled.
- Standing tickle: doc 14 §2.4 Probe 2/3 two-leg re-probe at CLI 2.1.214 — still untouched.
- ADR-23 end-to-end differential — still deferred behind its three-part AND, unchanged this session.

## Open Questions
**Needs User Input**
- How to sequence live-smoke design against the two newly-named unwitnessed surfaces (startup composition, orphan-crash path) — carry both forward labeled, or witness either first. Not resolved this session; explicitly left for the user to direct next.
