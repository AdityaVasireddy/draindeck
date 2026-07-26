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
  **UPDATE (2026-07-16, Session 7): amendment LANDED as ADR-21 Amendment 1 in
  doc 08 §5b (whole-tool-deny detects by init-manifest absence; carries a queued
  prerequisite that structured init-manifest capture must exist before Step-4
  ADR-19 metric work). Re-confirmed live via §2.4 Probe 3. `claude_headless.py`
  comment pointers updated (comment-only diff, 103-unit suite green).**

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

**CORRECTION NOTE (2026-07-16, Session 7 — doc 12 pattern, not a silent edit).**
The "**p2 no (C2)**" observation above is FALSIFIED as a state-of-the-world
claim. Re-inspection this session found `p2/knowledge/` DOES exist on disk
(`.gitignore` 8 B, `capture-rules.md` 684 B, `.sweep/sweep.log` with a single
`[SessionEnd]` line, session `afc8223a-8762-43f2-881d-78bfd0e20d65`, written
2026-07-16 09:43:40). **Contamination is therefore 4/4, not 3/4** —
`--allowedTools`-only (C2) does not avoid it. INFERRED: the Step-2 check raced
the `"async": true` SessionEnd hook — the write landed after the check ran, so
the probe saw a momentarily-clean cwd. NOT-OBSERVABLE: the exact
check-vs-write interleaving (no timestamp was captured for the Step-2 check
itself).

**Discriminating check (2026-07-16, Session 7 close-out — VERIFIED).** p2's own
engine-child session ID was recovered from its archived transcript
(`step2/c2-transcript.jsonl`, the C2 `--allowedTools` probe, `cwd` confirmed as
p2) via the init line: `session_id: afc8223a-8762-43f2-881d-78bfd0e20d65`. This
**MATCHES** the SessionEnd hook's recorded ID in
`p2/knowledge/.sweep/sweep.log` exactly. The contamination in p2 was produced
by p2's OWN probe run, not a later/unrelated session — the async-race
explanation is **confirmed as consistent**, not merely inferred by exclusion.

LOAD-BEARING CONSEQUENCE (INFERRED): because the hook is asynchronous
and can outlive the `claude` child, contamination can land AFTER `run()`
returns — after the orchestrator diffs, after check 3, even after a
`reset_hard`/`clean -fd`. Any observe-around or clean-up-after approach
therefore races; only prevention-at-source is deterministic. The mechanism
finding and options are ADR-22 (docs/08); the probe evidence is §2.4 below.

### 2.4 — ADR-22 suppression probe matrix (VERIFIED live, claude 2.1.211, 2026-07-16, Session 7)

All probes: fresh scratchpad dirs (never a real repo), trivial "reply OK, no
tools" prompt on stdin, subscription auth (`ANTHROPIC_API_KEY` unset), engine
argv mirror of `_command()` (model=default ⇒ no `--model`), full 23-entry
`_DENY_TOOLS`. Baseline for comparison: `apiKeySource:"none"` (doc 14 §2.1, all
four Step-2 runs). Ceiling 5 probes + 1 re-run; **5 run, 0 re-runs, 0 deviations.**

**Probe 0 — positive control (NO suppression), vacuity guard.** `rc=0`,
`apiKeySource=none`, `num_turns=1`, `total_cost_usd≈0.148`. Polled cwd from
spawn: **`knowledge/` appeared at t=4 s** (`.gitignore` 8 B, `capture-rules.md`
684 B, `.sweep/sweep.log` with one `SKIP no transcript` line, empty project
dir) — identical shape to the Step-2 probe cwds. Contamination is reproducible
and near-instant (the `"async"` hook writes at/around process exit). **VACUITY
GUARD PASSED** (the matrix can detect the failure mode). **WAIT derived =
max(450, 3×4) = 450 s** — every negative probe below polled the full 450 s.

**Probe 1 — `--setting-sources project,local`.** `rc=0`, **`apiKeySource=none`
(MATCHES baseline)**, `num_turns=1`, success. **CLEAN — no `knowledge/` after
450 s.** VERIFIED: omitting `user` from the sources suppresses the user-scope
SessionEnd hook without disturbing subscription auth.

**Probe 2 — `--setting-sources ""` (empty).** `rc=0` (**ACCEPTED**, not
rejected), **`apiKeySource=none` (MATCHES baseline)**, `num_turns=1`, success.
**CLEAN — no `knowledge/` after 450 s.** VERIFIED. **PREFERENCE ORDERING (for
ADR-22):** empty is PREFERRED over `project,local` — `project,local` still loads
project/local settings *from the child cwd, which on the production path is the
target repo*, so a `.claude/settings.json` written into a target repo would be a
cross-run persistence/config-injection vector; empty loads none. If
`project,local` is ever adopted instead, that residual project-scope surface is
the explicit open limitation.

