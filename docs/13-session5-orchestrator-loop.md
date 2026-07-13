# 13 — The Orchestrator Loop (Session 5)

**Status:** IMPLEMENTED & VERIFIED · **Date:** 2026-07-12
**Scope:** Session 5 per doc 07 ordering. Replaces `main.py`'s foundation-only CLI
with the real orchestrator: the doc 09 §8.2 loop wired to doc 03 §5's transition
table, driving the now-real seams (event log + projections, GitCliAdapter,
ClaudeHeadlessEngine) plus the concrete Validator, Reviewer, BudgetManager,
context pack, and Issues.md ingest. Doc 03 is the frozen contract and won every
conflict; doc 02 owns the advisory principle.

## Verified vs. assumed (honesty discipline)

**VERIFIED by running this session (Windows, `claude` 2.1.207, `.venv` python):**
- **Baseline before any change:** 74/74 unit, 51/51 harness (seed 42) — observed
  directly, converting NEXT.md's recorded counts.
- **Final:** **103/103 unit** (74 prior + 29 new); **55/55 harness on seeds 42
  AND 1337** (51 prior + 4 from the two new reject crash points).
- **Loop against real git** (`test_loop_real_git.py`): two issues shipped
  end-to-end through a real `GitCliAdapter` — checkout `-B` from a pinned base, a
  fake engine that writes a workspace file, `snapshot_commit`, validation run
  against the mutated tree, review, the I3 pin gate, object-DB `merge_to`, and
  attempt-ref GC. Two merges on `agent-work`'s first-parent chain, attempt refs
  emptied, both work files on trunk.
- **Mutation spot-checks:** gutting the I3 pin gate turns
  `test_pin_gate_break_halts` red; gutting the duplicate-feedback guard turns
  `test_duplicate_feedback_escalates_needs_human` red. Both reverted, re-verified
  green — the tests genuinely catch a broken guard.
- **The CLI fence probe (ADR-21)** — see §1; the load-bearing security finding of
  the session, version-pinned to 2.1.207.

**ASSUMED / NOT verified this session:**
- The real end-to-end `run` against **live** `claude` + **live** Ollama was NOT
  executed (needs Ollama up with `qwen2.5-coder`, and StockAgent config). The
  loop is proven against a real git repo with a fake engine/reviewer, and every
  seam is unit-tested, but "a real `claude` implements a real StockAgent issue
  and a real Qwen reviews it" is the **gated live smoke** (§6) — deferred to when
  the NEEDS-USER-INPUT items land.
- Individual `_DENY_TOOLS` patterns beyond the probed representatives
  (`Bash(curl:*)`, `Bash(git push …)`, whole-tool `Bash`/`Task` removal) are
  assumed to behave like the proven same-form patterns; a consolidated live
  smoke should spot-check one before the first supervised run.
- Power-loss (vs process-crash) durability — unchanged scope boundary from
  Sessions 2–4.

## 1. ADR-21 — the fence probe (the session's pivot)

The Session-4 forward-pointer assumed `--allowedTools` would fence the engine.
A live probe of `claude` 2.1.207 **falsified** that and reshaped the engine
config. Full decision in **doc 08 §5b (ADR-21)**; the probe evidence:

| Probe | Result |
|---|---|
| `--allowedTools Read`, ask Bash `whoami` | **ran** (`permission_denials:[]`) — allowlist does not restrict |
| `--allowedTools "Bash(echo:*)"`, run `whoami` | **ran** — pattern allowlist does not restrict |
| same, under `--permission-mode default` | **ran** — not a mode artifact |
| `--disallowedTools Bash`, run `whoami` | **blocked** ("not enabled in this context"); model then tried the `Task` sub-agent (which inherited the block) |
| ambient `Bash(git push *)` vs `echo START && git push` | **denied** — deny rules are chaining-resistant |
| `--disallowedTools "Bash(curl:*)" …`: `echo hello` / `curl` / `echo ok && curl` / `git push` | allowed / denied / denied / denied — **flag patterns are selective, chaining-resistant, and compose with ambient** |
| production `ClaudeHeadlessEngine.run()`, 25 s timeout, Bash child sleeps 600 s | `timed_out=True`; recorded descendant pid **dead** after kill — **A3 tree-kill confirmed** for an intact tree |

Outcome: `engine/claude_headless.py` now carries an explicit `_DENY_TOOLS`
denylist (`--disallowedTools`), self-contained (no reliance on ambient
`~/.claude/settings.json`). The falsified Session-4 docstring claim was
corrected; doc 12 carries a correction note.

## 2. What shipped

New modules (`src/runtime/`):
- `loop.py` — `Orchestrator`: one deterministic step per call keyed on the
  replayed projection (worker `step()` shape), owning all git contact and all
  event emission. Splits doc 03 §5's idle row into **activate** and **spawn** so
  a crash between `IssueActivated` and `ExecutionSpawned` re-enters cleanly.
  Intents (`ExecutionSpawned`, `CommitIntent`) fsync before their action. Two
  HALTs (reviewer failure, I3 pin break) and one clean budget stop.
- `validation/runner.py` — `Validator`: config commands, cheapest-first
  short-circuit, one flake-retry, logs to the runtime artifacts dir (never the
  workspace).
- `reviewer/{base,qwen_ollama}.py` — `ReviewerProvider` ABC + `QwenOllamaReviewer`
  (stdlib urllib; strict single-JSON parse contract; one transport retry, one
  parse-retry; transport/parse failure → HALT, never a fabricated verdict).
