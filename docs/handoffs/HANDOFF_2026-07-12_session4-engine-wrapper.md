# Session Handoff — ClaudeHeadlessEngine, ADR-18 hygiene, engine-orphan reaping (Session 4)

## Objective
Make the engine boundary of the autonomous issue-resolution runtime real.
Sessions 1–3 built the durable event log, projections, reconciler, and a real
git boundary (`RepositoryAdapter`/`GitCliAdapter`, all three reconciler seams
bound, kill-9 harness on a real temp git repo). This session designed (in Plan
Mode, user-approved with six review fixes) and implemented
`ClaudeHeadlessEngine` — the concrete engine wrapper that spawns `claude -p`,
enforces the wall-clock timeout and ADR-18 env hygiene, and gives the
reconciler a real `is_execution_alive` seam via a new `reap_orphans()` startup
step — closing the gap between "durability proven with a stub engine" and
"durability proven against a real spawned process."

## Current Status
- Completed: `ClaudeHeadlessEngine`/`EngineResult` (`src/runtime/engine/`), a
  new crash-harness fixture (`f4-engine-orphan`, invariant I-n), 14 new unit
  tests, doc 12 (as-built record), NEXT.md update. Working tree has these
  changes staged but **NOT committed** — see Runtime & System State.
- Blocked: nothing. Session 5 (orchestrator loop) can start immediately.

## Decisions & Rationale
- **`max_turns` is enforced reactively, not by a CLI flag.** The doc-11 §4
  sketch assumed `--max-turns` would exist; it doesn't in `claude` 2.1.207,
  and `--settings '{"maxTurns":N}'` is silently ignored in print mode
  (verified empirically: a capped and uncapped 2-turn task produced identical
  `num_turns=2`). After presenting three options to the user (investigate a
  settings-key path first, fall back to reactive if it dead-ends, reject a
  live-stream-counting preventive design), the settings probe dead-ended and
  the fallback was taken: `EngineResult.num_turns` (from the stream-json
  result line) is reported to the orchestrator, which compares it to
  `cfg.max_turns` and — on breach — records doc 03 §5's turn-budget row,
  `IssueEscalated(NEEDS_DECOMPOSITION)` (event #10, doc 03 §3; confirmed
  against the frozen vocabulary before accepting it). This is a **distinct**
  row from the wall-clock-timeout row (`ExecutionFinished(REJECTED,
  taxonomy=timeout)`); `timed_out` drives the latter, `num_turns` the former,
  and the orchestrator — not the engine — picks the row. `num_turns` is
  documented as an **explicit extension of the ADR-02/07 advisory carve-out**
  in `EngineResult`'s docstring: engine-reported data that may only select
  which frozen-vocabulary event fires, never whether work "worked".
- **`proc.communicate()`, not `stdin.write()` + `wait()`.** A pre-review pass
  of the plan caught that a bare `stdin.write()` followed by
  `wait(timeout=...)` could block the parent *before* the timeout ever arms —
  a wedged or early-dying child, or a prompt larger than the OS pipe buffer,
  would hang the write call itself. `communicate(input=..., timeout=...)`
  covers the stdin write, the wait, and the timeout as one operation (stdout
  and stderr are already file handles, not pipes, so there's nothing else to
  drain). Verified with a unit test using a child that never reads stdin and a
  prompt sized past the pipe buffer (`test_timeout_arms_when_child_never_reads_stdin`).
- **ADR-18 enforcement is `raise EngineEnvError`, never `assert`.** Asserts
  vanish under `python -O`; this is a billing invariant that must hold on
  every spawn regardless of interpreter flags. A second in-band witness closes
  the loop: after the run, the engine parses the transcript's `init` line and
  raises if `apiKeySource != 'none'` in subscription mode — a leaked
  credential surfaces even if the strip logic itself had a bug the unit tests
  missed.
- **Six vars stripped in subscription mode, not just `ANTHROPIC_API_KEY`.**
  `ANTHROPIC_AUTH_TOKEN` (the credential-chain fallback), `ANTHROPIC_BASE_URL`
  (proxy redirect), `ANTHROPIC_MODEL` (silent override — the model is
  config-driven via `--model`), `CLAUDE_CODE_USE_BEDROCK`/`_USE_VERTEX` (3P
  provider billing) — each, if present, would bill or route off the Pro
  subscription exactly as a stray API key would. This extends ADR-18's named
  variable but is squarely its stated mechanism; flagged for approval as an
  extension, not slipped in as a new ADR.
