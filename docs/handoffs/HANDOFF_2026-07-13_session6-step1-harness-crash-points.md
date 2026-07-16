# Session Handoff — Session 6 Step 1: the two deferred harness crash points

## Objective
Session 6 is doc 07's Phase-2 gate. This session was scoped by the user to Step 0
(baseline re-verify) and Step 1 (add the two harness crash points Session 5
deferred), then STOP — do not enter Step 2. The user attached a strict honesty
rider to Step 1: settle the doc-14 characterization of what the new crash points
actually prove, via three named checks, before committing. The plan was approved
with six amendments plus a redirect-proof addendum; Steps 2-5 are for later sessions.

## Current Status
- Completed: Step 0 baseline re-verified; Step 1 (two crash points) implemented,
  verified 59/59 on both seeds, coverage boundary settled, committed (`aaf6b60`);
  doc 14 written and committed (`d097f1f`).
- Blocked: nothing. Step 2 (preflight) is the next session's work, deliberately not
  started per the user's instruction.

## Decisions & Rationale
- **New scripted issue `045` (cap 2) drives the escalation window** — it fails
  validation on attempts 1 AND 2, exhausts its per-issue cap, and escalates to
  NEEDS_HUMAN, giving a deterministic `after_append:IssueEscalated` crash point.
  Lives in `tests/crash/worker.py` (CAP_BY_ISSUE, VAL_FAIL as attempt-sets,
  EXPECTED_TERMINAL) and mirrored in `tests/crash/harness.py`.
- **`verify()` generalised from all-DONE to an expected-terminal map** — a
  capped-out issue must verify with zero commits, no accepted execution, exactly one
  escalation; merge invariants I-j/I-l skip it. In `tests/crash/harness.py`.
- **Coverage boundary stated honestly, not as "joint coverage"** — see Knowledge
  Captured. `validate:post-artifact` proves loop-level crash survival only, NOT
  check-3's reset. Recorded in `docs/14-session6-phase2-gate.md` §1.3-1.5 and in
  inline comments on both crash-point definitions.
- **Reset-proof gap deferred, not closed in this commit (item R1)** — the fix (a
  planted `f5` fixture) is fully specified in doc 14 §1.5 but not built: it is a
  pre-existing gap (predates Step 1), the user scoped today's commit to exactly the
  two crash-point files, and a named deferral was explicitly sanctioned.
