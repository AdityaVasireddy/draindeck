# 12 — ClaudeHeadlessEngine (Session 4)

**Status:** IMPLEMENTED & VERIFIED · **Date:** 2026-07-12
**Scope:** Session 4 per doc 07 ordering. Makes the engine boundary real:
`ClaudeHeadlessEngine` (ADR-08 concrete, no abstraction), wall-clock
timeout/kill, ADR-18 env hygiene enforced per spawn, and a new crash-harness
fixture (f4/I-n) proving orphan reaping actually works. Doc 03 is the frozen
contract; doc 03 won every conflict. Doc 11 §4's engine sketch is superseded by
this document — it is no longer provisional.

## Verified vs. assumed (honesty discipline)

**VERIFIED by running this session (Windows, `claude` 2.1.207, `.venv` python):**
- CLI contract: `-p`/`--print` accepts the prompt on **stdin** (no positional
  arg needed); `--output-format stream-json` requires `--verbose` in print
  mode; the final `result` line carries `usage{input_tokens,output_tokens}`,
  `total_cost_usd`, `num_turns`, `stop_reason`; the `system`/`init` line
  carries `apiKeySource` (`'none'` under subscription with no key).
- **No `--max-turns` flag** in 2.1.207 (removed since the doc-11 sketch was
  written). **`--settings '{"maxTurns":N}'` is silently ignored** in print
  mode — confirmed empirically: a 2-turn task ran identically capped and
  uncapped (`num_turns=2` both times, `terminal_reason=completed`). Resolved to
  **reactive** enforcement (§3 below).
- pid discipline (I-h): `tests/crash/worker.py`/`harness.py` record the
  **orchestrator/writer** `os.getpid()` in both `ExecutionSpawned` and
  `ExecutionFinished`, never an engine child pid — confirmed by reading, not
  assumed. The engine child pid lives only in the pidfile.
- On Windows, `claude` resolves via `shutil.which` to a `.CMD` shim; a bare
  `Popen(["claude", ...])` raises `FileNotFoundError` — confirmed directly.
- 74/74 unit tests (`python -m pytest tests\unit -q`, 66 prior + 8 new).
- 51/51 harness scenarios on seeds 42 AND 1337 (50 prior scenarios + new
  fixture **f4-engine-orphan**, all passing on both seeds).
- Mutation **M3** (gut `reap_orphans` to a no-op): both the unit test
  `test_reap_orphans_kills_survivor` and harness fixture f4 went red (empty
  `repairs`, survivor left alive). Reverted, re-verified green.
- Mutation **M4** (drop the `ANTHROPIC_API_KEY` strip): unit test
  `test_subscription_strips_api_key` went red — the leaked key was visible in
  the child's environment. Reverted, re-verified green.