- **Pidfile-only tracking — no in-memory process registry.**
  `is_execution_alive` is called by the reconciler in a fresh post-crash
  process, where an in-memory dict would always be empty anyway, and `run()`
  is synchronous with recovery being startup-only (doc 01: single machine,
  single writer, sequential — no lock needed). The on-disk pidfile is
  therefore the sole crash-correct source of truth. This simplified an earlier
  design-doc sketch that included a registry.
- **Image-identity check, not a hardcoded process name.** `is_execution_alive`
  compares the *current* image name of a pid against the image name recorded
  in the pidfile *at spawn time* — not a hardcoded `"claude.exe"` — because the
  real child on Windows runs as `node.exe`/`cmd.exe` while unit-test dummies
  run as `python.exe`; a hardcoded name would either miss the real child or
  never match the test double. This also strengthens the PID-reuse defense (a
  reused pid must coincidentally hold the *same* executable to fool it).
- **Fixture, not a worker crash-point, for the orphan-reaping proof (f4/I-n).**
  A live worker can't be reliably timed to die at the exact instant a real
  child is mid-run, and the blocking `run()` can't self-kill from inside — so
  this is exactly the class of post-crash state the harness's existing
  fixture mechanism (f1/f2) exists for, not a new crash-point family. f4
  exercises the real production path end to end: `_write_pidfile`,
  `reap_orphans`, `is_execution_alive`, and `recover()`+`bind_reconciler` with
  `is_execution_alive` bound.
