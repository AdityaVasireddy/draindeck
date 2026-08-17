# Doc 17 — Spec: Issue B, the explicit no-validation contract (`acknowledged_no_gate`)

Status: DRAFT — Phase 1 (Specify) of spec-driven-development. Not yet
implemented. Extends doc 09 (config loader) and doc 16 (draindeck init spec,
§2 "Issue B" and §13 "Open questions carried into Issue B's own spec")
without amending either. Per the canonical handoff dated 2026-08-17, this
spec is the ONLY authorized output of this session — no `/plan`, no `src/`
edit, no ADR-24 file. Phase 2 begins only after this spec is reviewed.

## 0. Repository evidence this spec is grounded in (verified live, this
session, against HEAD `ba447e1`)

- `ValidationCfg.commands` (`src/runtime/config.py:32`):
  `Field(min_length=1)` — schema-level enforcement point #1.
- `ValidationCfg` has an existing `field_validator("commands")` at
  `config.py:61-68` (`_powershell_safe_commands`) that rejects empty-string
  entries and `$` characters. Cross-field checks in this codebase are
  written as `field_validator`/`model_validator` methods on the owning
  model, e.g. `Config._reviewer_subsection` (`config.py:157-162`) checking
  `reviewer.provider`/`reviewer.qwen` together. No precedent exists yet for
  a check spanning two fields *within* `ValidationCfg` itself, but the
  pattern generalizes directly.
- `Validator.__init__` (`src/runtime/validation/runner.py:69-70`):
  `if not commands: raise ValueError(...)` — enforcement point #2,
  independent of pydantic, verified as flagged but unresolved in doc 16 §13.
- `main.py:323-335`: the ADR-20 baseline-green check. Constructs a
  `Validator`, runs it once against `cfg.project.branch`'s HEAD before any
  issue is ingested, refuses to start if it fails. This is the only call
  site where a `Validator` gates *startup*, not an individual execution.
- `main.py:344-350`: the orchestrator's own long-lived `Validator`, passed
  into `Orchestrator(...)`, reused across every execution's `_validate`
  call in `loop.py:296-309`.
- `loop.py:296-309` (`Orchestrator._validate`): calls
  `self.validator.validate(...)`, then emits `ValidationPassed` or
  `ValidationFailed` (`events/schema.py:41-42`) with
  `payload["gate_results"] = result.gate_results()`. There is no branch
  today for "no validator" — a `Validator` always exists by the time
  `_validate` runs.
- `docs/03-state-machine-and-event-schema.md:41-43,70,104,144-145` (THE
  FROZEN CONTRACT): `VALIDATING` requires "`ValidationReport` pinned to
  `end_commit`"; `REVIEWING`'s entry precondition is literally
  "`ValidationReport(passed)` for same hash." `ValidationReport` is
  `{schema_version, execution_id, validated_commit, gates:[...],
  flake_retries, passed}`. Nothing in doc 03 currently allows an issue to
  reach `REVIEWING` without a `ValidationReport`, and nothing there
  distinguishes "validation genuinely ran and passed" from "validation was
  waived." This is the sharpest open question in this spec — see §3.
- `main.py:124-137` (`_load_runtime_config`): structural load
  (`load_config`, raises `ConfigError`) then `validate_environment`
  (`config.py:182-215`, target-repo/branch/env-var checks only — nothing
  about `commands` shape today). Structural cross-field checks belong in
  `config.py`'s pydantic layer per existing convention, not in
  `validate_environment`, which is reserved for facts about the live
  filesystem/environment that pydantic cannot see.
