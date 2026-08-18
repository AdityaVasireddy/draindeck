# Doc 16 — Spec: `draindeck init` (plug-and-play onboarding)

Status: DRAFT — Phase 1 (Specify) of spec-driven-development. Not yet
implemented. Supersedes nothing; extends doc 09 (config loader) and doc 08
§5d (ADR-23) without amending either.

## 0. Resolved conflicts between the original ask and current repo state

The originating feature request (reproduced in full at the bottom of this
doc for traceability) predates three things this repo has since done. Each
was raised as a clarifying question and resolved by the user (Adi) before
this spec was written; recorded here so a future reader doesn't re-litigate
them:

1. **Config filename.** The request said "write `config.yaml`, not
   `config.local.yaml`." But nothing in `src/` hardcodes a `config.yaml`
   filename — `--config` takes an arbitrary path — and the repo already
   completed a deliberate cutover to `config.example.yaml` (tracked
   template) + `config.local.yaml` (gitignored, holds real repo paths).
   **Decision: `init` writes `config.local.yaml`** by default, matching the
   existing convention. No new `.gitignore` entry needed.
2. **ADR-23 rule 2 vs. the Python detection row.** ADR-23 (doc 08 §5d,
   frozen) requires validation commands to use both an absolute interpreter
   path (rule 1) AND explicit file targets, never bare directory/glob
   discovery (rule 2) — bare `python -m pytest` previously produced a
   shell-state-dependent verdict flip. `init` cannot know a target repo's
   test file layout without deep inspection. **Decision: `init` satisfies
   rule 1 only** (resolves and writes the absolute interpreter path) and
   emits bare `-m pytest` discovery with a `# TODO: confirm` comment citing
   ADR-23 rule 2, telling the user to narrow it to explicit file targets
   before relying on it unattended. This is a conscious, flagged gap, not a
   silent one.
3. **Scope split.** **Decision: one spec, two issues at Plan phase** — see
   §2.

## 0b. Corrections from this revision (evidence-verified against current `src/`)

