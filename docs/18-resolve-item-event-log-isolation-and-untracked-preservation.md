# Doc 18 — resolve-item: event-log cross-repo isolation + untracked-file
# preservation (2026-08-18)

Status: DONE. Two confirmed runtime isolation / data-safety bugs, fixed
together in one gated `/resolve-item` pass, per CLAUDE.md's high-blast-radius
floor (real repository mutation, `src/runtime` behavior, Git/recovery
behavior). Both bugs surfaced in a real LUVZ smoke test.

## 1. Problem 1 — event log shared across target repositories

### Root cause
`EventLogCfg.path` defaulted to the bare relative string
`"state/events.jsonl"`, and every consumer (`main.py`'s
`_open_startup_recovery`, shared by both `run` and `recover`) did
`Path(cfg.event_log.path)` directly — resolved against `Path.cwd()`, i.e.
wherever the `python -m runtime.main` process happened to be invoked from,
**not** `project.repository`. Since the documented workflow always invokes
Draindeck from its own repo root (README's `Copy-Item config.example.yaml
config.local.yaml` / `run --config config.local.yaml`), every target repo's
default event log resolved to the *same* physical file:
`<draindeck-root>/state/events.jsonl`. A LUVZ run opened this stale,
StockPhotoAgent-authored log and replayed its projection against LUVZ. No
data was lost only because the stale log's tail had no active issue and
`_expected_commit` happened to fall through to LUVZ's actual branch tip — a
foreign log with an active issue or unresolved commit intent would have
caused real cross-repository corruption (checkout to the wrong commit,
merges targeting the wrong branch, etc).

### Fix
`resolve_event_log_path(cfg: Config) -> Path` (`config.py`) is now the sole
place `event_log.path` becomes a filesystem path: a relative path resolves
against `cfg.project.repository`; an absolute path passes through
unchanged. `main.py::_open_startup_recovery` — the single startup boundary
shared by `cmd_run` and `cmd_recover` — calls it instead of
`Path(cfg.event_log.path)` directly, for both the `EventLog(...)` open and
the derived `artifacts_dir`. That function was the *only* systemic
consumer of `cfg.event_log.path` in `src/` (verified by grep); no other
code path resolves, opens, reconciles, replays, or initializes the event
log independently.

`EventLogCfg.path`'s default changed from `"state/events.jsonl"` to
`".draindeck/state/events.jsonl"` — the same target-repo-owned convention
`draindeck init` already established for `config.local.yaml`'s default
destination (doc 16 §0c: `<repo-path>/.draindeck/config.local.yaml`, fixed
in an earlier `/resolve-item` pass for an analogous CWD-derived-default
bug). `init`'s `render_config` now also writes an explicit `event_log:`
section (previously relied on the invisible Python default) purely for
operator transparency — functionally identical either way.

### Why this design, not a target-repository-hash directory under Draindeck's
own root
An alternative would keep all target repos' logs under Draindeck's own
tree, namespaced by a hash of `project.repository`. Rejected: it would
still couple runtime state's location to *Draindeck's* directory rather
than the target's, doesn't match the `.draindeck/` convention `init`
already established, and gives an operator no obvious place to look for
"this target's event log" without recomputing a hash. Storing it inside
the target repo (gitignored, like `.draindeck/config.local.yaml` already
is) is simpler, discoverable, and self-evidently isolated per repo.

### ADR check
No ADR needed. Doc 03's event/state schema, `Config`'s existing fields, the
orchestrator loop, and the reconciler's decision logic are all untouched —
only *where* the log's bytes live on disk changed, and only for a relative
path (an explicit absolute override was always, and remains, honored
as-is). This mirrors doc 16 §0c's own ADR-check conclusion for the
analogous config-destination fix.

### Compatibility
- An operator-configured **absolute** `event_log.path` is completely
  unaffected — still used exactly as given.
- An operator-configured **relative** `event_log.path` now resolves against
  `project.repository` instead of the invocation CWD. Every config in this
  repo at the time of this fix (`config.example.yaml`, `config.local.yaml`)
  held the literal default string, i.e. the exact bug — so this is the
  correction, not a regression, for the common case.
- `config.local.yaml` (this repo's real, gitignored, operational config for
  StockPhotoAgent) is a special case: its `state/events.jsonl` already holds
  843 real events at `C:\Projects\Draindeck\state\events.jsonl` (the
  physical consequence of the old bug). Rather than silently starting a new,
  empty log under `StockPhotoAgent\.draindeck\` — losing continuity with
  real history for a backlog that (per NEXT.md) is already drained to
  terminal state and may still be referenced for ADR-19 evidence — its
  `event_log.path` was pinned to that exact absolute path. No file was
  moved. If continuity with `.draindeck/`-relative history is wanted
  later, that is a manual, explicit decision for whoever owns that config,
  not something this fix should do silently.
- `verify-log` / `show-state`'s own `--log` CLI flag (default
  `"state/events.jsonl"`, CWD-relative) was deliberately left unchanged:
  these are read-only inspection subcommands with no `--config`/`project.
  repository` concept at all — a human runs them ad hoc against an
  explicit path they choose. They cannot replay a foreign projection into
  a live target (they never reconcile or mutate), so the corruption risk
  this fix addresses does not apply to them.

## 2. Problem 2 — startup reconciler destroys legitimate untracked files

### Root cause
Reconciler check 3 (`check_dirty_workspace`, `recovery/bindings.py`) used
`adapter.is_dirty()` — a blanket boolean, true for *any* tracked
modification **or untracked file** — to decide whether the workspace held
crash residue worth archiving-then-discarding. Whenever it fired, it
staged and committed everything (`snapshot_commit`, `git add -A`) to an
attempt ref, then `git reset --hard` + `git clean -fd` back to the log's
pinned expected commit — `clean -fd` deletes every untracked file, with no
concept of which ones were ever Draindeck's. A real LUVZ smoke test hit
this with **no active issue in flight**: `Issues.md` and its own backup
were untracked, pre-existing, legitimate target-repo files, and check 3
swept both away as if they were crash byproducts. Restoring them from the
archived ref would not fix this — the very next `run`/`recover` would
destroy them again, since nothing about their provenance had changed.

### Fix — positive ownership, not a blanket exemption
Untracked files a Draindeck execution's engine run can legitimately create
(scratch files, work-in-progress artifacts) genuinely need this
crash-recovery path — doc 11 §3 models exactly that. The fix is **explicit
per-execution provenance**, not disabling reconciliation for untracked
files wholesale:

1. **Baseline capture at spawn** (`loop.py::_spawn_or_escalate`): right
   before the `ExecutionSpawned` intent is appended — durably, fsync'd,
   before the engine can touch anything (the existing I6 intent-before-
   action law) — the orchestrator records the workspace's *current*
   untracked paths as `payload.pre_execution_untracked`. This is an
   additive payload field on an existing event type, no new event, no
   schema change — the same pattern already used for `base_commit`
   (doc 11 §2) and `num_turns` (NEXT.md, session history).
2. **Projection carries it** (`events/projections.py`): `ExecutionView`
   gained `pre_execution_untracked: list`, populated by the
   `ExecutionSpawned` handler exactly like `base_commit` already is.
   Included in `StateProjection.digest()`'s canon for full state-identity
   coverage (I-b).
3. **Check 3 computes an ownership baseline**
   (`_untracked_ownership_baseline`, `bindings.py`): the *relevant*
   execution is the active issue's latest one. Its baseline is the set of
   untracked paths recorded at ITS OWN spawn. An untracked path currently
   present that is **not** in that baseline is attributable to this
   execution (or its validation run) and may be treated as residue; a path
   that WAS already there before spawn (Issues.md, its backup, anything
   pre-existing) never counts as residue, no matter how many times check 3
   runs. With no active issue, or an active issue with no execution yet,
   there is **no baseline at all** (`None`, distinct from an empty set) —
   untracked dirt is never touched in that case; only genuine
   tracked/staged/conflicted dirt or a HEAD/expected-commit mismatch can
   still trigger a reset, and even then every currently-untracked path
   survives it (see next point).
4. **Two adapter primitives learned to protect a preserve-list**
   (`repo/git_adapter.py`, both default to `()` — byte-identical prior
   behavior for every caller that doesn't pass one):
   - `reset_hard(commit, *, preserve_untracked=())` — adds `-e <path>` to
     `git clean -fd` for each preserved path.
   - `snapshot_commit(message, *, exclude_untracked=())` — unstages the
     given paths (`git reset -- <path>`) after `git add -A`, before
     committing. **Required, not optional**: without this, `git add -A`
     would sweep a baseline (pre-existing) untracked file into the residue
     commit as tracked content, and the *subsequent* `reset --hard` to a
     commit that never had it would delete it as ordinary tracked-content
     removal — a different code path than `clean -fd`, so
     `preserve_untracked` alone does not cover it. Both check 1
     (`preserve_residue`, passing `view.pre_execution_untracked`) and check
     3 (passing its own computed `preserve` set) now exclude the same
     paths from staging that the following reset keeps on disk.
5. **`untracked_paths()`** (`repo/adapter.py` + `git_adapter.py`): a new
   read-only witness (`git status --porcelain`'s `??` lines), the
   mechanism both the baseline capture and check 3's diff need.

### Worked example (also the regression test)
An issue is ACTIVE; `Issues.md` sits untracked in the repo before its first
execution spawns. `ExecutionSpawned.payload.pre_execution_untracked =
["Issues.md"]`. The execution crashes (orphaned EXECUTING); its engine also
dropped `scratch.tmp`, genuinely new. Check 1 archives residue but excludes
`Issues.md` from the commit (`exclude_untracked`); check 3 resets the
workspace back to base, excluding `Issues.md` from `clean -fd`
(`preserve_untracked`) while `scratch.tmp` — absent from the baseline — is
committed to the residue ref and then cleaned. Result: `Issues.md` survives
untouched; the genuine crash residue is still preserved as evidence and
still removed from the working tree. See
`tests/unit/test_bindings.py::test_check3_preserves_baseline_but_cleans_new_residue`.

### What this does NOT change
- `loop.py`'s own `reset_hard(base)` calls on the ordinary reject/retry/
  escalate paths (`_finish_rejected`, `_validate`, `_review`, the
  turn-budget branch) are unchanged — no `preserve_untracked` passed, same
  as before. These fire only while Draindeck already holds an active
  execution's workspace for a specific issue, which is the supported,
  exclusive-ownership model (`WorkspaceLease`); this fix is scoped to
  *startup reconciliation*, the code path the two real incidents actually
  went through, matching how the problem was reported ("the startup
  reconciler..."). Concurrent human edits to a target repo's tracked
  content *during* an active Draindeck run remain out of the supported
  model, unchanged by this fix.
- The crash harness's `fixture[f2-dirty-boot]` (`tests/crash/harness.py`)
  still asserts a clean worktree by the end of a full drain, but the
  mechanism changed: check 3 now correctly leaves the planted file alone at
  boot (no active issue, no baseline) — it is the WORKER's own
  unconditional `reset_hard(base)` at the first issue's EXECUTING entry
  (unrelated to this fix, mirrors ordinary reject/retry cleanup) that
  incidentally clears it later in the same run. The fixture's comment was
  updated to say so; the sharper, single-call proof of check 3's own
  behavior is
  `test_bindings.py::test_check3_no_active_issue_preserves_preexisting_untracked`,
  following the same "bypass the worker, call recover() directly" pattern
  `fixture[f5-reset]` already established for isolating check-3 properties
  a timed kill can't reliably produce.

### ADR check
No ADR needed. Doc 03's event vocabulary is unchanged (payload fields are
additive, not new event types — established precedent, see `pid` and
`num_turns`); the state machine, transition tables, and external contracts
are untouched. Doc 11 §1.1's "mechanism only, zero policy" stance for the
adapter is preserved — `preserve_untracked`/`exclude_untracked` are
mechanism (which paths a git operation touches), the *policy* of which
paths those are still lives entirely in `recovery/bindings.py`.

## 3. Acceptance evidence
See the session's `/resolve-item` report for full command output: unit
suite (393 passed, up from 235 baseline + this session's 58 new tests),
durability harness `ALL 60 SCENARIOS PASSED` on both seed 42 and seed 1337.

## 4. Remaining risk (explicitly out of scope here)
A new untracked file appearing in a target repo *while an issue is
genuinely ACTIVE* is still evaluated against that issue's latest
execution's baseline — if a human added a file after that baseline was
captured, it would be misclassified as residue. This is a narrower
exposure than the reported bugs (both real incidents had no execution
whose baseline could even apply) and sits inside the workspace's existing
exclusive-ownership assumption (`WorkspaceLease`) — concurrent human edits
during an active run are not a supported scenario. Flagged, not fixed here,
per the "avoid unrelated feature expansion" instruction for this pass.
