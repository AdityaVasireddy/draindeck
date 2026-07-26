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

**Session 12 update (2026-07-24, CLI now 2.1.215): re-run COMPLETE, GREEN —
see doc 14 §2.7.** The STANDING TICKLE was overdue (CLI had drifted
2.1.212 → 2.1.214 → 2.1.215 with no re-probe done at 2.1.214, contrary to
Session 11's stated next action). All three legs re-run at 2.1.215 using
Session 11's surviving synthetic-control scripts (fresh scratchpad, fresh
probe cwds) plus a Leg-B-style production check: production argv via real
`ClaudeHeadlessEngine.run()` (PASS — `knowledge/` absent 450s, no `skips.log`
entry, `git init` denied both signals), synthetic Step B (PASS on a
corrected re-run — see doc 14 §2.7 for the cwd-comparison bug found and
fixed, not a real mechanism issue), synthetic Step C (PASS — marker absent
450s). **`claude_code_version` is now witnessed inside every transcript**
(the version-witness gap flagged as a risk in the prior handoff is closed).
**Decision: re-probe and hold B — do NOT sunset this cycle** (explicit user
instruction). `HISTORIAN_SWEEP_ACTIVE` stays in `config.yaml`. Tickle
re-armed for the next CLI bump.

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
Re-attempt the full two-leg re-run on the NEXT version bump. **Session 11
update (2026-07-18): the control leg now has a working replacement** — the
synthetic-hook positive control (see VACUITY-GUARD GAP below) — use THAT
control on the next re-pin instead of expecting the real ambient historian
hook to discriminate; it hasn't in three independent attempts and there's no
reason to expect a fourth to differ. The synthetic control only proves
`--setting-sources` suppression works going forward, not that it would have
caught the original historian bug specifically (permanently INFERRED) — see
below for the full framing.

## VACUITY-GUARD GAP (Session 9, 2026-07-17; RESOLVED going-forward Session 11, 2026-07-18 — see below) — distinct from the B-sunset tickle above
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

**Session 10 update (2026-07-17, same day): third independent data point,
still not resolved.** Item 0's live run (doc 14 §2.6 "RUN this session")
included a positive control — a second, differently-constructed control from
Probe A (direct mutated-argv spawn with the empty-token pair stripped,
rather than a separate ambient-settings run) — designed specifically to
answer this gap for that one run. It also did not reproduce contamination
(`knowledge/` absent across the full 450s poll with the isolation mechanism
deliberately removed). This does not newly break anything — Item 0's main
(unmutated) pass was clean and closes the argv-composition gap it was built
for — but it means the vacuity concern is now reproduced under two
independently-built controls, not one. **Still no position taken between (a)
and (b) below; still parked.** Treat "clean under `--setting-sources ""`" as
weaker evidence than it would be if either control had ever gone red.

**Decision that was needed before the next CLI-bump re-pin cycle relies on
the vacuity guard again — RESOLVED Session 11 (2026-07-18), see the Session
11 update further below for the built-and-run evidence:**
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

**Session 11 update (2026-07-18): Option (a) BUILT and RUN — control
restored, going forward. Decision made, not left parked.**

A synthetic, zero-gate assay hook (`synth-hook-marker.sh` — unconditional
`mkdir -p .synth-marker && write fired.txt`, no checks of any kind, exit 0)
was registered via a scratch **project-scope** `.claude/settings.json`
(`SessionEnd` + `PreCompact`, `type: command`, absolute path,
`async: false`, `timeout: 30`) in a throwaway probe cwd — never the real
`~/.claude/historian` hook, never touching machine config. Two separate
probe cwds were used (`probe_cwd_trigger`, `probe_cwd_empty`) so a leftover
marker from one step could never be misread as the other's result.

- **Step B (REQUIRED FIRST — prove the assay can go red).** Spawned via a
  scratch witness script (`witness_synth_control.py`, uncommitted,
  scratchpad-only) with a **mutated copy** of the real `_command()` argv
  (`--setting-sources ""` → `--setting-sources project`) against
  `probe_cwd_trigger`. **VERIFIED PASS**: marker present at t=0s (first
  poll tick — essentially immediate, `async: false` as designed),
  `event=SessionEnd`, `pid=229655` mechanically confirmed distinct from the
  witness script's own pid (`22956`), `cwd` field in the marker exactly
  matches `probe_cwd_trigger` (not a wrong-cwd write). `exit_status=0`,
  `apiKeySource="none"`. The assay's own trigger mechanism is proven to
  fire — this control has now been watched go red before being trusted.
- **Step C (only run after Step B passed — the real A-empty comparison).**
  Spawned with the **real, unmutated** `_command()` output
  (`--setting-sources ""`, production shape) against a fresh, separate
  `probe_cwd_empty`. **VERIFIED PASS**: marker absent at every one of 16
  polls across the full 450s window; `exit_status=0`, `apiKeySource`
  unchanged. The wrong-cwd scan (checked for `.synth-marker/fired.txt`
  anywhere under the scratch root, not just the expected path) found only
  Step B's own leftover marker in `probe_cwd_trigger` — confirming
  `probe_cwd_empty` genuinely never got one, not that the scan missed it
  elsewhere.

