# Session Handoff — The Orchestrator Loop (Session 5)

## Objective
Sessions 1–4 built every load-bearing seam (durable event log, RepositoryAdapter/GitCliAdapter,
ClaudeHeadlessEngine) but nothing drove them as one system — `main.py` was still the Session-2
foundation CLI. Session 5's job was to design (Plan Mode, user-approved with seven review fixes)
and implement the real orchestrator loop: `main.py run`'s startup order plus the doc 09 §8.2 main
loop wired to doc 03 §5's frozen transition table, with the orchestrator owning all git contact
and all event emission and the engine staying strictly advisory (ADR-02/07).

## Current Status
- Completed: the full orchestrator loop, all concrete seams (Validator, QwenOllamaReviewer,
  BudgetManager, context pack, Issues.md ingest), the engine's ADR-21 fence, projection
  extensions, harness reject-path coverage, doc 13 (as-built), ADR-21 (doc 08 §5b), doc 12
  correction note, NEXT.md update. **Committed** at `2608ac7`.
- Blocked: nothing for continued development. The first *real* StockAgent run is blocked on the
  seven NEEDS-USER-INPUT items below (config facts only the user can supply — see Open
  Questions).

## Decisions & Rationale
- **The engine fence is a `--disallowedTools` denylist, not the plan's `--allowedTools`
  allowlist** — a live probe of `claude` 2.1.207 falsified the allowlist mechanism entirely (in
  `-p` mode a tool matching neither allow nor deny simply runs, under every permission mode
  tested). The denylist *is* enforced, is selective at the `Bash(cmd:*)` pattern level, and is
  chaining-resistant. Recorded as **ADR-21** in `docs/08-session-0-closure-and-adr-amendments.md`
  §5b; implemented as `_DENY_TOOLS` in `src/runtime/engine/claude_headless.py`, passed entirely
  as explicit flags (no reliance on ambient `~/.claude/settings.json`).
- **Strict "no credential access" (doc 02 §3) is accepted as structurally unclosable while Bash
  exists**, per explicit user direction during planning — a shell can always read a local file and
  egress via curl/python, and denylist whack-a-mole cannot close that. ADR-21 fences egress +
  destruction + git + recursive-spawn instead, with compensating controls (no push path, no git
  access, reconciler check 3, the supervised Phase-2 gate, ADR-20's safe-to-experiment target). A
  sanitized-env hardening is noted as a pre-Phase-4 item, not built.
- **doc 03 §5's idle row is split into two dispatcher rows (activate, spawn)** in `loop.py`, not
  kept as one combined step — this is what closes a crash gap the user flagged during plan review:
  a kill between `IssueActivated` (durable) and `ExecutionSpawned` (not yet appended) leaves an
  issue ACTIVE with zero executions. The spawn row's guard (`ex is None`) matches that state on
  restart and re-spawns with `spawn_reason="initial"`; `IssueActivated` never re-runs so
  `base_commit` stays pinned. Comment citing doc 03 §1 added at the guard in `loop.py` (near
  `Orchestrator.step`, the `ex is None or ex.state in _RETRYABLE_EXEC` line).
- **`ExecutionSpawned.pid` has no runtime consumer** — it exists purely as audit evidence for the
  I-h never-replayed rule (`Spawned.pid == Finished.pid` proves the same writer witnessed the
  finish). Orphan detection is a separate mechanism entirely: the engine-child pid lives only in
  `ClaudeHeadlessEngine`'s pidfile, consumed by `is_execution_alive`. Clarified in `loop.py`'s
  `_spawn_or_escalate` per user request during plan review.
- **Reviewer transport/parse failure and the I3 pin-gate break both HALT the run rather than emit
  an event** — overriding doc 09 §6.3/§8.2's text in favor of doc 03 §2 (REVIEWING is re-callable;
  no reject edge exists from ACCEPTED). Fabricating a `ReviewRejected` or reject event would
  require inventing `feedback[]` or breaking the honesty rule. Implemented in `loop.py`'s
  `_review` (propagates `ReviewerError`) and `_commit_sequence` (raises `OrchestratorHalt`).
  Reviewer transport gets one retry with backoff before halting (added per user request during
  plan review, distinct from the one parse-retry) — `reviewer/qwen_ollama.py::_call`.
