# Session Handoff — Session 6 continued: fail-safe trace + R1 (check-3 reset proof) closed

## Objective
Continue Session 6 after Step 0/Step 1 (committed `aaf6b60`/`d097f1f`). Step 1's
mutation spot-check had surfaced a pre-existing, harness-wide gap (doc 14 §1.3-1.5,
deferred as "R1"): check 3's `reset_hard` healing of a mid-VALIDATING dirty tree has
never been proven for any crash point, because every existing scenario runs inside
the worker loop, whose own blanket reset masks the reconciler's. The user asked
first for a cheap trace of what production actually does when `checkout_branch`
refuses on a dirty tree (to gauge urgency), then — given the trace — instructed
closing R1 now via the already-specified fixture `f5`, before Step 2 preflight
begins, on the same "do it first, independent of user-gated services" logic that
sequenced Step 1 ahead of Step 2.

## Current Status
- Completed: fail-safe trace done; fixture `f5` implemented, verified (baseline +
  isolated mutation spot-check), full harness green on both seeds; doc 14 and
  NEXT.md updated; two commits made (test-only, then docs).
- In Progress: none — R1 is fully closed for this session's scope.
- Blocked: none.

## Decisions & Rationale
- **Fail-safe finding: `checkout_branch`'s dirty-tree refusal is a safe wedge, not
  a corruption risk.** Traced directly (not assumed): `is_dirty()`
  (`src/runtime/repo/git_adapter.py:108-110`) is a pure `git status --porcelain`
  query; the `RepoError` raise (`git_adapter.py:165-174`) fires strictly before
  either mutating `checkout` call. `RepoError` is never caught in `loop.py` or
  `main.py` (not in the `OrchestratorHalt`/`ReviewerError`/`_BudgetExhausted`
  hierarchy) — it propagates uncaught and crashes the process before any event is
  emitted, so the log never diverges from the world. Recovery always runs before
  the orchestrator loop starts, so this can't race check 3 within one process
  lifetime. This determined the gap was real but non-urgent from a corruption
  standpoint — closed anyway per the user's explicit instruction.
- **R1 closed via fixture `f5-reset`, modeled on `f4`'s direct-`recover()`
  pattern** — `tests/crash/harness.py::run_reset_fixture`. Bypasses the worker
  subprocess entirely (structural isolation, not probabilistic) so the worker's
  masking reset cannot run. Called from `run_fixtures()`.
- **Isolated mutation spot-check is mandatory, not a full-run check** — the user
  explicitly required this after the plan draft initially proposed a full-harness
  red as sufficient evidence. A temporary standalone script
  (`%TEMP%/f5_isolated.py`, deleted after use, never committed) imported
  `harness.py` and called `run_reset_fixture` directly, so the fixture's own
  assertion — not some other scenario's — is what fails.
- **Doc 14's R1 closure is scoped narrowly on purpose** — the user required the
  claim be constrained to "reconciler-path healing of the VALIDATING dirty-tree
  state" only, with an explicit "still open" note on whether a live Ctrl+C during
  VALIDATING only ever produces states within f5's coverage. No "joint coverage"
  or "VALIDATING abort path covered" wording was used, matching the discipline
  §1.4 already applied to the two Step-1 crash points.

## Key Files
- Plan file: `~/.claude/plans/continuing-session-6-of-humming-parrot.md` — full
  detail on the traced fail-safe finding, the f5 fixture design, and the required
  isolated mutation-check + narrow-scope doc constraints (all three added by the
  user after the first plan draft was rejected).
- `tests/crash/harness.py` — new `run_reset_fixture` function (f5), wired into
  `run_fixtures()`. This session's only production-adjacent code change (harness
  is test-only, not `src/`).
- `src/runtime/recovery/bindings.py:78-104` (`check_dirty_workspace`) — the check-3
  seam f5 exercises; line 102 (`adapter.reset_hard(expected)`) is the exact call
  the mutation spot-check gutted and reverted. No net change to this file.
- `docs/14-session6-phase2-gate.md` §1.5 — rewritten this session: the fail-safe
  trace, f5's design/evidence, the narrowed scope statement, and the still-open
  live-abort question. §1.2 and §1.6 counts updated to 60.
