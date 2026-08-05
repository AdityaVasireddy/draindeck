# Session Handoff — Group S: gate (c) corrected to UNWITNESSED, gate (d) witnessed end-to-end synthetically, S-D upgraded to a real projection witness

## Objective
Continue item-9's Group S witness work under an EXECUTOR/REVIEWER relay: re-verify entering
state against the committed handoff, then respond to a sequence of reviewer-gated evidence
demands — correct an unwitnessed gate-(c) PASS claim, analyze why the leaf-resolution chain
fails to stabilize in two prior spawns, and build synthetic (non-StockPhotoAgent) harnesses that
exercise the REAL production code to witness gates (d) and (upgraded) S-D for the first time,
rather than continuing to rely on prior-session prose claims.

## Current Status
- Completed: gate (c) correction appended to the session-26 handoff; chain_log analysis
  distinguishing 11-e1's and 11-e2's failure modes; a synthetic Group-S harness witnessing gates
  S-A/S-B/S-C (cooperative-tree shape) end-to-end for the first time; a second synthetic harness
  upgrading S-D from a local-set stand-in to a real witness of the projection-layer guard;
  `.gitignore` updated for the harnesses' transient run-artifact directories.
- In Progress: none — all four reviewer-gated tasks this session reached a paste-and-verdict
  conclusion.
- Blocked: S-E (no real merge target in a synthetic harness) and gate (d) for 11-e2's specific
  frontier-churn failure mode both remain unwitnessed; both require a real StockPhotoAgent run,
  which needs Adi's fresh, explicit go-ahead not given this session.

## Decisions & Rationale
- Corrected the gate-(c) "PASS" claim in `HANDOFF_2026-08-01_session26-group-s-holdpid-queue-block.md`
  to UNWITNESSED via an append-only correction note — because no `tasklist` artifact exists on
  disk for the `11-e2` spawn to support the original claim; it rested on prior-session prose
  only. Append-only (doc-12 pattern) so the original claim stays visible, corrected in place
  rather than rewritten. Lives in
  `%USERPROFILE%\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-01_session26-group-s-holdpid-queue-block.md`.
- Built `scratch/group_s_synthetic_harness.py` to import and drive the REAL `_sentinel_pause`,
  `capture_work_liveness`, and `_kill_tree` from `claude_headless.py` against a real (but
  synthetic, cooperative) OS process chain — because gate (d) had never been witnessed at all,
  only asserted in prose, and a synthetic-but-real-process harness is the only way to witness it
  without a real StockPhotoAgent spawn. Deliberately kills the resolve-chain ROOT
  (`child_pid`), not the harness's own process, as a stand-in for "kill the orchestrator" —
  documented as a deviation in the file's own docstring, because a self-contained test cannot
  kill itself and still capture post-kill evidence.
- Built `scratch/group_s_synthetic_sd.py` to import the REAL `EventLog`, `Event`, `EventType`,
  `StateProjection`, and `TransitionError` and drive three real scenarios against a throwaway
  temp-dir event log — because the prior harness's S-D was a synthetic local Python `set`, not
  the real de-dup mechanism, and the reviewer required upgrading it to a real witness before
  accepting the S-D claim.
- Appended `scratch/_gs_synth_*/` to `.gitignore` — the two harnesses regenerate a fresh,
  timestamped run-artifact directory (real process logs, sentinel markers, work-target files)
  on every run; ignoring only the transient dirs (not the harness scripts themselves) keeps
  `git status` legible without losing the reusable test code.

## Key Files
- `%USERPROFILE%\Projects\issue-runtime\scratch\group_s_synthetic_harness.py` — the Group-S
  S-A/S-B/S-C/S-D/S-E synthetic harness; read the module docstring first (DESIGN NOTE, DEVIATION
  NOTE, and INCIDENT NOTE are all load-bearing context for interpreting its results).
- `%USERPROFILE%\Projects\issue-runtime\scratch\group_s_synthetic_sd.py` — the S-D real-projection
  harness; its docstring documents the correction to the mechanism's actual location
  (`projections.py`'s `_execution_spawned`, not `loop.py`'s `_next_actionable`).
