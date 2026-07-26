# Session Handoff — Step-3 precondition #4 (baseline non-vacuity) mutation-leg closure

## Objective
Close Step-3 precondition #4's remaining half — doc 08 §5d's non-vacuity requirement for baseline green against StockPhotoAgent. The collected>0 leg (rc=0, 26 passed via collection) had been witnessed in a prior session turn; this session's job was the mutation leg — proving the green is real by deliberately breaking a source assertion, witnessing the red, reverting, and re-witnessing green — the last piece needed to close all five Step-3 preconditions.

## Current Status
- Completed: Step-3 precondition #4 CLOSED. Both legs of doc 08 §5d witnessed this session (collected>0 leg re-confirmed this session too, after an initial Bash-tool false negative; mutation leg executed fresh). `NEXT.md` updated with a Session 16 entry recording the closure, the roll-up, and the three still-open orthogonal gates.
- Blocked: Live smoke is NOT authorized by this closure. Item 0 (composed real-spawn through ClaudeHeadlessEngine.run()): RUN, clean-with-caveat — not unqualified pass, and not the gate it was mislabeled as this session. Still open: (a) the vacuity-guard positive control has never confirmed detectability (three independent non-reproductions per doc 14 — the mechanism's ability to detect contamination is unproven, only its failure to observe any); (b) every Item 0 run so far used a scratch workspace — live smoke would be the first run against a real target repo (doc 14's own note). What IS done: two clean composed runs — 2026-07-17 (CLI 2.1.212, doc 14 §2.6/2.7) and 2026-07-24 re-probe (CLI 2.1.215) — exit 0, apiKeySource="none", denial signals present, .git/knowledge/ absent across the 450s poll. The earlier "unwitnessed/remains unwitnessed" wording in this session's artifacts was stale and wrong; doc 14 shows the composed run closed.

## Decisions & Rationale
- **Discarded the Bash-tool (Git Bash) execution result rather than reconciling it** — running the validation command's backslash-path string through the Bash tool mangled the escaping and produced a plausible-looking false negative (`RC=4`, `collected 0`). Re-ran the identical command string via `subprocess.run(cmd, cwd=..., shell=True)` invoked from `C:\Python314\python.exe` (matching `Validator._run_once`'s real call shape), which returned the true result. This was then bound as a hard constraint for the mutation leg: Bash-tool results are inadmissible for either the red or green-after-revert witness, because a false positive from the same artifact class would be far more dangerous than a visible false negative.
- **Rebound the mutation leg's red-leg pass/fail criterion away from an exact predicted count.** The first plan-mode draft gated PASS on an exact `1 failed, 25 passed` count derived by reading unmutated source — the user rejected this as repeating the exact failure mode being guarded against (a valid-but-untraced transitive effect could register as falsely inadmissible). Rebound to structural invariants instead: `returncode != 0` AND `collected == 26` (no collection/import error silently dropped tests) AND `≥1 test failed` AND the failure is an assertion failure, not a collection error. The specific `1 failed, 25 passed` prediction was kept as predicted-and-checked (report whether it matched), not as the gate itself.
- **Chose `src/qc/rules/resolution.py`'s `MIN_WIDTH_PX` (2000→500) as the mutation target** — a QC-rule numeric threshold, not a syntax/import change, so any resulting failure could only be an assertion mismatch, never confusable with the earlier Bash-tool collection-error artifact. Traced its effect on both tests in `tests/test_qc_rules.py` before mutating (predicted one test would fail, one would remain unaffected) — the prediction matched exactly when run.
- **Kept the green-after-revert leg as an exact gate** (`rc==0` AND exactly `26 passed`), unlike the red leg, because it restores a known, already-witnessed state rather than predicting an untraced one — asymmetric bindings were deliberate, not an inconsistency.
- **Wrote the NEXT.md closure entry with a sharper framing of the ADR-23 end-to-end differential's OPEN status** — not just "still deferred" but explicitly noting the differential's "before" half is structurally unwitnessable for the Phase-2 mechanism change that already landed (Session 15), since the pre-Phase-2 code no longer exists and a `git stash` reconstruction was already ruled inadmissible in the session that deferred it. The user confirmed this addition as correct and asked it be carried forward as a known permanent limit, not something to go hunting to fix.