**What this establishes, and what it does not (both halves, deliberately,
per the plan that authorized this run):** A-empty suppresses this
synthetic, zero-gate, project-scope hook — a discriminating positive
control now exists, is owned by this project, and does not depend on
whatever state the real ambient historian hook happens to be in on any
given machine. Every future CLI re-pin can be re-run against this control
and get an interpretable answer. **This does NOT, and cannot, retroactively
upgrade "A-empty stopped the ORIGINAL historian contamination" from
INFERRED to VERIFIED** — the synthetic hook is not the original historian
code, and no artifact of the original bugged `historian-sweep.sh` survives
to diff against (confirmed again this session: `~/.claude/historian` is not
a git repo, no backup/transcript of the pre-patch script exists anywhere).
That specific historical claim stays **permanently INFERRED**. Do not read
this entry as "the vacuity gap is closed" — read it as "a working control
exists going forward; the original root-cause question is closed off from
ever being answered, and both facts are recorded, not one implying the
other."

**Decision recorded: Option (a) chosen over Option (b).** This resolves the
"no position taken" line below — struck as of Session 11. The counter-case
for (b) (a synthetic hook only proves `--setting-sources` behaves as
CLI-documented in general, not that it would have stopped the specific
original bug) was weighed and accepted as a known, permanent limitation,
not a reason to skip building a forward-looking control.

## Resume point

**Session 16 (2026-07-26): Step-3 precondition #4 (baseline non-vacuity, doc
08 §5d) CLOSED — VERIFIED, both legs witnessed this session.**

**#4 CLOSED — both legs of doc 08 §5d witnessed.**
- Collected>0 leg: rc=0, 26 passed (prior turn), cwd=StockPhotoAgent root.
- Mutation leg: red = rc=1 / collected 26 (1 failed + 25 passed) /
  assertion failure on `test_resolution_measure_score_below_minimum`;
  green-after-revert = rc=0 / exactly 26 passed; revert-clean = `git status
  --short` and `git diff` both empty on `resolution.py`.
- Mutation used (for reproducibility): `src/qc/rules/resolution.py:17`,
  `MIN_WIDTH_PX` 2000→500, reverted.
- Execution surface both legs: `subprocess.run(cmd, cwd=..., shell=True)` via
  `C:\Python314\python.exe`, matching `Validator._run_once`. Bash-tool
  results excluded.

**What remains OPEN — so "#4 CLOSED" is not over-read:**
- Item 0 (composed real-spawn through ClaudeHeadlessEngine.run()): RUN,
  clean-with-caveat — not unqualified pass, and not the gate it was
  mislabeled as this session. Still open: (a) the vacuity-guard positive
  control has never confirmed detectability (three independent
  non-reproductions per doc 14 — the mechanism's ability to detect
  contamination is unproven, only its failure to observe any); (b) every
  Item 0 run so far used a scratch workspace — live smoke would be the
  first run against a real target repo (doc 14's own note). What IS done:
  two clean composed runs — 2026-07-17 (CLI 2.1.212, doc 14 §2.6/2.7) and
  2026-07-24 re-probe (CLI 2.1.215) — exit 0, apiKeySource="none", denial
  signals present, .git/knowledge/ absent across the 450s poll. The earlier
  "unwitnessed/remains unwitnessed" wording in this session's artifacts was
  stale and wrong; doc 14 shows the composed run closed.
- ADR-23 end-to-end differential — still deferred behind its own
  three-part AND (env-witness script not built, and the "before" half
  unwitnessable for the Phase-2 change already landed).
- Standing tickle: doc 14 §2.4 Probe 2/3 two-leg re-probes at CLI 2.1.214 —
  untouched.

**Precondition roll-up: 1 MET, 2 CLOSED, 3 CLOSED, 4 CLOSED, 5 MET — all
five satisfied.** This clears the precondition wall but does **NOT**
authorize live smoke. The real gate is not "run Item 0" (already run,
clean-with-caveat — see above) — what actually stands between here and
live smoke is the parked vacuity-guard question (positive control has
never confirmed detectability) and the scratch-vs-real-repo step (Item 0
has only ever run against a scratch workspace, never a real target repo).

**Session-scope note:** scratch-only mutation session — no issue-runtime
`src/` logic changed. Durability harness (60/60, seeds 42/1337) correctly
SKIPPED per harness-gate convention (gates on `src/` logic changes only;
none occurred this session).

**Session 17 (2026-07-26): Dry-run A — composed-loop witness against a
scratch clone of StockPhotoAgent — PASS. The LOOP-COMPOSITION variable of
gate (b) is collapsed** (not all composition — see the carried-unwitnessed
list below, worded this way deliberately so this line and that list can't
be read as contradicting each other).

Built per an approved plan (`twinkling-twirling-crane.md`), scratchpad-only,
no `src/` change. A real `git clone` of StockPhotoAgent (HEAD-matched,
verified) stood in for the real tree; `Orchestrator` was constructed
directly against it with only the `claude -p` spawn stubbed (canned
patches) — `GitCliAdapter`, `Validator` (real pytest command),
`QwenOllamaReviewer` (real Ollama call), the event log, and
commit-on-approval all ran real and unstubbed.

Three cycles run 1→2→4 via explicit `step()` calls, each outcome adjudicated
against a pre-committed matrix from mechanical git + event-log evidence
only (attempt refs via `for-each-ref`, branch tips via `rev-parse`, taxonomy
categories from event payloads — never engine/reviewer self-report):
- **Cycle 1 (issue "1") → VALIDATION_FAILED: PASS.** `set_attempt_ref`-before-
  `reset_hard` witnessed on real committed residue (`refs/attempts/1/1-e1` →
  `22a29f43`, `issue/1` tip back at base `5e4018d2`).
- **Cycle 2 (issue "2") → REVIEW_REJECTED: PASS**, second reject-path
  ordering witness on a different reject leg (`refs/attempts/2/2-e1` →
  `58ec1f16`, tip back at base). Real Qwen reviewer correctly REJECTed a
  deliberately off-target patch — not scored toward the vacuity-guard
  question (different mechanism), but a genuine positive datapoint on the
  reviewer seam, sharpened by Cycle 3: the same reviewer drew the
  discrimination on BOTH sides in this run — REJECT on off-target (this
  cycle), APPROVE on on-target (Cycle 3) — which is the datapoint that
  actually matters; either side alone would be consistent with a reviewer
  that just rejects (or just approves) everything.
- **Cycle 3 (issue "4") → clean APPROVE → commit-on-approval: PASS.** Real
  Qwen APPROVE on an on-target patch; `CommitIntent`→`CommitCreated`
  (`backfilled: false`)→`IssueCompleted`; `agent-work` advanced
  `5e4018d2`→`5b76887e` via a real, non-backfilled merge; attempt refs GC'd
  on completion (ADR-15). The leg the pre-commit said might have to be
  carried forward unwitnessed was witnessed for real.

One process note, not a finding about any seam: a `stderr_tail`-missing bug
in the first stub attempt crashed mid-Cycle-1, leaving a partial
`EXECUTION_SPAWNED` and a dirty `issue/1`. Fixed the stub, then **wiped and
re-cloned fresh** rather than resuming through the crash — resuming would
have driven the orphan-crash recovery seam instead of the intended one.
Recorded so it isn't over-read either way: **this run did not witness the
orphan-crash recovery path**; the accidental partial-spawn is not evidence
about it.

**What this licenses:** live smoke now changes exactly one variable (clone
→ real tree) instead of two (composition + real tree) — gate (b)'s stated
objective, achieved for the loop composition.
**What remains UNWITNESSED, carried into live smoke as first-surface, not
to be described as "composition already witnessed":**
1. `main.py`'s end-to-end startup composition (health checks →
   `_ingest_issues` → loop, under the real CLI entrypoint) — this run
   bypassed it by constructing `Orchestrator` directly (recorded boundary,
   harness docstring).
