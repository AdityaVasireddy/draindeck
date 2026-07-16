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

Post-R1 (§1.5): adding fixture f5 → **60** = 40 det + 15 rand + 4 fixtures
(f1/f2/f4/f5) + 1 control. **60/60 on seed 42 AND seed 1337.**

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

### 1.5 The reset-proof gap — CLOSED (VERIFIED 2026-07-15) via fixture `f5`

Before scheduling the fix, a cheap trace (no new fixture) answered the
prerequisite question: when `checkout_branch(create_from=base)` refuses on a
dirty tree in production, what happens end to end? **Traced result: it is a
safe wedge, not a corruption risk.** `is_dirty()` (`git_adapter.py:108-110`,
a pure `git status --porcelain` query) is checked before either mutating
`checkout` call, and the raise fires strictly before any ref/index mutation
(`git_adapter.py:165-174`). `RepoError` is never caught in `loop.py` or
`main.py` — it propagates uncaught, the process crashes before any event is
emitted, so the log never diverges from the world. Recovery always runs
before the orchestrator loop starts (`main.py` step 7 vs step 10), so this
raise cannot race the reconciler's own dirty-tree handling within one
process lifetime. Worst case: a live-tree wedge needing a restart or manual
`git status`/cleanup — never silent corruption, never a wrong-branch
operation. This confirmed the gap was real but non-urgent from a corruption
standpoint; it was closed anyway, on the same "before Step 2 preflight"
sequencing logic that put Step 1 ahead of Step 2.

**Fixture `f5-reset`** (`tests/crash/harness.py::run_reset_fixture`) closes
R1 as specified: modeled on `f4`'s direct-`recover()` pattern (no worker
loop, so structurally no masking reset can run — the worker process never
exists in this fixture, not merely "doesn't fire this time"). It plants a
log with one execution left in VALIDATING (`ExecutionFinished` with
`end_commit`, no `Validation*` event) and an attempt ref at `end_commit`,
checks out `work` at `end_commit`, dirties the tree with an untracked file,
calls `recover(...)` via `bind_reconciler`, and asserts the worktree is
clean **at `end_commit`** afterward with the residue archived to a distinct
reconciler ref.

**Isolated mutation spot-check (VERIFIED):** gutting `reset_hard` inside
`check_dirty_workspace` (`bindings.py:102`) and running **f5 alone** (a
temporary direct-call entry point, not the full harness) turned it red —
specifically on the fixture's own `current_commit() == end_commit` assertion
(`AssertionError: f5: worktree at 620586e4fd33, not pinned end_commit
e6322d368b7f`). Notably, f5's `is_dirty()` assertion still passed under the
mutation — check 3's own `snapshot_commit` archive step leaves the tree
clean at the *residue* commit even with `reset_hard` gutted, exactly the
masking mechanism §1.3 describes. f5 catches the gap specifically because it
pins the *commit identity*, not just cleanliness. Mutation reverted; `git
diff src/` confirmed empty before committing the fixture.

**Scope of what f5 proves — read narrowly.** f5 proves reconciler-path
healing of the VALIDATING dirty-tree state **in isolation from the worker
loop**: given a log frozen at VALIDATING with a dirty tree, `recover()`
restores the pinned commit and archives the residue. It does **not** prove
anything about a live process mid-abort — the running loop plus OS signal
handling is a different code path that f5 never exercises (f5 calls
`recover()` directly; no loop, no subprocess, no signal ever involved). Do
**not** read this as "the VALIDATING abort path is covered" or as "joint
coverage" with `validate:post-artifact` — that language is exactly what §1.4
already ruled out for the two original crash points, and the same discipline
applies here.

**Still open:** does a live Ctrl+C during VALIDATING only ever produce log/
tree states within f5's coverage — i.e. does the loop, wherever an external
kill actually lands mid-`_validate`, always leave behind a state
`_expected_commit`'s VALIDATING branch can heal the same way f5's planted
log does? Or can a live kill produce some intermediate state (e.g. mid-git-
operation) that f5's synthetic log doesn't model? This is unresolved and is
the natural follow-up when Step 4's abort-protocol claim ("worst-case kill
is exactly what the harness proves") is next revisited — it should not be
assumed answered by f5.

