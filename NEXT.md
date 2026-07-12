# NEXT

## Resume point
Session 4 complete AND verified on Windows. The engine boundary is real:
`ClaudeHeadlessEngine` (`src/runtime/engine/claude_headless.py`) spawns
`claude -p`, enforces the wall-clock timeout with a stdin-safe `communicate()`
call, tree-kills on timeout, and enforces ADR-18 env hygiene per spawn (six
vars stripped in subscription mode, plus an in-band `apiKeySource` witness).
`reap_orphans()`/`is_execution_alive()` give the reconciler a real seam for
surviving engine children; a new crash-harness fixture (f4/I-n) proves it.
See doc 12.

Verified THIS session (Windows, `claude` 2.1.207, `.venv` python):
- 74/74 unit tests (`python -m pytest tests\unit -q`; 66 prior + 8 new in
  `tests/unit/test_engine.py`).
- 51/51 harness scenarios on seeds 42 AND 1337 (50 prior + new
  `fixture[f4-engine-orphan]`).
- Mutations M3 (gut `reap_orphans`) and M4 (drop the `ANTHROPIC_API_KEY`
  strip) both confirmed to fail (unit test + harness fixture for M3; unit test
  for M4), then reverted.
- Live smoke run of `ClaudeHeadlessEngine.run()` against a real scratch git
  repo with a deliberately **invalid** `ANTHROPIC_API_KEY` exported in the
  parent shell: run succeeded via the `/login` subscription profile
  (`apiKeySource="none"` in the transcript) — the strip works; a leak would
  have surfaced as a loud auth error instead of silent billing.
- Also discovered and resolved: CLI 2.1.207 has **no `--max-turns` flag**
  (removed since doc 11 §4's provisional sketch was written), and
  `--settings '{"maxTurns":N}'` is silently ignored in print mode (verified
  empirically — capped and uncapped runs were identical). Resolved to
  **reactive** enforcement: `EngineResult.num_turns` → orchestrator compares
  to `cfg.max_turns` → doc 03 §5's turn-budget row
  (`IssueEscalated(NEEDS_DECOMPOSITION)`). Wall-clock timeout remains the hard
  backstop regardless.

## Verify commands (updated)
- Unit: `python -m pytest tests\unit -q`  (expect 74)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 51;
  self-calibrates its kill window. Uses a real temp git repo per scenario, so
  it is minutes, not seconds. `... %TEMP%\ch 42 <point>` filters to one crash
  point for fast iteration. `fixture[f4-engine-orphan]` skips cleanly if
  `claude` is not on PATH.)

## Still open (pre-Phase-1-gate config gaps, not blockers)
- Fill `project.validation.commands` in config.yaml with StockAgent's real test
  command; resolve StockAgent vs StockPhotoAgent directory name (config.example
  still carries the ⚠ note).
- `delete_attempt_refs` (ADR-15 GC) is implemented but not wired — belongs to
  the orchestrator's post-IssueCompleted step.
- `ClaudeHeadlessEngine`'s `--allowedTools` allowlist is intentionally left at
  a conservative default (`--permission-mode acceptEdits`, no explicit tool
  restriction beyond what doc 02 §3 implies). Finalizing it needs
  `config.project.validation.commands`, which the engine never reads by
  design (doc 09 §7) — it's the orchestrator/context-pack session's job.

## Session 5 (per doc 07 ordering)
Orchestrator loop: wire `ClaudeHeadlessEngine` + `RepositoryAdapter` +
Validator + Reviewer into the real transition table (doc 03 §5), replacing
`main.py`'s foundation-only CLI. Concretely:
- Startup order in `main.py`: config → log → `engine.reap_orphans()` →
  `recover(is_execution_alive=engine.is_execution_alive,
  **bind_reconciler(...))` → health checks → loop (the harness worker's
  `step()` shape is the template — see doc 12 §1.6 and the harness fixture
  f4 for the exact call sequence).
- Validator concrete implementation (doc 09 §6.5): run
  `config.project.validation.commands` against the workspace, deterministic
  gate chain.
- Reviewer provider (ADR-05): `qwen` (Ollama) or `claude`, per
  `config.reviewer`.
- Context pack construction (doc 02 §5) — this is also where
  `ClaudeHeadlessEngine`'s `--allowedTools` allowlist finally gets decided,
  since it depends on the same validation-commands config the context pack
  needs.
- Budget metering (ADR-09) using `EngineResult.usage.dollars` /
  `total_cost_usd` against `config.budget.hard_stop_proxy_cost_per_run_usd`.