- **Two separate commits** — code (`aaf6b60`, the two test files only, per the
  user's "commit ONLY" instruction) and doc 14 (`d097f1f`) — to keep the code
  commit clean while not leaving the record uncommitted. Both exclude the stray
  Session-5 handoff.

## Key Files
- Plan file: `~/.claude/plans/read-claude-md-next-md-the-deep-quail.md` — the
  approved Session-6 plan (all six amendments + addenda). The Step 2-5 contract.
- `~/.claude/CLAUDE.md`-equivalent project rules: `C:\Projects\issue-runtime\CLAUDE.md`.
- `docs/14-session6-phase2-gate.md` — as-built record; §1.3-1.5 carries the
  coverage-boundary finding and deferred item R1. Read before any harness work.
- `docs/13-session5-orchestrator-loop.md` — the Session-5 as-built; §4 is where
  these two crash points were originally deferred.
- `tests/crash/worker.py`, `tests/crash/harness.py` — the Step-1 changes.
- `NEXT.md` — NOT updated this session (see Deferred Work).

## Next Action
Begin Step 2 (preflight), opening with **2a billing re-verification**
(`billing.reverify_at: phase-2-gate`; last verified 2026-07-10 — WebFetch Help
Center article 15036540, update `config.yaml` billing block) and **2b engine
version pin + fence re-probe** (`claude --version`; ADR-21 is pinned to 2.1.207 — if
the version differs, re-run the fence micro-probe before trusting `_DENY_TOOLS`).
Full ordered contract, user-gated items, and model split are in the plan file.

## Knowledge Captured
- **Check-3's *reset* is unproven by the crash harness, and always has been.**
  Gutting `adapter.reset_hard(expected)` in `check_dirty_workspace`
  (`src/runtime/recovery/bindings.py`) and running the full harness passes 59/59,
  including the pre-existing f1/f2 fixtures. Two masks: the harness worker's blanket
  `reset_hard(base)` at every EXECUTING entry cleans any leftover; and check-3's own
  archive (`snapshot_commit`) commits the dirty state, leaving the tree clean at a
  different commit even without the reset (object-DB `merge_to` never reads worktree
  HEAD). Check-3's archive/residue-preservation IS proven (I-m, Session-5 M1); only
  the reset is not.
- **Production genuinely relies on check-3's reset where the harness does not.**
  `loop.py::_execute` calls `checkout_branch(create_from=base)`, which *refuses* on a
  dirty tree (`git_adapter.py:166` raises RepoError) rather than force-resetting;
  production's `reset_hard(base)` calls are only on reject/escalate paths
  (loop.py:243,257,275,301); `_validate` self-resets nothing. So on a mid-VALIDATING
  crash, production depends on recovery having reset the tree at startup — exactly
  the property the harness cannot currently prove.
- **The `escalated == 1` assertion is non-vacuous.** Adding a tolerant
  `(NEEDS_HUMAN, IssueEscalated)` transition and appending a second escalation to a
  clean run's log turns `verify()` red with "issue 045 has 2 IssueEscalated events
  (want 1)". Production's real guard is stronger: that transition is absent from
  `ISSUE_TRANSITIONS`, so a real double-emit is a hard TransitionError at replay.

## Testing / Verification Performed
- PASS: `python -m pytest tests\unit -q` → 103/103 (Step 0, and again after the
  harness edits).
- PASS: full crash harness 59/59 on seed 42 AND seed 1337; filtered single-point
  runs of both new points green (`after_append:IssueEscalated:2` correctly ran clean
  — only one escalation ever fires). Final 59/59 on seed 42 re-run on the committed
  logic (post-run edits were comment-only).
- PASS (mutations, all reverted; `git diff src/` empty after): escalation→DONE turns
  the harness red at worker completion (terminal-map assertion bites);
  double-escalation turns `verify()` red (exactly-once assertion bites).
- NOT TESTED: check-3's reset in isolation (deferred item R1 — the harness cannot
  currently prove it). Nothing in Steps 2-5 (live engine, live Ollama, StockAgent).

## User Constraints
- This session: Step 0 then Step 1 only; do NOT proceed into Step 2 today.
- Commit ONLY the two crash-point files for the Step-1 code commit; keep the stray
  `docs/handoffs/HANDOFF_2026-07-12_...md` (predates this session) out of it.
- Honesty discipline: state the crash points' true coverage boundary, do not write
  "joint coverage" unless production actually blanket-resets (it does not).
- Standing project rules: architecture FROZEN (changes via ADR); doc 03 wins any
  event/state conflict; ANTHROPIC_API_KEY stays unset (subscription billing, ADR-18);
  commit only when asked.

## Runtime & System State
- Commit at handoff: `d097f1f` (code `aaf6b60` beneath it).
- Background processes: none (the final harness run completed; its Monitor ended).
- Open branches/worktrees: on `master` (established commit target for this repo).
- Memory files updated: none.
- Untracked, intentionally left alone: `docs/handoffs/HANDOFF_2026-07-12_...md`
  (stray, predates this session). This handoff is a new file in the same directory.

## Deferred Work
- **NEXT.md not updated this session.** It still points at Session 6 generically. The
  next session should refresh its resume pointer to "Session 6 Step 2 (preflight)"
  and add the user-required follow-up line: harden `_reviewer_reachable` to query
  `/api/tags` and assert the configured model tag is present (today it GETs the root
  and would pass with the model missing). Left undone because the user scoped today
  to Step 0-1 + commit + handoff.
- **Deferred item R1** (prove check-3 reset via a planted `f5` fixture) — specified
  in doc 14 §1.5, for the next harness pass.

## Open Questions
**Needs User Input**
- Confirm whether deferred item R1 (the `f5` reset-proof fixture) should be built at
  the start of the next session or folded into a later harness pass — doc 14 proposes
  the latter but flags it as the user's call.
- Config fact discovered during planning (already in the plan, still unactioned):
  the pulled Ollama model is `qwen2.5-coder:14b` but `config.yaml` says
  `qwen2.5-coder` (untagged → `:latest`, not pulled). Step 2c fixes this; surfaced
  here so it is not lost.