- `docs/16-draindeck-init-spec.md` §2 "Issue B" subsection (`config.py:250-268`
  in that doc's own line numbering) already sketches the target shape:
  `acknowledged_no_gate: bool = False` on `ValidationCfg`, relaxing
  `min_length=1` to "≥1 unless acknowledged," a startup refusal for the
  unacknowledged-empty case, and a note that ADR-24 is required because
  this changes an external contract. That sketch is a design lean, not an
  approved decision — this spec is where it gets decided with evidence.
- No `docs/*ADR-24*` or `ADR-24` reference exists anywhere in `docs/`
  (verified via grep this session) — confirms ADR-24 has not been created,
  consistent with the handoff's "ADR creation belongs to the later approved
  workflow."
- `init/command.py` (`cmd_init`, full read this session): no
  `--no-validation` flag exists on the `init` subparser
  (`main.py:430-433` only has `--branch`, `--yes`, `--force`). Confirmed:
  Issue A's `resolve_validation_command` (`init/command.py:85-113`) always
  requires a non-blank command string or aborts — it has no path that
  produces `commands: []`.

## 1. Objective

Give Draindeck an explicit, auditable way to run an issue-drain with **no**
validation gate, for repositories where no meaningful automated check
exists yet — without ever allowing an *empty* `validation.commands` list to
silently mean "no gate" by default. The absence of a command must always be
either (a) a rejected, invalid configuration, or (b) a configuration that
required a deliberate, named acknowledgement to write and to load. There is
no third state.

This spec's job is to lock down the exact schema, the exact enforcement
sites (there are at least two independent ones, verified in §0), the exact
event/state semantics for an issue that never gets validated, and the exact
`init --no-validation` UX — before any of it is built.

## 2. Decisions

### 2a. Schema

Add to `ValidationCfg` (`config.py:31-68`):

```python
acknowledged_no_gate: bool = False
```

Relax the existing `Field(min_length=1)` on `commands` to `Field()`
(no length constraint at the field level), and add a `model_validator
(mode="after")` on `ValidationCfg` that enforces the real invariant:

```python
if not self.commands and not self.acknowledged_no_gate:
    raise ValueError(
        "validation.commands is empty; set "
        "validation.acknowledged_no_gate: true to intentionally run "
        "without a validation gate, or supply at least one command"
    )
```

Rationale: `min_length=1` was doing double duty as both "commands must be
well-formed" and "commands must be non-empty." Splitting the non-empty
check into a model validator that also sees `acknowledged_no_gate` keeps
the single-field syntactic check (`_powershell_safe_commands`, unaffected)
separate from the new cross-field policy check, matching this codebase's
existing separation of concerns (syntactic vs. cross-field validators).

**Decision: `acknowledged_no_gate: true` with a non-empty `commands` list
is accepted, not rejected.** Forcing mutual exclusivity would mean a user
who later adds a real check must remember to flip the flag back, and a
stale `true` alongside real commands is harmless — commands still run, the
flag simply goes unused. Silently ignoring a stray flag is safer than
inventing a second reason to refuse a config that has real validation
commands in it. `check-config` (§2f) surfaces this as an informational
note, not an error.

**Decision: no change to `min_length` semantics for `env`, `timeout_seconds`,
or the Gap-2 fields.** Out of scope — untouched by this issue.

### 2b. Second enforcement site — `Validator.__init__`

`Validator.__init__` (`validation/runner.py:60-82`) gains an explicit,
named parameter — not an inferred one:

```python
def __init__(self, commands: list[str], *, timeout_seconds: int,
             artifacts_dir: Path | str, env: dict[str, str | None] | None = None,
             acknowledged_no_gate: bool = False) -> None:
    if not commands and not acknowledged_no_gate:
        raise ValueError("Validator requires at least one command "
                          "unless acknowledged_no_gate is set")
```

Both `main.py:324-327` and `main.py:346-349` (the two existing `Validator(...)`
construction sites) pass `acknowledged_no_gate=cfg.project.validation.acknowledged_no_gate`
explicitly.

**Why keep two enforcement sites instead of collapsing to one.** Doc 16 §13
already flagged this as real, independent duplication — not accidental.
`Validator` is constructible directly by anything that imports it (tests,
future callers), independent of whether a `Config` object was ever
involved. Relying solely on the pydantic layer would mean a hand-built
`Validator(commands=[], ...)` silently vacuous-passes with no
acknowledgement anywhere in the call — a foot-gun for exactly the class of
bug this feature exists to prevent. Requiring the caller to pass
`acknowledged_no_gate=True` explicitly at the `Validator` layer, not merely
inferred from an empty list, means the safety property holds even for
direct `Validator` construction outside the config path. This mirrors the
existing precedent of `_powershell_safe_commands` and `Validator`'s own `$`
check being independently duplicated (`config.py:66-67` and
`runner.py:71-72`) — the codebase's established pattern is defense in
depth at both layers, not a single source of truth.

### 2c. `Validator.validate()` behavior when `commands == []`

When constructed with `acknowledged_no_gate=True` and an empty `commands`
list, `validate()` runs zero commands and returns a `ValidationResult` with
`passed=True`, `gate_results() == []`. No change to `ValidationResult`'s
shape (`runner.py:40-57`) — an empty list of per-command dicts is already a
valid value for that field; this is a *value* the existing type already
supports, not a new field. `extra_commands` (Gap-2) passed into `validate()`
still run normally even when `self.commands == []` and
`acknowledged_no_gate=True` — the no-gate acknowledgement covers the
config-sourced baseline only, not a bypass of Gap-2's per-execution
new-test-file mechanism. (If `extra_commands` is non-empty, `gate_results()`
reflects those, and `passed` reflects their outcome, same as today.)

**Decision: no separate "no-gate path" in the orchestrator or in
`main.py`'s baseline check.** Doc 16 §13 raised this as the open question;
resolved here as: teach `Validator` that zero acknowledged commands is a
vacuous pass, and change nothing else downstream. `loop.py:296-309` and
`main.py:328-333` (baseline check) call `validator.validate(...)` exactly
as they do today; they get back a `passed=True` result with an empty
`gate_results` list and proceed unmodified. This is the smallest change
that satisfies the objective — no new control-flow branch, no new state,
no event-schema change (§3 confirms this is safe).

### 2d. ADR-20 baseline-green check (`main.py:323-335`)

**Decision: still runs, still constructs a `Validator`, still calls
`validate()` — it is not skipped.** Per §2c, an acknowledged-empty
`Validator` returns `passed=True` immediately (no subprocess spawned,
nothing to time out), so this is not a meaningful cost. Skipping the call
entirely would require a second code path whose only job is "don't call
this," for zero behavioral difference in outcome — rejected as
unnecessary complexity per this repo's own simplicity rule. The startup
log line changes from `"[health] baseline green"` to
`"[health] baseline green (no validation gate configured — commands=[],
acknowledged_no_gate=true)"` when `gate_results() == []`, so the operator
sees *why* it was trivially green, not just that it was. This is a
`print_fn` text change in `main.py`, not a schema or control-flow change.

### 2e. State machine / event schema (doc 03, THE FROZEN CONTRACT)

**Decision: no event-schema change. `ValidationPassed` still fires, with
`gate_results: []`.** `REVIEWING`'s entry precondition
("`ValidationReport(passed)` for same hash," doc 03:42) is satisfied
exactly as today — `loop.py:296-309`'s existing code, unmodified per §2c,
still constructs the event from `result.gate_results()`, which is now
sometimes `[]`. `ValidationReport`'s shape (`gates:[...]`) already permits
an empty list; this is a value within the existing contract, not outside
it. Reviewers, recovery replay, and reconciliation all key off
`ValidationPassed`/`ValidationFailed` existing for a commit hash — they do
not currently branch on `len(gate_results)`, verified by inspection of the
reconciler seams (`preserve_residue`, `check_unwitnessed_commit`,
`check_dirty_workspace`) and `events/projections.py:40`, none of which
inspect `gate_results` contents.

**This is the specific claim ADR-24 needs to record and hold for review**
(see §4): that a vacuous `ValidationPassed` is semantically safe to treat
identically to a real one throughout state machine, reconciliation, and
review. This spec asserts it based on the code-path evidence above; ADR-24
is where that assertion gets formally adopted or overturned before Issue B
implementation starts.

**Recovery/replay implication:** none identified. Replay re-derives state
purely from logged events; a logged `ValidationPassed` with `gate_results:
[]` replays identically to any other `ValidationPassed`. No new event type,
no new reconciler seam.

**Config fingerprint/identity:** out of scope for this spec to resolve
definitively — grep found no existing "config fingerprint" concept in
`src/runtime` (config is loaded fresh each run, not hashed/pinned anywhere
found this session). If Issue B implementation discovers one, it must be
reconciled with ADR-24; flagged here as an open item for Phase 2, not
assumed resolved.

### 2f. `check-config` (`main.py:216-229`, `cmd_check_config`)

No code change needed beyond what `load_config` already does. Today,
`ConfigError` (structural) is caught and reported as `CONFIG INVALID:`;
the new `ValidationCfg` model validator (§2a) raises via the same pydantic
path, so an unacknowledged empty `commands` list already produces
`CONFIG INVALID: ... validation.commands is empty; set
validation.acknowledged_no_gate: true ...` with no new branch in
`cmd_check_config`. For the accepted acknowledged-empty case,
`check-config` prints its existing `"OK: structure and environment valid"`
— **decision: add one informational line** when
`acknowledged_no_gate=True`, e.g. `"NOTE: no validation gate configured
(acknowledged_no_gate=true) — issues will be accepted without an automated
check."` This is a `print_fn` addition, not new validation logic.

### 2g. Startup refusal message (unacknowledged empty case)

Never reachable in practice once §2a's model validator exists (it fires at
`load_config` time, before `_load_runtime_config`'s `validate_environment`
call or `cmd_check_config` even run) — this is intentional: the refusal
happens at the earliest possible point (structural config load), not
deferred to environment validation or engine startup. `_load_runtime_config`
(`main.py:124-137`) needs no new code; the existing `except ConfigError`
branch already prints the pydantic message and returns `None`, causing
`main`'s caller to exit non-zero before workspace/log ownership is
acquired — i.e., before any lease, log, or engine involvement. This is
strictly earlier and safer than adding a check inside
`validate_environment` or the engine wrapper.