- Live smoke run: `ClaudeHeadlessEngine.run()` against a real scratch git repo,
  with a **deliberately invalid** `ANTHROPIC_API_KEY` exported in the parent
  shell (`sk-ant-invalid-...`). Run succeeded (`exit_status=0`,
  `result="SMOKE_OK"`, `apiKeySource="none"` in the transcript) — proving the
  strip worked and auth fell through to the `/login` subscription profile. Had
  the strip failed, the invalid key would have caused a loud auth error
  instead of silent billing (the observable, zero-cost-on-failure design from
  the approved plan's FIX 5).

**ASSUMED / NOT verified:** whether `claude` spawns tool subprocesses as true
OS-level children requiring tree-kill (the live smoke and unit tests used no
tools beyond a plain reply, so this specific case was never exercised;
`_kill_tree` is written defensively — tree-kill by default — regardless). Any
platform other than this Windows machine. The exact tool-scoping doc 02 §3 calls
for is deliberately deferred to the orchestrator session. Power-loss durability
(same scope boundary as Sessions 2–3's harness — kill-tests prove process-crash
durability only).

> **CORRECTION (Session 5, 2026-07-12).** This document's assumption that the
> engine would be fenced by a `--allowedTools` allowlist, and the shipped
> docstring's claim that "in -p mode a disallowed tool is recorded as a
> `permission_denial` rather than blocking," were both **falsified by probe**
> against `claude` 2.1.207: `--allowedTools` does not restrict at all in `-p`
> mode (a tool matching neither allow nor deny simply runs), so no
> `permission_denial` was ever produced by an allowlist. The engine is instead
> fenced by an explicit **denylist** (`--disallowedTools`, the only mechanism
> that enforces). See **ADR-21** (doc 08 §5b) and the corrected
> `engine/claude_headless.py` docstring. Tree-kill under a real timeout (the
> other assumption above) was **confirmed** in Session 5's probe for an intact
> process tree; the reparented-grandchild escape remains the documented,
> unexercised limitation (§1.5).

---

## 1. `ClaudeHeadlessEngine` (`src/runtime/engine/claude_headless.py`)

### 1.1 Stance
ADR-08: the sole concrete engine, no abstraction layer. Constructed once from
`config.engine` and an `artifacts_dir` that lives under the runtime's own
state directory — **never** inside the target repo, or every
transcript/pidfile would trip reconciler check 3 / `is_dirty()`. The wrapper
never touches git and never appends events: it stays strictly on the
subprocess/artifacts side, matching doc 02 §3's advisory-output principle
(ADR-02/07) — an engine can lie in its summary, never in the diff, so nothing
on `EngineResult` may gate a transition. `RepositoryAdapter` (via
`recovery/bindings.py` and the future orchestrator) owns every git contact;
doc 03 §5 owns every event.

### 1.2 `EngineResult` — advisory contract
`exit_status`, `timed_out`, `duration_s`, `usage {input_tokens, output_tokens,
dollars}` (dollars ← `total_cost_usd`), `num_turns`, `transcript_path`,
`stderr_tail`. No pid, no success flag, no file list, no diff, no summary —
treating this as truth is structurally impossible. `exit_status`/`timed_out`
may only select which doc 03 §5 row the orchestrator records (the timeout row
vs. the normal-exit row); `num_turns` is an **explicit extension of that same
carve-out** (§3 below) — engine-reported, and only ever used to pick a row,
never to judge whether work "worked".

### 1.3 Spawn, timeout, and the stdin fix
`argv`: `claude -p --output-format stream-json --verbose
--no-session-persistence [--model M] --permission-mode acceptEdits`. The
prompt is delivered via `proc.communicate(input=prompt_bytes,
timeout=cfg.timeout_seconds)` — **never** a bare `stdin.write()` followed by
`wait()`. A child that dies early, wedges before reading stdin, or fills the
pipe buffer while not draining would otherwise block the parent inside
`write()`, *before* any `wait(timeout=...)` line — punching a hole in doc 02
§3's "hard wall-clock timeout" (this was FIX 1 from the approved plan review;
`communicate()` covers the write + wait + timeout as one operation since
stdout/stderr are already file handles, nothing else to drain). stdout/stderr
are redirected to `artifacts/<execution_id>/{transcript.jsonl, stderr.log}` at
spawn time — never buffered through pipes in the parent, so a killed process
leaves a valid *partial* transcript (line-oriented stream-json) instead of one
truncated JSON blob.

### 1.4 ADR-18 env hygiene — enforced per spawn
`_hygienic_env()` rebuilds the child environment from scratch on **every**
call — no startup-check-then-drift window. Subscription mode strips six vars,
not just the named one: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `CLAUDE_CODE_USE_BEDROCK`,
`CLAUDE_CODE_USE_VERTEX` — each, if present, could bill or route off the Pro
subscription (auth-token credential chain, a 3P-provider redirect, a proxy
base URL, or a silently overridden model). The strip is enforced with a
`raise EngineEnvError`, **never** an `assert` (FIX 2 — asserts vanish under
`python -O`, and this is a billing invariant). api_key mode fails fast,
pre-spawn, if the key is absent. A second, in-band witness closes the loop:
after the run, the engine parses the transcript's `init` line and raises
`EngineEnvError` if `apiKeySource != 'none'` in subscription mode — a leaked
credential cannot go unnoticed even if the strip logic itself had a bug the
unit tests missed.

### 1.5 Kill semantics and the known tree-kill gap
A timeout tree-kills: Windows `taskkill /F /T /PID <pid>` (force, tree); POSIX
`os.killpg` on a process group established via `start_new_session=True`.
`taskkill`'s nonzero exit on a pid that already exited in the race window is
**tolerated**, not treated as an error (the caller reaps unconditionally
either way). **Known limitation:** `taskkill /T` walks the tree *at kill
time* — a grandchild whose parent already exited is reparented and escapes
the sweep, and since only the direct child pid lives in the pidfile,
`reap_orphans`/`is_execution_alive` cannot observe such a survivor either.
Reconciler check 3 (dirty workspace) is the partial backstop for anything
dirtied *before* recovery ran; a survivor dirtying the workspace *after*
recovery is invisible until the next `is_dirty()` witness. Accepted for v1 —
no psutil (deps stay frozen to pyyaml/pydantic/pytest).

