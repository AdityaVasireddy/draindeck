# Session Handoff — Session 8: ADR-22 accepted, mechanism landed, committed

## Objective
Session 8 opened with a single gate blocking Step 3 (gated live smoke): ADR-22
(engine-child ambient-hook isolation, doc 08 §5c) was drafted Proposed at the
end of Session 7, with the option selection pending. This session's job was to
mark it Accepted per the option the user endorsed (gated by external review),
land the mechanism in `src/`/`config.yaml`, gate it behind the full test +
durability suite, and commit — closing NEXT.md item 1.

## Current Status
- Completed: ADR-22 marked Accepted (doc 08 §5c); mechanism landed
  (`--setting-sources ""` in the engine argv + config-driven `engine.child_env`
  merged in `_hygienic_env()`); 3 new unit tests; 106/106 unit suite; 60/60
  durability harness on both seeds; doc 14 §2.5 as-built record with
  corrected, per-claim evidence labels; NEXT.md item 1 closed, Step 3 marked
  UNBLOCKED-but-not-started with 6 separate unconfirmed preconditions listed.
  Two commits made: `4115b4e` (mechanism) and `1df420b` (NEXT.md
  strengthening — Step-3 argv gate reframed as hard, not checklist; ADR-22 B
  sunset tickle added).
- Blocked: none. Step 3 itself remains not-started — separate preconditions
  (real validation command, Ollama+qwen2.5-coder, Issues.md, baseline green,
  `.gitignore` hygiene, plus a new item 0 argv gate) are unconfirmed and out
  of scope for this session by explicit instruction.

## Decisions & Rationale
- **ADR-22 Accepted: A-empty + B, B under a sunset condition** — the option
  set endorsed via external review at session start. A-empty
  (`--setting-sources ""`) preferred over `project,local` because the empty
  value loads NO settings scope, whereas `project,local` still loads
  project/local scope from the child cwd (the target repo on the production
  path) — a residual cross-run injection vector. B
  (`HISTORIAN_SWEEP_ACTIVE=1`) is config-driven (`engine.child_env`) so the
  machine-specific var name lives in config, not `src/`. Landed in
  `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md`
  §5c "Accepted decision" subsection.
- **`_hygienic_env()` merges `child_env` before the ADR-18 strip, not after**
  — the strip must always win (a `child_env` key colliding with a strip-list
  entry, e.g. `ANTHROPIC_API_KEY`, ends up stripped, never present). This
  was a load-bearing ordering decision, verified by a result-shape unit test
  (asserts on the final env dict, not call order) in
  `C:\Projects\issue-runtime\tests\unit\test_engine_adr22.py`.
- **Argv empty-token survival — label corrected mid-session after external
  review.** An earlier draft claimed VERIFIED on the rationale "no shell-join
  anywhere in the path to `Popen`" — that's false on Windows (`Popen` with a
  list argv does join via `subprocess.list2cmdline()` before
  `CreateProcess`). Corrected in `docs/14-session6-phase2-gate.md` §2.5 by
  splitting the claim into two independently-labeled legs: (1) Python-side
  handoff, VERIFIED via a live spawn this session (real `_command()` output,
  unmodified, spawned through real `subprocess.run()`, dummy child echoing
  its received `sys.argv`); (2) CLI-side interpretation, VERIFIED via the
  pre-existing doc 14 §2.4 Probe 2/3 (live `claude` 2.1.211, hand-built argv
  predating this session). The two legs were never composed into one live run
  through `ClaudeHeadlessEngine.run()` against the real `claude` binary —
  flagged explicitly as a residual gap, not glossed over.
- **That residual gap reframed as a hard gate on Step 3's live smoke, not a
  checklist line** — per the reviewer's explicit follow-up: if the composed
  path (real `_command()` → `Popen` → OS join/resplit → real `claude`)
  mangles the empty token in a way neither isolated leg predicted, the smoke
  is where it would surface, so it must be observed to pass before the smoke
  is judged to validate anything else. Landed as item 0 in NEXT.md's Step-3
  preconditions list.
- **Standing tickle added for ADR-22's B-layer sunset** — per the reviewer's
  second follow-up: a sunset condition gated on a future CLI-upgrade event,
  with nothing pointing at it, tends to silently outlive its own rationale.
  Added as a new top-of-file section in `NEXT.md` ("STANDING TICKLE") rather
  than buried in the Session-8 resume-point prose, so it survives future
  resume-point rewrites.
