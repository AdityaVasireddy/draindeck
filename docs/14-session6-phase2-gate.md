# 14 — Phase-2 Gate (Session 6)

**Status:** IN PROGRESS · **Started:** 2026-07-13
**Scope:** doc 07's Phase-2 gate. This document is the as-built record. It is
written incrementally as the session proceeds; only sections marked COMPLETE are
final. Doc 03 is the frozen contract and wins every conflict; ADR-21 governs the
engine fence; ADR-19 kill criteria are frozen.

Honesty discipline: each section separates VERIFIED (ran it, saw it this session)
from ASSUMED. The plan is `~/.claude/plans/read-claude-md-next-md-the-deep-quail.md`
(user-approved with six amendments + a redirect-proof addendum + a conftest note).

---

## Step 0 — Baseline re-verify — COMPLETE (VERIFIED 2026-07-13)

Fresh observations on this Windows machine, `.venv` python, converting NEXT.md's
recorded counts into this-session evidence:
- **103/103 unit** (`python -m pytest tests\unit -q`, 27.9 s).
- **55/55 crash harness, seed 42** (pre-Step-1 baseline). `fixture[f4-engine-orphan]`
  ran (not skipped) → `claude` is on PATH.
- `ANTHROPIC_API_KEY` confirmed **unset** (ADR-18 posture) before any work.

---

## Step 1 — The two deferred harness crash points — COMPLETE (VERIFIED 2026-07-13)

Session 5 deferred `validate:post-artifact` and `after_append:IssueEscalated`
(doc 13 §4). Both are now added, and — importantly — their **actual proven
coverage boundary is narrower than the plan's original framing**, established by
three checks below. Changes are confined to `tests/crash/worker.py` and
`tests/crash/harness.py`; no production code changed (verified: `git diff src/`
empty after all spot-checks).

### 1.1 What shipped
- **New scripted issue `045`**, last in `ISSUES`, per-issue cap **2**
  (`CAP_BY_ISSUE`). It fails validation on attempts 1 AND 2, exhausting the cap, so
  the spawn guard escalates it → `IssueEscalated(reason=cap)` →
  **NEEDS_HUMAN**. This is the deterministic source of the escalation crash window.
- **`validate:post-artifact`** — the worker writes an untracked byproduct
  (`valcache-<xid>.tmp`) in the VALIDATING step, hits the crash point, then deletes
  it. A kill there leaves a dirty tree with the execution still VALIDATING.
- **`after_append:IssueEscalated`** — a kill right after the durable cap-hit
  escalation fact for 045.
- **`verify()` generalised** from "every issue DONE" to an expected-terminal map
  (`EXPECTED_TERMINAL`: 042/043/044 → DONE, 045 → NEEDS_HUMAN). New assertions:
  a capped-out issue ships **zero** CommitCreated, has **no** accepted execution,
  and escalates **exactly once** (idempotent across crash restarts); merge
  invariants I-j/I-l skip the escalated issue. The worker's completion check moved
  to the same map (so a run that leaves 045 escalated is a clean exit 0, not an
  error).

### 1.2 Scenario count (VERIFIED both seeds)
Pre-Step-1: 55 = 36 det (18 pts × 2 nth) + 15 rand + 3 fixtures (f1/f2/f4) + 1
control. Adding 2 crash points → +4 det → **59** = 40 det (20 × 2) + 15 rand + 3
fixtures + 1 control. **59/59 on seed 42 AND seed 1337**, plus filtered
single-point runs of both new points green. `after_append:IssueEscalated:2`
correctly "ran clean (point fired <2x)" — only one escalation ever fires.

### 1.3 Coverage boundary — the three checks (the load-bearing finding)

The plan proposed proving the extended harness "still bites" by gutting check 3's
`reset_hard(expected)` and expecting `validate:post-artifact` to go red. It did
**not**. Rather than document around that, three checks established the true
boundary:

