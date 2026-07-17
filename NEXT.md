# NEXT

## STANDING TICKLE — check on every `claude` CLI version bump
**ADR-22 B-layer sunset (`engine.child_env.HISTORIAN_SWEEP_ACTIVE`,
`config.yaml`).** B is removable once A-empty (`--setting-sources ""`) has
survived one clean CLI-upgrade cycle with the doc 14 §2.4 probes re-run
green (control still contaminates; `--setting-sources ""` still `rc=0`,
still clean at 450 s, `apiKeySource` unchanged). **On the next `claude`
version bump, before anything else: re-run those probes, and if they pass,
remove `HISTORIAN_SWEEP_ACTIVE` from `config.yaml → engine.child_env` and
strike the B layer from doc 08 §5c as sunset-fulfilled.** A sunset condition
gated on a future event with nothing pointing at it tends to silently outlive
its own rationale — this line exists so it doesn't. (Session 8, 2026-07-16/17.)

**Session 9 update (2026-07-17, CLI now 2.1.212): re-run attempted, PARTIAL —
see doc 14 §2.6.** The `--setting-sources ""` leg re-verified clean at
450s/rc=0/apiKeySource unchanged (Probe B), AND independently corroborated by
a NEW signal (no `~/.claude/historian/skips.log` entry at all for that probe's
cwd — the hook never even loaded). But the "control still contaminates"
vacuity-guard leg (Probe A) **could not be reproduced.** **Root cause is
INFERRED, not VERIFIED** (label corrected this session after review): the
best-supported explanation is that the historian hook's own write-before-check
bug was independently patched upstream (current `historian-sweep.sh:293-304`
now gates before any vault write, and Probe A's `skips.log` entry shows the
hook ran to completion without writing) — but **no before/after code
comparison exists** (the tool has no git history; doc 08/doc 14's prior
records describe the old bug's *effects*, not its *source lines*) to confirm
this is a genuine upstream change rather than something else. Local-confound
alternatives (missing `jq`, a leaked `HISTORIAN_SWEEP_ACTIVE`, a disable
flag) were actively checked and ruled out — see doc 14 §2.6. **Do NOT treat
this as "B is now provably safe to sunset"** — the sunset condition is
specifically about A-empty surviving a CLI bump with BOTH probe legs green,
and leg 1 is currently unfalsifiable-by-this-guard, not passed. B stays.
Re-attempt the full two-leg re-run on the NEXT version bump — but see the
"vacuity-guard gap" item below first, since the control leg may need a
different construction before it can discriminate again.

## VACUITY-GUARD GAP (Session 9, 2026-07-17) — distinct from the B-sunset tickle above
The Probe-0/Probe-A style control (no suppression, expect contamination) is
what makes a clean `--setting-sources ""` probe *mean* "A-empty is doing
work" rather than "nothing was ever going to contaminate this run anyway." As
of this session that control **no longer discriminates**: it comes back
clean regardless of suppression, because (per the finding above) the ambient
historian hook itself no longer exhibits the write-before-check bug the
guard was built to detect. A clean Probe B is therefore currently consistent
with BOTH "A-empty still necessary and working" and "A-empty is now a
no-op, masked by an unrelated upstream fix" — **the two are no longer
distinguishable with this control.**

**Decision needed before the next CLI-bump re-pin cycle relies on the
vacuity guard again — not resolved this session (out of scope; recorded so
it isn't silently dropped):**
- **Option (a) — re-establish a discriminating control**, e.g. a small
  synthetic hook script (deliberately reproducing the "write before check"
  shape doc 08 §5c originally described: unconditionally touch a marker file
  under the child cwd, THEN check for a condition and exit) registered via a
  scratch **project-scope** `.claude/settings.json` in an isolated probe cwd
  — never the real `~/.claude/historian` hook, never touching machine
  config. Compare a run with `--setting-sources project` (loads the synthetic
  hook, should see the marker) against `--setting-sources ""` (should not).
  This tests A-empty's suppression mechanism directly and stops depending on
  whatever state the *real* ambient historian hook happens to be in —
  arguably a strictly better control than the original, since it no longer
  drifts out from under this repo when the operator's own tooling changes.
  Not built or run this session (probe-design work, same class as item 0 —
  deliberately left for a dedicated follow-up, not squeezed into this
  tight-scope session).
- **Option (b) — accept the control is retired**, record explicitly that
  vacuity is no longer independently checkable via the historian hook, and
  name a replacement guarantee (e.g. rely solely on the structural evidence —
  `_command()`'s unit-tested argv shape plus the CLI's own documented
  `--setting-sources` semantics — rather than a live behavioral control).

**This session takes no position between (a) and (b)** — flagged as an open
decision for the next session that touches ADR-22 re-pinning, so it is
chosen deliberately rather than by default when nobody remembers the guard
used to exist.

## Resume point
**Session 9 (2026-07-17): `claude` CLI version witnessed = 2.1.212 (bumped
from 2.1.211). Step-3 preflight sweep done — see doc 14 §2.6 for full
evidence.** ADR-18 strip-vars + ADR-22 A-empty mechanism re-verified live at
2.1.212 (Probe B: rc=0, clean at 450s, apiKeySource unchanged, fence intact,
plus a new skips.log-absence corroboration); the vacuity-guard control leg
(Probe A) could not be reproduced — INFERRED (not VERIFIED) that this is
because the historian hook's own bug was independently patched upstream,
with local confounds actively ruled out but no before/after code comparison
available — see STANDING TICKLE and VACUITY-GUARD GAP above; not treated as
a regression in this repo's mechanism, but also not fully closed. Item 0
(argv survival through `ClaudeHeadlessEngine.run()`
against real `claude`) is DESIGNED (doc 14 §2.6) but explicitly NOT RUN this
session. Step 3's other four preconditions re-checked live: #2 (Ollama
qwen2.5-coder) and #3 (Issues.md location+format) are UNMET; #1 (validation
command) remains genuinely unanswerable without user input; #4 (baseline
green) is blocked on #1; #5 (.gitignore hygiene) is MET. **Step 3 is still
not ready to start.** No `src/` change this session; no commit (standing
rule).