- `%USERPROFILE%\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-01_session26-group-s-holdpid-queue-block.md`
  — carries this session's append-only gate-(c) correction at its tail.
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\events\projections.py` — `_execution_spawned`
  (lines 167-185) is the real guard S-D now witnesses; read this before touching S-D again.
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — unchanged this
  session (still carries the pre-existing, uncommitted `hold_pid` diff); the synthetic harness
  imports directly from it.

## Next Action
Awaiting Adi's decision on which of the three open next-action forks (see Open Questions) to
authorize for session 28 — no next step is self-evident without that choice, since all three
remaining gaps (ADR-19 sampling, S-E/gate-(d)-churn witnessing, residual cleanup) require either
a fresh go-ahead or are simply independent of each other.

## Knowledge Captured
- The two prior "gate (d) miss" spawns are NOT the same failure mode. `11-e1`'s resolve loop
  actually stabilized (leaf pid 68048 held for 3 consecutive polls, polls 2-4) — its failure is
  downstream of a successful resolution (the resolved leaf died before an external witness could
  round-trip to it), not a resolution failure. `11-e2` never stabilized: a single 2-poll
  near-miss (polls 2-3) followed by six consecutive poll-to-poll leaf changes (polls 4-9),
  terminated by the 10.0s wall-clock deadline rather than the 20-poll cap (9 polls observed, well
  under 20, so the time branch must have fired). This corrects an earlier premise treating both
  as the same non-stabilizing mode.
- `_next_actionable` is NOT in `projections.py` — it lives in `loop.py` and only decides which
  issue to work on next; it never itself rejects a duplicate spawn. The real projection-layer
  de-dup/in-flight guard is `_execution_spawned` (`projections.py:167-185`), and it does not
  silently skip — it raises `TransitionError`, with two distinct guards: an exact-duplicate
  `execution_id` and a separate issue-level "already has a non-terminal open execution" check.
- A `.venv`-run Python process spawning a child via `sys.executable` produces more intermediate
  OS processes than the direct parent-child count would suggest (observed directly this session:
  a 3-script chain intended to produce exactly 2 descendants below the root instead produced 5,
  and a `taskkill /T` on one companion process surfaced an undocumented grandchild). This matches
  a "venv redirector-stub extra process" phenomenon already noted in an earlier handoff, now
  independently reproduced.
- `StateProjection.apply()` mutates `last_event_id`/`counts` before invoking the event handler,
  so those two fields still advance even when the handler subsequently raises `TransitionError`
  — the `issues`/`executions`/`issue_executions` dicts, however, are only mutated at the very end
  of a handler, after all raise-conditions are checked, so a rejected `apply()` leaves projection
  state otherwise unchanged (verified directly: the same `StateProjection` instance was reused
  across three sequential scenarios in `group_s_synthetic_sd.py` with no cross-contamination).

## Assumptions
- MED confidence: the synthetic harnesses' "cooperative settling" process shape (shim spawns one
  mid spawns one leaf, all real OS processes) is representative enough of production's
  `claude.CMD -> cmd.exe -> node -> worker` shape for the S-A/S-B/S-C results to generalize —
  based on both using `_resolve_leaf_worker`'s real BFS-descendant-walk-to-stable-leaf logic
  unmodified, not on any claim that the exact process depth/count matches (it does not — see
  Knowledge Captured on the venv-stub inflation). NOT verified against an actual StockPhotoAgent
  spawn this session.
- LOW confidence: whether `_resolve_leaf_worker`'s existing constants (`_LEAF_MAX_POLLS=20`,
  `_LEAF_MAX_SECONDS=10.0`, `_LEAF_STABLE_COUNT=3`) would ever catch a stable leaf in `11-e2`'s
  specific churn shape given more time/polls — the 9-poll window analyzed this session showed no
  convergence trend, but the log simply ends there; nothing in the data proves convergence is
  impossible, only that it hadn't started within the observed window. Not retested this session.

## Testing / Verification Performed
- PASS: `.gitignore` append is a pure addition — `git status --porcelain` reviewed, and
  `git check-ignore scratch/_gs_synth_20260802T051926Z` confirmed matched while
  `git check-ignore scratch/group_s_synthetic_harness.py` confirmed NOT matched (both raw
  outputs captured in-session).
- PASS: gate-(c) correction append verified via `git diff` showing only `+` lines added at the
  file's existing tail — zero deletions or modifications to prior content.
- PASS: `scratch/group_s_synthetic_harness.py`, second run — exit code 0. S-A (both layers alive
  + `capture_work_liveness` showing mtime/hash advancing), S-B (leaf survives a `/F`-no-`/T` kill
  of its parent), and S-C (residue preserved — confirmed-dead leaf, stable + containing content
  across two post-death reads) all captured via raw `tasklist`/`taskkill` output and asserted in
  the script itself.
- FAIL then PASS: the harness's first run crashed on an S-C assertion comparing file hashes
  across the exact kill instant, which raced the leaf's own 0.3s write cadence — a bug in the
  test's own assertion, not in `claude_headless.py`. The crash (no `try/finally` at that point)
  left one process (`hold_pid`) alive until it was manually killed and independently
  reconfirmed dead via `tasklist`. Fixed (try/finally cleanup; S-C changed to wait for confirmed
  death, then check content containment/stability rather than exact-hash equality) and re-run
  clean.
- PASS: `scratch/group_s_synthetic_sd.py`, first run — exit code 0. Both positive scenarios
  (exact-duplicate `execution_id`; same-issue-still-open) raised the real `TransitionError` with
  the expected messages; the negative control (fresh, unseen issue/execution pair) was accepted
  with no exception and landed in `EXECUTING` state inside `open_executions()`.
- PASS: real `state/events.jsonl` confirmed byte-identical (109 lines, same tail) before and
  after both harness runs — neither harness touched it.
- NOT TESTED: S-E (merge second-parent content check) — no git repo/merge/target exists in
  either synthetic harness; explicitly marked NOT-OBSERVABLE rather than fabricated.
- NOT TESTED: gate (d) against `11-e2`'s specific frontier-churn shape (leaf pid changing every
  poll rather than settling) — the synthetic harness only produces the settling/stabilizing
  shape (`11-e1`'s mode).

## Outstanding Issues
- The first run of `scratch/group_s_synthetic_harness.py` crashed mid-execution (too-strict S-C
  assertion) and left one process (`hold_pid`) running until manually killed — see Testing /
  Verification Performed. Already fixed in the harness (try/finally + corrected S-C logic) and
  re-run clean; flagged here because it manifested (however briefly) during this session, not
  because it is still open.

## User Constraints
- No commit without explicit per-commit authorization (standing) — nothing committed this
  session; `.gitignore`, the gate-(c) correction, and both harness scripts are all
  unstaged/untracked.
- `src/runtime/engine/claude_headless.py`'s `hold_pid` diff stays uncommitted until Group S fully
  passes (standing) — S-E remains unwitnessed, so this gate is not cleared; the diff is unchanged
  this session.
- No StockPhotoAgent `cmd_run`/spawn without Adi's explicit fresh go-ahead (standing) — none
  given or used this session.
- Any future `src/` change requires the 60/60 durability harness on both seeds (42 and 1337)
  before commit (standing) — not applicable this session, no `src/` changes made.

## Runtime & System State
- Commit at handoff: `d32a917` (build repo `master`; unchanged this session — nothing committed).
- Background processes: none running. All synthetic-harness processes (real OS processes spawned
  and killed during this session's two harness runs) confirmed dead via both the harnesses' own
  final `tasklist` sweeps and an independent post-hoc `tasklist` check.
- Dev servers / ports: none started or stopped. Ollama reviewer endpoint (`localhost:11434`)
  confirmed serving `qwen2.5-coder:14b` at session start; not otherwise touched.
- Open branches / worktrees: none opened or modified this session. StockPhotoAgent not touched.
- Memory files updated: none this session.

## Deferred Work
- Witnessing S-E (merge second-parent content check) and gate (d) against `11-e2`'s
  frontier-churn shape specifically — both deferred because both require a real StockPhotoAgent
  run, which needs a fresh Adi go-ahead not sought this session.
- Continuing ADR-19 kill-criteria sampling toward n=20 — deferred pending resolution of two
  scoring questions (attempt-1 numerator definition; issue-11/issue-12 pool de-dup) and a fresh
  go-ahead for a new real spawn.
- `config.yaml`'s `StockAgent`/`StockPhotoAgent` name mismatch (previously flagged, low blast
  radius) — deferred again, not touched this session.

## Open Questions
**Needs User Input**
- Which of three independent next-action forks should session 28 pursue: (A) continue ADR-19
  sampling with a new distinct issue (needs a fresh `cmd_run` go-ahead and the pool-de-dup
  question resolved first — high blast radius), (B) attempt to witness S-E and/or gate (d) in
  `11-e2`'s churn mode against a real StockPhotoAgent run (needs a fresh go-ahead — high blast
  radius), or (C) the low-blast-radius `config.yaml` name-mismatch cleanup? None are mutually
  exclusive across sessions, but each needs its own explicit decision before work starts.
- ADR-19 scoring: does issue-11's eventual third-attempt success (`11-e3`) count toward an
  "attempt-1 success" numerator, and how? Unresolved, blocks any n=20 verdict.
- ADR-19 scoring: how should the issue-11/issue-12 byte-identical-duplicate pair be handled in
  the pool count — does the id-space (currently 1-12) need de-duplicating before scoring?
  Unresolved, blocks any n=20 verdict.

**Model Uncertainty**
- Whether the synthetic harnesses' cooperative-settling process shape generalizes to production's
  real `claude.CMD -> cmd.exe -> node -> worker` chain closely enough for the S-A/S-B/S-C results
  to carry over — see Assumptions; not independently re-verified against a real StockPhotoAgent
  spawn this session.