### 2h. `init --no-validation`

Two new flags on the `init` subparser (`main.py:430-433`), both
`action="store_true"`:

- `--no-validation` — requests an acknowledged no-gate config.
- `--yes-no-validation` — the dedicated, single-purpose acknowledgement
  that satisfies `--no-validation`'s confirmation requirement
  non-interactively. **Locked name, not a placeholder** — this is a public
  CLI safety contract, fixed by this spec, not deferred to Phase 2.

**`--force` is not reused for this.** `--force` keeps its existing Issue A
meaning exactly (`init/command.py:40-41`, config-overwrite authorization)
and has no bearing on validation-gate acknowledgement.

**Locked semantics:**

1. `--no-validation` alone (no `--yes`, no `--yes-no-validation`): stack
   detection still runs (it is useful independent of validation — see
   below), but the validation-command decision is diverted to a dedicated
   interactive confirmation prompt (new, distinct from
   `confirm_detected_command`/`resolve_validation_command`). Declining
   aborts with nothing written, matching every other refusal path's
   contract.
2. `--yes` alone (no `--no-validation`): unchanged from Issue A today —
   accepts a detected command non-interactively, or refuses if none exists
   (`resolve_validation_command`'s existing `yes=True` → `return None` →
   abort path, `init/command.py:98-99`).