### 1.6 Recovery integration — pidfile-only, no in-memory registry
`is_execution_alive(execution_id)` is called by the reconciler in a **fresh
post-crash process**, where an in-memory registry would always be empty
anyway; and `run()` is synchronous with recovery startup-only (doc 01: single
machine, single writer, sequential — confirmed, no lock needed), so there is
never an in-process concurrent query. The on-disk pidfile — `{pid, image,
started_at}`, image captured **at spawn** — is therefore the sole source of
truth. `is_execution_alive` compares the pidfile's recorded image against the
pid's *current* image (Windows `tasklist`/POSIX `ps`, no psutil) to defeat PID
reuse (FIX 3 — a hardcoded name like `claude.exe` would either miss the real
child, which under Windows runs as `node.exe`/`cmd.exe`, or falsely match a
Python test dummy; recording the actual spawned image is what makes the check
correct in both places).

`reap_orphans()` is the new startup pre-step, run **before** `recover()`: it
walks every surviving pidfile, tree-kills anything still alive, and reports
what it killed (no event — doc 03 has no vocabulary for it, same reasoning as
check 3's `workspace_repairs`). After it runs, `is_execution_alive` is False
for every open execution, so reconciler check 1 correctly crashes them all —
doc 03's "EXECUTING is abandonable, never resumed" is preserved; the wrapper
never adopts a surviving orphan, only kills it and lets check 1 do its normal
job. This also restores the ADR-04 single-writer precondition that
`recover_workspace`'s stale-lock removal already presumes.

---

## 2. `max_turns` — resolved as reactive (option 1)

The doc-11 sketch assumed a `--max-turns` CLI flag; it does not exist in
`claude` 2.1.207, and `--settings '{"maxTurns":N}'` is silently ignored in
print mode (verified empirically this session — see above). After the
options were weighed against the user, **reactive enforcement** was chosen:
the engine reports `num_turns` (from the result line) on `EngineResult`; the
**orchestrator** compares `num_turns >= cfg.max_turns` and, on breach, records
doc 03 §5's turn-budget row — `IssueEscalated(NEEDS_DECOMPOSITION,
reason=decompose, taxonomy_category=needs-decomposition)`. This is event #10
in doc 03 §3 and the exact event named in §5's "EXECUTING (context blowout) |
budget=context/turns | escalate for splitting" row — no invented event, and a
row distinct from the wall-clock-timeout row (`ExecutionFinished(REJECTED,
taxonomy=timeout)`, driven by `timed_out`). The wall-clock `timeout_seconds`
remains the hard runaway backstop regardless of turn count; `--max-budget-usd`
(also new in 2.1.207) is available as a future dollar-bound lever if a config
field for it is added later.

---

## 3. Crash-harness fixture f4 (I-n)

Implemented as a **planted fixture** (`run_engine_orphan_fixture`, alongside
f1/f2), not a worker crash-point: a live worker cannot be reliably timed to
die at the exact instant a real child is mid-run, and the blocking `run()`
cannot self-kill from inside — exactly the class of post-crash state the
harness's fixture mechanism exists for (docs/11 §3.4's own framing). f4 spawns
a **real** long-lived Python child that dirties the workspace, writes its
pidfile via the **production** `ClaudeHeadlessEngine._write_pidfile`, plants a
matching `EXECUTING` execution in the log, then runs the production startup
order (`reap_orphans()` → `recover(is_execution_alive=...,
**bind_reconciler(...))`). New invariant **I-n**: the orphan is reaped
(reported + verified dead), the orphaned execution is CRASHED with a non-null
`residue_ref`, and no pidfile remains. Skips cleanly if `claude` is not on
PATH (it wasn't skipped in this session — `claude` was resolvable throughout).
Mutation M3 (gut `reap_orphans`) turns it red on all three checks
simultaneously (empty repairs, live survivor, execution never reaches
CRASHED because `is_execution_alive` still reports it alive) — the harness
run count rose from 50 to **51**.

---

## 4. Files
New: `src/runtime/engine/{__init__,claude_headless}.py`,
`tests/unit/test_engine.py`, this document (`docs/12-...`). Changed:
`tests/crash/harness.py` (new fixture `run_engine_orphan_fixture` + I-n
docstring, wired into `run_fixtures`). No change to the frozen contract
(doc 03), the event schema, or `main.py` (still foundation-only per its own
docstring — the orchestrator loop that would call `reap_orphans`/`run` in
production doesn't exist yet; that startup-order wiring is proven here via the
harness fixture instead, and lands for real when the loop does).
