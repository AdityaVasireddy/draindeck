# NEXT

## Resume point
Session 6 Steps 0, 1, R1, AND Step 2 preflight (2a + 2b) complete and verified
on Windows (2026-07-16). Full detail in doc 14 §2. Next up: **Step 3 (gated
live smoke) is BLOCKED** — see the two queued items below before any engine
run touches a real repo.

**Step 2 outcome (doc 14 §2):**
- **2a billing** — split still PAUSED (Help Center art. 15036540, re-fetched
  2026-07-16); `apiKeySource:"none"` on all 4 live runs; `config.yaml →
  billing.verified_on` bumped to `'2026-07-16'`. Billed-pool remains INFERRED.
- **2b fence** — `claude` upgraded to **2.1.211** (off the 2.1.207 pin). Fence
  re-derived live: deny enforced/selective/chaining-resistant (C1), production
  path denies too (C4), `--allowedTools` still non-restricting (C2). Decision
  matrix → row 2 (comment-only re-pin, landed in `claude_headless.py`;
  103-unit gate + zero-non-comment-line diff review passed).

**BLOCKERS / queued decisions for Adi (both require an ADR before Step 3):**
1. **`knowledge/`-contamination — Step-3 blocker. Mechanism finding COMPLETE;
   ADR-22 drafted as PROPOSED (doc 08 §5c); awaiting Adi's option selection.**
   Mechanism (VERIFIED, Session 7): the operator's **user-scope**
   `~/.claude/settings.json` registers `SessionEnd`/`PreCompact` hooks
   (`~/.claude/historian/historian-sweep.sh`) that load in every `claude`
   process on this machine — engine children included — and write the
   `knowledge/` vault bootstrap into the child cwd *before* the hook's own gate.
   Not a skill auto-load, not parent inheritance. Contamination is **4/4**
   across the Step-2 probes (doc 14 §2.3 correction note; the earlier "p2 clean"
   was an async-hook race). Against a real repo it dirties the tree every run →
   `is_dirty()`/check 3 trips → guaranteed false failure, can mask real signals;
   the hook is async and can land AFTER `run()`/`reset_hard`, so only
   prevention-at-source is deterministic.
   **Probe matrix run this session (doc 14 §2.4, ceiling 5, 0 re-runs, 0
   deviations):** control contaminates at 4 s; `--setting-sources ""` (A-empty,
   PREFERRED), `--setting-sources project,local` (A-projlocal), and
   `HISTORIAN_SWEEP_ACTIVE=1` (B) all clean for 450 s with `apiKeySource=none`
   unchanged; fence intact under A-empty.
   **DECISION FOR ADI:** pick the ADR-22 option (recommendation: A-empty durable
   + B belt-and-braces, B sunset after one clean CLI-upgrade cycle; C rejected;
   D optional operator hygiene). No mechanism landed — Status = Proposed.
   **Step 3 unblock criteria: ADR-22 marked Accepted AND the adopted mechanism
   probe-verified (the §2.4 probes already cover A-empty/A-projlocal/B).**
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
- Unit: `python -m pytest tests\unit -q`  (expect 103)
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