## Key Files
- `C:\Projects\issue-runtime\NEXT.md` — Session 16 entry (top of "## Resume point" section) records the #4 closure, the mutation used (`resolution.py:17`), the execution surface, the three OPEN gates, and the precondition roll-up (1 MET, 2 CLOSED, 3 CLOSED, 4 CLOSED, 5 MET — all five satisfied, live smoke not authorized).
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` §5d — ADR-23, the non-vacuity requirement this session's work satisfies; also documents the three-part AND still blocking the separate end-to-end differential.
- `C:\Projects\StockPhotoAgent\src\qc\rules\resolution.py` — mutation target this session (`MIN_WIDTH_PX`), mutated to 500 for the red leg and reverted to 2000; confirmed clean via `git status --short` / `git diff` after revert (both empty).
- `C:\Projects\issue-runtime\knowledge\issue-runtime\2026-07-26.md` — this session's historian day file (3 `status: auto` cases, not yet reviewed/confirmed — see Next Action).
- Plan file (this session): `~\.claude\plans\woolly-squishing-nest.md` — the approved mutation-leg plan, including the red-leg rebinding the user required before execution.

## Next Action
Item 0 (composed real-spawn through ClaudeHeadlessEngine.run()): RUN, clean-with-caveat — not unqualified pass, and not the gate it was mislabeled as this session. Still open: (a) the vacuity-guard positive control has never confirmed detectability (three independent non-reproductions per doc 14 — the mechanism's ability to detect contamination is unproven, only its failure to observe any); (b) every Item 0 run so far used a scratch workspace — live smoke would be the first run against a real target repo (doc 14's own note). What IS done: two clean composed runs — 2026-07-17 (CLI 2.1.212, doc 14 §2.6/2.7) and 2026-07-24 re-probe (CLI 2.1.215) — exit 0, apiKeySource="none", denial signals present, .git/knowledge/ absent across the 450s poll. The earlier "unwitnessed/remains unwitnessed" wording in this session's artifacts was stale and wrong; doc 14 shows the composed run closed. The real next action is not "run Item 0" (already run) — it's resolving the parked vacuity-guard question and deciding how to handle the scratch-vs-real-repo step before live smoke.

## Knowledge Captured
- The Bash tool (Git Bash) mangles backslash-escaped path strings (`\\` sequences) differently than Windows `subprocess.run(shell=True)` does — a command that is correct for the real runtime invocation can produce a spurious, plausible-looking failure under the Bash tool alone. Any future witness of a `Validator`-shaped command must go through `subprocess.run(shell=True)` via the target interpreter directly, not the Bash tool, to be admissible.
- `ResolutionRule.MIN_WIDTH_PX` / `MIN_HEIGHT_PX` in StockPhotoAgent's `src/qc/rules/resolution.py` control a `min(width, height)`-as-percent-of-requirement score; only `tests/test_qc_rules.py`'s two tests exercise this rule, and only one (`test_resolution_measure_score_below_minimum`, using a 1000×1000 fixture) is sensitive to lowering the threshold to 500 in the range tested this session.

## Assumptions
None outstanding — both witnessed legs (red, green-after-revert) and the revert-clean check were directly observed this session, not inferred.

## Testing / Verification Performed
- PASS: Collected>0 leg re-confirmed this session via `subprocess.run(cmd, cwd=r"C:\Projects\StockPhotoAgent", shell=True)` from `C:\Python314\python.exe` — rc=0, `26 passed`.
- PASS: Mutation red leg — same execution surface, `MIN_WIDTH_PX=500` active — rc=1, `collected 26 items` (1 failed + 25 passed), `AssertionError: assert 200.0 == 50.0` at `tests\test_qc_rules.py:19` in `test_resolution_measure_score_below_minimum`. All bound structural conditions met; the specific predicted count matched exactly.
- PASS: Green-after-revert leg — same execution surface, `MIN_WIDTH_PX` reverted to 2000 — rc=0, exactly `26 passed`.
- PASS: `git status --short -- src/qc/rules/resolution.py` and `git diff -- src/qc/rules/resolution.py` in StockPhotoAgent — both empty after revert.
- NOT TESTED (this session): the ADR-23 end-to-end differential and the standing CLI-2.1.214 tickle (doc 14 §2.4 Probe 2/3) — neither touched this session, both remain open per NEXT.md. Item 0 (composed real-spawn) — TESTED, clean-with-caveat; see Current Status. Not "not tested." Still-open items are the vacuity-guard positive control and the scratch-vs-real-repo step, not Item 0 itself.

## Technical Debt
None introduced this session — the mutation was scratch-only and fully reverted; `resolution.py` is confirmed byte-identical to its pre-mutation state via `git diff`.

## User Constraints
- No commit in either repo (issue-runtime or StockPhotoAgent) this session — standing rule, explicitly reaffirmed for this session's closes.
- The NEXT.md entry was the only authorized write until this handoff; the historian sweep and this handoff document were separately authorized afterward, in that fixed order (sweep → handoff → hold for confirmation before any further action).
- Bash-tool results are inadmissible as evidence for any future witness of a `Validator`-shaped command; only `subprocess.run(shell=True)` via the correct interpreter counts.

## Runtime & System State
- Commit at handoff (issue-runtime): unchanged from session start — no commit made this session.
- Commit at handoff (StockPhotoAgent): unchanged from session start — no commit made this session; `resolution.py` confirmed clean (no diff) after the mutation was reverted.
- Background processes: none started this session.
- Dev servers / ports: none.
- Open branches / worktrees: none opened this session.
- Memory files updated: none (per this skill's own rule — memory is never updated by a handoff).

## Deferred Work
- ADR-23 end-to-end differential (env-witness script + #4-non-vacuity + live "before" observation, all three required) — still deferred; the "before" half is now understood as structurally unwitnessable for the already-landed Phase-2 change specifically, not merely postponed. A future session performing this differential would need a *different*, not-yet-landed mechanism change to have a genuine "before" to observe.
- Standing tickle: doc 14 §2.4 Probe 2/3 two-leg re-probe at CLI 2.1.214 — untouched this session, still owed whenever the CLI version is next checked.

## Open Questions
**Needs User Input**
- Item 0 is already run (see Current Status) — the open question is not "proceed to Item 0" but how to resolve the parked vacuity-guard question and the scratch-vs-real-repo step before live smoke. The user's own framing of this session's close was explicit that all-five-satisfied does not imply "go," and that decision is a deliberate go/no-go the user reserved for themselves.

**Model Uncertainty**
- None — this session's scope was narrow and fully witnessed; no unresolved technical uncertainty carries forward beyond the pre-existing, already-documented open gates.