A second review pass checked every code claim below against the live
repository (not against the first draft's memory of it) and found one
substantive error and several under-specified areas. Fixed here; each is
cross-referenced from the section it changes.

4. **Acceptance-gate correction (was wrong in the first draft).** The first
   draft classified Issue A as "low–medium blast radius" and scoped it to
   unit tests only. That contradicts CLAUDE.md's own explicit rule: `src/
   runtime behavior` and `real repository mutation` are BOTH named,
   verbatim, in CLAUDE.md's high-blast-radius list — and Issue A is both (a
   new `src/runtime/init/` module; it creates/checks out a branch in the
   target repo). This repo's own session handoffs treat that classification
   as triggering the full floor, not a lighter one — e.g. `docs/handoffs/
   HANDOFF_2026-08-15_durability-gate-closed-stuck-resolving-reap.md`:
   *"Any `src/` change requires full five gates + 60/60 pass on both seed
   42 and seed 1337 + an ADR check ... per CLAUDE.md's blast-radius rule."*
   **Corrected decision: Issue A requires the same five-gate + 60/60-both-
   seeds floor as Issue B** (§2 below). It does NOT require a new ADR
   (unlike Issue B) — see §2 for why those are separable requirements.
5. **Static-web row was non-deterministic.** `node --check <each changed
   .js>` cannot execute as a literal, static `validation.commands` string:
   `Validator` runs a fixed list of command strings from config
   (`validation/runner.py:60-118`) with no per-invocation "changed files"
   substitution — that "changed" framing only makes sense for a diff at
   drain time, and `init` runs once, before any drain, against a tree with
   no diff yet. **Corrected decision: `init` enumerates the target repo's
   existing top-level `*.js` files at generation time** (excluding
   dot-directories and common vendor/build folder names) and emits one
   `node --check <file>` command per file — deterministic, static, and
   consistent with ADR-23 rule 2's "explicit named targets, never bare
   discovery" convention already used elsewhere in this codebase (the
   Gap-2 hook, doc 08 §5d). See §5 (table) and §12 (success criteria).
6. **Config destination was stated ambiguously.** "the repo's invocation
   directory" conflated two different repositories. Verified: no code
   anywhere hardcodes a `config.yaml`/`config.local.yaml` path — every
   existing subcommand takes `--config`/positional `config` explicitly
   (`main.py:415-425`: `recover --config`, `check-config config`,
   `run --config`) — but the established *convention*, per
   `.gitignore`'s bare `config.local.yaml` entry and README's own
   documented workflow (`Copy-Item config.example.yaml config.local.yaml`,
   then `... run --config config.local.yaml`, README lines 61/81/82), is
   that `config.local.yaml` lives at the **Draindeck runtime repo's own
   root** — i.e., wherever `python -m runtime.main` is invoked from — never
   inside `<repo-path>` (the target repo being onboarded). **Corrected
   decision: `init` writes to `Path.cwd() / "config.local.yaml"`**,
   matching that convention exactly, and every step that references "the
   config" (`--force`, the existing-file preflight check, the post-init
   `check-config`/`run` command it prints) uses that same resolved path.
   **Known limitation, recorded as a non-goal for Issue A:** a single fixed
   `config.local.yaml` in the invocation directory does not support
   onboarding multiple target repos concurrently from the same Draindeck
   checkout without overwriting one config with another (`--force` is the
   only current escape hatch, and it destroys the prior file). No
   `--config-out`-style flag is being added to solve this now — flagged as
   a future limitation, not built here, since nothing in the original
   request or current repo architecture requires multi-target support yet.
7. **Branch-setup step had a latent bug.** `GitCliAdapter.checkout_branch`
   (`repo/git_adapter.py:178-187`) does `git checkout -B branch
   create_from` whenever `create_from` is given — `-B` **force-resets** an
   *existing* branch's tip to `create_from`, it does not "use it as-is."
   Unconditionally calling `checkout_branch(branch, create_from=head)`
   would silently destroy a pre-existing branch's history, directly
   contradicting the spec's own "if it exists, use it as-is" requirement.
   **Corrected decision:** `init` calls `adapter.head_of(branch)` first; if
   `None`, `checkout_branch(branch, create_from=current_commit)` (create
   at HEAD); if not `None`, `checkout_branch(branch)` with no `create_from`
   (plain checkout, preserves the existing tip). See §4 step 5.
8. **Interactive manual-validation UX was prose-only.** Fully specified in
   a new §4a, covering the no-usable-command prompt, blank-input handling,
   preview/confirm/revise/cancel, and `--yes` behavior — see §4a.
9. **Python success-criterion overclaimed.** "Runs green" was written as
   if it proved the generated gate was trustworthy unattended. It only
   proves the command is *executable*. ADR-23 rule 2 (explicit file
   targets) remains unresolved by Issue A — see §12's reworded criterion.

## 0c. Post-ship correction (resolve-item, 2026-08-17): untracked-only preflight + target-derived config destination

Two onboarding problems surfaced running `init` against a real new target
repo (LUVZ) and were fixed together in one gated `/resolve-item` pass.
Both corrections supersede specific claims in §0b item 6 and §3/§4 below;
this section is the current source of truth for the two behaviors named,
everything else in §0b–§13 is unchanged.

1. **Untracked-only no longer blocks `init`.** §0b item 6/§4 step 1's
   description of `adapter.is_dirty()` (blanket tracked-OR-untracked) as
   the preflight gate is corrected: preflight now calls a new read-only
   `GitCliAdapter.worktree_status()` classification and refuses only on
   tracked/staged/deleted/renamed/conflicted changes. Untracked-only
   proceeds with a printed `[init] NOTE: N untracked file(s) ... — left
   untouched` and is never staged, moved, or deleted. `is_dirty()` itself,
   and every other caller of it (reconciler check 3, `checkout_branch`'s
   own default precondition, `snapshot_commit`), is untouched — this is a
   strictly additive capability, not a semantics change to the existing
   witness. `checkout_branch` gained an `allow_untracked: bool = False`
   parameter (default preserves prior behavior for every non-init caller);
   `init`'s own `setup_branch` passes `allow_untracked=True`, which still
   refuses on tracked/staged/conflicted dirt and still lets Git's own
   checkout refuse cleanly (no force, no auto-stash) if switching branches
   would overwrite an untracked file the target tree contains.
2. **Config destination is now target-repo-derived, not CWD-derived.**
   §0b item 6's "Corrected decision: `init` writes to `Path.cwd() /
   "config.local.yaml"`" is superseded. That convention meant `init`
   against any target repo could collide with, and (with `--force`)
   silently overwrite, an unrelated config sitting in whatever directory
   Draindeck happened to be invoked from — observed directly: a LUVZ
   `init` run from Draindeck's own root targeted its existing
   StockPhotoAgent `config.local.yaml`. **New default:
   `<repo-path>/.draindeck/config.local.yaml`**, computed from `repo_path`
   alone (`init/command.py`'s `resolve_config_dest`) — the invoking CWD
   never influences it. §0b item 6's "No `--config-out`-style flag is
   being added to solve this now" is also superseded: **`--config-out
   PATH` was added.** A relative `--config-out` resolves against the
   invoking CWD (same convention as `repo_path`/`--config`/`--log`
   elsewhere in this CLI) — that is an explicit override, not the default
   the CWD-independence invariant protects. `--force` is unchanged in
   shape but now scoped to whichever destination was actually resolved
   (target-default or `--config-out`), never an unrelated CWD file.
   `write_config` now creates the destination's parent directory
   (`.draindeck/`, or whatever `--config-out` implies) if it doesn't
   exist.
3. **ADR check for this correction (documented conclusion: no ADR
   needed).** Neither change touches doc 03's event/state schema,
   `Config`/`ValidationCfg` (the YAML *schema* `generate.py` writes is
   byte-identical; only where it's written changed), the orchestrator
   loop, engine wrapper, or recovery reconciler — the same criteria §2
   above used to conclude Issue A itself needed no ADR. §0b item 6 was a
   spec-level decision (this doc), not one of the numbered ADRs in
   `docs/08` (ADR-20..24) — reversing it is a spec correction, not an
   architecture change.
4. **Full five-gate + 60/60-both-seeds floor applied**, per §2's
   established floor for any `src/` change of this blast radius (real
   repository mutation via `checkout_branch`, `src/runtime` behavior).

## 1. Objective

`draindeck init <repo-path>` takes an arbitrary git repository — Python,
Rust, Node, React, plain HTML/JS, or unrecognized — and produces a
`config.local.yaml` plus a checked-out work branch, so a first-time user
goes from "cloned this tool" to "ready to run `draindeck run`" without
hand-writing YAML or knowing the schema.

**Design principle (unchanged from the request):** the engine does not
become stack-aware. It still just runs a command string and checks the
return code (doc 02 §3/§4). Stack-awareness lives entirely in `init`'s
detection table and the command string it writes into config. `init` never
touches `src/runtime/loop.py`, `events/`, `recovery/`, the engine wrapper,
or `Config`/`ValidationCfg` — but it IS new `src/runtime` code that
performs real git mutation in the target repo, which CLAUDE.md's own
blast-radius list names explicitly (§0b item 4, §2). Staying off the
schema/state-machine/recovery surface keeps Issue A from needing an ADR;
it does not exempt Issue A from the five-gate + durability-harness floor
every other `src/` change in this repo's history has been held to.

**Who this is for:** someone pointing Draindeck at a *new* target repo for
the first time — today that's manual (see `config.example.yaml`'s header
comment and README's config section). Every StockPhotoAgent session so far
has hand-authored `config.local.yaml`; `init` replaces that hand-authoring
for the common cases and forces an explicit decision (not a silent gap) for
the uncommon one — no detectable validation gate.

## 2. Two issues, one shared gate floor, one extra requirement for Issue B

Per CLAUDE.md's blast-radius rule and the user's own scoping note, this
spec covers two issues. **Only Issue A is authorized to start after this
spec is approved.** Issue B needs its own ADR and its own five-gate pass,
opened as a separate spec-driven-development round when Issue A is done or
nearly done. The two issues do **not** differ in how heavily they're
gated — both are high-blast-radius and both are held to the same
five-gate + 60/60-both-seeds floor. They differ in one thing only: Issue B
additionally requires a new ADR, Issue A does not.

### Acceptance gate (applies identically to both issues)

CLAUDE.md's high-blast-radius list names, verbatim: *"real repository
mutation, src/runtime behavior, event schemas, state transitions, external
contracts, Git/recovery behavior, and safety or durability claims about
committed behavior."* Issue A is new `src/runtime` code that performs real
repository mutation (branch create/checkout in the target repo). Issue B
is new `src/runtime` code that changes an external contract (the config
schema) and startup/recovery-adjacent refusal behavior. **Both match the
list on multiple independent grounds** — neither gets the lighter,
documentation-style process CLAUDE.md reserves for "documentation,
NEXT.md, handoffs, scratch work, and reversible cleanup."

This repo's own session history treats that classification as an
unconditional floor for any `src/` change, not a suggestion:
`docs/handoffs/HANDOFF_2026-08-15_durability-gate-closed-stuck-resolving-reap.md`
states it plainly — *"Any `src/` change requires full five gates + 60/60
pass on both seed 42 and seed 1337 + an ADR check ... per CLAUDE.md's
blast-radius rule"* — and multiple other handoffs (sessions 20, 21, 23, 44)
independently confirm the same floor was applied to changes far smaller in
surface area than `init` (a single exit-path fix, a single parser-halt
fix). **Nothing about Issue A's smaller footprint is evidenced as an
exception to that floor**, so this spec does not invent one.

**Required before either issue is considered complete:**
1. Full five-gate discipline, heavy apparatus (pre-committed outcome
   matrices, detailed evidence accounting, multi-phase approvals) — not
   the lightweight scope-check CLAUDE.md reserves for low-blast-radius
   work.
2. Full unit suite green: `python -m pytest tests\unit -q`, the existing
   235 plus every new test the issue adds.
3. Durability gate green on **both** seeds:
   `python tests\crash\harness.py %TEMP%\ch 42` and `... 1337`, expect
   `ALL 60 SCENARIOS PASSED` on each.
4. An explicit **ADR check** — a documented "does this change the frozen
   architecture, event schema, state machine, or an external contract?"
   determination, held for review, not skipped.

**Honest note on what the harness proves for Issue A specifically.** The
60/60 harness's invariants (I-a..I-h) exercise event-log replay, crash
recovery, and orchestrator/engine boundary conditions — `init` calls none
of that machinery; it runs standalone, before any event log exists, and
never during `run`/`recover`. So a green harness run is **regression
evidence** for Issue A (proof that adding a new subcommand, a new import
block in `main.py`, and a new `src/runtime/init/` package did not
destabilize the existing frozen recovery machinery it sits beside) — it is
**not** direct correctness evidence for `init`'s own detection/generation
logic. That correctness evidence comes from the Issue-A-specific tests in
§10. Both kinds of evidence are still required; the harness requirement is
not waived because it happens to be vacuous with respect to `init`'s own
control flow — CLAUDE.md's rule is keyed to blast radius (what could this
change destabilize if wrong), not to whether the specific harness
scenarios happen to touch the new code.

### Issue A — `draindeck init` command
New code only: a detection table, a config writer, a CLI subcommand. Does
not change `Config`, the event schema, or anything under `recovery/` or
`engine/`. Reuses `GitCliAdapter` for repo introspection (`is_dirty`,
`current_commit`, `head_of`, `checkout_branch`) rather than re-implementing
git calls — `RepositoryAdapter` is explicitly "mechanism only, zero
policy, constructed from a path argument" (`repo/adapter.py` docstring), so
this is exactly the reuse it was designed for. Constructing
`GitCliAdapter(repo_path)` itself performs the git-repository and
git-version (>=2.38) preflight checks (`repo/git_adapter.py:40-43`) — see
§4 step 1.

**ADR check for Issue A (documented conclusion: no ADR needed).** Issue A
does not modify doc 03's event/state schema, does not modify `Config` or
`ValidationCfg`, does not modify the orchestrator loop, engine wrapper, or
recovery reconciler — it is new, additive, self-contained code that runs
to completion before any of those systems start. This conclusion must be
re-verified live at Issue A's own five-gate scope step (item 4 above), not
assumed permanently true from this spec — a future change to `init` that
starts touching config-loading internals would need to re-ask the
question.

**Consequence of not touching the schema yet:** `ValidationCfg.commands`
still has `Field(min_length=1)` (`config.py:32`), and `Validator.__init__`
independently raises `ValueError("Validator requires at least one
command")` when given an empty list (`validation/runner.py:69-70`) — **two
separate enforcement points**, not one; Issue B must account for both, not
just the pydantic schema (carried into §13). Issue A cannot write a config
with zero commands. So until Issue B ships:
- The "no gate" resolution path exists at the UX level (`init` stops and
  asks — fully specified in §4a) but its *write* side (`--no-validation`
  producing `commands: [], acknowledged_no_gate: true`) is not yet
  possible.
- `init` on a repo with no detected command and no manually-supplied one
  **refuses to write a config at all** and exits non-zero with an
  explanation, rather than accepting `--no-validation` and writing
  something the schema would reject anyway (or working around the schema
  from outside — not acceptable; `init` must never produce a config that
  contradicts what the loader currently enforces).
- The `--no-validation` flag is therefore **deferred to ship alongside
  Issue B** (or as a small follow-up once B lands), not built now with a
  stub. Building a flag that can't do its one job is worse than not having
  it yet.

### Issue B — engine config-contract change (additionally needs ADR-24)
Adds `acknowledged_no_gate: bool = False` to `ValidationCfg`, relaxes
`commands`'s `min_length=1` to "≥1 unless `acknowledged_no_gate` is true,"
and adds a startup refusal (in `_load_runtime_config` / `validate_environment`,
`main.py:121` / `config.py:182`) when `commands` is empty and
`acknowledged_no_gate` is not true — **and** must also relax or bypass
`Validator.__init__`'s independent empty-commands guard
(`validation/runner.py:69-70`), verified this session as a second site the
first draft of this spec missed. This is a state/contract change to the
engine's start path — CLAUDE.md's "external contracts" category, and
independently a genuine new architectural policy decision (should the
engine ever run ungated, and how is that recorded) of the same kind ADRs
01-23 already record. It needs its own new ADR: **ADR-24** (next number,
since ADR-23 is the highest currently used) — this is *in addition to* the
five-gate + 60/60-both-seeds floor in the "Acceptance gate" subsection
above, not instead of it. Also needs its own design pass for how the
ADR-20 baseline-green check (`main.py:320-332`) and the orchestrator's
per-execution `Validator` behave when `commands == []` — skip entirely,
most likely, but that's Issue B's decision to make with evidence, not
something to bake into this spec (§13).

## 3. Command surface (Issue A)

```
python -m runtime.main init <repo-path> [--branch NAME] [--yes] [--force]
```

Deferred to Issue B: `--no-validation`.

- `<repo-path>` — target repo. Required, positional.
- `--branch NAME` — branch to create/use. Default `agent-work` (matches
  `config.example.yaml`'s default).
- `--yes` — non-interactive; accept every detected default without
  prompting. Without it, `init` prints what it will write and asks for
  confirmation before writing anything.
- `--force` — required to proceed if `Path.cwd() / "config.local.yaml"`
  (§0b item 6 — the Draindeck invocation directory, never `<repo-path>`)
  already exists; without it, an existing file aborts the run.

**Entry point note:** there is no installed `draindeck` console script
today (pyproject.toml has no `[project.scripts]` table; the CLI is invoked
as `python -m runtime.main <subcommand>`, per main.py's own usage banner).
`init` becomes a new subcommand of the existing `runtime.main` parser,
consistent with `verify-log` / `show-state` / `recover` / `check-config` /
`run`. Adding a literal `draindeck` console-script entry point is a
one-line `pyproject.toml` addition and is in scope for Issue A if it turns
out to be cheap, but the CLI contract this spec commits to is
`python -m runtime.main init ...`.

## 4. What `init` does, in order (Issue A)

1. **Preflight.**
   - Construct `GitCliAdapter(repo_path)`. This alone performs the
     git-repository check (raises `RepoError` if `<repo-path>/.git` doesn't
     exist, `repo/git_adapter.py:40-42`) and the git-version floor check
     (raises `RepoError` if git < 2.38, `git_adapter.py:83-96`). `init`
     catches `RepoError` here and aborts with a clear message (matches
     acceptance criterion "aborts cleanly on non-git path") — no separate
     `git rev-parse` shell-out needed; the adapter already does this on
     construction.
   - `adapter.is_dirty()` — dirty tree → abort. Never init over
     uncommitted work (mirrors `checkout_branch`'s own dirty-tree
     precondition in `git_adapter.py:179-183`, so `init` fails the same way
     the engine would fail later, not a different way).
   - `Path.cwd() / "config.local.yaml"` (§0b item 6) already exists → abort
     unless `--force`.
2. **Stack detection.** Walk the repo root for marker files per the table
   in §5. Collect *all* matches, ordered by table priority — a repo can be
   Node + Python. The top match drives the proposal; the rest are recorded
   as a comment block in the generated config so the user can see what else
   was found and switch.
3. **Validation-command proposal.** From the top match, build the command
   string (absolute interpreter where applicable — §6). If the top match
   produces no usable command (Unknown stack, or a matched row whose
   command-construction step fails — e.g. Python with no interpreter
   found, or static-web with zero `.js` files surviving the vendor/dotdir
   exclusion), enter the manual-validation UX (§4a) instead of proposing
   nothing silently. Otherwise: shown to the user for confirmation (unless
   `--yes`); editable before write.
4. **Dependency install (optional, gated).** If the matched stack has a
   standard install step (table in §5), *print* the command. Only run it if
   the user explicitly confirms (even under `--yes`, printing yes; running,
   no — `--yes` accepts detected *defaults*, not *side effects on the
   user's environment*, which is a separate trust boundary).
5. **Branch setup.** Call `adapter.head_of(branch)` first (`git_adapter.py:
   102-106`) to decide which form to use — **do not** unconditionally pass
   `create_from`, since `checkout_branch(..., create_from=X)` compiles to
   `git checkout -B branch X`, which force-resets an *existing* branch's
   tip to `X` (`git_adapter.py:178-187`); that would silently destroy a
   pre-existing branch's history and contradict "if it exists, use it
   as-is."
   - `head_of(branch)` returns `None` (doesn't exist yet) →
     `adapter.checkout_branch(branch, create_from=adapter.current_commit())`.
   - `head_of(branch)` returns a sha (already exists) →
     `adapter.checkout_branch(branch)` — no `create_from` — preserves the
     existing tip exactly.
   - Either way, report the branch name and its tip commit
     (`adapter.current_commit()` after checkout).
6. **Config generation.** Write `Path.cwd() / "config.local.yaml"` (§0b
   item 6 — the Draindeck runtime repo's own root, never inside
   `<repo-path>`). Every field filled from detection; `# TODO: confirm` on
   anything guessed (the validation command itself, the interpreter path if
   resolved by PATH-fallback rather than a found venv, and the
   ADR-23-rule-2 gap noted in §0 item 2). Schema-identical to what
   `load_config` already parses — no new keys (Issue A adds none; Issue B
   adds `acknowledged_no_gate` later).
7. **Post-init report.** Print: stack(s) detected, branch created + tip
   commit, validation command chosen, and the exact next command
   (`python -m runtime.main check-config config.local.yaml` then
   `python -m runtime.main run --config config.local.yaml`, both resolved
   against the same `Path.cwd()`-relative file just written). End with any
   outstanding TODO the user must resolve before a real run.

## 4a. Interactive manual-validation UX (Issue A)

Triggered whenever detection produces no usable command — Unknown stack,
or a matched row whose command-construction step fails (§4 step 3). Fully
specified so this is testable, not prose-only (tests listed in §10).

1. **What's displayed.** A summary of what detection found (the matched
   stack(s), if any, and why no command resulted — e.g. "matched Python
   (pyproject.toml) but no interpreter was found: no `.venv` and `python3`
   is not on PATH" or "no recognized stack marker found"), followed by:
   `No automatic validation command could be proposed.`
2. **Prompt (only when a TTY and not `--yes`; see point 9).**
   `Enter a validation command to run in this repository (blank to
   cancel):`
3. **Blank/whitespace-only input does not count as a command.** Input is
   stripped; if the result is empty, treat it identically to an explicit
   cancel (point 8) — never silently proceed and never re-prompt in a loop
   waiting for non-blank input, since an unattended/scripted caller
   accidentally piping EOF must not hang.
4. **After a non-blank command is entered:** proceed to preview (point 5);
   after blank/cancel: proceed directly to point 8.
5. **Preview.** Print the exact `validation.commands` entry (and, since
   it's the only line that changed from the rest of the auto-filled
   config, the surrounding config summary already shown per step 3's
   normal confirmation path) exactly as it will be written — no
   transformation, no wrapping, no interpreter resolution applied to a
   manually-entered command (resolving/rewriting user-typed text would
   contradict "editable before write — never silently committed as
   truth").
6. **Confirm.** `Write this config? [y/N]`
7. **Revise.** Answering `n` (or anything other than `y`/`Y`) returns to
   the prompt in point 2 rather than aborting outright, so the user can
   correct a typo without restarting `init`. There is no fixed retry limit;
   the loop only ever exits via a confirmed `y` (proceeds to write) or a
   blank/cancel input at point 2/3 (proceeds to point 8).
8. **Cancel.** Exit non-zero. Print that no config was written and why
   (blank input / explicit decline), and that `init` can be re-run once a
   validation command is available. Nothing is written to disk.
9. **Under `--yes`.** `init` never opens an interactive prompt when
   `--yes` is set — there is no TTY interaction of any kind under this
   flag, by definition (`--yes` means "unattended"). If detection produces
   no usable command, `--yes` goes straight to the point-8 abort: prints
   the same "no automatic validation command could be proposed" message,
   exits non-zero, writes nothing. **`--yes` never invents a command,
   never writes `commands: []`, and never bypasses
   `ValidationCfg.commands`'s `min_length=1`** — there is no safe default
   command to fabricate for an unrecognized stack, and inventing one would
   be exactly the "silently ship unreviewed edits" failure mode the
   original request explicitly called out as unacceptable.

## 5. Stack-detection table (data-driven, per repo request)

A list of ordered rows, not `if`/`elif` chains — the acceptance criterion
"adding a stack is one row, no engine change" is enforced by this shape,
not just aspired to.

| Priority | Marker(s) | Stack | Proposed command | Install command |
|---|---|---|---|---|
| 1 | `pyproject.toml` or `requirements.txt` | Python | `<abs-interpreter> -m pytest` (§0 item 2 caveat) | `<abs-interpreter> -m pip install -r requirements.txt` |
| 2 | `Cargo.toml` | Rust | `cargo test` | `cargo fetch` |
| 3 | `package.json` with a `test` script | Node/JS | `npm test` | `npm install` |
| 4 | `package.json` with `lint` but no `test` script | Node/JS | `npm run lint` | `npm install` |
| 5 | `package.json` + React dep, no `test`/`lint` | React | `npm run build` (build-as-smoke — comment says so explicitly) | `npm install` |
| 6 | `go.mod` | Go | `go test ./...` | `go mod download` |
| 7 | `*.html` + `*.js`, no `package.json` | Static web | One `node --check <file>` command per discovered top-level `*.js` file (§0b item 5) — empty after exclusion → falls into §4a like Unknown | — |
| — | nothing recognized | Unknown | none — falls into the manual-validation UX (§4a) | — |

Implementation note: this table lives as a plain Python data structure
(list of dataclasses or dicts) in one module, e.g.
`src/runtime/init/detect.py`. The detector function walks marker files,
returns *all* matches in priority order; a separate function turns the top
match into a command string (or, for static-web, a *list* of commands —
one per file, since the row's own single-command-per-file semantics need
that shape). Keeping detection and command-construction as two functions
(not one) is what makes "add a stack = one row" literally true — a new row
needs no new branching logic unless its command needs special
construction (e.g. the interpreter-resolution step Python already needs,
or the per-file enumeration static-web needs).

**Static-web row, precisely (§0b item 5):** enumerate `*.js` files under
`<repo-path>`, excluding dot-directories (`.git`, `.venv`, etc.) and common
vendor/build folder names (`node_modules`, `vendor`, `dist`, `build`) —
this row's own marker already requires no `package.json`, so
`node_modules` is unlikely, but the exclusion is cheap insurance, not a
new feature. Each surviving file becomes its own `node --check <path>`
entry in `validation.commands` — static and deterministic, no "changed
files" concept (that phrase from the original request only applies to a
drain-time diff, which doesn't exist yet at `init` time — §0b item 5). If
zero files survive the exclusion, this row produces no usable command and
`init` falls into §4a exactly as it would for an Unknown stack.

`node --check` is syntax-only, not a real test — the generated config's
comment says this explicitly next to every command this row produces, so
no one mistakes a green `node --check` for test coverage.

## 6. Interpreter resolution (Python row only)

Order of resolution, cross-platform (mirrors the `os.name == "nt"`
platform-dispatch idiom already used in `validation/runner.py:26`):
1. `<repo-path>/.venv/Scripts/python.exe` (Windows) or
   `<repo-path>/.venv/bin/python` (POSIX), if it exists.
2. Else, resolve `python3` (POSIX) / `python` (Windows) via `shutil.which`
   and take its **absolute** resolved path — never write a bare `python`
   invocation into the config (ADR-23 rule 1, doc 08 §5d: bare `python`
   resolves differently depending on shell/venv state, which is the exact
   bug ADR-23 exists to prevent).
3. Neither found → the Python row does not produce a usable command;
   `init` falls into the manual-validation UX (§4a), whose point 1 display
   states the reason ("no interpreter found").

## 7. Cross-platform requirements

- No hardcoded backslash-only paths in generated output — use `pathlib`
  and let it render native separators, or explicitly branch on `os.name`
  where a string must be spelled out (matching `runner.py`'s existing
  pattern, not inventing a new one).
- Install-command printing (not running) works identically on both
  platforms since it's just a string.
- `ValidationCfg._powershell_safe_commands` (config.py:61) rejects any
  command containing `$`. None of the table's default proposals contain
  `$`, so this is a non-issue for defaults; worth a one-line note in the
  generated comment only if a user hand-edits toward something like a
  POSIX `$(...)` substitution, since that would fail `check-config` with a
  possibly-confusing message otherwise.

## 8. Project structure (Issue A)

```
src/runtime/init/
    __init__.py
    detect.py       → stack-detection table + marker-file walk + interpreter resolution
    generate.py      → config.local.yaml writer (fills ValidationCfg-compatible YAML + TODO comments)
    command.py        → cmd_init(args), wired into main.py's subparsers like the other cmd_* functions
tests/unit/
    test_init_detect.py     → table-driven: one test per row, plus multi-match ordering,
                               plus static-web file-enumeration/exclusion and the
                               zero-files-survive-exclusion fallthrough
    test_init_generate.py   → generated YAML round-trips through load_config()
    test_init_command.py    → preflight aborts (dirty tree, non-git, existing config w/o
                               --force); branch setup against both a new-branch and an
                               already-existing-branch temp-repo fixture (regression test
                               for §0b item 7 — asserts the existing branch's prior tip
                               commit is unchanged after init, i.e. create_from was NOT
                               passed on that path); the §4a manual-UX loop (blank input,
                               decline-then-revise, confirm, cancel); --yes against an
                               undetectable repo (refuses, writes nothing, no prompt)
```

`main.py` gains one import block and one `sub.add_parser("init")`
registration, following the exact pattern already used for
`check-config`/`run` (main.py:407-427). No existing subcommand's code
changes.

## 9. Code style

Match what's already here — this codebase's docstrings explain *why*, not
*what*, and cite the ADR/doc section a design choice traces to. Example,
shaped like the existing `repo/adapter.py` style:

```python
def resolve_interpreter(repo_path: Path) -> Path | None:
    """Absolute interpreter path per ADR-23 rule 1 (doc 08 §5d): bare
    `python` resolves differently depending on shell/venv state, which
    previously flipped a validation verdict. Prefers a project venv over
    PATH resolution."""
    venv = repo_path / (".venv/Scripts/python.exe" if os.name == "nt"
                         else ".venv/bin/python")
    if venv.exists():
        return venv
    found = shutil.which("python" if os.name == "nt" else "python3")
    return Path(found).resolve() if found else None
```

No comments explaining what a line does; comments only for the non-obvious
*why* (ADR citations, a prior-bug reference, a cross-platform branch
rationale).

## 10. Testing strategy

- Framework: `pytest`, same as the rest of the repo (`tests/unit`,
  `testpaths = ["tests/unit"]` per `pyproject.toml`).
- Detection table: one test per row asserting the marker → stack → command
  mapping, plus a multi-marker-match test (Node + Python repo) asserting
  ordering and that both appear in the recorded comment.
- Config generation: assert the written file round-trips through
  `runtime.config.load_config()` without error — this is the acceptance
  criterion "byte-identical in schema to what the engine already parses"
  made concrete as a test, not just a claim.
- Command-level: build temp git repos per test (same idea as the crash
  harness's "real temp git repo as the world," `tests/crash/harness.py`,
  though `init`'s tests are unit-speed, not the crash harness itself) and
  assert each preflight-abort path and the full happy path for at least
  the Python and no-detection cases.
- No live network, no live engine, no live reviewer needed for any of
  this — `init` never spawns `claude -p` or calls the reviewer endpoint.

## 11. Boundaries

- **Always:** run `python -m pytest tests\unit -q` (existing 235 + new
  Issue-A tests) AND `python tests\crash\harness.py %TEMP%\ch <seed>` for
  both seed 42 and seed 1337 before considering Issue A done — per §2's
  gate correction, this is not optional for a change of Issue A's
  blast-radius classification; validate every generated config with
  `load_config()` in a test, not just by eyeballing YAML.
- **Ask first:** anything that would touch `src/runtime/config.py`,
  `main.py`'s startup path (`_load_runtime_config`, `validate_environment`),
  `src/runtime/validation/runner.py`'s `Validator.__init__` guard, or any
  file under `recovery/`/`events/`/`engine/` — that's Issue B's territory
  and needs its own ADR-24 gate, not a drive-by in Issue A. Adding a
  `[project.scripts]` console-script entry (if pursued) — cheap, but
  touches the package's public surface, worth a one-line confirmation.
- **Never:** auto-run an install command without explicit user
  confirmation; write a config with `commands: []` (the schema doesn't
  support it yet — see §2); invent or fabricate a validation command under
  `--yes` when detection found none (§4a point 9); overwrite an existing
  `Path.cwd()/config.local.yaml` without `--force`; hardcode a repository
  path, branch name, or validation command anywhere under `src/` (CLAUDE.md
  hard rule — the detection *table* is data, never a literal baked into
  control flow).

## 12. Success criteria (Issue A; Issue B's own criteria come with its own spec)

- `init` on a Python repo (with a `.venv`) produces a `config.local.yaml`
  that parses via `load_config()` and whose generated command **is
  executable and exits 0** against that repo's test suite, with zero
  manual edits. This demonstrates the command *runs* — it does **not**
  demonstrate the generated gate is a trustworthy unattended validation
  gate: bare `-m pytest` discovery satisfies ADR-23 rule 1 only (absolute
  interpreter), not rule 2 (explicit file targets), and the generated
  `# TODO: confirm` + ADR-23-rule-2 comment (§0 item 2) says so. A human
  narrowing the command to explicit file targets before relying on it
  unattended is a separate, un-automated step this criterion does not
  claim to satisfy.
- `init` on a Rust repo (`Cargo.toml`) proposes `cargo test` and creates
  the branch.
- `init` on a Node repo with a `test` script proposes `npm test`.
- `init` on a static-web repo (HTML+JS, no `package.json`) generates one
  `node --check <file>` command per discovered top-level `.js` file
  (excluding dot-directories/vendor folders), each carrying the
  syntax-only caveat in its comment; if zero files survive the exclusion,
  it falls into the §4a manual-validation UX identically to the Unknown
  case (verified by test, not just asserted — §10/§8).
- `init` on a repo with nothing recognized, or a matched row that produces
  no usable command, enters the §4a manual-validation UX: refuses to write
  a config and exits non-zero on blank input or explicit cancel; writes
  only after an explicit preview + `y` confirmation of a non-blank,
  user-supplied command.
- `init --yes` against a repo with no usable detected command exits
  non-zero without writing a config and without opening any interactive
  prompt (§4a point 9) — never invents a command, never writes
  `commands: []`.
- `init` aborts cleanly (non-zero exit, clear message, nothing written)
  on: non-git path, dirty working tree, existing
  `Path.cwd()/config.local.yaml` without `--force`.
- Branch setup preserves an already-existing branch's tip commit exactly
  (no `create_from` passed on that path — §0b item 7); only a genuinely
  new branch is created at current HEAD.
- The stack table is data-driven: a unit test asserts that adding a new
  row (via a parametrized fixture, not editing `detect.py`'s control flow)
  requires touching only the table, proving the "one row" property rather
  than just asserting it in prose.
- Generated config round-trips through `load_config()` with no new
  required fields.
- Cross-platform: `detect.py`/`generate.py` contain no hardcoded
  backslash-only path literals; interpreter resolution branches on
  `os.name` exactly once, in `resolve_interpreter`.
- **Gate criterion (§2):** Issue A is not considered complete until the
  full unit suite (235 existing + new Issue-A tests) is green, the
  durability harness reports `ALL 60 SCENARIOS PASSED` on both seed 42 and
  seed 1337, and the ADR-check documented in §2 ("no ADR needed") has been
  re-verified live against the actual diff, not assumed from this spec.

## 13. Open questions carried into Issue B's own spec (not answered here)

- **Verified this session, not previously in the spec:** `Validator.__init__`
  (`validation/runner.py:69-70`) independently raises `ValueError` on an
  empty `commands` list — a second enforcement point beyond
  `ValidationCfg.commands`'s `min_length=1`. Issue B must decide how this
  guard changes (relaxed identically? bypassed entirely when the caller
  knows `acknowledged_no_gate` is set? never constructed at all in that
  case?) — not designed here, just confirmed as a real, verified surface
  Issue B's own scope step must enumerate.
- Does `commands: []` under `acknowledged_no_gate: true` skip the ADR-20
  baseline-green check entirely, or run it as a vacuous pass? (Leaning
  "skip entirely and say so in the startup log" — but that's a design
  decision for Issue B with its own evidence, not assumed here.)
- Does the per-execution `Validator` in the orchestrator loop need any
  change when `commands` is empty, or does an empty list already behave
  correctly by running zero commands and reporting `passed=True` today?
  (Moot as stated — `Validator.__init__` currently refuses construction
  with an empty list at all, per the bullet above, so this question is
  really "what replaces `Validator` construction on the acknowledged-no-gate
  path," not "how does an existing `Validator` behave with zero commands."
  Needs to be resolved as part of Issue B's five-gate work, not assumed
  here.)
- Whether `--no-validation`'s write path belongs in `init`'s `generate.py`
  (Issue A's module, gated by a feature check on whether the installed
  schema supports it) or is added fresh once Issue B lands — a small
  sequencing decision to make when Issue B is actually scheduled.

---

## Appendix: original feature request (verbatim, for traceability)

Reproduced as given; superseded section-by-section by §§0b–13 above
wherever the two differ. **§5 above, not the table below, is
authoritative** — this appendix exists so a future reader can see exactly
what was asked for and why a given line in §§0–13 diverges from it, not as
a second source of truth to implement against.

> Feature: draindeck init — plug-and-play onboarding
>
> **Goal.** One command takes any repo — Python, Rust, Node, React, plain
> HTML/JS — from nothing to drain-ready. It detects the stack, proposes a
> validation command, sets up the branch, and writes a config the user only
> has to confirm.
>
> **Design principle (keep the blast radius small).** The engine does not
> change. Draindeck already just runs a command string and checks the
> return code. So init only produces a correct config.yaml and a branch.
> Stack-awareness lives entirely in a detection table plus the generated
> command — the core loop stays stack-blind. This is what keeps the
> feature from touching state/recovery code.
>
> **Command surface:**
> `draindeck init <repo-path> [--branch NAME] [--no-validation] [--yes]`
> - `<repo-path>` — target repo. Required.
> - `--branch NAME` — branch to create/use for agent work. Default
>   `agent-work`.
> - `--no-validation` — explicit opt-in to run with no gate (see safety
>   section). Without this flag, a repo with no detectable gate stops and
>   asks.
> - `--yes` — non-interactive; accept all detected defaults (for
>   scripting). Without it, init is interactive and shows what it will
>   write before writing.
>
> **What init does, in order:**
> 1. Preflight checks. Path exists and is a git repo (`git rev-parse`
>    succeeds). Working tree is clean; if not, stop and tell the user.
>    Never init over uncommitted work. No existing `config.yaml` already
>    pointing here; if present, require `--force` or abort. Don't silently
>    overwrite.
> 2. Stack detection. Walk the repo root for marker files (table below).
>    Produce an ordered list of matches, not just the first — a repo can be
>    Node + Python. Record what was found so the config can show it as a
>    comment.
> 3. Validation-command proposal. From the top match, propose a command
>    string. This is a proposal, shown to the user, editable before write —
>    never silently committed as truth. Detection guesses; the user
>    confirms.
> 4. Dependency install (optional, gated). If the stack has a standard
>    install step (`npm install`, `cargo fetch`, `pip install -r
>    requirements.txt`), offer to run it. Default is to print the command,
>    not run it, unless the user confirms. Installing into someone's
>    environment is high-trust; make it opt-in.
> 5. Branch setup. Create `<branch>` off the current HEAD if it doesn't
>    exist; check it out. If it exists, use it as-is. Report the branch and
>    its tip commit.
> 6. Config generation. Write `config.yaml` (not `config.local.yaml` — see
>    naming note) with every field filled from detection, and explicit
>    `# TODO: confirm` markers on anything guessed. Mirror the existing
>    schema exactly so the engine reads it unchanged.
> 7. Post-init report. Print: stack detected, branch created, validation
>    command chosen, and the exact next command to start a drain. End with
>    any TODO the user still must resolve.
>
> **Stack-detection table (the extensible core).** Make this a data
> structure, not hardcoded ifs — the whole point is that adding a stack is
> a one-row change.
>
> | Marker file(s) present | Stack | Proposed validation command | Install command |
> |---|---|---|---|
> | `pyproject.toml` or `requirements.txt` | Python | `python -m pytest` | `pip install -r requirements.txt` |
> | `Cargo.toml` | Rust | `cargo test` | `cargo fetch` |
> | `package.json` with a test script | Node/JS | `npm test` | `npm install` |
> | `package.json` with a lint but no test | Node/JS | `npm run lint` | `npm install` |
> | `package.json`, React deps, no test | React | `npm run build` (build-as-smoke) | `npm install` |
> | `go.mod` | Go | `go test ./...` | `go mod download` |
> | `*.html` + `*.js`, no `package.json` | Static web | `node --check <each changed .js>` or none | — |
> | nothing recognized | Unknown | none — force `--no-validation` decision | — |
>
> Notes for the builder: detection reports all matches; the proposal takes
> the highest-priority one but the comment block lists the rest so the user
> can switch. The static-web row is the case that exposed this whole gap.
> `node --check` is syntax-only — say so in the generated comment so no one
> mistakes it for a real test. Interpreter path: StockPhotoAgent's config
> hardcodes `C:\Python314\python.exe` per ADR-23 (absolute interpreter, not
> bare `python`). init should detect a project venv
> (`.venv\Scripts\python.exe`) or fall back to resolving the absolute path
> of whatever's on PATH — and write the absolute form, preserving that
> ADR-23 rule.
>
> **The no-test case (the important safety design).** This is where
> correctness matters most, because it's where Draindeck could silently
> ship unreviewed edits. If detection finds no validation command, init
> must stop and make the user choose — it must not default to "no gate."
> Two valid resolutions: the user supplies a command manually (even a
> trivial one), or the user passes `--no-validation`, which writes an
> explicit `validation: {commands: [], acknowledged_no_gate: true}` into
> config. That flag is the audit trail proving the user chose to run
> ungated. The engine should refuse to run a drain against a config with
> empty commands unless `acknowledged_no_gate: true` is present. This makes
> "ran with no gate" a deliberate, recorded decision, never an accident.
>
> **Config naming note.** Right now the schema lives in `config.local.yaml`
> and the header says "copy to `config.yaml`." Decide the convention as
> part of this feature: init should write the file the engine actually
> loads. If that's `config.yaml`, generate that. Don't leave the user with
> a `.local` file they must manually rename — that's exactly the friction
> you're removing.
>
> **Cross-platform note.** StockPhotoAgent is Windows/PowerShell-only, and
> item (4) in your hardening backlog was removing that coupling (commit
> `2bff89f`). init should not re-introduce it — path handling, the
> interpreter resolution, and any install step must work on both
> PowerShell and POSIX shells, or at minimum detect the OS and emit the
> right form. Otherwise the plug-and-play feature only plugs into Windows.
>
> **Acceptance criteria (build these into the issue set):** init on a
> Python repo produces a config that parses and whose validation command
> runs green, with zero manual edits. init on a Rust repo (`Cargo.toml`)
> proposes `cargo test` and creates the branch. init on a Node repo with a
> test script proposes `npm test`. init on a no-test static-web repo
> refuses to complete without either a manual command or `--no-validation`.
> A config with empty commands and no `acknowledged_no_gate` flag causes
> the engine to refuse to start a drain. init aborts cleanly on: non-git
> path, dirty working tree, existing config without `--force`. The stack
> table is data-driven — adding a stack is one row, no engine change.
> Generated config is byte-identical in schema to what the engine already
> parses (no new required fields the loader doesn't know). Cross-platform:
> runs on PowerShell and POSIX; no hardcoded backslash-only paths in
> generated output.
>
> **Scope boundary (what NOT to build).** Don't make the engine
> stack-aware — it stays a command-runner. Don't auto-run installs or
> drains without explicit confirmation. Don't invent a new config schema —
> extend the existing one with the two new optional keys
> (`acknowledged_no_gate`, and whatever `--force` needs).
>
> One last flag for your plan: the two new config keys
> (`acknowledged_no_gate`, empty-commands refusal) are a state/contract
> change to the engine's start path — that's the part that carries real
> gate cost, not the detection table. Scope that as its own issue with the
> 60/60 harness; the init command wrapper around it is lower-risk and can
> be a separate issue. Splitting them keeps the heavy gate on the small
> surface that actually needs it.