Session 8 (2026-07-16/17): ADR-22 marked **Accepted** (doc 08 §5c) and its
mechanism **landed and verified** — see below. NEXT.md item 1 (the
`knowledge/`-contamination Step-3 blocker) is now **CLOSED**. Item 2 (ADR-21
Amendment) was already closed Session 7. **Step 3 (gated live smoke) is now
UNBLOCKED on the contamination question — but NOT started, and has its own
separate preconditions still unconfirmed** — see "Step 3 unblock criteria"
below. Do not read "unblocked" as "ready to run."

**Item 1 — CLOSED (Session 8, 2026-07-16/17).** ADR-22 Accepted: **A-empty
(`--setting-sources ""` in the engine argv) + B
(`HISTORIAN_SWEEP_ACTIVE=1` via `config.yaml → engine.child_env`, merged in
`_hygienic_env()` with ADR-18 strip-list supremacy preserved), B sunsetting
after one clean CLI-upgrade cycle.** Mechanism landed in `src/` + `config.yaml`
(doc 14 §2.5 has the full as-built record). VERIFIED this session:
- `pytest tests/unit -q` → **106 passed**, identity-confirmed (not just
  arithmetic): `--collect-only` shows 106 total, and the new file collects
  exactly the 3 named tests (`test_command_carries_setting_sources_empty`,
  `test_child_env_merged_into_child_environment`,
  `test_child_env_cannot_override_strip_list`).