3. `--yes --no-validation` (no `--yes-no-validation`): **still requires
   the dedicated interactive no-validation confirmation.** `--yes` does
   NOT satisfy it — `--yes` only ever meant "accept the detected
   configuration default," which has no detected default to accept here.
   The command blocks on `input_fn` for the no-validation prompt
   specifically.
4. `--no-validation --yes-no-validation` (no `--yes`, or with `--yes`):
   the no-validation confirmation is satisfied non-interactively.
   `--yes-no-validation` acknowledges *only* the no-gate decision; it has
   no effect on any other prompt.
5. `--yes --no-validation --yes-no-validation`: fully non-interactive
   `init` with respect to validation selection. Issue A's separate
   dependency-install trust boundary (`confirm_and_run_install`,
   `init/command.py:129-180`) is untouched by any of this — `--yes` still
   never authorizes running the install command; that remains its own,
   third, independent gate.
6. `--yes-no-validation` **without** `--no-validation`: invalid CLI usage.
   `cmd_init` refuses non-zero before any preflight/detection work, with a
   clear stderr message (e.g. `"INIT ABORTED: --yes-no-validation requires
   --no-validation."`), matching the existing `InitAbort` → stderr →
   `return 1` shape (`init/command.py:21-24`, `230-233`).

**Detection/override semantics (corrected wording — automatic stack
detection is not a CLI flag, so "mutually exclusive at the flag level" was
inaccurate).** The actual behavior:

- Stack detection (`detect_stacks`, `init/command.py:235`) still runs
  unconditionally, `--no-validation` or not — its output remains useful
  for install-command proposals and for the `_print_report`/generated-YAML
  "also detected" commentary (`generate.py:74-79`), independent of whether
  a validation command gets written.
