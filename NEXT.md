# NEXT

## Resume point
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

**Step 3's OWN separate preconditions — still UNCONFIRMED, must be checked
before Step 3 runs (unrelated to ADR-22):**
0. **Live end-to-end re-witness of the ADR-22 argv (new, from this session's
   review):** a single live run of `ClaudeHeadlessEngine.run()` against the
   real `claude` binary, with the child-side settings-scope behavior directly
   observed, to close the residual gap between the Python-side live-spawn
   witness (this session, dummy child) and the CLI-side probe (§2.4, hand-
   built argv). This is cheap to fold into whatever Step-3-preflight
   smoke run happens first — no separate session needed, just don't skip it.
1. `project.validation.commands` in `config.yaml` still has the placeholder
   `'<StockAgent test command — REQUIRED before first run>'` — a real
   validation command has not been confirmed.
2. Ollama running with `qwen2.5-coder` pulled — not verified this session.
3. `Issues.md` authored in StockAgent in the `## <id>: <title>` format — not
   done.
4. Baseline green on StockAgent's `agent-work` branch — not re-verified this
   session.
5. StockAgent `.gitignore` hygiene (covers build/test byproducts) — not
   re-verified this session.

**Do NOT mark Step 3 planned or begin planning it — out of scope for Session
8, explicitly.**

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
