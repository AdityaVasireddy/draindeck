# 11 — RepositoryAdapter, Reconciler Seam Binding, Git-World Crash Harness (Session 3)

**Status:** IMPLEMENTED & VERIFIED · **Date:** 2026-07-11
**Scope:** Session 3 per doc 07 ordering. Makes the git boundary real:
`RepositoryAdapter` + `GitCliAdapter`, the three reconciler seams bound to it,
and the kill-9 harness rebuilt on a real temp git repository. Doc 03 is the
frozen contract; doc 03 won every conflict.

This document is the as-built record. Where the pre-implementation design (the
approved Session-3 plan) changed under contact with real git, the delta is
called out inline.

## Verified vs. assumed (honesty discipline)

**VERIFIED by running this session (Windows, Python via `.venv`, git 2.53.0):**
- Baseline before any new code: 19/19 unit tests; 46/46 harness scenarios ×
  2 seeds — after fixing a real Windows-portability bug (harness crashed
  encoding `→`/`—` under the cp1252 console; now forces UTF-8 on stdout/stderr).
- After Session 3: **58/58 unit tests** (19 foundation + 26 `test_git_adapter`
  + 13 `test_bindings`); **50/50 harness scenarios on seeds 42 and 1337** (16
  crash points × 2, 15 random-timing rounds landing ≥10 kills each, 2 planted
  fixtures, 1 control).
- **Mutation M1** (gut `preserve_residue` → return None): harness went red on
  I-m (`killed at engine:post-edit … but no ExecutionCrashed carried a
  residue_ref`). Reverted. **Mutation M2** (drop `clean -fd`): unit test
  `test_reset_hard_removes_untracked` went red. Reverted. The suite can
  actually fail.

**ASSUMED / NOT verified:** power-loss durability (git ref/object fsync is
`core.fsync`-dependent — out of scope on the same grounds as the harness's
page-cache caveat; kill-tests prove process-crash durability only). The real
`claude -p` engine, reviewer, budget, queue, and orchestrator loop are not in
scope this session. Git ≥ 2.38 (for `merge-tree --write-tree`) is enforced at
adapter construction; verified present here, assumed to be checked in other
environments.

---

## 1. RepositoryAdapter (`src/runtime/repo/adapter.py`, `git_adapter.py`)

### 1.1 Stance
Mechanism only, zero policy. The adapter never appends events, reads the log,
or reads config. Constructed once as `GitCliAdapter(repo_path, ref_namespace)`
from `config.project.repository` / `config.attempts.ref_namespace`; every path
and branch is a method argument (ADR-20). All git goes through one `_git`
runner: `cwd`-pinned, `GIT_TERMINAL_PROMPT=0`, 60 s timeout, identity injected
per-invocation (`-c user.name/-c user.email`) so commits never depend on the
target repo's config; snapshot commits use `--no-verify` so the target repo's
hooks can't block evidence. Errors surface as `RepoError`; merge conflicts as
`MergeConflictError`. Nothing is swallowed.