- If `--no-validation` is present and stack detection *would have*
  produced a usable command proposal, that proposal is **not** sent
  through `confirm_detected_command` — the no-validation acknowledgement
  path (item 1 above) is used instead, and `cmd_init` prints an explicit
  NOTE naming what was overridden: `"[init] NOTE: --no-validation set;
  overriding detected validation command(s) for <stack>."` This is an
  **explicit override of automatic validation selection**, not a
  mutual-exclusivity rejection — no error, no non-zero exit, just a
  visible change of path.
- If `--no-validation` is present and stack detection produced *no* usable
  proposal, `resolve_validation_command`'s manual-entry prompt
  (`init/command.py:85-113`) is bypassed entirely — the operator is never
  asked to type a command by hand only to have it discarded.
- `commands: []` is written **only after** the dedicated no-validation
  acknowledgement (interactive confirmation or `--yes-no-validation`)
  succeeds — never as a side effect of detection merely failing to find
  something.
- **Without `--no-validation`, Issue A's existing detected/manual
  validation-selection behavior is completely unchanged** —
  `confirm_detected_command` and `resolve_validation_command` run exactly
  as they do today, byte-for-byte.

**Generated YAML** (`generate.py:82-121`) gains, only when
`--no-validation` was actually applied and acknowledged:

```yaml
validation:
  # --no-validation was passed to `draindeck init`; no automated gate
  # will run for this drain. Remove `acknowledged_no_gate` and add real
  # commands to turn validation back on.
  commands: []
  acknowledged_no_gate: true
  timeout_seconds: 600
```

replacing the `commands:` block Issue A currently always emits
(`generate.py:91-96`). No other section of the template changes.

`_print_report` (`init/command.py:191-206`) gains a corresponding line
when no-validation was used, replacing the `"[init] validation
command(s):"` loop with `"[init] validation: NONE (acknowledged_no_gate)"`.

**Decision: `resolve_validation_command`'s existing "no usable proposal →
refuse to write anything" behavior (Issue A, `init/command.py:85-113`) is
unchanged for the case where `--no-validation` was NOT passed.**
`--no-validation` is the only way to opt into an empty-commands config;
declining the manual prompt still aborts with nothing written, exactly as
today. This preserves Issue A's reviewed behavior byte-for-byte (handoff
§4 "Do not regress this behavior" applies to the general refusal-on-decline
shape, even though that note was written about branch safety specifically
— the same non-regression bar applies here).

### 2i. Compatibility / migration

- **Old configs without `acknowledged_no_gate`:** pydantic default
  (`= False`) applies; a pre-existing config with a non-empty `commands`
  list is completely unaffected (the model validator's condition is never
  true). A pre-existing config that somehow already had `commands: []`
  would previously have failed to load at all (`min_length=1`) — there is
  no such config in the wild by construction, so there is no silent
  behavior change for any config that loaded successfully before this
  issue. Verified: no `commands: \[\]` or `commands:\s*$` pattern exists in
  `config.example.yaml` or any tracked `config*.yaml` in this repo today.
- **No schema version bump.** `ValidationReport`'s `schema_version` field
  (doc 03:104) is an execution-time payload field, unrelated to
  `Config`'s own (nonexistent) versioning; adding an optional field with a
  safe default to `ValidationCfg` is additive and backward compatible by
  pydantic's own semantics (`extra="forbid"` on `_Frozen` means old YAML
  without the key still loads fine — pydantic fills the default; it would
  only break if old YAML had an *unexpected extra* key, which is the
  opposite direction).

## 3. Enforcement-site summary (both required, per §2b)

| Site | File:line | Guard today | Guard after Issue B |
|---|---|---|---|
| Config schema | `config.py:32` | `Field(min_length=1)` | `Field()` + `ValidationCfg` model validator checking `commands`/`acknowledged_no_gate` together |
| Validator construction | `runner.py:69-70` | unconditional `raise` on empty | `raise` only when `not acknowledged_no_gate` |
| Startup (baseline) | `main.py:323-335` | N/A (never reached with empty commands today) | unchanged code path; now sometimes trivially green |
| `check-config` | `main.py:216-229` | rejects via `ConfigError` today | still rejects unacknowledged-empty via same `ConfigError` path; adds one informational line for the acknowledged case |
| `init` | `init/command.py` | cannot produce empty `commands` | `--no-validation` is the only writer of `commands: []` |