- **Harness coverage was deliberately narrowed from four planned new crash points to two**
  (`after_append:ValidationFailed`, `after_append:ReviewRejected`) — the other two
  (`validate:post-artifact`, `after_append:IssueEscalated`) were cut late in a long session to
  avoid destabilizing the mutation-tested harness; their loop-side logic is unit-tested
  (`test_loop.py`) even though the crash-window itself is unexercised. Recorded as a deferred item
  in doc 13 §4 and NEXT.md, not silently dropped.

## Key Files
- Plan file: `~/.claude/plans/read-claude-md-next-md-the-sparkling-pebble.md` — the approved
  Session-5 design, including the seven user review fixes applied before/during implementation
  (activate/spawn split, pid-consumer note, chaining probe case, transport retry, DONE/ACCEPTED
  terminology convention, retry workspace-prep semantics, doc-03-line citation for outcome/
  taxonomy fields).
- `docs/13-session5-orchestrator-loop.md` — the as-built record: full VERIFIED/ASSUMED split, the
  ADR-21 probe evidence table, event-ordering summary, harness coverage table including the two
  deferred crash points, all plan/doc-07 deviations flagged with rationale. Read this first.
- `docs/08-session-0-closure-and-adr-amendments.md` §5b — ADR-21 itself (the fence decision,
  probe evidence, accepted deviation, rejected alternatives).
- `docs/12-session4-engine-wrapper.md` — carries a correction note (near the ASSUMED section) for
  the Session-4 `--allowedTools`/`permission_denial` claim ADR-21 falsified.
- `src/runtime/loop.py` — `Orchestrator`: the dispatcher. Every design decision (event ordering,
  the activate/spawn split, the two HALT paths) is inline in the module docstring and per-method,
  mirroring the engine/adapter documentation style from prior sessions.
- `src/runtime/engine/claude_headless.py` — `_DENY_TOOLS` and the corrected `_command()`/module
  docstring (ADR-21, replacing the falsified allowlist text).
- `src/runtime/events/projections.py` — `ExecutionView` gained `validated_commit`,
  `reviewed_commit`, `taxonomy_category`, `feedback`; `StateProjection` gained `issue_depends_on`,
  `issue_meta`, and the `deps_met`/`reviewer_feedback_categories` queries the loop's guards use.
- `NEXT.md` — updated resume pointer; points at Session 6 (the Phase-2 gate: gated live smoke,
  then 5 supervised StockAgent issues), with the NEEDS-USER-INPUT list reproduced.

## Next Action
Session 6 per doc 07/NEXT.md: run the **gated live smoke** first — one issue end-to-end on a
scratch repo with the real `claude` engine and real `QwenOllamaReviewer` (Session-4-style,
zero-cost-on-failure design), spot-checking at least one `_DENY_TOOLS` pattern live since only a
few were probe-verified this session. This is blocked on Ollama being up with `qwen2.5-coder`
pulled (Open Questions item 4) — everything else in the codebase is ready to drive it.

## Knowledge Captured
- **`claude` 2.1.207's `--allowedTools` does not restrict tool use in `-p` mode at all** — a tool
  matching neither an allow nor a deny rule simply runs, confirmed under both
  `--permission-mode default` and `acceptEdits`. This falsifies not just the Session-5 plan's
  fence design but Session 4's docstring claim that a disallowed tool records a `permission_denial`
  — no allowlist-driven denial was ever possible to observe, since the allowlist never denies.
- **`--disallowedTools` is the only enforced mechanism**, and it behaves correctly at three levels
  probe-verified this session: whole-tool removal (`--disallowedTools Bash` → tool absent from the
  toolset, model sees "not enabled in this context"), selective pattern removal
  (`Bash(curl:*)` denies `curl` while `echo hello` still runs under the same flag set — proving the
  pattern form is accepted and is *not* whole-tool removal), and chaining resistance (`echo ok &&
  curl ...` is denied by the `curl` pattern; ambient `Bash(git push *)` denies `echo START && git
  push origin main` even though `git push` is not the leading token).