- `tests\crash\harness.py` → **60/60 BOTH seeds** (42 in `%TEMP%\ch2`, 1337 in
  `%TEMP%\ch3`) — gating because `src/` logic changed. Both runs hit stale
  Windows-read-only git-object files (unrelated 2026-07-11/13 scratch,
  pre-existing) that blocked the harness's own pre-flight calibration reset
  before any scenario ran; cleared (outside the repo, disposable state), then
  each seed ran clean on its first full attempt — no partial run folded into
  the reported 60/60. Full invocation lines + environmental note: doc 14 §2.5.
- **Argv empty-token survival — corrected label, split into two legs (doc 14
  §2.5 has the full writeup; an earlier draft of this note wrongly claimed
  "no shell-join" as the reason for VERIFIED — struck, Windows `Popen` with a
  list DOES join via `list2cmdline` before `CreateProcess`).**
  1. **Python-side handoff — VERIFIED, live.** The real, unmodified
     `_command()` return value was spawned through a real `subprocess.run()`
     on this Windows machine (dummy Python child, not `claude`); the child's
     own received `sys.argv` showed the `--setting-sources`/`''` pair as two
     adjacent elements, empty string intact, in the right position. This is
     not just the `_command()`-only unit test (which is list-construction
     level only) — it's a live spawn through the actual OS mechanism.
  2. **CLI-side interpretation — VERIFIED, doc 14 §2.4 Probe 2/3** (live
     `claude` 2.1.211, hand-built argv predating this session's code, not a
     call through `_command()` itself): `rc=0`, clean at 450 s, fence intact.
  Composing 1+2 is not one single end-to-end run through
  `ClaudeHeadlessEngine.run()` against the real `claude` binary; that closes
  the residual gap and is queued as a Step-3-preflight item below (Session-6
  preflight discipline), not done ad hoc this session.
- Strip-list supremacy — VERIFIED by a result-shape assertion (asserts on the
  final env dict `_hygienic_env()` returns, not on call order): a
  `child_env` key colliding with an ADR-18 strip-list entry does not survive
  into the built env; a non-colliding sibling key does.
- HEAD unchanged this session — no commit made (standing rule); nothing
  staged.