- `NEXT.md` — resume point rewritten to current state (Step 0/1/R1 done, commit
  hashes, Step 2 as next action); verify-commands section updated to 60 and now
  notes to use `.venv` python (system `python` on this machine lacks
  `pyyaml`/`pydantic` — discovered this session, see Knowledge Captured).

## Next Action
Begin Session 6 Step 2 preflight: **2a billing re-verification**
(`billing.reverify_at: phase-2-gate`, last verified per NEXT.md on 2026-07-10) then
**2b engine-version/fence re-probe** (`claude --version`; ADR-21 is pinned to
2.1.207) — per doc 14's "Steps 2-5 — NOT STARTED" section and the user-approved
plan's ordered contract. Do not skip 2a/2b or jump ahead to the gated live smoke.

## Knowledge Captured
- This machine's system `python` (`C:\Python314\python.exe`) lacks `pyyaml` and
  `pydantic` — the harness and orchestrator must be run with the project's
  `.venv` (`./.venv/Scripts/python.exe`), not bare `python`, or `run_fixtures()`
  fails on the `f4-engine-orphan` import with `ModuleNotFoundError: No module
  named 'yaml'`. Prior sessions' NEXT.md already said "`.venv` python" but didn't
  explain why; this session hit and confirmed the failure mode directly. Verify
  commands in NEXT.md now say so explicitly.
- `check_dirty_workspace`'s masking mechanism (doc 14 §1.3) was directly observed,
  not just theorized: gutting `reset_hard` still leaves `is_dirty()` returning
  False afterward (because `snapshot_commit` already archived the dirty state to
  a residue commit), so a naive "is the tree clean" assertion cannot catch the
  gap — only a commit-identity assertion (`current_commit() == end_commit`) can.
  f5 was written with that in mind.

## Testing / Verification Performed
- PASS: f5 fixture standalone (unmodified code), via a temporary direct-call
  script — `PASS fixture[f5-reset]`.
- PASS (as a spot-check, expected to fail): f5 fixture standalone with
  `reset_hard` gutted in `bindings.py:102` — raised
  `AssertionError: f5: worktree at 620586e4fd33, not pinned end_commit
  e6322d368b7f -- check-3 reset landed wrong`. Confirms f5 catches the gap on
  its own assertion, in isolation, not via a full-run failure.
- PASS: `git diff src/` empty after reverting the mutation, verified before
  committing the fixture.
- PASS: full crash harness, `.venv` python, seed 42 — `ALL 60 SCENARIOS PASSED`.
- PASS: full crash harness, `.venv` python, seed 1337 — `ALL 60 SCENARIOS PASSED`.
- PASS: `python -m pytest tests\unit -q` (`.venv`) — `103 passed`.
- NOT TESTED: the live-abort path itself (a real `claude -p` process killed
  mid-VALIDATING) — this remains unexercised by any harness scenario; see Open
  Questions.

## Runtime & System State
- Commit at handoff: `b539239` (docs/NEXT.md commit; `777ccab` is the preceding
  test-only fixture commit; both are new this session, on top of `06f964f`/
  `d097f1f`/`aaf6b60` from prior sessions).
- Background processes: none left running.
- Untracked files present but out of scope (left alone per plan, predate this
  session): `docs/handoffs/HANDOFF_2026-07-12_session5-orchestrator-loop.md`,
  `docs/handoffs/HANDOFF_2026-07-13_session6-step1-harness-crash-points.md`,
  `knowledge/.sweep/failed/`.

## Open Questions
**Model Uncertainty**
- Doc 14 §1.5 (and this handoff) explicitly leave open whether a live Ctrl+C
  during VALIDATING only ever produces log/tree states within f5's coverage, or
  whether some intermediate state (e.g. mid-git-operation) a live kill could
  produce isn't modeled by f5's synthetic log. This was flagged by the user as a
  required "still open" item, not something to resolve this session — surface it
  again when Step 4's abort-protocol claim ("worst-case kill is exactly what the
  harness proves") is next revisited.