### 1.2 Methods (idempotency contract)
Read witnesses (idempotent): `current_commit`, `head_of`, `is_dirty`
(tracked+untracked, ignored excluded), `commit_exists`, `is_ancestor` (check
2's witness, doc 02 §4.2), `ref_target`, `list_attempt_refs`, `diff` (ADR-15),
`find_merge_commit` (locates a merge by its second parent — deterministic
because merges are always two-parent no-ff).

Mutations: `checkout_branch(create_from=…)` (idempotent, refuses dirty);
`snapshot_commit` (**convergent** — returns None on a clean tree, so callers
use `snapshot_commit() or current_commit()`); `set_attempt_ref` (evidence
never regresses: unset→X / X→X / fast-forward-only, else `RepoError`);
`reset_hard` (`reset --hard` **plus** `clean -fd` — untracked files a bare
reset leaves would break I1); `merge_to` (§1.3, **not** idempotent — caller
check-then-acts with `is_ancestor`); `delete_attempt_refs` (ADR-15 GC, wired
into the adapter but not called anywhere yet — deferred to orchestrator
policy); `recover_workspace` (clears stale `.git/index.lock` / merge state
left by a killed git process; safe because recovery precedes all spawning and
v1 is single-writer, ADR-04).

A no-op instrumentation seam `_checkpoint(name)` sits between the internal
steps of `snapshot_commit` and `merge_to`. Production: no-op. The harness
overrides it (in a `GitCliAdapter` subclass) to inject kills mid-operation —
windows a timed external kill cannot reliably hit inside a single git
subprocess. This is test instrumentation, not an architecture change; it adds
one empty method to production.

### 1.3 `merge_to`: object-database merge (the load-bearing choice)
The CommitIntent→CommitCreated action is done entirely in the object DB, never
touching the worktree:
```
tree = git merge-tree --write-tree <target_head> <commit>   # git ≥ 2.38
mc   = git commit-tree <tree> -p <target_head> -p <commit> -m <msg>
git update-ref refs/heads/<target> <mc> <target_head>       # CAS on old value
```
Steps 1–2 create only unreferenced objects, so a crash before the atomic
`update-ref` is **zero observable world change**. The merge therefore has
exactly two post-crash states — "ref moved" or "ref didn't" — distinguished by
`is_ancestor(end_commit, target)`, which is precisely doc 02 §4.2's witness.
Because the worktree is never touched, a crashed merge can never be the cause
of a check-3 dirty workspace. Conflicts (structurally a tamper signal in v1)
raise `MergeConflictError`; the caller escalates rather than resolves.

### 1.4 Doc 09 §7 divergences resolved (doc 03 wins)
`push_attempt_ref` split into `snapshot_commit` + `set_attempt_ref` (each
crash window between them is now individually recoverable). Check-2 trigger is
the log-side intent/fact gap, not "HEAD ahead of last commit" (dead under the
object-DB merge, where HEAD never moves). Check 1 is always `ExecutionCrashed`,
never a witnessed finish (doc 10 row 13). Doc 09 omitted merge, ancestor check,
`find_merge_commit`, branch-from-base, stale-lock recovery, and ref GC — all
added per doc 03 §5 / doc 02 §4 / ADR-15.

---

## 2. Reconciler seam binding (`src/runtime/recovery/bindings.py`)
`bind_reconciler(adapter, target_branch)` returns the seam kwargs for
`recover()`. It is the only code that knows both git and the log; the adapter
is pure git, the reconciler pure log. Two supporting changes: `preserve_residue`
now takes the whole `ExecutionView` (needs `issue_id` + `base_commit`); the
projection was widened to carry `base_commit` (per issue and copied onto the
view at spawn), `end_commit`, and the CommitIntent payload — all straight from
doc 03 §3, no new events, no schema change.

**Check 1 — `preserve_residue`** (re-entrant by construction): existing ref →
short-circuit (window b6); else snapshot; residue = `sha or current_commit()`
(window b5); a clean tree still at base means nothing happened (b1). Then
`recover()` appends `ExecutionCrashed` — residue-ref-before-event ordering is
structural (the seam runs before the emit). Every EXECUTING-window crash (b1–b7)
converges; b2 and b3 are indistinguishable in the world (git has no testimony
about engine exit — `end_commit` is created by the orchestrator *after* exit),
which is exactly why an orphan is always CRASHED: `ExecutionFinished`'s payload
(exit_status, usage, duration, transcript) died with the process and cannot be
forged from git.

**Check 2 — unwitnessed commit**: for each CommitIntent without CommitCreated,
`is_ancestor(end, target)` → backfill `CommitCreated(backfilled=True)` via
`find_merge_commit`; else redo `merge_to` → `CommitCreated(backfilled=False)`.
Under the object-DB merge, c1 and c2 collapse to the same "redo" path. If `end`
is on target but no merge commit witnesses it (a human squash/ff), recovery
**raises `ReconcilerTamperError`** rather than forge the join key (ADR-11).

**Check 3 — dirty workspace**: restores the workspace to the commit implied by
the log's last pinned expectation (VALIDATING/REVIEWING/ACCEPTED → its
`end_commit`; terminal-and-active → base; no active issue → target head),
archiving any residue first (guarded against double-archiving b7's ref). It
**emits no event** — doc 03's vocabulary has none and inventing one would be an
ADR — so its evidence trail is the attempt ref plus
`RecoveryReport.workspace_repairs` (harvested from a `repairs` attribute on the
seam, so recovery still never silently claims work).

---

## 3. Git-world crash harness (`tests/crash/`)
The world is now a real temp git repo (`git init`, seed commit + `.gitignore`,
target branch `trunk` — deliberately not `main`, proving nothing hardcodes it;
work happens on a persistent `work` branch). The worker's engine stage does
`reset_hard(base)` → edit `issues/<issue>.txt` + an untracked scratch file →
`snapshot_commit` → `set_attempt_ref`; the commit stage does the real object-DB
`merge_to`. Recovery runs the production `bind_reconciler` path — checks 2 and 3
are no longer SKIPPED.

**Invariants:** log-level I-a…I-h retained; I-f's file-artifact checks replaced
by git-level **I-i** (each end_commit is a real commit == its attempt ref; each
residue_ref resolves and is diffable from base), **I-j** (exactly one merge on
trunk's first-parent chain per issue, second-parent = accepted end_commit,
matching the CommitCreated.merge_commit set), **I-k** (final tree clean, no
index.lock/MERGE_HEAD, HEAD on a branch), **I-l** (merge_commit ancestor of
trunk; trunk's `issues/<issue>.txt` names the accepted execution), **I-m**
(a kill at a provably-dirty point yields a non-null residue_ref).

**Crash surface:** 16 deterministic points × 2 — 10 `after_append:*`, plus
worker-level `engine:post-edit/-snapshot/-attempt-ref` and adapter-internal
`git:snapshot:post-add` and `git:merge:post-tree/-commit-tree/-update-ref` (via
`_checkpoint`). Plus planted fixtures **f1** (stale index.lock + dirty tree →
`recover_workspace` + check 3) and **f2** (dirty boot → check 3). A `--points`
filter (4th argv) iterates one point family for fast debugging.

**Mutation-testability (as-built delta):** M1 (lazy `preserve_residue`) fails
the harness on I-m, as designed. M2 (drop `clean -fd`) is caught by the adapter
unit test `test_reset_hard_removes_untracked` rather than the harness — my
check-3/residue paths snapshot untracked files before any reset, so `clean -fd`
is load-bearing precisely at the adapter primitive, where the unit test pins it.
The planned fixture f3 (check-2 tamper) is covered by unit test
`test_check2_tamper_raises`; a tamper mid-harness would surface as an `errored`
restart, which `restart_until_done` already forbids, so a separate harness
fixture would be redundant.

---

## 4. Provisional (NOT frozen) — Session 4+ interfaces
Engine wrapper `ClaudeHeadlessEngine.run(prompt_file, workspace) -> EngineResult`
(advisory only, ADR-07; strips `ANTHROPIC_API_KEY` in subscription mode,
ADR-18). Reviewer `ReviewerProvider.review(ReviewPack) -> ReviewVerdict` (diff +
issue + guidelines + validation output only; malformed → reject, never
retry-until-approve). Orchestrator loop = the harness worker's `step()` shape
(pure dispatcher from projection to the next transition-table row) with real
seams substituted; startup order config → log → `recover(**bind_reconciler(…))`
→ health checks → loop, with incremental projection application replacing the
worker's replay-per-step.

## 5. Files
New: `src/runtime/repo/{__init__,adapter,git_adapter}.py`,
`src/runtime/recovery/bindings.py`, `tests/unit/test_git_adapter.py`,
`tests/unit/test_bindings.py`. Changed: `events/projections.py` (widened),
`recovery/reconciler.py` (seam signature + `recover_workspace` +
`workspace_repairs`), `tests/crash/{worker,harness}.py` (git world),
`tests/unit/test_foundation.py` (seam-signature update). No change to the frozen
contract (doc 03) or the event schema.