- **`--allowedTools` allowlist deliberately deferred, not decided here.** Doc
  02 §3's exact tool-scoping (which of Bash/Edit/Write/... the agent needs)
  depends on `config.project.validation.commands`, which the engine never
  reads by design (doc 09 §7: the engine takes only `config.engine`). Building
  that allowlist belongs to the context-pack/orchestrator session, which
  already needs that same config. `--permission-mode acceptEdits` is the
  conservative default in the meantime (auto-accepts file edits; denied tools
  record a `permission_denial` rather than hanging on a TTY prompt that
  print-mode can't show anyway).

## Key Files
- `docs/12-session4-engine-wrapper.md` — as-built record: full VERIFIED/ASSUMED
  split, all decisions with doc-precedence citations, the `max_turns`
  resolution, and the f4/I-n fixture design. Read this first for full
  reasoning; this handoff is the session-flow summary of the same work.
- `src/runtime/engine/claude_headless.py` — `ClaudeHeadlessEngine`,
  `EngineResult`, `EngineError`, `EngineEnvError`. Every design decision is
  inline in the module docstring (VERIFIED CLI contract, pid discipline
  ruling, the Windows tree-kill known-limitation) and per-method — mirrors
  `git_adapter.py`'s idempotency-contract documentation style.
- `src/runtime/engine/__init__.py` — package exports.
- `tests/unit/test_engine.py` — 14 tests via a `_DummyEngine` that substitutes
  a Python child through the `_command()` test seam (no real `claude` CLI in
  unit tests: slow, non-deterministic, would bill real usage if it leaked).
  Covers env-hygiene (strip + fail-fast + apiKeySource witness), the
  stdin-timeout fix, tree-kill, transcript survival across a kill, advisory
  parsing edge cases (empty/malformed/partial transcripts), and pidfile
  lifecycle (clean removal, unknown execution, stale-pid cleanup).
- `tests/crash/harness.py` — new `run_engine_orphan_fixture` (fixture f4) +
  invariant I-n documented at the top of the file alongside I-a…I-m. Wired
  into `run_fixtures()`; skips cleanly if `claude` is not on PATH (it wasn't
  skipped this session).
- `NEXT.md` — updated resume pointer; points at Session 5 (orchestrator loop),
  with the exact startup-order sequence and where `--allowedTools` finally
  gets decided.

## Next Action
Session 5 per doc 07 ordering: the orchestrator loop, replacing `main.py`'s
foundation-only CLI. Concretely: startup order `config → log →
engine.reap_orphans() → recover(is_execution_alive=engine.is_execution_alive,
**bind_reconciler(...)) → health checks → loop` (the harness worker's
`step()` shape is the template — see doc 12 §1.6 and fixture f4 for the exact
call sequence); a concrete Validator (doc 09 §6.5, runs
`config.project.validation.commands`); a Reviewer provider (ADR-05, qwen or
claude); the context pack (doc 02 §5) — which is also where the engine's
`--allowedTools` allowlist finally gets decided, since it needs the same
validation-commands config; and budget metering (ADR-09) off
`EngineResult.usage.dollars`.

## Knowledge Captured
- **`claude` 2.1.207 has no `--max-turns` flag** (present in some earlier
  version the doc-11 sketch was apparently written against) — replaced by
  `--max-budget-usd` (a dollar cap, not a turn cap). `--settings
  '{"maxTurns":N}'` does not substitute for it: settings-file keys that don't
  validate are silently dropped in print mode, confirmed by running a capped
  and uncapped task side by side and observing identical `num_turns`. Anyone
  re-verifying this contract on a CLI upgrade should re-run that same
  side-by-side probe rather than trusting `--help` text alone (the flag being
  *absent* from `--help` was the first signal, but `--settings` silently
  failing needed an actual run to catch).
- **On Windows, `claude` is an npm `.CMD` shim**, not a direct executable:
  `shutil.which("claude")` resolves it correctly, but a bare
  `Popen(["claude", ...])` raises `FileNotFoundError` — confirmed directly
  (`shutil.which` → `claude.CMD`; bare string → `WinError 2`). The engine
  resolves the executable once at construction and uses the resolved path for
  every spawn.
- **A stream-json `result` line's `apiKeySource` field is a genuine in-band
  ADR-18 witness** — it reads `'none'` under a clean subscription strip and
  something else (e.g. `'ANTHROPIC_API_KEY'`) if a credential leaked through,
  independent of whatever the strip logic itself did. This gave a second,
  cheap layer of defense beyond the env-dict manipulation, verified directly
  by the invalid-key live smoke test.
- **The pid recorded in `ExecutionSpawned`/`ExecutionFinished` is the
  orchestrator/writer's pid, never an engine child's** — confirmed by reading
  `tests/crash/worker.py` (both events record `os.getpid()`) and harness
  invariant I-h (asserts they're equal, as the never-replayed rule). This
  resolved a design fork before any code was written: `EngineResult` correctly
  carries no pid field, and the engine child's pid is scoped entirely to the
  pidfile mechanism.

## Assumptions
- Whether `claude` spawns tool subprocesses as true OS-level children
  requiring tree-kill was never directly exercised — the live smoke test and
  unit tests used no tools beyond a plain text reply. `_kill_tree` is written
  defensively (always tree-kill) regardless of this being unconfirmed. MED
  confidence the defensive design is sufficient even if unconfirmed, since a
  single-process kill is a strict subset of what tree-kill covers.
  **Recommend:** exercise this directly in Session 5 once the engine is driven
  with a real prompt that invokes Bash/Edit tools, ideally under a deliberate
  timeout to confirm the grandchild dies too.
- Power-loss (not process-crash) durability remains out of scope, same
  precedent as Sessions 2–3 (git ref/object fsync is `core.fsync`-dependent;
  kill-tests prove process-crash durability only). HIGH confidence this is
  the correct scope boundary — no new reasoning introduced this session, just
  inherited.
- The `--allowedTools`/`--permission-mode` scoping is conservative
  (`acceptEdits`, no explicit allowlist) rather than fully resolved. MED
  confidence this is correctly sequenced rather than a gap: the orchestrator
  session needs `config.project.validation.commands` for the context pack
  regardless, so deferring the tool allowlist to the same session avoids
  building it twice against incomplete information.

## Testing / Verification Performed
- PASS: unit suite, run twice this session — once after initial
  implementation (74/74, `.venv/Scripts/python.exe -m pytest tests/unit -q`),
  once again after the final docstring pass to confirm no regression (74/74,
  same command, both observed directly in tool output this session).
- PASS: full crash harness, seed 42 — 51/51 scenarios (the prior 50 plus new
  `fixture[f4-engine-orphan]`), observed directly in tool output.
- PASS: full crash harness, seed 1337 — 51/51 scenarios, independently
  observed in a separate run.
- PASS: mutation M3 (gut `reap_orphans` to a no-op) — confirmed red on
  **both** the unit test `test_reap_orphans_kills_survivor` (empty repairs,
  survivor left alive) and the harness fixture f4 (same failure mode plus the
  execution never reaching CRASHED, since `is_execution_alive` still reported
  it alive), observed directly this session, then reverted and re-verified
  green on both.
- PASS: mutation M4 (drop the `ANTHROPIC_API_KEY` strip from
  `_hygienic_env`) — confirmed `test_subscription_strips_api_key` fails with
  the leaked key literally visible in the dummy child's captured environment
  (`KEY='sk-should-be-stripped'`), observed directly, then reverted and
  re-verified green.
- PASS: live smoke test — `ClaudeHeadlessEngine.run()` against a real scratch
  git repo, with `ANTHROPIC_API_KEY=sk-ant-invalid-deliberately-wrong-key`
  exported in the parent shell. Run succeeded (`exit_status=0`,
  `result="SMOKE_OK"`, transcript's `apiKeySource` field read `"none"`) —
  observed directly this session. This is the observable, zero-cost-on-failure
  proof requested in plan review FIX 5: had the strip failed, the invalid key
  would have produced a loud auth error instead of silent billing; success
  here means the strip worked and the run authenticated via the `/login`
  subscription profile.
- NOT TESTED: the real orchestrator loop, Validator, Reviewer, budget manager,
  queue, context pack (all out of scope through Session 4, per existing
  project scope — same boundary as prior sessions). Tool-subprocess tree-kill
  against a real `claude` child running actual tools (see Assumptions). Any
  platform other than this Windows machine.

## Technical Debt
- `--allowedTools` allowlist is not finalized (see Decisions & Assumptions
  above) — intentional, deferred to the orchestrator/context-pack session
  which needs the same config input.
- `delete_attempt_refs` (ADR-15 GC) remains implemented but unwired from
  Session 3 — unchanged this session, still belongs to the orchestrator's
  post-`IssueCompleted` step.

## User Constraints
- Architecture is FROZEN; doc 03 wins any conflict; changes require an ADR,
  not ad hoc edits. No architecture changes were made — the engine wrapper is
  new code implementing an already-approved (doc 11 §4, now doc 12) seam;
  `max_turns`'s enforcement mechanism was resolved through user consultation
  (AskUserQuestion) precisely because the original CLI-flag assumption turned
  out to be false, not because the frozen design changed.
  Honesty discipline: every session summary must separate what was verified
  (ran it, saw it pass) from what is assumed; never report a test as passing
  without running it. Applied throughout this handoff and doc 12.
- Target repo path, branch, and test commands are CONFIG ONLY — nothing under
  `src/` may hardcode them. The engine takes `config.engine` and
  per-call `execution_id`/`prompt_file`/`workspace` arguments; verified by
  inspection of `claude_headless.py` (no path/branch/command literals found
  beyond the doc-02-mandated CLI flags themselves).
- ANTHROPIC_API_KEY must stay unset in this development environment for
  Claude Code sessions themselves — confirmed unset throughout this session
  (checked before every live/smoke invocation); the one deliberate exception
  was the FIX-5 invalid-key smoke test, which used an obviously-fake value
  specifically to prove the strip without any risk of real billing.
- Plan-mode review fixes (six, from the user's plan-approval message) were
  all applied before implementation began: stdin-timeout hole (communicate),
  assert→raise for the billing invariant, image-identity pidfile check
  (not a hardcoded name), two implementation-step-1 verification items (pid
  ruling + env-var enumeration), the invalid-key observable smoke test, and
  the `exit_status: Optional[int]` → `int` type nit. All six are reflected in
  the shipped code and doc 12.

## Runtime & System State
- **Working tree is NOT committed as of this handoff** — per the standing
  git-safety rule (commit only when explicitly asked), the session's changes
  are staged in the working tree but no commit was made. `git status --short`
  shows: modified `NEXT.md`, `tests/crash/harness.py`,
  `knowledge/.sweep/sweep.log` (pre-existing, unrelated to this session);
  new `docs/12-session4-engine-wrapper.md`, `src/runtime/engine/`,
  `tests/unit/test_engine.py`. `git diff --stat` against the prior checkpoint
  (`1d60374`) for the tracked-file changes: `NEXT.md` +58/-22,
  `tests/crash/harness.py` +114, plus the new untracked files. **If this
  project's established checkpoint-per-session convention (Sessions 2 and 3
  both ended with a commit) should continue, the next action is a commit —
  ask the user to confirm before creating one.**
- Prior commit: `1d60374 Correct handoff: config.yaml gap was resolved in a
  parallel session` (session-3-era checkpoint chain).
- Two scratch artifacts from this session's live testing were left in the
  scratchpad directory (`smoke_repo`, `smoke_artifacts` under
  `.../scratchpad/`) after a cleanup command was denied by the permission
  system — harmless, session-scoped scratch content, not part of the repo.
- No background processes, dev servers, or open worktrees remain (both
  background harness runs completed and were read to completion).

## Open Questions
**Needs User Input**
- Should this session's changes be committed as a checkpoint now, matching
  the Session 2/3 pattern? (Not done automatically per the git-safety
  standing rule — awaiting explicit confirmation.)
- None of the substantive design questions from the plan-approval review
  remain open — all six requested fixes were applied, and the `max_turns`
  mechanism question was resolved via AskUserQuestion mid-session (reactive
  enforcement chosen; option 2 — preventive live-stream counting — was
  explicitly rejected by the user and is not implemented).
