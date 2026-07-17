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

## Steps 3–5 — NOT STARTED

Gated live smoke (3) is now **UNBLOCKED on the ADR-22 contamination question**
(§2.5) but still gated on its own separate preconditions (see NEXT.md) — not
started this session. Supervised StockAgent runs (4) and wrap (5) follow.