**Step 3 unblock criteria (from NEXT.md's earlier wording) — SATISFIED:**
ADR-22 Accepted AND mechanism probe-verified. Both true as of this session.

**Step 3's OWN separate preconditions — checked LIVE Session 9 (2026-07-17,
`claude` 2.1.212) — see doc 14 §2.6 for full evidence. NONE satisfied yet;
none carried forward from Session 7/8 assumption:**
0. **GATE, not a checklist line — live end-to-end re-witness of the ADR-22
   argv, through `ClaudeHeadlessEngine.run()` against the real `claude`
   binary, is a hard precondition on Step 3's live smoke, not an optional
   preflight nicety.** **DESIGNED this session (doc 14 §2.6), NOT RUN**
   (explicit scope boundary). Reason unchanged: the Python-side handoff (live
   spawn, dummy child) and the CLI-side interpretation (hand-built argv,
   including this session's Probes A/B) remain two *separate* legs — never
   composed into one real run through the production `_command()` → `Popen`
   → real `claude` path via the actual `ClaudeHeadlessEngine.run()` method.
   The design: real `EngineCfg`/engine instance, scratch workspace (never a
   real repo), call the real `_command()` for a structural pre-spawn assert,
   then the real `run()` for the behavioral witness (fence-trip prompt +
   450s contamination poll + `skips.log` cross-check). Full spec in doc 14
   §2.6. **This must run and pass before Step 3's smoke, per the original
   gate wording — unchanged.**
1. `project.validation.commands` in `config.yaml` still has the placeholder
   `'<StockAgent test command — REQUIRED before first run>'`. **RE-CHECKED
   LIVE, STILL UNCONFIRMED — genuinely no answer available without user
   input.** No `pytest.ini`/`pyproject.toml`/`setup.cfg`/`conftest.py`/
   `Makefile`/CI workflow exists anywhere in `C:\Projects\StockPhotoAgent`;
   `CLAUDE.md` documents many `python -m src....` operational commands but no
   test runner. This is not a probing gap — there is nothing left to probe;
   someone must author or supply the command.
2. Ollama running with `qwen2.5-coder` pulled. **RE-CHECKED LIVE — UNMET.**
   `ollama list` shows only `qwen2.5vl:7b`; `qwen2.5-coder` (the model
   `config.yaml → reviewer.qwen.model` names) is not pulled. `ollama ps`
   shows the service reachable but idle.
3. `Issues.md` authored in StockAgent in the `## <id>: <title>` format.
   **RE-CHECKED LIVE — UNMET, two independent problems.** (a) Wrong
   location: an untracked `docs/Issues.md` exists, but `main.py` resolves the
   issues file at repo-ROOT (`Path(project.repository) / project.issues_file`
   = `C:\Projects\StockPhotoAgent\Issues.md`), which does not exist. (b)
   Wrong format: `docs/Issues.md` is a numbered list with inline
   `**STATUS:**` markers, not `## <id>: <title>` headings — parsing it as-is
   would raise `IssuesParseError` (no `## ` heading matches the grammar at
   all).
4. Baseline green on StockAgent's `agent-work` branch. **BLOCKED on #1, not
   independently re-verifiable this session** — no known test command to
   run; guessing one (e.g. bare `pytest`) was judged unsafe given the
   `tests/` dir contains files that look auth/network-probe-shaped
   (`test_401_response_body.py`, `test_csrf_cookie_match.py`,
   `test_login_only.py`, ...), not obviously StockAgent's own suite. `git
   status` on `agent-work` itself is otherwise clean (only the untracked
   `docs/Issues.md` from #3).
5. StockAgent `.gitignore` hygiene (covers build/test byproducts).
   **RE-CHECKED LIVE — MET.** Covers `input/output/done/failed/review/`,
   `database/`, `logs/`/`*.log`/`debug_logs/`, `__pycache__/`, venv
   variants, IDE/OS cruft, and `config.ini` (credentials).

Directory-name caveat from doc 08 §6 (`⚠ confirm directory name on disk`):
**RESOLVED** — `C:\Projects\StockPhotoAgent` matches `config.yaml →
project.repository` exactly; `StockAgent` is cosmetic naming only
(`project.name`).

**Do NOT mark Step 3 planned or begin planning it — still out of scope; 0/1
of the 6 preflight items (0–5) is fully closed (5 only).**

**Step 2 outcome (doc 14 §2):**
- **2a billing** — split still PAUSED (Help Center art. 15036540, re-fetched
  2026-07-16); `apiKeySource:"none"` on all 4 live runs; `config.yaml →
  billing.verified_on` bumped to `'2026-07-16'`. Billed-pool remains INFERRED.
- **2b fence** — `claude` upgraded to **2.1.211** (off the 2.1.207 pin). Fence
  re-derived live: deny enforced/selective/chaining-resistant (C1), production
  path denies too (C4), `--allowedTools` still non-restricting (C2). Decision
  matrix → row 2 (comment-only re-pin, landed in `claude_headless.py`;
  103-unit gate + zero-non-comment-line diff review passed).

**BLOCKERS / queued decisions (history — both now closed):**
1. **`knowledge/`-contamination — CLOSED (Session 8, 2026-07-16/17).** ADR-22
   Accepted and its mechanism landed + verified — see the Resume-point section
   above and doc 14 §2.5 for the full as-built record. (Prior Session-7 finding
   retained here for history: the operator's **user-scope**
   `~/.claude/settings.json` registers `SessionEnd`/`PreCompact` hooks
   (`~/.claude/historian/historian-sweep.sh`) that load in every `claude`
   process on this machine — engine children included — and write the
   `knowledge/` vault bootstrap into the child cwd *before* the hook's own gate.
   Contamination was 4/4 across the Step-2 probes, doc 14 §2.3.)
2. **ADR-21 amendment note — CLOSED (Session 7, 2026-07-16).** Landed as
   **ADR-21 Amendment 1** in doc 08 §5b; `claude_headless.py` comment pointers
   updated (comment-only diff, 103-unit suite green); doc 14 §2.2 + new §2.4
   record it (§2.4 Probe 3 re-confirmed pattern-deny still emits BOTH signals).
   The whole-tool-removal DETECTION MECHANISM changed at 2.1.211 (denied tool
   dropped from the init `tools` manifest; no tool_use/is_error/denial — was:
   is_error + empty denials at 2.1.207). Enforcement is unchanged (stronger, if
   anything) — documentation/auditing amendment, not a fence break.
   **Forward consequence (for Step 4 ADR-19 metric capture / any future audit
   logic):** after 2.1.211 a whole-tool denial is NO LONGER observable from
   the result stream — there is no attempt, no `is_error`, and no
   `permission_denials` entry. The only evidence is the init `tools` manifest
   captured at spawn. Any "was a tool denied this run" signal must key on
   manifest ABSENCE, never on a result-stream signal that no longer exists.
   **QUEUED PREREQUISITE (new, from Amendment 1):** that init `tools` manifest
   is NOT yet persisted structurally — `_parse_result`
   (`src/runtime/engine/claude_headless.py:461-462`) reads only `apiKeySource`;
   the manifest survives only as raw lines in the archived transcript
   (`EngineResult.transcript_path`). Before any Step-4 ADR-19 "was a tool
   denied" metric, add a structured init-manifest capture. Mechanism TBD
   (engine artifact on `EngineResult`, advisory per ADR-07, vs. an event-schema
   addition) — **doc 03 governs**; no event-schema change made this session.

**Session 6 so far:**
- **Step 0** (baseline re-verify) — COMPLETE. 103/103 unit, 55/55 harness
  (pre-Step-1 baseline).
- **Step 1** (the two deferred harness crash points, `validate:post-artifact`
  + `after_append:IssueEscalated`) — COMPLETE, committed `aaf6b60` (code) /
  `d097f1f` (doc 14 as-built). Harness → 59/59 both seeds. Established that
  `validate:post-artifact` proves loop+recovery *system survival* but does
  NOT isolate check-3's `reset_hard` — the worker's blanket reset masks it
  (doc 14 §1.3-1.4). Named as deferred item R1 rather than silently dropped.
- **R1** (prove check-3 reset via planted fixture `f5`) — COMPLETE, committed
  `777ccab` (test-only: `tests/crash/harness.py`) + doc/NEXT commit (this
  one). Harness → **60/60 both seeds** (40 det + 15 rand + 4 fixtures
  f1/f2/f4/f5 + 1 control). Isolated mutation spot-check (gutting
  `reset_hard` in `bindings.py:102`, running f5 alone) confirmed red on f5's
  own commit-pin assertion, then reverted (`git diff src/` empty). Full
  detail, including the fail-safe trace of `checkout_branch`'s dirty-tree
  refusal (safe wedge, not corruption) and the still-open question about
  live Ctrl+C-during-VALIDATING coverage, is in doc 14 §1.5.

Prior baseline (Session 5, unchanged): the orchestrator loop is real:
`main.py run --config config.yaml` runs the full startup order (config → env →
log → `engine.reap_orphans()` → `recover(...)` → health checks → idempotent
Issues.md ingest → loop) and `src/runtime/loop.py`'s `Orchestrator` drives doc
03 §5's transition table, owning ALL git contact and ALL event emission. The
concrete seams landed: `Validator`, `QwenOllamaReviewer` (+ `ReviewerProvider`
ABC), `BudgetManager`, context-pack builder, Issues.md parser. See doc 13.

**The big finding (ADR-21, doc 08 §5b):** a live probe FALSIFIED the plan's
`--allowedTools` fence — in `-p` mode `--allowedTools` does not restrict at all
(a tool matching neither allow nor deny just runs). The engine is now fenced by
an explicit `--disallowedTools` DENYLIST (`_DENY_TOOLS` in
`engine/claude_headless.py`): network egress, git, destruction, recursive
spawns, WebFetch/WebSearch/Task. Strict "no credential access" (doc 02 §3) is
accepted as structurally unclosable while Bash exists; ADR-21 fences egress +
destruction instead, with compensating controls. Session-4's docstring claim
was corrected; doc 12 carries a correction note.

Verified THIS session (Windows, `claude` 2.1.207, `.venv` python):
- **103/103 unit** (74 prior + 29 new: engine fence ×2, seams ×13, loop ×11,
  ingest ×2, real-git end-to-end ×1).
- **55/55 harness on seeds 42 AND 1337** (51 prior + 4 from two new reject
  crash points: `after_append:ValidationFailed`, `after_append:ReviewRejected`;
  check 3 heals the post-reject window).
- Loop driven end-to-end against a REAL git repo (fake engine/reviewer): two
  issues shipped, two merges on `agent-work`, attempt refs GC'd.
- Mutations (gut I3 pin gate; gut duplicate-feedback guard) both confirmed red,
  then reverted green.
- ADR-21 fence probe: 7 live `claude -p` runs + 1 production
  `ClaudeHeadlessEngine.run()` tree-kill run (A3 confirmed).

## Verify commands (updated)
- Unit: `python -m pytest tests\unit -q`  (expect 106)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 60;
  minutes. `... %TEMP%\ch 1337` also 60. `... %TEMP%\ch 42 <point>` filters to
  one crash point.) Use the `.venv` python — the system Python on this
  machine lacks `pyyaml`/`pydantic`.
- Orchestrator (needs config + live services): `python -m runtime.main run
  --config config.yaml` (see NEEDS-USER-INPUT below before first run).

## NEEDS USER INPUT before the first real StockAgent run (doc 13 §6)
1. `project.validation.commands` — StockAgent's real test command (config.yaml
   still has the `<REQUIRED>` placeholder).
2. Directory name (StockAgent vs `C:\Projects\StockPhotoAgent`) + `agent-work`
   branch exists.
3. Issues.md in StockAgent in the `## <id>: <title>` format (or author it).
4. Ollama up + `qwen2.5-coder` pulled — gates the reviewer health check and the
   live smoke.
5. Baseline green on `agent-work` (startup health check enforces it).
6. StockAgent `.gitignore` covers build/test byproducts.
7. ADR-19 tamper guard has no doc-03 event home — defer to Phase-4 prep.

## Session 6 (per doc 07 — PHASE 2 GATE)
Drive the FIRST supervised issues against StockAgent, watched, not walked away
from (doc 07 Session 6). Concretely:
- ~~Harness follow-up: add the two deferred crash points~~ — DONE (Step 1).
- ~~Prove check-3 reset (R1 / fixture f5)~~ — DONE.
- ~~Step 2 preflight (2a billing re-verify + 2b engine-version/fence re-probe)~~
  — DONE (2026-07-16, doc 14 §2; `claude` now 2.1.211). See the Resume-point
  BLOCKERS above.
- **Next: gated live smoke — BLOCKED** on the `knowledge/`-contamination ADR
  decision (Resume-point item 1). One issue end-to-end on a scratch repo with
  the real engine + real QwenOllamaReviewer (Session-4-style, zero cost on
  failure), spot-checking one `_DENY_TOOLS` pattern live — cannot run until the
  ambient-hook workspace contamination is resolved, or the tree dirties every
  run and the smoke false-fails.
- Then 5 real StockAgent issues, supervised; record cost + outcomes; expect to
  revise the context pack (first contact with reality always does).
- `--allowedTools`/settings hardening is a non-goal (ADR-21 settled the fence);
  the sanitized-env hardening is a pre-Phase-4 item, not Session 6.