2. The orphan-crash recovery path (see process note above).
3. Real-tree behavior itself — the irreducible remaining variable.
**Still UNPROVEN, untouched, carried into smoke labeled per standing
ruling:** the vacuity-guard detectability question (three independent
non-reproductions, positive control never fired).

Scratch clone (`dryrun_a_clone`) and harness (`dryrun_a_harness.py`,
`dryrun_a_run.py`) — scratchpad-only, abandoned, not committed, no doc 14
edit.

**Correction note (Session 17, 2026-07-26):** the Session-16 entry above
(and this session's opening orientation, echoing it) describes a
"correction pass" that "fixed stale 'unwitnessed' language across NEXT.md,
the day file, and the handoff." That phrasing overstates what happened.
Checked this session: `grep` for the doc-12 "**Correction note:**" marker
across all three artifacts finds only the pre-existing Session-14 note
(the mtime/commit-date mixup, unrelated); `git log --oneline` on the day
file (`knowledge/issue-runtime/2026-07-26.md`) and the Session-16 handoff
(`docs/handoffs/HANDOFF_2026-07-26_step3-precondition4-mutation-leg-closure.md`)
both return zero commits — neither file was ever committed, so no diff can
prove a stale "unwitnessed" version of either ever existed on disk. What
actually happened: the corrected wording was reached in-draft during
Session 16, before anything was written to disk, and only the corrected
text ever landed. That is a same-session self-edit, not a doc-12-pattern
correction pass (which appends a note flagging an error in previously
*committed* text). The self-edit itself is not a data-integrity problem —
low severity, correct final text, no prior committed error to have
propagated — but the phrase "correction pass across three artifacts"
should not be read as implying appended correction notes exist for this
claim, and future sessions should not cite it as such.

**Session 15 (2026-07-25): ADR-23 Phase 2 (`src/` mechanism) LANDED and
VERIFIED at the unit + live-child level. The ADR-spec end-to-end
differential against StockPhotoAgent is DEFERRED (not performed) — see the
three-part blocker below.**

**What landed (all VERIFIED this session — each ran, none assumed):**
- `ValidationCfg.env: dict[str, str | None]` in `src/runtime/config.py` —
  a `None` VALUE means UNSET the key in the child (not "" and not
  "inherited"). Declared field (not `extra="forbid"` passthrough — verified
  in the failing direction: a typo'd sibling key and the same dict one level
  up are both still rejected).
- `Validator._child_env()` in `src/runtime/validation/runner.py` — builds a
  fresh `dict(os.environ)` per call, then a SINGLE pass over the overlay:
  `built.pop(key, None)` on a `None` value (pop from the BASE — not the
  overlay, which is the whole point of the `str | None` design; popping the
  overlay would leave the inherited copy in place and neutralize nothing),
  else `built[key] = value`. Passed as `env=` to the validation
  `subprocess.run` (which previously passed NO `env=` at all — the actual
  ADR-23 defect). Closes the four enumerated vectors (PATH, VIRTUAL_ENV,
  PYTHONPATH, PYTHONHOME); does NOT close the unenumerated tail (option F,
  deferred).
- `src/runtime/main.py` — BOTH `Validator(...)` call sites (baseline check
  ~204, orchestrator ~227) now pass `env=cfg.project.validation.env`,
  identically. Baseline must not run under different hygiene than real
  validation or it reintroduces the exact divergence Phase 2 exists to close.
- `tests/unit/test_validation_env_adr23.py` — 6 result-shape tests (assert on
  the built dict, never on `subprocess.run` call args). The load-bearing one
  (`test_inherited_key_nulled_is_absent_from_child`) asserts membership-
  ABSENCE, the ONLY assertion that discriminates: verified RED under a
  pop-from-overlay mutant, the other 5 staying green, then restored.

**Gate chain (all green, ran this session):** full unit suite **112/112**
(identity-confirmed: new file collects exactly 6, suite-minus-new-file
collects exactly 106 = prior baseline unmoved). Durability harness **60/60 on
seed 42 AND 60/60 on seed 1337**, reported separately (gating because `src/`
logic changed). Live-child witness (scratchpad-only, uncommitted): with
`VIRTUAL_ENV` seeded into the parent env and `None` in the overlay, a real
child spawned through the Validator's exact `subprocess.run(shell=True)` shape
saw `VIRTUAL_ENV` genuinely ABSENT (`present=false, value=null`), while an
unenumerated parent-only var still inherited — the absent-vs-empty
distinction (ADR-23 probe 7) confirmed at the OS boundary, and the open tail
confirmed still open.

**DEFERRED — the ADR-spec end-to-end differential (step 6) was NOT run.**
Deferral is blocked by a THREE-PART AND, each independently sufficient, and
fixing any one alone does NOT unblock it — all three must hold before the
differential can run as a genuine verification:
- **(a)** The env-witness script (docs/08 §5d) is not built — correctly out
  of scope this session (do-not-touch list).
- **(b)** Precondition #4 non-vacuity: the configured target
  (`tests\qc\test_qc_rules.py`) collects **0 items** (pytest exit 5)
  regardless of interpreter — a StockPhotoAgent-side gap. A differential
  against a target that collects nothing compares two vacuous runs; the delta
  is vacuous (the project's own vacuity discipline — a green that proves
  nothing is worse than none, because it later gets cited as real).
- **(c)** The "before" half is unwitnessable for THIS change: Phase 2 code
  now exists, and ADR-23 requires the check go red-before / green-after to be
  a verification rather than a tautology. A prior session's probes are not
  this session's live observation.

**CARRY-FORWARD (do not let the deferred session inherit a fake "before"):**
that session's differential CANNOT use a `git stash` reconstruction as its
before-half — a stashed pre-mechanism state is SIMULATED, not witnessed, and
that is a semantic defect, not a sequencing inconvenience to engineer around.
It must either (i) observe "before" live AHEAD of the NEXT mechanism change,
or (ii) record the honest claim as "mechanism verified at unit + live-child
level; end-to-end differential not performed" and label it EXACTLY that. A
stashed before must never be quietly upgraded to a witnessed one.

**Still UNMET after Phase 2 (unchanged — Phase 2 does not touch these):**
Step-3 preconditions #1(b) (target collects 0 tests) and #4 (baseline
non-vacuity) remain StockPhotoAgent-side gaps. Phase 2 fixed the env-hygiene
MECHANISM, never the non-vacuity of the configured target.