**Probe 3 — fence sanity under the surviving A-form (`--setting-sources "").**
Prompt instructed a Bash `git init` (denied by `Bash(git:*)`). `rc=0`,
`apiKeySource=none`. The `git init` `tool_use` WAS attempted (not
self-censored); it was denied with **BOTH 2.1.211 pattern-deny signals**: a
`permission_denials` entry (`tool_name:"Bash"`, `command:"git init"`) AND a
`tool_result is_error:true` ("Permission to use Bash with command git init has
been denied."). **`.git` ABSENT.** VERIFIED: the explicit-argv denylist fence
(ADR-21) is unaffected by `--setting-sources ""` — expected, since the fence is
passed as explicit flags, not via settings.

**Probe 4 — `HISTORIAN_SWEEP_ACTIVE=1` in child env (Option B).** `rc=0`,
`apiKeySource=none`, `num_turns=1`, success. **CLEAN — no `knowledge/` after
450 s.** VERIFIED: the sweep script's own recursion guard (`historian-sweep.sh`
line 51) exits before any write when the var is set, and the var reaches the
hook process through the child env.

**Matrix outcome.** Control contaminates (4 s); all three suppression forms
(A/`project,local`, A/empty, B/env-var) are clean at 450 s with auth unchanged;
the fence survives the empty A-form. No deviation, nothing adopted this session
(mechanism selection is ADR-22, still Proposed).

---

### 2.5 — ADR-22 mechanism landed (Session 8, 2026-07-16/17; see per-claim labels below — not a blanket VERIFIED)

ADR-22 marked Accepted (doc 08 §5c): **A-empty + B, B under a sunset
condition.** Mechanism landed in `src/` and `config.yaml`, no re-probe needed
this session (the §2.4 probes above already cover both live candidates; this
session is a straight code-landing of the already-verified mechanism).

**Code changes.**
- `src/runtime/engine/claude_headless.py::_command()` — appends
  `"--setting-sources", ""` to the engine argv, before the variadic
  `--disallowedTools` fence, with a comment citing ADR-22.
- `src/runtime/config.py::EngineCfg` — new field `child_env: dict[str, str]`
  (default `{}`) — machine-specific var names live in config, never in `src/`.
- `src/runtime/engine/claude_headless.py::_hygienic_env()` — merges
  `cfg.child_env` into the child env immediately after the base `os.environ`
  copy and **before** the ADR-18 subscription strip, so the strip is applied
  last and always wins (a `child_env` key colliding with a strip-list entry
  ends up stripped, never present).
- `config.yaml` — `engine.child_env: {HISTORIAN_SWEEP_ACTIVE: "1"}`, commented
  as the ADR-22 B layer with its sunset condition.

**Argv empty-token survival to spawn — CORRECTED, jointly labeled.**

An earlier draft of this section claimed "no shell-join anywhere in the path
to `subprocess.Popen`" as the basis for a VERIFIED label. **That mechanism
claim was wrong and has been struck.** `shell=` is indeed never passed to
`Popen` (defaults to `False`, so there is no *cmd.exe shell* interposed), but
on Windows `subprocess.Popen` with a list argv is **not** a direct
`argv[]`-to-`CreateProcess` handoff: Python builds a single command-line
string via `subprocess.list2cmdline()` (MSVCRT quoting rules), and
`CreateProcess` hands that single string to the child, whose own CRT/runtime
re-splits it back into an argv array. There **is** a join in the path; the
question is whether that join-then-resplit round-trips an empty element
faithfully. It does — `list2cmdline` renders a bare empty string as `""`
(two double-quotes, verified live below), which the standard MSVCRT
command-line parser (and Node's, which `claude` runs under) re-splits back to
an empty string. This is evidence *for* survival, but by a different and more
specific mechanism than originally stated, so the label is corrected to match
what was actually shown, split into its two independent legs:

1. **Python-side handoff (production argv → spawned child's real `argv[]`,
   same OS, same Windows `Popen` mechanism as `run()`) — VERIFIED, live,
   this session.** `ClaudeHeadlessEngine._command()` was called for real (not
   re-implemented or mocked) via a bare-init instance; its unmodified return
   value (everything after `argv[0]`) was spawned through a real
   `subprocess.run()` on this Windows machine, with a Python dummy child
   printing its own received `sys.argv`. The child's stdout: the
   `--setting-sources`/`''` pair arrived as two adjacent elements, the second
   an empty string, at the same position `_command()` puts it, ahead of
   `--disallowedTools`. `subprocess.list2cmdline()` was also inspected
   directly on the real argv tail and confirmed to render the empty token as
   `""` rather than dropping it. This closes the Python→OS→child-process leg
   of the path end-to-end, not just `_command()`'s return value.
2. **CLI-side interpretation (does `claude`'s own arg parser treat `""` as
   "load no settings scopes," and does auth/fence stay intact) — VERIFIED,
   doc 14 §2.4 Probe 2/3, live at `claude` 2.1.211, 2026-07-16.** That probe
   spawned a real `claude -p` process with a hand-built argv mirroring
   `_command()`'s shape (not `_command()` itself, since it predates this
   session's code change) and observed `rc=0` (accepted, not rejected), clean
   at 450 s, `apiKeySource` unchanged, and the fence intact (Probe 3).

Composing 1 + 2 covers the full path (`_command()` → `Popen` → OS
join/resplit → real `claude` process → observed behavior) but **not as a
single end-to-end run this session** — leg 1 used a Python dummy child, leg 2
used a hand-built argv rather than a live call through `_command()`. A single
live spawn of `ClaudeHeadlessEngine.run()` against the real `claude` binary,
with the child-side argv or settings-scope behavior directly observed, would
close this to one unqualified VERIFIED; that live run is queued below as a
Step-3-preflight item (mirroring the existing Session-6 preflight discipline)
rather than done ad hoc in this session.

**Tests added (3 new, `tests/unit/test_engine_adr22.py`):**
1. `test_command_carries_setting_sources_empty` — asserts on `_command()`'s
   **return value only** (`argv = eng._command(...)`, then
   `argv[i+1] == ""`, `argv[i+1:i+2] == [""]`, position before
   `--disallowedTools`). This is list-construction-level: **VERIFIED** that
   `_command()` builds the pair correctly; it does not itself touch `Popen`
   (the live spawn check above supplies that leg separately).
2. `test_child_env_merged_into_child_environment` — a `engine.child_env` entry
   appears in `_hygienic_env()`'s built environment.
3. `test_child_env_cannot_override_strip_list` — asserts on the **final env
   dict returned by `_hygienic_env()`**, not on call order: places
   `ANTHROPIC_API_KEY` (a strip-list entry) into `child_env`, then asserts
   `"ANTHROPIC_API_KEY" not in env` on the returned dict, alongside a
   non-colliding sibling key (`HISTORIAN_SWEEP_ACTIVE`) asserted present. This
   is a result-shape assertion, not a structural/order assertion — it would
   catch a future reordering that broke supremacy, not just document today's
   order. **VERIFIED.**

**Unit suite — VERIFIED.** `./.venv/Scripts/python.exe -m pytest tests/unit -q`
→ **106 passed**, 0 failed, `.venv` python, Windows, 2026-07-16/17.
`--collect-only` on the full suite: 106 items. `--collect-only -v` on the new
file alone lists exactly the 3 named tests above (`test_engine_adr22.py`,
collected 3 items) — the count is corroborated by identity, not arithmetic
alone (106 = 103 prior + these named 3, not some other combination).

**Durability gate — VERIFIED, 60/60 BOTH SEEDS, environmental deviation
recorded.**

*Environmental note (belongs here per doc 12 pattern — deviations are
recorded, not silently worked around).* The standard invocation target
`%TEMP%\ch` (and a first alternate, `%TEMP%\ch2`) held stale
Windows-read-only git-object files left over from an unrelated scratch run
dated 2026-07-11/13 (predates this session). `shutil.rmtree` inside
`fresh_scenario()`'s calibration-repo reset failed with `PermissionError:
[WinError 5] Access is denied` on those files before either seed's run could
start — this happened on the **first attempt** at `%TEMP%\ch` (seed 42) and
again on a first attempt at a second path `%TEMP%\ch3` (seed 1337, which
turned out to also hold pre-existing stale scratch from 2026-07-11). Neither
failure was mid-harness — both were the harness's own pre-flight
`_calibration` reset, before any scenario ran, so **no scenario run was
partially completed or discarded**; nothing from a failed attempt was folded
into the reported 60/60. Read-only attributes were cleared
(`os.chmod(path, stat.S_IWRITE)` walked over the stale tree) on that
pre-existing, outside-the-repo, disposable scratch data — not user work, not
part of this session's product — after which each seed ran clean to
completion on its first full attempt post-clear.

Invocations (both post-clear, first full attempt, verbatim commands and
result lines):
```
$ ./.venv/Scripts/python.exe tests/crash/harness.py "$TEMP/ch2" 42
...
ALL 60 SCENARIOS PASSED

$ ./.venv/Scripts/python.exe tests/crash/harness.py "$TEMP/ch3" 1337
...
ALL 60 SCENARIOS PASSED
```
- seed 42, `%TEMP%\ch2` → **ALL 60 SCENARIOS PASSED** (40 det + 15 rand + 4
  fixtures f1/f2/f4/f5 + 1 control — same 60-scenario shape as Session-6 R1).
- seed 1337, `%TEMP%\ch3` → **ALL 60 SCENARIOS PASSED**, same shape.

This gate applies because `src/` logic changed this session (unlike Session
7's comment-only diff, which explicitly did not require it).

**Step 3 unblock status.** ADR-22 Accepted + mechanism landed + probe-verified
(via §2.4, re-used) + this session's pytest/harness gates green ⇒ the
Step-3-blocking condition from NEXT.md item 1 is satisfied. Step 3 itself is
**UNBLOCKED but NOT started this session** — its own separate preconditions
(real validation command, Ollama + qwen2.5-coder, authored Issues.md, green
baseline, `.gitignore` hygiene) are unrelated to ADR-22 and remain unconfirmed;
see NEXT.md.

---

### 2.6 — Session 9 (2026-07-17): Step-3 preflight — CLI re-pin re-probe (2.1.212) + full precondition sweep

**Scope discipline for this session:** live re-probe of ADR-18/21/22 against
the now-installed CLI version, re-check of Step 3's five own preconditions,
and a DESIGN (not run) of the item-0 argv-survival gate. No `src/` change.
No commit (standing rule). No live smoke.

**CLI version witnessed: `claude 2.1.212`** (`claude --version`) — off the
2.1.211 pin used in §2.2/§2.4/§2.5. This IS a version bump, so the doc 08 §5c
binding upgrade re-pin discipline applies before any engine run against a
real repo.

#### ADR-18 re-verify (billing/provider)
All six `_SUBSCRIPTION_STRIP` vars (`ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`,
`CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX`) — **VERIFIED unset** in
this shell (`printenv` on each, checked immediately before probing). Both
live probes below returned `apiKeySource:"none"`, matching the subscription
baseline. **VERIFIED**, unchanged from §2.1.

#### ADR-22 binding re-pin discipline — two live probes, fresh scratchpad dirs (never a real repo)

Methodology mirrors §2.4 (trivial prompt or a targeted fence-trip prompt,
subscription auth, engine argv mirroring `_command()`), executed via
hand-built Python `subprocess.Popen` scripts (same class of evidence as §2.4
— NOT yet a call through the real `ClaudeHeadlessEngine.run()`; that
composition is item 0, designed but not run this session — see below).

**Probe A — control (no `--setting-sources`, i.e. the pre-ADR-22 argv
shape), vacuity-guard intent.** `rc=0`, `apiKeySource:"none"`, 5.2 s.
Workspace polled at t≈30s and again at t≈90s post-completion: **no
`knowledge/` directory appeared** — contrary to §2.4 Probe 0, which showed
contamination at t=4s under the same "no suppression" condition at 2.1.211.

**Finding — the vacuity guard no longer fires.** `~/.claude/historian/skips.log`
recorded a `SKIP no transcript` line for Probe A's cwd, timestamped at the
probe's spawn, with a correctly-populated project path and session id — so
the SessionEnd hook DID fire (ambient user-scope settings loaded normally, as
expected with no suppression), DID successfully parse its hook-JSON input via
`jq`, and DID run `run_pipeline()` through to its `return 2` at line 303. But
no `knowledge/` write preceded that skip, at t≈30s, t≈90s, and re-checked
again ~3 hours later (all clean). Reading
`~/.claude/historian/historian-sweep.sh:293-304` (the operator's own tool,
outside this repo) as it exists NOW shows the transcript-existence gate
returning *before* any `$VAULT`-directory write; the code comment at line 296
reads "a headless `-p` child SKIPs in a cwd it doesn't own; **the vault used
to get created anyway**" (past tense, in the *current* source).

**Label correction (this session, in response to review): downgraded from
VERIFIED to INFERRED.** The original phrasing ("independently patched
upstream, applied between Session 8 and this session") asserted a *causal,
temporal* claim — that the code at 293-304 differs from what ran during
Session 7/8's probes. That claim was not backed by a before/after comparison:
doc 08 §5c's and doc 14 §2.3/§2.4's records of the *original* vulnerable
behavior are prose descriptions of observed effects ("the mkdir/seed writes
happen before its own triviality gate," contamination witnessed live at t=4s
across p1-p4/Probe-0) — **no line-anchored quote, diff, or snapshot of
`historian-sweep.sh`'s Session-7/8-era source exists anywhere in this repo's
records to set against the current read of 293-304.** `~/.claude/historian`
is not itself a git repository (`git status` there: "fatal: not a git
repository") — no independent version history is available either. The
line-296 comment is suggestive (self-referential textual evidence, from the
tool's own author, that its behavior changed at some point) but is not an
independently corroborated record of *when* relative to Session 7/8, so it
cannot carry a VERIFIED label on its own.

**What IS verified, kept separate from the causal inference:**
1. Contamination occurred under matching "no suppression" conditions in
   Session 7/8 (doc 14 §2.3/§2.4, established then, not re-litigated here).
2. Contamination does **not** occur now, under this session's Probe A, run
   under the same class of live-spawn conditions (fresh scratch cwd, no
   real repo, no `--setting-sources`, no `child_env`, ambient settings
   loading normally) — re-checked clean at three separate poll times.
3. The hook executed to completion this session (behavioral, via the
   well-formed `skips.log` entry — not just "current source reading"), and
   the current source text structurally places the transcript check ahead of
   any write.

**What is INFERRED, not VERIFIED:** that (1)+(2) is explained by an upstream
code change to `historian-sweep.sh` made *between* Session 8 and this
session, rather than some other cause. Recorded as INFERRED in both this doc
and NEXT.md.

**Cause 3 (local confound in THIS repo's probe env, not upstream) — actively
ruled out, not just assumed away:**
- `HISTORIAN_SWEEP_ACTIVE` (the ADR-22 B-layer var) — confirmed **unset** in
  the shell that launched Probe A, and Probe A's env-construction only
  stripped the six `_SUBSCRIPTION_STRIP` vars, so it could not have been
  silently inherited and suppressed the hook via the B mechanism.
- `jq` availability — the sweep script fails closed silently
  (`command -v jq >/dev/null 2>&1 || exit 0`, line 699) if `jq` is missing,
  which would produce a clean-but-uninformative result for a reason having
  nothing to do with any upstream fix. **Ruled out**: `jq 1.8.2` is on PATH
  (`jq --version` succeeds), and — more directly — Probe A's `skips.log`
  entry has a real project path and a real session id, which are only
  populate-able if `jq` successfully parsed the hook JSON. A silent
  jq-missing exit would happen at line 699, before `CWD`/`SESSION_ID` are
  even parsed, and would produce no `skips.log` line at all (the `glog`
  helper isn't defined that early) — so the well-formed log line is itself
  evidence against this cause.
- No disable/pause flag files found under `~/.claude/historian/` (checked by
  listing for `*.disable*`/`*.pause*`).
- No other early-exit gate exists between hook entry and line 302 besides
  the `jq`-missing check above (read lines 691-706 directly).
- Hook registration in `~/.claude/settings.json` is unchanged from what this
  session already confirmed earlier (SessionEnd/PreCompact →
  `historian-sweep.sh`, `async: true`) — the hook is still wired up, it just
  doesn't write before its gate anymore.

Residual, un-ruled-out possibility (cause 2: some other divergence between
this session's probe conditions and Session 7/8's — e.g. an undocumented
difference in how the original `floating-napping-pelican.md` probe harness
invoked `claude` versus this session's hand-built `subprocess.Popen` script).
Not demonstrated, not ruled out either — flagged as residual uncertainty
rather than silently assumed clean.

**Consequence for the re-pin discipline:** leg 1 ("a Probe-0-style control
still shows contamination — the vacuity guard proving the probe can detect
the failure mode") **could not be reproduced**, and — per the label
correction above — it is INFERRED rather than VERIFIED that this is because
the failure mode was independently patched at its source rather than some
other cause. This is recorded as an honest gap, not papered over: **the
control-contaminates leg of the binding discipline is NOT currently
re-affirmable, and the reason it isn't is not fully closed either.** ADR-22's
A-empty + B mechanism stays landed regardless of which explanation is true —
Option D was always described as "ambient operator tooling the runtime
cannot depend on" (doc 08 §5c) and could regress on a historian
reinstall/rollback with no signal to this repo. See the new vacuity-guard
NEXT.md item for what happens next.

**Probe B — production argv (`--setting-sources ""` + full 23-entry
`_DENY_TOOLS`, exact mirror of the current `_command()`), fence-trip prompt
("run `git init`").** `rc=0`, `apiKeySource:"none"`, 6.5 s spawn.
`git init` WAS attempted (not self-censored) and denied with **both** 2.1.211+
signals: a `permission_denials` entry (`tool_name:"Bash"`,
`command:"git init"`) and `tool_result is_error:true`
("Permission to use Bash with command git init has been denied."). `.git`
**absent** from the workspace. Workspace polled at the full **WAIT=450s**
per the binding discipline: **clean, no `knowledge/`.** Corroborating
signal: **no entry at all appears in `~/.claude/historian/skips.log`** for
Probe B's cwd (contrast Probe A, which DID log a skip) — with
`--setting-sources ""`, the user-scope hook settings never load in the
child, so the SessionEnd hook never fires, not even to reach its own
transcript gate. This is a stronger, independent confirmation of A-empty's
mechanism than Probe A can now provide.

**Re-pin verdict:** leg 2 (empty `--setting-sources` still accepted `rc=0`,
still clean at 450s, `apiKeySource` unchanged, fence intact) —
**RE-VERIFIED live at 2.1.212.** Leg 1 (control-contaminates vacuity guard) —
**NOT reproducible; root cause INFERRED, not VERIFIED** (see the label
correction above — an external/upstream fix is the best-supported
explanation and the local-confound alternatives were actively ruled out, but
no before/after code comparison exists to confirm the *temporal* claim, so
this stays INFERRED). Net assessment: the mechanism this repo landed
(A-empty) is unaffected by the CLI bump and independently corroborated by
the skips.log absence on Probe B; whether the ambient contamination risk it
was built to fence is *currently* also closed by an unrelated cause is
open — but B (the config-driven belt-and-braces layer) and the sunset-gate
discipline in NEXT.md's standing tickle stay exactly as written regardless,
since Option D was never the thing being sunset-tracked, and the sunset
condition explicitly requires BOTH probe legs green, not one.

#### ADR-21 fence re-verify
Covered by Probe B above: deny enforcement (`permission_denials` +
`tool_result is_error`), selectivity is unchanged from §2.2 (not re-run
standalone this session — the fence-trip prompt targeted one denied pattern,
matching §2.4 Probe 3's scope, not the full C1–C4 matrix). **No regression
observed at 2.1.212.** A full C1–C4 re-run was judged unnecessary: §2.2
already re-derived the full matrix at the 2.1.207→2.1.211 bump, and nothing
in the 2.1.211→2.1.212 diff (a patch-level bump) suggests permission-model
change; the one live fence-trip here is a spot-check, not a claim of full
re-coverage.

#### Item 0 — argv-survival-through-`run()` witness: DESIGNED, NOT RUN

Per explicit session scope, this is a design only.

**Gap being closed.** §2.5 composed two *separate* legs: (1) Python-side —
`_command()`'s real return value spawned through a bare `subprocess.run()`
against a **dummy Python child** (not `claude`); (2) CLI-side — a
**hand-built argv** (not `_command()` itself) spawned against real `claude`.
This session's Probes A/B are the same class of evidence as leg 2 (hand-built
mirror, not a call through the actual `_command()`/`run()` code). No session
yet has called the real, unmodified `ClaudeHeadlessEngine.run()` — which
invokes the real `_command()` AND the real `Popen`/`communicate` path — against
the real `claude` binary in one composed run.

**Witness design:**
1. **Setup.** Real `EngineCfg` (subscription mode, `model: default`,
   `child_env: {HISTORIAN_SWEEP_ACTIVE: "1"}` — i.e. the actual
   `config.yaml` shape, both ADR-22 layers active together as production
   would run them). Real `ClaudeHeadlessEngine(cfg, artifacts_dir=<scratch,
   never the repo>)`. Workspace: a fresh scratch dir, never a real repo
   (matches every probe so far — the live smoke, not this gate, is the first
   time a real target repo is touched).
2. **Argv-construction witness (pre-spawn, structural).** Call
   `engine._command(prompt_file)` directly — the real method, unmodified —
   and assert `"--setting-sources"` is immediately followed by `""` as two
   distinct list elements, at the position before `--disallowedTools`. This
   is the same assertion `test_command_carries_setting_sources_empty`
   already makes (unit-level); repeating it here just pins that the SAME
   engine instance about to be spawned carries the pair, closing any doubt
   that construction and spawn could diverge.
3. **Behavioral witness (the actual gap-closer).** Call `engine.run(execution_id,
   prompt_file, workspace)` — the real method, unmodified, real `claude`
   binary — with a Probe-B-shaped prompt (attempt a denied `Bash` pattern,
   e.g. `git init`).
4. **Post-run assertions**, all against the real `EngineResult` and the real
   workspace, no hand-built parallel path:
   - `EngineResult.exit_status == 0`, no `EngineEnvError` raised (the in-band
     ADR-18 `apiKeySource` check inside `run()` itself passing IS a witness —
     a raise would mean a credential leaked or apiKeySource unexpectedly
     changed).
   - Parse `EngineResult.transcript_path` (the real archived transcript, via
     the real `_parse_result` path if convenient, or the same manual
     line-by-line read used in the probes) for `apiKeySource == "none"`.
   - `permission_denials` entry + `tool_result is_error:true` for the
     attempted denied command; `.git` absent from `workspace`.
   - Poll `workspace` for `knowledge/` absence at WAIT=450s (contamination
     leg) — this is the load-bearing new evidence: composing settings-scope
     suppression WITH the real spawn/wait/kill/pidfile machinery in `run()`
     (pidfile write/unlink, `_hygienic_env()` merge-then-strip order,
     `communicate()` timeout wiring) rather than a bare `Popen` mirror.
   - Optionally cross-check `~/.claude/historian/skips.log` for absence of
     any entry keyed to this run's cwd, as Probe B did — a second, independent
     signal that settings-scope suppression (not just the hook's own gate)
     is what prevented the write.
5. **Gate condition, stated per NEXT.md item 0's original wording:** if this
   composed run mangles the empty token in a way neither isolated leg
   predicted (e.g. `communicate()`'s stdin-pipe timing interacts with
   `list2cmdline` differently than the bare `subprocess.run()` leg-1 check
   did, or the pidfile/`_xdir` bookkeeping around the Popen call somehow
   perturbs argv construction), this is where it would show up as a `git`
   directory or `knowledge/` tree appearing despite the mechanism's prior
   two-leg VERIFIED status. Passing collapses the two-leg composition into
   one unqualified live VERIFIED; failing is a hard block on Step 3 and
   reopens ADR-22.

#### Item 0 — RUN this session (2026-07-17, later same day). Behaviorally
VERIFIED clean; positive control did NOT confirm detectability.

**CLI version witnessed this run:** `2.1.212 (Claude Code)` — captured live
via `shutil.which("claude")` + `--version` at the top of the witness script,
matching the version already re-pinned earlier this session. No drift.

**Pre-flight (design step 0):** `ClaudeHeadlessEngine._parse_result()` does
NOT expose `permission_denials` or `tool_result` — confirmed by reading the
function body (it extracts only `apiKeySource`, `usage`, `num_turns`). The
witness script parses the transcript independently, keying on the `result`
line's `permission_denials` array and `is_error:true` inside `tool_result`
blocks nested in `user`-role messages — the same field names used by every
prior probe (doc 08 §2.4, doc 13, §2.4/§2.5 above). Confirmed present and
correctly shaped in the real transcript; this check is load-bearing (a
missing field would have failed loudly, not silently passed).

**Pass 1 (real, unmodified `engine.run()`, real `claude`, scratch workspace,
`child_env={"HISTORIAN_SWEEP_ACTIVE": "1"}`):**
- Argv-construction witness: `["--setting-sources", ""]` present as two
  distinct elements, before `--disallowedTools`. OK.
- `exit_status=0`, no `EngineEnvError`, `apiKeySource="none"`.
- `git init` attempted (not self-censored), denied with BOTH signals:
  `permission_denials` entry (`tool_name:"Bash"`, `command:"git init"`) and
  `tool_result is_error:true`. `.git` absent from workspace.
- `knowledge/` absent across all 16 polls over the full WAIT=450s window
  (t=0,30,...,450), final check clean.
- **Required independent signal**: zero new lines appended to
  `~/.claude/historian/skips.log`, and no line (new or otherwise) keyed to
  this run's workspace path.
- Spawn-to-result: ~11s.

This closes the specific composition gap §2.5/Item-0-design identified: the
real `_command()` output, the real `Popen`/`communicate`/pidfile/
`_hygienic_env()` path, and real `claude` were exercised together in one
call for the first time, and it came back clean.

**Pass 2 (positive control — mutated argv, `["--setting-sources", ""]` pair
stripped from a copy of the real `_command()` output, spawned directly with
the same `_hygienic_env()`, bypassing only `engine.run()`'s wrapper so the
point — proving the assay can go red — isn't re-testing the real path):**
- `exit_status=0`, `apiKeySource="none"`, `git init` still denied via the
  explicit `--disallowedTools` flags (unaffected by the settings-source
  mutation — the fence and the settings-isolation are independent argv
  elements). `.git` absent.
- `knowledge/` **absent across all 16 polls, full WAIT=450s window** — the
  positive control did NOT reproduce contamination even with the isolation
  mechanism deliberately removed and ambient settings scopes loading.

**This is the load-bearing finding of this session's run.** The positive
control was designed to prove the assay can discriminate "mechanism working"
from "nothing was ever going to contaminate" (Session 6's R1 finding: "probe
matrix lacked a positive control"). It did not confirm that. This is the
SAME non-reproduction pattern as session 9's Probe A, now independently
reproduced under a second, differently-constructed control (direct mutated
spawn vs. Probe A's separate ambient-settings run) — a third data point, not
a coincidence dismissible as one-off noise. Per NEXT.md's already-open
VACUITY-GUARD GAP: a clean result under `--setting-sources ""` remains
ambiguous evidence for whether A-empty is doing anything, versus the ambient
historian hook simply no longer contaminating for reasons still INFERRED,
not VERIFIED (no before/after diff of the hook's source exists).

**Label precision:** every assertion above is BEHAVIORAL (permission denial,
contamination absence, unchanged `apiKeySource`, skips.log absence) — real
`claude` cannot echo its own `sys.argv` the way session 8's dummy Python
child could. "VERIFIED" here means "behaviorally verified via a composed
live run," not a literal argv echo.

**Net status:** the specific gap Item 0 was designed to close — no session
had ever composed the real `_command()`/`run()`/`Popen` path against real
`claude` in one call — IS closed, and the composed run is clean. Item 0's
own stated gate condition, however, also required the positive control to
confirm detectability before collapsing to "one unqualified live VERIFIED";
it did not. **Do not read this session as proof ADR-22 A-empty is working
end-to-end** — read it as "no regression observed, AND the vacuity-guard gap
is now independently reproduced a third time, deepening rather than
resolving the open (a)/(b) decision already parked in NEXT.md." That
decision is intentionally NOT resolved here, per this session's explicit
scope boundary (parked for whoever next touches ADR-22 re-pinning) — this
entry only adds the new evidence.

Witness script: ad hoc, uncommitted, scratchpad-only (matches prior probe
convention) — not checked into `tests/` or `src/`. Full JSON result and
transcripts retained under the scratch `artifacts`/`artifacts_pc` dirs for
this session; workspace dirs (`ws_real`, `ws_positive_control`) were torn
down after the run (teardown step; no unexpected `.git` was created, so the
defensive read-only-clear path was not exercised).

Not executed this session (explicit scope boundary). Queued as the literal
first action before Step 3's live smoke.

#### Step 3's own five preconditions — re-checked LIVE this session (StockPhotoAgent, `C:\Projects\StockPhotoAgent`, branch `agent-work`)

| # | Precondition | Status | Evidence |
|---|---|---|---|
| 1 | `project.validation.commands` real test command | **STILL UNCONFIRMED — genuinely open, needs user input** | `config.yaml` still has the `<REQUIRED>` placeholder. No `pytest.ini`/`pyproject.toml`/`setup.cfg`/`conftest.py`/`Makefile`/`.github/workflows/` found anywhere in the repo (checked directly). `CLAUDE.md` documents many `python -m src....` invocation commands but none are a test runner. This is not a probe gap — there is no discoverable command to confirm; it must come from the user or from authoring one. |
| 2 | Ollama + `qwen2.5-coder` pulled | **UNMET** | `ollama list` shows only `qwen2.5vl:7b` (6.0 GB, pulled ~4 weeks ago). `qwen2.5-coder` (the model `config.yaml → reviewer.qwen.model` names) is **not present**. `ollama ps` shows no loaded models (service idle but reachable). |
| 3 | `Issues.md` in `## <id>: <title>` format | **UNMET, two independent problems** | (a) **Wrong location**: `main.py:131` resolves the issues file as `Path(cfg.project.repository) / cfg.project.issues_file` = repo-root `Issues.md`; the repo has no root-level `Issues.md`, only an untracked `docs/Issues.md`. (b) **Wrong format**: `docs/Issues.md` is a numbered list (`1. **Title:** ...`) with inline `**STATUS: OPEN**` markers — none of it matches `src/runtime/queue/issues_md.py`'s required `## <id>: <title>` heading grammar (`_HEADING`/`_ID_TITLE` regexes). Parsing it as-is would raise `IssuesParseError` at startup (no `## ` headings present at all). |
| 4 | Baseline green on `agent-work` | **BLOCKED on #1, not independently re-verified** | Cannot run a test suite without a known command; running `pytest` bare was not attempted (no config found means an unqualified `pytest` run risks picking up unrelated/broken suites — e.g. the `tests/` dir contains files like `test_401_response_body.py`, `test_csrf_cookie_match.py`, `test_login_only.py` that look auth/network-probe-shaped, not obviously StockAgent unit tests; guessing a command here was judged worse than reporting the gap honestly). `git status` on `agent-work`: clean except the untracked `docs/Issues.md` from #3 — the branch itself is not dirty. |
| 5 | `.gitignore` hygiene | **MET — CONFIRMED** | `.gitignore` covers `input/`, `output/`, `done/`, `failed/`, `review/`, `database/`, `logs/`, `debug_logs/`, `*.log`, `__pycache__/`, `.venv/`/`venv/`/`env/`, plus IDE/OS cruft and a `config.ini` credentials exclusion. Adequate for build/test-byproduct hygiene as the precondition asks. |

Additional directory-name note (doc 08 §6's `⚠ confirm directory name on
disk` caveat): **RESOLVED** — the repo lives at `C:\Projects\StockPhotoAgent`
(matches `config.yaml → project.repository` exactly); the `StockAgent`
naming is cosmetic (`project.name`) only.

**Net: Step 3 remains NOT ready.** Preconditions 1, 2, 3 are hard blockers
(2 and 3 concretely UNMET; 1 has no available answer without user input); 4
cannot be checked until 1 is resolved; 5 is clear. None of these are ADR-22
questions — they are unrelated StockAgent-side setup gaps, consistent with
NEXT.md's existing framing.

---

## Session 11 (2026-07-18) — ADR-22 vacuity-guard: synthetic positive control BUILT and RUN

Session 10 left the ADR-22 family with three independent non-reproductions
of the original contamination control (session 9's Probe A, session 10's
Item-0 Pass 2). No pre-patch artifact of `~/.claude/historian/
historian-sweep.sh` exists anywhere to diff against — confirmed again this
session (`~/.claude/historian` is not a git repo; no backup, no archived
transcript of the pre-patch behavior survives). NEXT.md's parked "Option
(a)" blueprint (a synthetic, self-owned hook, never the real historian) was
built and run this session, resolving the "no position taken" state.

**Design, deliberately distinct from the real historian:** `synth-hook-
marker.sh` — zero internal gates (`mkdir -p .synth-marker && write
fired.txt`, unconditional, exit 0) — vs. the real hook's four early-return
checks (no-transcript, triviality, dedup, lock). Registered via a scratch
**project-scope** `.claude/settings.json` (`SessionEnd` + `PreCompact`,
`type: command`, absolute path to the script, `async: false` — deliberately
NOT matching the real hook's `async: true`, to remove async-scheduling
uncertainty while validating the assay itself — `timeout: 30`). Two
separate, freshly-built probe cwds (`probe_cwd_trigger`, `probe_cwd_empty`)
so a leftover marker from one step could never be misread as the other's.

**Step B — prove the assay can go red (required first, own pass/fail).**
Real `EngineCfg`/`ClaudeHeadlessEngine`, `engine._command(prompt_file)`
called for its real production argv, then a **copy** mutated
(`--setting-sources ""` → `--setting-sources project`), spawned against
`probe_cwd_trigger` with a trivial "Reply OK. Do not use any tools." stdin
prompt (subscription auth, model default). **PASS**: marker present at the
very first poll tick (t=0s — essentially immediate under `async: false`);
`marker_contents = {event: "SessionEnd", pid: "229655", cwd: ".../
probe_cwd_trigger"}`; `pid` mechanically confirmed distinct from the
witness script's own pid (`22956`, via `os.getpid()` at record time); `cwd`
field in the marker matches the expected probe dir exactly (rules out a
wrong-cwd write). `exit_status=0`, `apiKeySource="none"`.

**Step C — the real A-empty comparison (only run after Step B passed).**
`engine._command(prompt_file)` called **unmutated** — real production argv,
`--setting-sources ""` — spawned against a fresh `probe_cwd_empty`. **PASS**:
marker absent at all 16 poll ticks across the full `WAIT=450s` window
(t=0,30,...,450); `exit_status=0`, `apiKeySource` unchanged. A scan for
`.synth-marker/fired.txt` anywhere under the scratch root (not just the
expected path — guards against a wrong-cwd false negative) found only Step
B's own leftover marker in `probe_cwd_trigger`, confirming `probe_cwd_empty`
genuinely never produced one.

**Net finding, both halves stated (do not read as one collapsing into the
other):**
1. A-empty suppresses this synthetic, zero-gate, project-scope hook —
   VERIFIED, mechanically, via file-existence checks and a pid-distinctness
   check, not engine/reviewer self-report. This control is now owned by
   this project and can be re-armed on demand for any future CLI re-pin,
   independent of whatever state the real ambient historian hook happens to
   be in on a given machine.
2. This does **not**, and structurally cannot, retroactively upgrade "A-
   empty stopped the ORIGINAL historian contamination" from INFERRED to
   VERIFIED. The synthetic hook is not the original historian code and
   never was; no artifact of the pre-patch script survives to compare
   against. That specific historical claim remains **permanently INFERRED**
   — this session closes off the possibility of ever resolving it further,
   rather than resolving it.

Decision recorded (NEXT.md updated in parallel): Option (a) chosen over
Option (b). The counter-case for (b) — a synthetic hook only proves
`--setting-sources` semantics work in general, not that they'd have caught
the specific original bug — was weighed and accepted as a permanent,
named limitation, not treated as a reason to skip building a forward-facing
control.

Scope discipline preserved: no `src/` change (Step C uses `_command()`
unmutated; Step B's mutation is a copy, made in the scratch script only,
same technique as session 10's Item-0 Pass 2); no `schema.py`/
`transitions.py`; no Step 3 live smoke; no commit. Witness script
(`witness_synth_control.py`) and hook (`synth-hook-marker.sh`) are ad hoc,
uncommitted, scratchpad-only — matching every prior ADR-22 probe in this
family.

Also this session (prerequisite, not part of the control work): a
working-tree `config.yaml` corruption (duplicate `child_env:` key) was
diagnosed and fixed — not committed. Diagnosis: an earlier restore-style
edit's replacement was anchored below the `child_env:` header rather than
at it, so it appended a duplicate header instead of replacing in place —
confirmed via `git diff` against HEAD plus a live `load_config()` call
before and after the fix (`ConfigError` before, clean load after).

---

### 2.7 — Session 12 (2026-07-24): CLI re-pin re-probe at 2.1.215 (STANDING TICKLE)

CLI drifted 2.1.212 → 2.1.214 (Session 11, incidental discovery) → **2.1.215**
(this session, live check). NEXT.md's STANDING TICKLE requires re-running the
ADR-22 probes on every version bump, before anything else. That re-probe was
never actually done at 2.1.214 — this session closes the gap directly at
2.1.215, using Session 11's surviving synthetic-control scripts (copied into a
fresh scratchpad, fresh probe cwds) plus a re-run of the Leg-B-style production
check (`item0_witness.py`'s `pass1_real()` pattern). All three legs run
sequentially with escalate-don't-retry: any RED halts before the next leg.

**Improvement folded in (per Session 11's own "Knowledge Captured" note):**
every spawn's transcript is now parsed for `claude_code_version` off the
`system`/`init` line, so the CLI version is witnessed *inside* the same
artifact as `apiKeySource` — neither prior script (`item0_witness.py`,
`witness_synth_control.py`) did this.

**Leg B — production argv via real `ClaudeHeadlessEngine.run()`.** Real,
unmutated engine, fresh scratch workspace (never StockPhotoAgent), prompt
instructs `git init`. **PASS**: `exit_status=0`, `apiKeySource="none"`,
`claude_code_version="2.1.215"` (witnessed in-transcript), `git init` denied
with both signals (`permission_denials` entry + `tool_result is_error:true`),
`.git` absent, `knowledge/` absent across all 16 polls / full 450s, zero new
`skips.log` lines for this run's cwd (re-verified via direct `grep -c` on the
real `~/.claude/historian/skips.log`, not just the script's own delta check).

**Synth Step B — prove the assay still goes red.** Mutated copy
(`--setting-sources project`) against a fresh `probe_cwd_trigger`. First
attempt **falsely reported FAIL** — root-caused, not a real mechanism issue:
the witness script's cwd-equality check compared the marker's raw
`$(pwd)`-sourced string (`/tmp/claude/...`, Git Bash's own mount view of the
Windows temp path) against Python's `str(cwd)` (`C:\Users\...`) with strict
string equality; these name the same directory but never match as strings.
Session 11's original script never enforced this comparison automatically (it
was eyeballed manually), so the gap was latent, not new. Fixed to a
path-suffix comparison and **re-ran Synth Step B fresh** (new probe cwd,
teardown of the stale marker via the script's existing `rmtree_force`).
**PASS on re-run**: marker present at t=0s (immediate, `async:false`),
`event=SessionEnd`, `pid=2180` mechanically distinct from the witness script's
own pid (`27192`), `cwd` suffix matches `probe_cwd_trigger` exactly,
`claude_code_version="2.1.215"`. Re-verified raw via direct `cat` of the
marker file on disk, not the script's JSON summary.

**Synth Step C — the real A-empty comparison.** Unmutated production argv
against a fresh `probe_cwd_empty`. **PASS**: marker absent at all 16 polls
across the full 450s window; `exit_status=0`, `apiKeySource` unchanged,
`claude_code_version="2.1.215"`. Re-verified raw: `ls` on the expected path
(nonexistent), plus a scratch-root-wide `find -iname fired.txt` under this
session's scratchpad confirming the only marker anywhere is Synth Step B's own
(in `probe_cwd_trigger`) — `probe_cwd_empty` genuinely never produced one.

**Net finding:** the ADR-22 mechanism (A-empty suppressing both the real
production path and the self-owned synthetic control) is re-verified green at
CLI 2.1.215, with the CLI version now witnessed inside every transcript
directly (closing the version-witness gap Session 11 flagged as a risk). Per
NEXT.md's explicit framing, this does **not** touch the original
"A-empty stopped the ORIGINAL historian contamination" claim, which remains
permanently INFERRED (no pre-patch artifact survives). **Decision: re-probe
and hold B** — `HISTORIAN_SWEEP_ACTIVE` stays in `config.yaml →
engine.child_env`; the B-layer sunset was NOT evaluated or acted on this
session (explicit user instruction — see NEXT.md). The STANDING TICKLE is
re-armed for the next CLI bump.

Scope discipline preserved: no `src/`, `schema.py`, `transitions.py` change.
Witness script (`witness_repin_2_1_215.py`, adapted from Session 11's
`witness_synth_control.py` + Session 10's `item0_witness.py`) and the copied
`synth-hook-marker.sh` are ad hoc, uncommitted, scratchpad-only — matching
every prior ADR-22 probe in this family. `ANTHROPIC_API_KEY` confirmed unset
before and asserted-unset at script entry.

Also this session (prerequisite, not part of the probe work): committed the
Sessions 9–11 pending `config.yaml`/`NEXT.md`/doc-14 changes plus three
untracked handoff files (`c376eea`). Found and corrected an additional,
undocumented `config.yaml` drift beyond the known duplicate-key fix: the
`reviewer.qwen.model` line had been changed to `qwen2.5-coder:14b`, a model
not present in `ollama list` (only `qwen2.5vl:7b` is pulled) — reverted to the
bare `qwen2.5-coder` value with an honest comment, since neither value
actually matches the local inventory and Step-3 precondition #2 remains
UNMET. The `validation.commands` fix (now pointing at
`tests\qc\test_qc_rules.py`, confirmed to exist in StockPhotoAgent) was kept
as-is.

---

## Steps 3–5 — NOT STARTED

Gated live smoke (3) is now **UNBLOCKED on the ADR-22 contamination question**
(§2.5) but still gated on its own separate preconditions (see NEXT.md) — not
started this session. Supervised StockAgent runs (4) and wrap (5) follow.

---

### Carried-forward note (Session 16-17, 2026-07-26) — surfaces named UNWITNESSED ahead of live smoke

This is a carry-forward transcription, not a new finding: transcribed from NEXT.md's
Resume-point section (L269-276, Session 17) and
`docs/handoffs/HANDOFF_2026-07-26_session17-dryrun-a-pass-correction-note.md`, which are
the provenance for every item below. Each surface remains exactly as recorded there —
UNWITNESSED / carried-forward — and no claim in this note is assigned any evidence label
(VERIFIED / INFERRED / etc.) beyond what it already carried in those two sources. This note
records that these surfaces are unwitnessed; it does not witness anything.

1. **`main.py`'s end-to-end startup composition** (health checks → `_ingest_issues` → loop,
   under the real CLI entrypoint) — Dry-run A (Session 17) bypassed it by constructing
   `Orchestrator` directly; this composition remains carried-forward, unwitnessed.
2. **The orphan-crash recovery path** — an accidental partial-spawn crash occurred mid-Dry-run-A
   (Session 17), but the session wiped and re-cloned fresh rather than resuming through it, so
   this path remains carried-forward, unwitnessed; the accidental crash is not evidence about it.
3. **Real-tree behavior itself** — every Item 0 / Dry-run A run to date has used a scratch
   workspace or clone, never StockPhotoAgent's actual working tree; this remains the
   irreducible carried-forward, unwitnessed variable ahead of live smoke.