### 1.6 Verify commands (updated)
- Unit: `python -m pytest tests\unit -q` — expect **103**.
- Durability gate: `python tests\crash\harness.py %TEMP%\ch` — expect **60**
  (seed 42; `... %TEMP%\ch 1337` also 60; `... %TEMP%\ch 42 <point>` filters).

---

## Step 2 — Preflight: 2a billing re-verify + 2b fence re-probe — COMPLETE (VERIFIED 2026-07-16)

Plan: `~/.claude/plans/floating-napping-pelican.md` (user-gated twice: six
external-review amendments before execution, four more before C2–C4). Probe
budget: 4 planned live runs used, 0 re-runs (ceiling was 7). Proxy costs:
C1 $0.4026, C2 $0.2218, C3 $0.1973, C4 $0.3637. Probe workspaces p1–p4
verified EMPTY immediately before each spawn; the six `_SUBSCRIPTION_STRIP`
vars confirmed unset in the same shell instance as every spawn.

### 2.1 — 2a billing / execution-provider re-verification (ADR-18)

| Claim | Status | Evidence (this session) |
|---|---|---|
| Billing mode: no API-key/gateway routing | **VERIFIED** | All six strip vars unset per-spawn; `apiKeySource:"none"` on ALL FOUR live runs, incl. the production-path C4 (whose in-band `EngineEnvError` check passed) |
| Which pool is billed (Pro subscription) | **INFERRED** | Policy (Help Center) + `apiKeySource:"none"`. No probe on this machine can observe the billing ledger directly |
| Headless split status | **VERIFIED (policy level)** | Help Center art. 15036540 fetched 2026-07-16, same June 15 banner verbatim: "nothing has changed: Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription's usage limits"; the monthly credit "isn't available." `headless_split_status: paused` stands |
| Auth token readability | **VERIFIED** | `~/.claude/.credentials.json` exists (504 B, `rw-r--r--`) and a field-filtered read SUCCEEDED (user-authorized; first attempt was blocked by this session's own permission classifier — a session-layer control, not an OS one, so it does not weaken the doc 12 residual: a spawned engine child has no such classifier on plain `cat`) |
| Session lifetime | **VERIFIED as timestamp; refresh INFERRED** | `claudeAiOauth.expiresAt = 1784232058801` → 2026-07-16T20:00:58Z (short-lived access token). That the CLI refreshes it transparently is inferred from continued operation, never observed |
| doc 02 §3 "no credential access" | **Confirmed unchanged (A4)** | ADR-21 accepted-deviation text (doc 08 §5b) and doc 12's Session-5 correction note both intact; not re-litigated |
| ADR-09 proxy-cost feed | **VERIFIED** | `total_cost_usd`, `usage{input,output}_tokens`, `num_turns` all present and parsed on 2.1.211 (C4 via production `_parse_result`) |

`config.yaml → billing.verified_on` moved to `'2026-07-16'`.

### 2.2 — 2b engine version + fence re-probe (ADR-21)

**Version: `claude` 2.1.211 — OFF the 2.1.207 pin.** All findings below are
re-derived by observation at 2.1.211; nothing carried forward.

- **C1 (hand-built argv mirror, full `_DENY_TOOLS`): PASS, exact match with
  ADR-21.** All three exact command strings present as `tool_use` blocks (no
  vacuity). Allowed `echo` ran (`is_error:false`, marker file created) →
  selective. `git init` denied (`is_error:true` + listed in
  `permission_denials`; no `.git`). Chain `echo start > chain-marker.txt &&
  git init` denied whole (`is_error:true` + in `permission_denials`; NEITHER
  artifact created) → **chaining resistance holds; the pre-named row-3 mixed
  outcome (chain-marker present, `.git` absent) did NOT occur.** Pattern-deny
  detection signals unchanged: BOTH `permission_denials` AND `tool_result
  is_error`.
- **C2 (`--allowedTools Read`, no denies): ADR-21 finding HOLDS at 2.1.211 —
  `--allowedTools` still does not restrict.** Transcript-primary
  classification: `tool_use` with the exact absolute-path echo present, no
  denial signal, `permission_denials:[]`, file created.
- **C3 (whole-tool removal, `--disallowedTools WebFetch`): enforcement holds;
  DETECTION SIGNAL CHANGED.** At 2.1.211 a whole-tool deny removes the tool
  from the session's init `tools` manifest entirely — the model never
  attempts it (num_turns 1, "unavailable", `permission_denials:[]`, no
  tool_result at all). The 2.1.207 signal (tool_result `is_error` with empty
  denials) is moot when nothing is attempted. Controlled cross-check: C1's
  manifest (denying Task/WebFetch/WebSearch) lacked exactly those three;
  C3's (denying WebFetch only) retained Task and WebSearch. **Transcript
  auditing note: for whole-tool denies, key on manifest ABSENCE in the init
  line, not on error signals.** Enforcement is structurally stronger, not
  weaker; per the plan's pre-commitment C3's load-bearing claim was "no
  execution," which held.
- **C4 (production `ClaudeHeadlessEngine.run()`, deny exercised on the
  production path): PASS on all pre-committed criteria.** `c4-marker.txt`
  created, `.git` ABSENT, exact `git init` `tool_use` present with
  `is_error:true` + `permission_denials` entry — deny enforced through the
  production code path, not just the hand-built mirror. `_parse_result`
  green on 2.1.211 (usage/dollars/num_turns non-None); no `EngineEnvError`.
- **Spawned argv:** the recorder wrapping `subprocess.Popen` was overwritten
  by a later internal `subprocess.run` (tasklist pid-image check — run() uses
  Popen internally), so the literal spawn-site argv is
  **INFERRED-from-code-reading** per the pre-committed fallback. Supplements:
  (a) zero-cost in-process capture of the same `_command()` builder run()
  passes to Popen — full 23-entry deny list, `claude.CMD` resolved path,
  documented flag order; (b) the behavioral witness above (production child
  denied `git init`) proves the fence flags reached the child regardless.
- **Flag surface at 2.1.211:** `--max-turns` still ABSENT (grep count 0) —
  **Steps 3–4 continue with no hard turn budget; post-hoc proxy cost per
  ADR-19 only** (wall-clock timeout remains the hard backstop). New flags
  observed: `--tools`, `--agents`, `--bg` — **observation only**; adopting
  any of them (e.g. `--tools` as a stronger fence) is ADR territory and
  would put an unprobed mechanism under a load-bearing invariant.
- **Decision matrix outcome: row 2 WITH A CAVEAT.** Deny enforcement,
  selectivity, chaining resistance, and `--allowedTools` non-restriction are
  IDENTICAL → comment-only re-pin in `claude_headless.py` docstrings (2.1.211,
  2026-07-16) + this record. BUT the whole-tool-removal detection mechanism
  CHANGED (manifest drop; §2.2 C3) → **ADR-21 amendment note QUEUED (decision
  for Adi)**, not resolved this session. Gate for the comment-only re-pin per
  the pre-committed src/ rule: 103-unit suite + diff review confirming zero
  non-comment lines changed.

### 2.3 — NEW FINDING: ambient user config writes into engine-child cwd (Step-3 BLOCKER)

Unrequested `knowledge/` trees (`.gitignore`, `.sweep/sweep.log`,
`capture-rules.md` — the operator's engineering-historian hook/skill vault
bootstrap) appeared in probe cwds: **p1 YES (C1), p2 no (C2), p3 YES (C3),
p4 YES — the PRODUCTION `run()` path (C4)**. The writes never appear as
`tool_use` blocks in any transcript (the hook runs outside the model's tool
stream), so the pre-committed amendment-4 noise guard was not needed — and
transcript auditing cannot see these writes at all.

Consequences, recorded verbatim:
- Every production engine run against a real repo would dirty the target
  tree → `is_dirty()` / reconciler check 3 trips on every run → the Step-3
  smoke becomes a guaranteed false failure at best, and at worst masks real
  dirty-tree signals behind expected noise. **An ADR-level decision
  (sanitized settings / hook suppression / other) is required BEFORE any
  engine run touches a real repo.** No fix was attempted this session.
- Scope caveat on 2.2: all fence results are "CLI 2.1.211 **plus this
  machine's ambient user config**," not bare CLI. This does not weaken the
  fence claims (denied patterns were denied regardless), but it is the
  honest scope.
- Retroactively explains the modified `knowledge/.sweep/sweep.log` in this
  repo's own git status (ambient sweep activity, not runtime work).

---

## Steps 3–5 — NOT STARTED

Gated live smoke (3) is **BLOCKED on the §2.3 ADR decision** in addition to
its own preconditions. Supervised StockAgent runs (4) and wrap (5) follow.