**Session 14, continued (2026-07-25): ADR-23 ACCEPTED (docs/08 §5d) —
validation-command toolchain resolution and child-env hygiene. Phase 1
(docs + config.yaml command line) landed this session; Phase 2 (`src/`
mechanism) explicitly NOT started — separate session, gated on the full
suite + harness.**

**Why this exists:** re-checking Step-3 preconditions #1 (real validation
command) and #4 (baseline green) surfaced that `Validator._run_once`
(`src/runtime/validation/runner.py:90-94`) spawns `validation.commands` with
no `env=` — the child inherits the orchestrator's whole environment.
ADR-18's hygiene covers only the engine child (`claude -p`), never the
validator child. VERIFIED live: the exact same command, repo, and commit
produced `ModuleNotFoundError: No module named 'PIL'` under an activated
`.venv` shell and a *different* outcome under a clean shell — the
validation verdict was a function of operator shell state, not of the tree
alone, in tension with doc 03 / ADR-11's `validated_commit` pinning. Full
evidence (8 probes), decision rationale, rejected options, and the
escalation trigger are in `docs/08-session-0-closure-and-adr-amendments.md`
§5d — not duplicated here.

**Phase 1 (this session, landed):**
- `docs/08-session-0-closure-and-adr-amendments.md` — new §5d, ADR-23
  ACCEPTED, full text (problem, evidence, decision, options A–F, escalation
  trigger, sequencing, env-witness spec, non-vacuity requirement, gate
  chain for Phase 2).
- `config.yaml` — `validation.commands` changed from bare `python` to
  absolute `C:\Python314\python.exe` (ADR-23 rule 1). **This fixes the
  interpreter defect ONLY.** `tests\qc\test_qc_rules.py` has ZERO
  pytest-collectible `test_*` functions (VERIFIED: even with the correct
  interpreter, `collected 0 items`, exit 5) — so ADR-23's non-vacuity
  requirement is still unmet by this command. **Step-3 precondition #1
  remains UNMET** — the interpreter half of the bug is fixed, the "points
  at a non-test script" half is not, and that second half is a
  StockPhotoAgent-side fix, out of scope for this repo.