- **A denied pattern and a whole-tool removal surface through different transcript signals**:
  pattern denial populates `result.permission_denials` *and* yields a `tool_result` `is_error`;
  whole-tool removal yields only the `tool_result` error with `permission_denials` staying empty.
  Any future transcript-based fence auditing must check both signals, not just
  `permission_denials`.
- **A model routes around a removed tool via the `Task`/Agent sub-agent tool** — observed directly
  when `Bash` was disallowed: the model spawned a `general-purpose` sub-agent to attempt the
  command. In that run the sub-agent inherited the restriction and also failed, but this means
  `Task` must be in any tool denylist that's meant to be load-bearing (it is, in `_DENY_TOOLS`).
- **Explicit `--disallowedTools` flags compose with ambient `~/.claude/settings.json`'s `deny`
  list, and deny always wins** — confirmed by the micro-probe: `git push` was denied by the
  ambient settings rule even while explicit `--disallowedTools` flags (a different pattern) were
  simultaneously active. This is why the fence could be built as flags-only with no reliance on
  settings-file state.
- **The production `ClaudeHeadlessEngine.run()` tree-kill was directly exercised this session**
  (not just the Session-4 unit-test dummy-child path): a real `claude -p` process spawning a
  long-lived Bash-tool Python descendant, killed via the actual `_kill_tree`/`taskkill /F /T` path
  under a 25-second timeout. The descendant was confirmed dead after the kill — this is the first
  session A3 (real tool-subprocess tree-kill) was verified against a genuine `claude` child rather
  than a synthetic dummy.

## Assumptions
- Only a subset of `_DENY_TOOLS` entries were probe-verified as behaving like the proven forms
  (`Bash(curl:*)`, the ambient `git push` pattern, and whole-tool `Bash`/`Task` removal). The
  remaining entries (`wget`, `ssh`, `scp`, `powershell`, `rm`, `sudo`, `chmod`, `claude`, `npx`,
  etc.) are assumed to behave identically because they use the same probed `Bash(cmd:*)` colon
  form. MED confidence — the mechanism is proven, but no individual untested entry was fired.
  **Recommend:** spot-check one or two of these live during the Session-6 gated smoke.
- The real end-to-end `run` command was never executed against a live `claude` engine and live
  Ollama reviewer together — only against fakes (unit) and a real git repo with a fake
  engine/reviewer (`test_loop_real_git.py`). HIGH confidence the wiring is correct (every seam is
  independently unit-tested and the git choreography is proven on real git), but "the whole system
  end to end with real LLM calls" remains unverified. This is explicitly the Session-6 gated smoke.
- Reparented-grandchild tree-kill escape (a grandchild whose parent already exited before the kill,
  first flagged as an open assumption in Session 4) remains unexercised — this session's tree-kill
  probe used an intact process tree and confirmed the kill reaches a live descendant, but did not
  specifically construct the escape scenario. HIGH confidence this is still the correct honest
  characterization (reconciler check 3 is the documented backstop) — unchanged from Session 4, not
  newly assumed.

## Architecture Changes
- `main.py` gained a `run` subcommand implementing the doc 09 §8.1 startup order (config → env
  validation → log → engine construction → adapter construction → `engine.reap_orphans()` →
  `recover(...)` with all three reconciler seams bound → health checks [reviewer reachability,
  first-run baseline-green] → idempotent Issues.md ingest → `Orchestrator.run()`). This is the
  first session `main.py` does anything beyond the foundation CLI commands.
- New package `src/runtime/loop.py` sits above every existing seam per doc 09 §2's dependency
  direction (`main → loop → queue, context, engine, validation, reviewer, repo, budget →
  events`). `Orchestrator.step()` is a pure function of the replayed projection, matching
  `tests/crash/worker.py::step()`'s shape — one deterministic move per call, event ordering
  governed by I5/I6 (intents fsync before their action).