**Check 1 — production fidelity (result: the harness worker does NOT model
production's dirty-tree handling).** Production (`loop.py`) does **not**
blanket-reset the worktree the way `tests/crash/worker.py` does at every EXECUTING
entry:
- `_execute` calls `adapter.checkout_branch(create_from=base)`, which **refuses on
  a dirty tree** (`git_adapter.py:166` raises `RepoError`) — it asserts
  cleanliness, it does not force it.
- Production's `reset_hard(base)` calls are all on **reject/escalate paths, after a
  terminal outcome** (`loop.py:243, 257, 275, 301`).
- Production's `_validate` (VALIDATING) does **no** reset of its own. On a
  mid-VALIDATING crash, production re-enters `_validate` and relies **entirely on
  recovery (check 3)** having reset the tree to `end_commit` at startup.

The harness worker, by contrast, uses `reset_hard(base)` at every EXECUTING entry
and self-unlinks its byproduct in the VALIDATING step. So the worker's own resets
mask the reconciler's role.

**Check 1 corollary (VERIFIED, and larger than the new point):** gutting check 3's
`reset_hard(expected)` and running the **full** harness passes **59/59** — including
the pre-existing `f1-stale-lock` and `f2-dirty-boot` fixtures. **Check 3's *reset*
is unproven by the harness, and always has been** (since f1/f2 in Session 2). Two
mechanisms mask it: (a) the worker's blanket `reset_hard(base)` at the next
EXECUTING entry cleans any leftover; (b) check 3's own **archive** step
(`snapshot_commit`) commits the dirty state, leaving the tree clean *at a different
commit* even without the reset, and the object-DB `merge_to` never depends on
worktree HEAD. Check 3's **archive/residue-preservation** IS proven (I-m + Session
5's M1 mutation); only its **reset** is not.

**Check 2 — free evidence (result: none exists).** No run landed
`validate:post-artifact` on 045's second (cap-2) attempt — the only placement with
no *subsequent* worker EXECUTING reset. Deterministic runs exercise only nth=1/nth=2
(by hit-order `042-e1`, `043-e1`; 045-e2 is the 7th VALIDATING entry, never run);
random kills are timed and not point-labeled. And the placement would be masked
anyway (045-e2's own VALIDATING re-entry self-unlinks; its reject path resets).

**Check 3 — targeted mutation for `after_append:IssueEscalated` (result: the
"exactly once" assertion bites).** The DONE-vs-NEEDS_HUMAN mutation earlier proved
the terminal-map assertion bites (it turned the harness red at worker completion),
but did not touch the double-emit path. Confirmed separately: temporarily adding a
tolerant `(NEEDS_HUMAN, IssueEscalated)` transition (so replay survives a duplicate)
and appending a second `IssueEscalated` for 045 to a clean run's log turns
`verify()` red with the exact message *"issue 045 has 2 IssueEscalated events
(want 1)"*, while the honest single-escalation baseline verifies clean. Production's
real idempotency guard is stronger: `(NEEDS_HUMAN, IssueEscalated)` is **absent**
from `ISSUE_TRANSITIONS`, so a real double-emit is a hard `TransitionError` at
replay. Mutation fully reverted (`git diff src/` empty).

### 1.4 Proven coverage — stated honestly
- **`after_append:IssueEscalated`: PROVEN.** The cap-hit escalation fact is
  crash-durable and reconstructs 045 as NEEDS_HUMAN on restart; a kill after the
  fact does not wedge and does not re-escalate (exactly-once, non-vacuously
  asserted). Terminal-map and escalation-count assertions both proven to bite.
- **`validate:post-artifact`: PARTIAL — narrower than originally scoped.** It
  proves the loop+recovery **system survives** a mid-VALIDATING dirty-tree crash and
  reaches correct terminals without wedging. It does **not** independently prove the
  reconciler's check-3 mid-VALIDATING **reset** — the property production actually
  relies on — because the harness worker's blanket resets mask it. This is **not**
  "joint coverage" to celebrate; it is a real harness/production fidelity gap that
  predates Step 1 (it affects f1/f2 identically).

### 1.5 The reset-proof gap — named deferral + proposed close
Check 3's reset (the reconciler returning the worktree to the log's pinned
expectation) is a **load-bearing recovery property production depends on**, yet is
unproven by the harness. Recommendation (same standard as the original two crash
points — an explicit, named deferral, not a silent drop):

> **Deferred item R1 — prove check-3 reset via a planted fixture `f5`.** Model it
> on `f4`'s direct-`recover()` pattern (no worker loop, so no masking): plant a log
> with one execution left in VALIDATING (`ExecutionFinished` with `end_commit`, no
> Validation event) and an attempt ref at `end_commit`; check out the work branch at
> `end_commit`; dirty the worktree with an untracked file; call `recover(...)` with
> `bind_reconciler`; assert the worktree is **clean at `end_commit`** afterward and
> the residue was archived to a reconciler ref. This directly exercises
> `_expected_commit`'s VALIDATING branch + check 3's `reset_hard`, and a gutted
> reset would then turn `f5` red. Small (~30 lines), faithful, stays within
> `harness.py`. Proposed for the next harness pass; **not** bundled into the Step-1
> commit, which is scoped to exactly the two deferred crash points.

Rationale for deferring rather than closing in this commit: (a) it is a
**pre-existing** gap, not introduced by Step 1 — bundling its fix would misrepresent
what Step 1 is; (b) the user's instruction scoped today's commit to the two
crash-point files and explicitly sanctioned a named deferral with rationale; (c)
the fix is fully specified above, so the deferral is concrete, not vague.

### 1.6 Verify commands (updated)
- Unit: `python -m pytest tests\unit -q` — expect **103**.
- Durability gate: `python tests\crash\harness.py %TEMP%\ch` — expect **59**
  (seed 42; `... %TEMP%\ch 1337` also 59; `... %TEMP%\ch 42 <point>` filters).

---

## Steps 2–5 — NOT STARTED

Preflight (2), gated live smoke (3), supervised StockAgent runs (4), wrap (5) are
the resume point. Preflight opens with **2a billing re-verification**
(`billing.reverify_at: phase-2-gate`, last verified 2026-07-10) and **2b engine
version pin + fence re-probe** (`claude --version`; ADR-21 is pinned to 2.1.207).
See the plan for the full ordered contract, user-gated items, and the model split.