- This entry (`NEXT.md`).

**Phase 2 (NOT started — separate session, Opus per this session's own
gating instruction):** `ValidationCfg.env: dict[str, str | None]` (null =
unset) in `src/runtime/config.py` (note: `extra="forbid"` there today, so
`validation.env:` must NOT be added to `config.yaml` before this schema
change lands — it would raise at config load) + child-env construction in
`runner.py` + new unit tests. Hard merge preconditions per the ADR: unit
suite green (106) AND durability harness 60/60 on **both** seeds 42 and
1337 (gating because `src/` logic changes).

**Binding sequencing constraint (ADR-23, applies to Step 3 planning
whenever it resumes):** a watched, single-issue diagnostic smoke MAY run on
the Phase-1-only fix, provided the env witness described in docs/08 §5d is
captured for that run. The **ADR-19 20-issue measured sample MUST NOT start
until Phase 2 has landed and been verified** — those 20 verdicts are
consumed once as kill-criteria evidence under a hard budget; a
shell-state-contaminated verdict there would be permanent and
undetectable, unlike in a supervised smoke.

**Precondition #4 (baseline green) — non-vacuity requirement added (ADR-23):**
a zero exit code alone no longer establishes baseline green. The gate must
be witnessed non-vacuous once (collected count > 0, and a deliberate
mutation to the code under test turns it red) before #4 can be marked MET
— same discipline as the crash harness's own mutation-testing (fixture
`f5`). Today's command fails this even before reaching that question
(collects 0 items outright).

