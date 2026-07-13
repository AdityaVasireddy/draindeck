# NEXT

## Resume point
Session 5 complete AND verified on Windows. The orchestrator loop is real:
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
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 55;
  minutes. `... %TEMP%\ch 42 <point>` filters to one crash point.)
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
- Run the **gated live smoke** first: one issue end-to-end on a scratch repo
  with the real engine + real QwenOllamaReviewer (Session-4-style, zero cost on
  failure), spot-checking one `_DENY_TOOLS` pattern live.
- Then 5 real StockAgent issues, supervised; record cost + outcomes; expect to
  revise the context pack (first contact with reality always does).
- Harness follow-up: add the two deferred crash points
  (`validate:post-artifact`, `after_append:IssueEscalated`) — doc 13 §4.
- `--allowedTools`/settings hardening is a non-goal (ADR-21 settled the fence);
  the sanitized-env hardening is a pre-Phase-4 item, not Session 6.