## 4. ADR-24 — decision this spec hands off (not written here)

Per CLAUDE.md ("Architecture is FROZEN. Changes go through an ADR... never
ad hoc") and doc 16 §2's own determination, Issue B requires **ADR-24**.
This spec identifies exactly what ADR-24 must record, so Phase 2 does not
have to re-derive it:

1. The engine may intentionally run an issue-drain with zero validation
   commands, gated by a single explicit `acknowledged_no_gate: true` config
   flag — not inferred from an empty list alone.
2. A vacuous `ValidationPassed` event (`gate_results: []`) is treated
   identically to a real one by the state machine, recovery/replay, and
   the reviewer's `REVIEWING` entry precondition (doc 03) — §2e's claim,
   to be formally adopted or overturned.
3. Two independent enforcement sites (`ValidationCfg` model validator,
   `Validator.__init__`) are both required, deliberately duplicated — not
   a design smell to be simplified away later.
4. `--yes` on `init` never by itself authorizes writing a no-gate config —
   the dedicated `--yes-no-validation` flag (§2h) is required, regardless
   of `--yes`, to acknowledge it non-interactively (mirrors the existing
   dependency-install trust boundary precedent).

**ADR-24 is not created in this session, and this spec does not schedule
its creation for "the start of Phase 2."** Phase 2 in this repo's
spec-driven-development workflow is Plan (task breakdown), not
implementation — creating ADR-24 there would be premature, and the earlier
wording conflated the two. The correct sequencing:

1. This SPEC (Phase 1) identifies the ADR-24 decision (the four points
   above) — done, in this document.
2. No ADR file is created during Phase 1.
3. Phase 2 (Plan) must carry ADR-24 as an explicit prerequisite/gate: a
   named task that blocks implementation-task authorization, not an
   implementation task itself.
4. ADR-24 is drafted from this approved SPEC and reviewed **before any
   Issue B `src/` implementation begins** — i.e., after Phase 2 planning
   produces the task breakdown, but before the first `src/`-touching task
   in that breakdown is authorized to start.
5. ADR-24 must formally decide the central open claim from §2e: whether an
   acknowledged empty-command `Validator` producing `ValidationPassed`
   with `gate_results: []` is compatible with the frozen doc-03
   state-machine/event contract.
6. **If ADR review rejects that premise, the correct next step is to
   return to this SPEC for revision — not to silently implement an
   alternate architecture** (e.g., a new event type, a distinct
   REVIEWING-bypass path) that was never specified or reviewed.

## 5. Testing strategy (for Phase 2, not run in this session)

Net-new unit tests, following this repo's existing file convention
(`tests/unit/test_config_backlog.py`, `test_validation_env_adr23.py`):

- `ValidationCfg` accepts `commands: []` iff `acknowledged_no_gate: true`;
  rejects it otherwise with the exact message from §2a.
- `ValidationCfg` accepts `commands: [...]` + `acknowledged_no_gate: true`
  together (no mutual-exclusion rejection, per §2a).
- `Validator(commands=[], acknowledged_no_gate=True, ...)` constructs and
  `.validate()` returns `passed=True`, `gate_results() == []`, spawns no
  subprocess. **Verified this session: `Validator` has no injectable
  execution seam today** — `_run_once` (`runner.py:149-168`) calls
  `subprocess.run` directly, module-level, not through a constructor
  parameter or method the caller can substitute (unlike
  `init/command.py`'s `confirm_and_run_install`, which *does* take an
  injected `run_fn` — that pattern does not already exist in
  `validation/runner.py` and this spec does not claim otherwise). Because
  `commands == []` makes the `for i, cmd in enumerate(commands)` loop
  (`runner.py:102`) iterate zero times, the smallest correct test seam is
  a `monkeypatch` on `runtime.validation.runner.subprocess.run` (module-
  level patch) asserting it is never called for this case — proving zero
  subprocess execution by observing the actual seam that exists, without
  adding a new constructor parameter or otherwise redesigning the
  validation runner. If Phase 2 implementation later decides an injected
  seam is warranted for other reasons, that is a separate decision, not
  assumed here.
- `Validator(commands=[], acknowledged_no_gate=False, ...)` still raises,
  matching current behavior exactly (regression guard).
- `Validator(commands=[], acknowledged_no_gate=True, ...).validate(...,
  extra_commands=[...])` still runs the extra commands (Gap-2 interaction,
  §2c).
- `cmd_init` with `--no-validation --yes-no-validation`: writes
  `commands: [], acknowledged_no_gate: true`; does not call
  `confirm_detected_command`/`resolve_validation_command`; prints the NOTE
  line when a stack was also detected (§2h detection-override semantics).
- `cmd_init` with `--no-validation` alone (no `--yes`, no
  `--yes-no-validation`): blocks on the dedicated no-validation
  confirmation prompt; declining aborts with nothing written.
- `cmd_init` with `--yes --no-validation` (no `--yes-no-validation`):
  still blocks on the dedicated no-validation confirmation prompt —
  `--yes` does not satisfy it (§2h truth table row 3).
- `cmd_init` with `--yes-no-validation` and no `--no-validation`: refuses
  non-zero before any preflight/detection work, with the exact stderr
  message from §2h row 6 (regression guard against silent acceptance of
  invalid flag combinations).
- `cmd_init` with `--yes --no-validation --yes-no-validation`: fully
  non-interactive; confirms `confirm_and_run_install` is still never
  auto-authorized by `--yes` (existing Issue A behavior, unaffected).
- `cmd_check_config` on an acknowledged-empty config: exits 0, prints the
  informational NOTE line.
- `main.py` baseline-check integration test: acknowledged-empty config
  reaches `"[health] baseline green (no validation gate configured...)"` and
  proceeds to ingest, without spawning any subprocess (same module-level
  `subprocess.run` patch as the `Validator` unit test above).
- **Compatibility regression guard (corrected — no serializer/round-trip
  mechanism exists in this codebase to claim byte-identical output from;
  `load_config` produces a `Config` object, not re-serialized YAML).** An
  old-style config file (no `acknowledged_no_gate` key, non-empty
  `commands`) loaded through `load_config`:
  - still loads successfully (no `ConfigError`);
  - produces `cfg.project.validation.acknowledged_no_gate is False`
    (pydantic default);
  - produces `cfg.project.validation.commands` and every other parsed
    field equal to what today's `load_config` produces for that same file
    (compared as Python values, not as re-serialized text);
  - `validate_environment`/`Validator` construction/baseline-check
    behavior for that config is unchanged from pre-Issue-B behavior.

Full acceptance floor per CLAUDE.md/doc16 §2 (high-blast-radius, unchanged
by this spec): five gates, full unit suite green (current 298 + all new
tests above), crash harness 60/60 on **both** seed 42 and seed 1337, and
the ADR-24 check (§4) held for review before commit.

## 6. Boundaries

- Do not touch Issue A's committed surface (`src/runtime/init/detect.py`,
  branch-safety logic, dependency-install trust boundary) except the two
  named, additive touch points in §2h (`generate.py`'s validation block,
  `command.py`'s new flag handling, `main.py`'s `init` subparser).
- Do not modify `ValidationResult`/`gate_results()`'s shape — an empty list
  is a value within the existing type, not a new field.
- Do not add a new event type or touch `events/schema.py`, `events/
  projections.py`, or the reconciler seams — §2e's evidence is that none
  of this is required; if Phase 2 discovers otherwise, that is new
  evidence requiring a return to this spec, not a silent scope expansion.
- Do not resolve the "config fingerprint" question (§2e) speculatively —
  flagged as unresolved, not assumed absent.
- Do not create ADR-24 in this session (§4).
- Do not run `/plan` in this session.

## 7. Unresolved / deferred to Phase 2

- Whether a "config fingerprint" concept exists anywhere else in the
  codebase that Phase 2 must reconcile with (§2e) — grep found none this
  session, but Phase 2's own five-gate evidence pass must re-verify against
  HEAD at implementation time, not trust this snapshot.
- Whether POSIX-specific `init` code paths (already flagged as
  under-covered in the canonical handoff §5 item 4, an Issue A residual
  observation) need any `--no-validation`-specific POSIX coverage — out of
  scope per the handoff's explicit instruction not to fold Issue A
  residuals into Issue B.