- Five new leaf packages: `validation/`, `reviewer/`, `budget/`, `context/`, `queue/` — each a
  concrete implementation of an interface doc 09 §6 had only sketched as a contract.
  `reviewer/base.py` defines the `ReviewerProvider` ABC (ADR-05); `reviewer/qwen_ollama.py` is the
  only concrete implementation shipped this session (the `claude` reviewer provider raises
  `NotImplementedError` in `main.py::_make_reviewer`, deferred to doc 07's Session 7 slot).
- `events/projections.py`'s `StateProjection`/`ExecutionView` widened with Session-5-specific
  fields (pin-gate commits, feedback categories, dependency graph, static issue text) — all
  derived from existing doc 03 §3 event payloads, no schema change, no new event types.

## Testing / Verification Performed
- PASS: baseline re-run before any change — 74/74 unit, 51/51 harness (seed 42) — observed
  directly this session, converting NEXT.md's recorded counts into this-session observations.
- PASS: final full unit suite, 103/103 (`.venv/Scripts/python.exe -m pytest tests/unit -q`),
  observed multiple times this session (after each major addition and again at close).
- PASS: full crash harness, seed 42 — 55/55 scenarios (51 prior + 4 new from the two added crash
  points), observed directly.
- PASS: full crash harness, seed 1337 — 55/55 scenarios, independently observed in a separate run.
- PASS: filtered single-crash-point runs for both new points
  (`after_append:ValidationFailed`, `after_append:ReviewRejected`) before committing to the full
  multi-minute runs, both green.
- PASS: `test_loop_real_git.py` — the orchestrator driven against a real temporary git repository
  (not fakes) with a fake engine that genuinely writes a file into the workspace and a fake
  reviewer; two issues shipped end to end, two merges landed on the target branch's first-parent
  chain, attempt refs were garbage-collected, exactly one `CommitCreated` per issue.
- PASS: mutation spot-check — commenting out the I3 pin-gate check in `loop.py` turned
  `test_pin_gate_break_halts` red (`DID NOT RAISE OrchestratorHalt`); reverted, re-verified green.
- PASS: mutation spot-check — commenting out the duplicate-feedback guard turned
  `test_duplicate_feedback_escalates_needs_human` red; reverted, re-verified green.
- PASS: ADR-21 fence probe — 7 live `claude -p` invocations (cases a, b, a2, disallowedTools-Bash,
  reframed chaining-vs-deny, micro-probe with 4 sub-commands) plus 1 production
  `ClaudeHeadlessEngine.run()` tree-kill run, all outputs read and interpreted directly this
  session (not delegated).
- NOT TESTED: the `run` command against a live `claude` engine and live Ollama reviewer together
  (see Assumptions — this is the Session-6 gated smoke). The `claude` reviewer provider (raises
  `NotImplementedError`, out of scope this session). Any platform other than this Windows machine.
  Power-loss (vs. process-crash) durability — unchanged scope boundary from prior sessions.

## Technical Debt
- Two planned harness crash points (`validate:post-artifact`, `after_append:IssueEscalated`) were
  not added — **intentional**, cut to avoid destabilizing the mutation-tested harness late in a
  long session. Loop-side logic for both is unit-tested; only the crash-window itself is
  unexercised. Recorded in doc 13 §4 and NEXT.md as a Session-6 follow-up.
- `--allowedTools`/`allowed_tools` as a per-issue orchestrator-passed parameter (sketched in the
  original plan §4) was dropped in favor of the engine-level `_DENY_TOOLS` constant —
  **intentional**, not a shortcut: the fence is a security invariant of the engine itself
  (ADR-06's "fence yourself"), not per-issue policy, so parameterizing it would have been the wrong
  shape once the mechanism changed from allow to deny.
- Verdict caching by `(issue, tree_hash)` (doc 03 §4 calls this out as a property verdicts should
  have) is not implemented — **intentional**, deferred to doc 07's Session-7 reviewer slot per the
  original plan. A restart mid-REVIEWING re-bills one review call; acceptable for v1 scale.

## User Constraints
- Architecture is FROZEN; doc 03 wins any event/state-semantics conflict, doc 02 wins the advisory
  principle; changes go through an ADR, not ad hoc edits. Two doc 09 text overrides this session
  (reviewer-failure halt, pin-gate-break halt) were resolved in doc 03's favor and documented
  inline, not treated as architecture changes.
- Honesty discipline: every session summary separates VERIFIED (ran it, saw it) from ASSUMED;
  applied throughout doc 13 and this handoff, including the narrower disclosure that only a subset
  of `_DENY_TOOLS` entries were individually probe-fired.
- Repo path/branch/test commands are CONFIG ONLY, nothing hardcoded under `src/` — the loop takes
  `Config` and per-call arguments throughout; no path/branch/command literals were introduced.
- ANTHROPIC_API_KEY stayed unset throughout this session's own Claude Code usage and every probe
  invocation (confirmed via `echo "ANTHROPIC_API_KEY is: [${ANTHROPIC_API_KEY:-<unset>}]"` before
  the probe sequence began).
- User reviewed the Session-5 plan externally and required seven specific fixes before approval
  (see Decisions & Rationale and the plan file) — all seven confirmed applied in the shipped code
  before this handoff was written.
- Commit only when explicitly asked (standing git-safety rule) — the user explicitly approved the
  commit this session via AskUserQuestion, after two spot-check confirmations (the activate/spawn
  gap location and the `Bash(pattern)`-as-flag probe evidence) were supplied and verified against
  transcript output rather than asserted from memory.

## Runtime & System State
- Commit at handoff: `2608ac7` — "Session 5: orchestrator loop + concrete seams; ADR-21 engine
  fence". Working tree is clean except `knowledge/.sweep/` (the historian hook's own artifacts,
  unrelated to this session's work, deliberately excluded from the commit).
- No background processes remain running — the two backgrounded harness runs (seed 42, seed 1337)
  both completed and were read to completion before this handoff.
- Scratch probe artifacts remain under
  `%TEMP%\claude\C--Projects-issue-runtime\192fd380-303f-4dff-9f40-18be3dc49e84\scratchpad\`
  (`probe_c_treekill.py`, `probe_abd/`) — session-scoped scratch content from the ADR-21 probe, not
  part of the repo, harmless to leave or clean up.
- No dev servers, no open worktrees, no memory files updated this session.

## Open Questions
**Needs User Input**
- `project.validation.commands` — StockAgent's real test command; `config.yaml` still carries the
  `<StockAgent test command — REQUIRED before first run>` placeholder (unresolved since Session 0).
- Directory name: does StockAgent live at `C:\Projects\StockPhotoAgent` on disk, and does the
  `agent-work` branch exist there (ADR-20's original naming discrepancy, still unresolved)?
- Does StockAgent have an `Issues.md` file, and if so does it use the `## <id>: <title>` heading
  format this session's parser expects, or does one need to be authored/the parser adjusted?
- Is Ollama running with `qwen2.5-coder` pulled? Required for the reviewer health check in
  `main.py run` to pass at all, and for the Session-6 gated live smoke.
- Is StockAgent's test suite green on `agent-work` right now (ADR-20's baseline-green
  precondition)? The startup health check will enforce this on first run but the user should
  confirm before attempting it.
- Does StockAgent's `.gitignore` cover build/test byproducts? If not, `snapshot_commit`/check 3
  will capture junk into attempt refs and validation runs will look like spurious workspace
  mutations.
- Where should the ADR-19 experiment-params tamper guard live, now that doc 03 removed the
  `run_started` event doc 09 §3 had anchored it to? Flagged, not decided — proposal on the table
  (doc 13 §6 item 7) is to defer to Phase-4 prep since it only bites the falsification run itself.

**Model Uncertainty**
- None outstanding — every design question raised during this session's planning was either
  resolved via AskUserQuestion at the time or is captured above as an explicit NEEDS-USER-INPUT
  config fact, not a design ambiguity.