- `budget/manager.py` — run-level execution + proxy-cost caps (ADR-09/19).
- `context/pack.py` — pure prompt builder (issue + accumulated feedback +
  constraints; `prompt_hash`).
- `queue/issues_md.py` — pure Issues.md parser (explicit `## <id>: <title>`
  format; fail-loud on malformed/duplicate).
- `main.py` `run` command — startup order config → env → log → engine → adapter
  → `reap_orphans` → `recover` → health (reviewer reachable; first-run baseline
  green) → idempotent ingest → loop.

Engine change: `_DENY_TOOLS` fence in `_command()` (ADR-21).
Projection change: `ExecutionView` gained `validated_commit`/`reviewed_commit`/
`taxonomy_category`/`feedback`; `StateProjection` gained `issue_depends_on`,
`issue_meta`, and the `deps_met` / `reviewer_feedback_categories` queries.

## 3. Event ordering per loop iteration (doc 03 §5)

Activate → spawn (intent, fsync) → EXECUTING (checkout `-B` base; engine.run;
`snapshot_commit`→ref **before** the fact; advisory route on
`timed_out`/`num_turns`/`exit_status` → `ExecutionFinished` [+ `IssueEscalated`
for turn-budget]) → VALIDATING (`ValidationPassed|Failed`) → REVIEWING
(`ReviewApproved|Rejected`; failure HALTs) → ACCEPTED (I3 pin gate →
`CommitIntent` [intent] → check-then-act `merge_to` → `CommitCreated` →
`IssueCompleted` → attempt-ref GC). Rejections `reset_hard(base)` after the fact
(residue already on the attempt ref); the next spawn-row guard decides
retry vs escalate. All verified across the 11 `test_loop.py` scenarios.

## 4. Crash coverage (harness)

Reject paths are now crash-durable: the worker scripts a validation-fail (043@1)
and a review-reject (044@1), each passing on retry so all issues still reach
DONE (I-c holds). New crash points **`after_append:ValidationFailed`** and
**`after_append:ReviewRejected`** — a kill after the reject fact, before the
`reset_hard(base)`, leaves head at `end_commit` while the log says REJECTED, and
**reconciler check 3 heals it** (55/55 both seeds; filtered runs confirmed each
point individually). No new invariants were needed — I-a…I-n already express the
loop-level properties.

**Deferred (documented gap, not silently dropped):** the plan also named
`validate:post-artifact` (a validation step that dirties the workspace) and
`after_append:IssueEscalated`. Both were scoped out this session to avoid
destabilizing the mutation-tested harness late in a long session. Their loop-side
logic *is* unit-covered (`test_loop.py`: turn-budget decomposition, cap-hit and
duplicate-feedback escalation, and the reviewer/pin HALTs), so the gap is in
crash-window coverage only, not in the transition logic. Recommend adding both
in the next session's harness pass.

## 5. Deviations from plan / doc 07, flagged

- **Fence is a denylist, not the `--allowedTools` allowlist the plan §4
  described** — falsified by probe; see ADR-21. The `allowed_tools` run()
  parameter the plan sketched was dropped: the fence is an engine-level security
  constant, not orchestrator-passed per-issue policy (cleaner, matches ADR-06
  "fence yourself").
- **Issues.md ingest pulled forward** from doc 07's Session 6 — the loop cannot
  select from an empty queue. doc 07 is a plan, not the frozen contract; no doc
  03 conflict (the `IssueCreated` payload matches §3).
- **Reviewer failure and pin-break override doc 09 §8.2/§6.3** in favor of doc 03
  §2 (HALT, don't fabricate a verdict; no reject edge from ACCEPTED). Recorded in
  the module docstrings.

## 6. NEEDS USER INPUT (between here and the first real StockAgent run)

Unchanged from the plan; nothing below is assumed in code:
1. `project.validation.commands` — StockAgent's real test command.
2. Directory name (StockAgent vs `StockPhotoAgent`) and that `agent-work` exists.
3. Issues.md in StockAgent, in the `## <id>: <title>` format (or author it).
4. **Ollama up + `qwen2.5-coder` pulled** — gates the reviewer health check and
   the live smoke (§ below).
5. Baseline green on `agent-work` (the startup health check enforces it).
6. StockAgent `.gitignore` covers build/test byproducts (else snapshots capture
   junk / check 3 fires).
7. ADR-19 experiment-params tamper guard has no doc-03 event home
   (`run_started` was removed) — deferred to Phase-4 prep.

**Gated live smoke (recommended first, once #4 lands):** one issue end-to-end
against a scratch repo with the *real* engine + *real* QwenOllamaReviewer — the
Session-4-style zero-cost-on-failure proof. Not a substitute for the supervised
StockAgent Phase-2 gate.

## 7. Files
New: `src/runtime/{loop.py, validation/, reviewer/, budget/, context/, queue/}`,
`tests/unit/{test_seams,test_loop,test_main,test_loop_real_git}.py`, this doc,
ADR-21 (doc 08 §5b). Changed: `main.py` (run command), `engine/claude_headless.py`
(_DENY_TOOLS + corrected docstring), `events/projections.py` (view/projection
fields + queries), `tests/unit/test_engine.py` (+2 fence tests),
`tests/crash/{worker,harness}.py` (reject paths + 2 crash points),
`docs/12` (correction note). No change to the frozen contract (doc 03) or the
event schema.