- **`knowledge/.sweep/sweep.log` excluded from both commits** — ambient
  output from the operator's own engineering-historian `SessionEnd` hook
  (unrelated to this session's product), following the exact precedent set in
  Session 7's handoff. Confirmed via `git diff` that the only change was an
  auto-appended sweep-log line, not session content.

## Key Files
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md`
  — ADR-22 §5c, now Accepted; the "Accepted decision" subsection has the
  binding mechanism description and the upgrade re-pin discipline.
- `C:\Projects\issue-runtime\docs\14-session6-phase2-gate.md` — §2.5, the
  full as-built record with the corrected per-claim evidence labels (argv
  survival split into two legs; harness invocation lines + environmental
  deviation note; test identities, not just counts).
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` —
  `_command()` (the `--setting-sources ""` addition) and `_hygienic_env()`
  (the `child_env` merge, ordered before the ADR-18 strip).
- `C:\Projects\issue-runtime\src\runtime\config.py` — `EngineCfg.child_env`.
- `C:\Projects\issue-runtime\config.yaml` — `engine.child_env:
  {HISTORIAN_SWEEP_ACTIVE: '1'}`, commented with the sunset condition.
- `C:\Projects\issue-runtime\tests\unit\test_engine_adr22.py` — new file, 3
  tests; read this alongside doc 14 §2.5 since the doc explicitly describes
  what each test does and does not prove.
- `C:\Projects\issue-runtime\NEXT.md` — item 1 closed; new top-of-file
  STANDING TICKLE section (B-layer sunset); Step-3 preconditions list with
  the new item-0 hard gate.

## Next Action
Session 9 (or whenever Step 3 is picked up) should NOT begin Step 3 directly
— first work through NEXT.md's "Step 3's OWN separate preconditions" list,
starting with item 0 (the live end-to-end argv re-witness through
`ClaudeHeadlessEngine.run()` against the real `claude` binary), which is a
hard gate, not optional preflight. The other five preconditions (real
validation command, Ollama+qwen2.5-coder, Issues.md, baseline green,
`.gitignore` hygiene) are all still unconfirmed as of this session.

## Testing / Verification Performed
- PASS: `./.venv/Scripts/python.exe -m pytest tests/unit -q` → 106 passed,
  `--collect-only` used to confirm total (106) and the new file's 3 named
  tests, not arithmetic alone.
- PASS: `./.venv/Scripts/python.exe tests/crash/harness.py "$TEMP/ch2" 42` →
  ALL 60 SCENARIOS PASSED.
- PASS: `./.venv/Scripts/python.exe tests/crash/harness.py "$TEMP/ch3" 1337`
  → ALL 60 SCENARIOS PASSED.
- PASS (environmental note): both harness paths initially hit
  `PermissionError` on `shutil.rmtree` during the harness's own pre-flight
  calibration reset, caused by stale Windows-read-only git-object files left
  from an unrelated 2026-07-11/13 scratch run (predates this session, outside
  the repo). Failures occurred before any scenario ran; nothing partial was
  folded into the reported 60/60. Cleared via `os.chmod(path,
  stat.S_IWRITE)` walked over the stale tree, then each seed ran clean on its
  first full attempt.
- PASS (live spawn, this session): real `_command()` output spawned through a
  real Windows `subprocess.run()`, dummy Python child echoing its received
  `sys.argv` — confirmed the `--setting-sources`/`''` pair arrived as two
  adjacent elements with the empty string intact. `subprocess.list2cmdline()`
  also inspected directly and confirmed to render the empty token as `""`
  rather than dropping it.
- NOT TESTED: a single live run of `ClaudeHeadlessEngine.run()` against the
  real `claude` binary (composing both argv-survival legs into one witnessed
  path) — explicitly queued as NEXT.md Step-3 item 0, not done this session.
- NOT TESTED: Step 3 itself (gated live smoke) — out of scope, not started.

## User Constraints
- No commit without explicit request — held through the plan/execute/review
  sequence; committed only after the user's explicit "clear to commit"
  verdict following the evidence-pack exchange.
- Architecture frozen; mechanism changes go through an ADR — followed: ADR-22
  was marked Accepted before any `src/` change landed.
- Honesty discipline (separate VERIFIED from ASSUMED/INFERRED in every
  summary) — this was the central corrective of the session: an initial
  VERIFIED label on argv-survival was downgraded and re-evidenced after
  review found its stated rationale factually wrong on Windows.
- Kill criteria (ADR-19) not touched this session.
- Config-only machine-specific values — followed: `HISTORIAN_SWEEP_ACTIVE`
  lives in `config.yaml`, not hardcoded in `src/`.

## Runtime & System State
- Commit at handoff: `1df420b` on branch `master` (issue-runtime is the build
  repo, `master`-only; `agent-work` is the target repo's branch, not this
  repo's).
- Working tree: clean except the pre-existing, ambient
  `knowledge/.sweep/sweep.log` change (historian hook output, deliberately
  left unstaged, same pattern as Session 7).
- No background processes, dev servers, or open worktrees from this session.

## Open Questions
**Model Uncertainty**
- Whether the composed argv-survival path (real `ClaudeHeadlessEngine.run()`
  → real `claude` binary) behaves identically to the two separately-witnessed
  legs is genuinely open — not just a formality. Node's own command-line
  parser (which `claude`'s `.CMD` shim runs under) was not directly probed
  with the *exact* production argv this session; the §2.4 probe used a
  hand-built mirror. This is why NEXT.md item 0 is a hard gate rather than a
  formality to wave through.