**Session 14 (2026-07-25, earlier this day): Step-3 precondition #3 CLOSED,
plus a NEW separate tracked item opened (not folded into #3) — see both
dated entries below.**

**Entry 1 — PRECONDITION #3 CLOSED (2026-07-25).** `Issues.md` authored in
StockAgent at the correct location and format. Evidence trail, all VERIFIED
this session (or the two prior sessions of this same investigation):
- File exists at `C:\Projects\StockPhotoAgent\Issues.md`, committed
  `58bc162`, `CommitDate: Sun Jul 19 13:53:45 2026 -0400` (`git show 58bc162
  --format=fuller --no-patch`, raw output verified).
- **Correction note:** an earlier turn in this same investigation
  misreported this commit as dated 2026-07-17, by reading the file's
  filesystem mtime (`stat` → `Modify: 2026-07-17 15:54:01`) and reporting
  that as the commit date, without ever running `git log`/`git show` on the
  hash itself. Filesystem mtime and commit date are distinct facts — this is
  flagged as the specific error, not silently fixed, so the pattern (mtime
  mistaken for commit date) is visible to future sessions. Same
  dated-correction convention as doc 12's two prior correction notes.
- Committed and currently present on `agent-work` — `git branch --all
  --contains 58bc162` → `agent-work` only (no `main`/`master`, no remotes).
- Parses cleanly via the real `issues_md.py` parser: 5 valid `IssueSpec`s,
  no errors.
- Checked against the only pinned grammar
  (`src/runtime/queue/issues_md.py:1-19` docstring, cross-checked against
  `tests/unit/test_seams.py:23-41`): all 5 issues PASS — valid `## id: title`
  heading form, valid ids (`[A-Za-z0-9][A-Za-z0-9_-]*`), no duplicates,
  `Depends-On`/`### Acceptance` correctly absent (both optional per spec, so
  absence is not a defect).
- **Content-readiness flag, not a format defect:** all 5 real issues have
  zero acceptance criteria. If the reviewer gate leans on acceptance
  criteria to judge issue resolution, these five currently give it nothing
  concrete to check against. Separate concern from format compliance —
  worth attention before/during Step 3, not a blocker to precondition #3
  itself.

**Entry 2 — NEW TRACKED ITEM (2026-07-25): "Ingest does not verify/enforce
checked-out branch before reading `Issues.md`."** Status: **OPEN, decision
needed.** Do NOT fold into precondition #3; do NOT close; no `src/` change
made or proposed as part of this entry. Evidence, VERIFIED this session:
- Currently checked out in StockPhotoAgent: `agent-work` (`git -C
  C:\Projects\StockPhotoAgent branch --show-current`).
- `main.py` startup order: adapter init → `recover()` → health checks →
  `_ingest_issues` (`main.py:218`) → loop starts. No `checkout_branch` call
  anywhere before ingest.
- The only `checkout_branch` call in `src/` is `loop.py:204`, which fires
  downstream of ingest and creates a per-issue work branch
  (`issue/{issue}`) — not a checkout of `cfg.project.branch`, and not a
  precondition for ingest.
- Grep across all of `src/` confirms exactly two `checkout_branch`
  definitions (`repo/adapter.py:100`, `repo/git_adapter.py:165`) and one
  call site (`loop.py:204`) — no others.
- **Conclusion:** `Issues.md` is currently read correctly only because
  ambient `HEAD` happens to match `cfg.project.branch`. Nothing in the
  runtime enforces or verifies this match. This is a gap between what
  `config.yaml` declares (`project.branch: agent-work`) and what the
  runtime actually checks at ingest time.
- **Two options recorded for Adi's decision — neither chosen:**
  - **Option A** — add an explicit `checkout_branch(cfg.project.branch)`
    call before `_ingest_issues` in `main.py`. This is a `src/` change —
    needs explicit sign-off (and likely an ADR, per the ADR-18→22 pattern of
    documenting which environment facts the runtime assumes vs. enforces)
    before implementation.
  - **Option B** — accept as scoped risk for now; rely on Step 3 preflight
    Item 0 (the end-to-end composed real-spawn run through
    `ClaudeHeadlessEngine.run()`) to catch a branch mismatch before live
    smoke, rather than fixing root cause pre-emptively.
  - **Coverage check on Option B, done this session, VERIFIED (not
    assumed):** Item 0 as currently scoped does **NOT** cover this. Per doc
    14 §2.6/§2.7 (Leg B, and every prior Item 0 run), Item 0 spawns
    `ClaudeHeadlessEngine.run()` against a **scratch workspace — explicitly
    "never StockPhotoAgent"** (doc 14's own wording, repeated at every
    Item-0 run to date) — it verifies ADR-22's argv/contamination fence, not
    `main.py`'s startup sequence, and never calls `_ingest_issues` or
    touches StockPhotoAgent's repo or its checked-out branch at all. If
    Option B is pursued, Item 0 in its current form would silently NOT
    surface a branch mismatch — that would require either widening Item 0's
    scope to run against the real StockPhotoAgent repo, or a separate check.
    This is stated explicitly rather than assumed, per instruction.

## Resume point (prior sessions)
**Session 13 (2026-07-24): Step-3 precondition #2 CLOSED — `settings.json`
Write→Edit permission-rule fix applied and verified; `reviewer.qwen.model`
reinstated to `qwen2.5-coder:14b`.** Session 12 (below) had reverted
`reviewer.qwen.model` from an unattributed `qwen2.5-coder:14b` edit back to
the bare `qwen2.5-coder`, on the stated grounds that `:14b` was "NOT pulled
locally yet" per `ollama list`. **That check was wrong**: it ran against the
machine's native CLI Ollama instance, not the separate Docker instance
actually serving `config.yaml → reviewer.qwen.endpoint`
(`http://localhost:11434`). Queried `localhost:11434/api/tags` directly this
session: `qwen2.5-coder:14b` **is present** there (14.8B, Q4_K_M, pulled
2026-04-17); the bare `qwen2.5-coder` the Session-12 revert landed on does
not exist at that endpoint at all. `config.yaml` reinstated to
`qwen2.5-coder:14b`, committed `cb23943`. See the two doc-12 correction
notes (`docs/12-session4-engine-wrapper.md`, end of file) for the full
provenance of both the original drift and this reinstatement. **This closes
Step-3 precondition #2** — see the itemized precondition list below, item 2,
now marked CLOSED. Also this session: applied the `settings.json`
`Write(path)` → `Edit(path)` permission-rule fix at `~/.claude/settings.json`
(user-scope, outside this repo, not git-tracked) after mechanical
verification (8/8 Edit+Write attempts against 4 sensitive-path patterns
denied in-transcript, all 4 target files independently re-hashed
byte-identical pre/post) — unrelated to Step 3 but found and fixed in the
same session; full raw evidence in that session's conversation record, not
duplicated here. No `src/` change. Full handoff:
`docs/handoffs/HANDOFF_2026-07-24_adr22-repin-settings-fix-model-reinstate.md`.

**Session 12 (2026-07-24): ADR-22 STANDING TICKLE re-probe RUN and GREEN at
CLI 2.1.215** — see the STANDING TICKLE section above and doc 14 §2.7 for
full evidence (Leg B, Synth Step B, Synth Step C all PASS, raw-verified,
`claude_code_version` witnessed in every transcript). Decision: re-probe and
hold B (explicit instruction) — no sunset action taken, `config.yaml`
unchanged on the B layer. Also committed (`c376eea`) the Sessions 9–11
pending `config.yaml`/`NEXT.md`/doc-14 changes plus three untracked handoff
files, after finding and fixing an undocumented `config.yaml` drift
(`reviewer.qwen.model` had been changed to an unpulled `qwen2.5-coder:14b`;
reverted to the bare tag with an honest UNMET note — Step-3 precondition #2
status unchanged). `validation.commands` fix (StockAgent test command) was
kept — Step-3 precondition #1 may now be resolvable, NOT independently
re-verified this session (out of scope; Unit A only). Unit tests re-run as a
post-commit sanity check: 106/106 pass. No `src/` change. Step 3's other
preconditions untouched, still whatever Session 9 last recorded (#2 Ollama
model, #3 Issues.md location/format, #4 blocked on #1).

**Session 11 (2026-07-18): synthetic positive control for ADR-22 BUILT and
RUN — see VACUITY-GUARD GAP above for full evidence (Step B/Step C, both
VERIFIED PASS).** Also fixed a working-tree `config.yaml` corruption
(duplicate `child_env:` key, diagnosed as an earlier Edit-tool replacement
that anchored below the header instead of at it — not committed). Net
effect: ADR-22's vacuity-guard gap now has a forward-looking, owned,
discriminating control (Option (a), chosen and recorded) — future re-pins
should use it instead of expecting the real ambient historian hook to
discriminate. The original root-cause claim ("A-empty stopped the ORIGINAL
contamination") remains and will always remain permanently INFERRED — no
artifact of the pre-patch hook survives to ever verify it. Step 3 is still
NOT started — this session did not touch Step 3's own five preconditions
(Ollama/Issues.md/validation command/baseline-green/.gitignore), all still
in whatever state Session 9 last recorded them. No `src/` change. No commit
(standing rule). Witness scripts uncommitted, scratchpad-only.

**Session 10 (2026-07-17, same day as Session 9): Item 0 RUN (not just
designed) — see doc 14 §2.6 "RUN this session".** `claude` CLI version
witnessed live again this run: 2.1.212, no drift. Real, unmodified
`ClaudeHeadlessEngine.run()` composed against real `claude` for the first
time (scratch workspace, never the StockPhotoAgent repo): clean —
`exit_status=0`, `apiKeySource="none"`, `git init` denied with both
`permission_denials` + `tool_result is_error:true` signals, `.git` absent,
`knowledge/` absent across the full 450s poll, zero new `skips.log` lines
for this run's cwd (required signal, not skipped). This closes the specific
"never composed in one call" gap Item 0 targeted. **However**, the
session's positive control (mutated argv, isolation mechanism stripped) also
came back clean — see the VACUITY-GUARD GAP update above — so this is NOT
read as an unqualified "ADR-22 mechanism proven working end-to-end"; it is
"no regression observed in the composed path, and the vacuity-guard gap is
now independently reproduced a third time." Step 3's precondition item 0 is
therefore marked RUN/CLEAN-WITH-CAVEAT below, not silently CLOSED. No `src/`
change this session; no commit (standing rule). Witness script uncommitted,
scratchpad-only.

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
   preflight nicety.** **RUN Session 10 (2026-07-17, doc 14 §2.6 "RUN this
   session") — CLEAN, WITH A CAVEAT, not an unqualified pass.** The composed
   real-`_command()`→`Popen`→real-`claude` path (never exercised together
   before) came back clean: `exit_status=0`, `apiKeySource="none"`, `git
   init` denied with both detection signals, `.git` absent, `knowledge/`
   absent across the full 450s poll, zero new `skips.log` lines for this
   run's cwd. That specific "never composed" gap IS closed. The caveat: this
   session's positive control (mutated argv, isolation stripped) also came
   back clean, so the run does NOT independently prove the mechanism is
   doing detectable work — see VACUITY-GUARD GAP above (now a third
   non-reproduction). Do not treat this line as "ADR-22 proven"; treat it as
   "the specific composition gap is closed, the vacuity question is
   separately still open."
1. `project.validation.commands` in `config.yaml` still has the placeholder
   `'<StockAgent test command — REQUIRED before first run>'`. **RE-CHECKED
   LIVE, STILL UNCONFIRMED — genuinely no answer available without user
   input.** No `pytest.ini`/`pyproject.toml`/`setup.cfg`/`conftest.py`/
   `Makefile`/CI workflow exists anywhere in `C:\Projects\StockPhotoAgent`;
   `CLAUDE.md` documents many `python -m src....` operational commands but no
   test runner. This is not a probing gap — there is nothing left to probe;
   someone must author or supply the command. **RE-CHECKED LIVE Session 14
   (2026-07-25) — STILL UNMET, two independent problems found and only ONE
   fixed.** (a) Bare `python` in the configured command resolved
   ambiguously — VERIFIED to different interpreters depending on operator
   shell state (this repo's own `.venv`, lacking StockPhotoAgent's Pillow
   dependency, vs. `C:\Python314\python.exe`, which has it) — **FIXED this
   session**: `config.yaml` now pins the absolute path (ADR-23 rule 1, see
   dated entry at the top of Resume point and `docs/08` §5d). (b) Even with
   the correct interpreter, `tests\qc\test_qc_rules.py` has ZERO
   pytest-collectible `test_*` functions — VERIFIED exit 5, `collected 0
   items` — **NOT FIXED**, out of scope (StockPhotoAgent-side authoring).
   Precondition #1 stays UNMET on (b) alone.
2. Ollama running with the configured reviewer model pulled. **RE-CHECKED
   LIVE Session 9 — UNMET at the time** (`ollama list` showed only
   `qwen2.5vl:7b`; `config.yaml → reviewer.qwen.model` named the un-pulled
   `qwen2.5-coder`). **CLOSED Session 13 (2026-07-24)** — that Session-9
   check queried the wrong Ollama instance. `config.yaml →
   reviewer.qwen.endpoint` (`http://localhost:11434`) is served by a
   separate Docker Ollama instance; `localhost:11434/api/tags` queried
   directly confirms `qwen2.5-coder:14b` present (14.8B, Q4_K_M, pulled
   2026-04-17). `config.yaml` now points at `qwen2.5-coder:14b`, matching
   the endpoint that will actually serve the reviewer at runtime.
3. `Issues.md` authored in StockAgent in the `## <id>: <title>` format.
   **RE-CHECKED LIVE — UNMET, two independent problems.** (a) Wrong
   location: an untracked `docs/Issues.md` exists, but `main.py` resolves the
   issues file at repo-ROOT (`Path(project.repository) / project.issues_file`
   = `C:\Projects\StockPhotoAgent\Issues.md`), which does not exist. (b)
   Wrong format: `docs/Issues.md` is a numbered list with inline
   `**STATUS:**` markers, not `## <id>: <title>` headings — parsing it as-is
   would raise `IssuesParseError` (no `## ` heading matches the grammar at
   all). **CLOSED Session 14 (2026-07-25)** — see the dated entry at the top
   of the Resume point section below for full evidence. The file now exists
   at the correct repo-root path, is committed on `agent-work` (`58bc162`),
   and parses cleanly (5 valid `IssueSpec`s, no errors).
4. Baseline green on StockAgent's `agent-work` branch. **BLOCKED on #1, not
   independently re-verifiable this session** — no known test command to
   run; guessing one (e.g. bare `pytest`) was judged unsafe given the
   `tests/` dir contains files that look auth/network-probe-shaped
   (`test_401_response_body.py`, `test_csrf_cookie_match.py`,
   `test_login_only.py`, ...), not obviously StockAgent's own suite. `git
   status` on `agent-work` itself is otherwise clean (only the untracked
   `docs/Issues.md` from #3). **RE-CHECKED LIVE Session 14 (2026-07-25) —
   STILL BLOCKED on #1, plus a NEW requirement added (ADR-23): a zero exit
   code alone no longer counts as baseline green.** The gate must be
   witnessed non-vacuous (collected count > 0, and a deliberate mutation to
   the code under test turns it red) before #4 can be marked MET — same
   discipline as the crash harness's own mutation-testing. VERIFIED this
   session: the auth/network-probe suspicion above is confirmed, not just
   suspected — grepped the full `tests/` tree for `^def test_|^class Test`;
   only `test_button_selector_only.py` and `test_login_only.py` match, and
   both are live credentialed Playwright browser automation against a real
   third-party site (`keyring` credentials, non-headless Chromium,
   hardcoded batch UUIDs) — confirmed by reading them, not run. No safe,
   appropriate, currently-passing baseline exists anywhere in this repo's
   `tests/` tree today; see `docs/08` §5d for the full non-vacuity
   requirement text.
5. StockAgent `.gitignore` hygiene (covers build/test byproducts).
   **RE-CHECKED LIVE — MET.** Covers `input/output/done/failed/review/`,
   `database/`, `logs/`/`*.log`/`debug_logs/`, `__pycache__/`, venv
   variants, IDE/OS cruft, and `config.ini` (credentials).

Directory-name caveat from doc 08 §6 (`⚠ confirm directory name on disk`):
**RESOLVED** — `C:\Projects\StockPhotoAgent` matches `config.yaml →
project.repository` exactly; `StockAgent` is cosmetic naming only
(`project.name`).

**Do NOT mark Step 3 planned or begin planning it — still out of scope. Of
the 6 preflight items (0–5): item 5 is fully CLOSED; item 0 is now
RUN/CLEAN-WITH-CAVEAT (not a plain close — see item 0 above, its own gate
condition wasn't unqualifiedly met); items 1–4 remain
UNMET/blocked/unconfirmed. Step 3 is still not ready to start.**

> **UPDATE (Session 14, 2026-07-25).** Item counts above are stale as of
> this date: item 2 is now CLOSED (Session 13) and item 3 is now CLOSED
> (Session 14 — see the dated entry at the top of the Resume point section).
> Item 0's caveat stands exactly as originally written above (RUN/CLEAN-WITH-
> CAVEAT, not a plain close — its own gate condition still wasn't
> unqualifiedly met; nothing about that finding has changed). Of the
> remaining items, only 1 and 4 are still open (item 1's
> `validation.commands` now has a real value in `config.yaml` per Session
> 12, but has not been run to confirm it passes — item 4 stays blocked on
> that until it is). A NEW, SEPARATE tracked item (not one of the original
> 0–5, not folded into item 3) was opened Session 14: ingest does not verify
> or enforce the checked-out branch before reading `Issues.md` — see the
> dated entry at the top of the Resume point section for full evidence and
> the two options recorded for decision.

> **UPDATE 2 (Session 14, continued, 2026-07-25).** Item 1's "has not been
> run to confirm it passes" (previous update) has now been run — result:
> UNMET, on two independent grounds. Interpreter ambiguity (bare `python`,
> VERIFIED resolving to different interpreters depending on operator shell
> state) is FIXED (`config.yaml` now pins an absolute path, ADR-23 rule 1).
> The target file itself is not fixed: `tests\qc\test_qc_rules.py` has zero
> pytest-collectible tests (VERIFIED, exit 5, `collected 0 items`) — a
> StockPhotoAgent-side gap, out of scope here. Item 4 stays blocked on item
> 1, plus ADR-23 adds a non-vacuity requirement to item 4 itself (zero exit
> code alone no longer counts as green). New ADR: **ADR-23** (`docs/08` §5d,
> ACCEPTED) — ADR-18 covered the engine child's environment only; the
> validator child had none. Phase 1 (docs + config line) landed this
> session; Phase 2 (`src/` mechanism, `project.validation.env` with
> null-unset semantics) is a separate session, gated on unit-suite-green +
> harness-60/60-both-seeds. Binding constraint: the ADR-19 20-issue measured
> sample must not start until Phase 2 lands — see the dated entry at the
> top of the Resume point section for full evidence and rationale.

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
4. Ollama up + reviewer model pulled — gates the reviewer health check and
   the live smoke. **CLOSED Session 13 (2026-07-24)** — see the Resume point
   Session 13 entry and Step-3 precondition #2 above; `config.yaml` now
   points at `qwen2.5-coder:14b`, verified present at the actual serving
   endpoint (`localhost:11434`, Docker Ollama instance).
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
