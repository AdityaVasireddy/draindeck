# Doc 25 — reconciler check-3 resets the checked-out branch onto an
# unmerged execution commit (2026-08-19)

Status: DONE. One confirmed runtime recovery bug, fixed via a gated
`/resolve-item`-style pass, per CLAUDE.md's high-blast-radius floor (real
repository mutation, `src/runtime` behavior, Git/recovery behavior). Surfaced
in a real LUVZ live run, after doc 18's two fixes (event-log isolation,
untracked-file preservation) were already active and working correctly.

**Correction (2026-08-19, later same day):** §"Root cause" below claims
production "runs the engine directly on the checked-out `target_branch`
(advancing its local tip in place, not on a separate per-issue branch)".
That claim is wrong. `git blame` on `loop.py:215` shows the per-issue-branch
checkout (`issue/{issue}`) has existed unchanged since the original
`loop.py` commit (`2608ac7`, 2026-07-12) — the engine has always run on a
per-issue branch, never on `target_branch` directly. This does not affect
this doc's fix or evidence, both of which stand. The corrected mechanism
(how `target_branch` actually ends up checked out when the collision this
doc fixes occurs) is in `docs/26-recovery-redo-merge-checked-out-target-collision.md`.

## 1. Problem — check-3 pins the branch at an unmerged commit, colliding
## with check-2's unwitnessed-commit guard

### Root cause
`_expected_commit` (`recovery/bindings.py`) computed the commit check-3's
`reset_hard` should restore the workspace to. For an active issue whose
latest execution was `VALIDATING`, `REVIEWING`, or `ACCEPTED`, it
unconditionally returned `latest.end_commit` — the execution's own produced
commit. While `CommitCreated` has not yet been witnessed for that execution,
`end_commit` is an unmerged, in-flight commit that lives only on its
`refs/attempts/<issue>/<execution>` ref (docs/11 §2.1); nothing has recorded
it as part of `target_branch`'s real history yet.

Because production `loop.py` runs the engine directly on the checked-out
`target_branch` (advancing its local tip in place, not on a separate
per-issue branch), `check_dirty_workspace`'s `adapter.reset_hard(expected)`
moved `target_branch`'s own ref onto that unmerged commit whenever it fired
during this window — not just the working tree. Once the run then reached
`ReviewApproved` → `CommitIntent` and tried to record `CommitCreated`, the
unwitnessed-commit guard (`check_unwitnessed_commit`, same file) correctly
found `end_commit` already sitting on `target_branch` with no merge commit
carrying it, and refused to forge one (ADR-11 join-key integrity):
```
[halt] run stopped abnormally: 69b00c1141a7 is on agent-work but no merge commit witnesses it — refusing to forge merge_commit
```
The guard did exactly what it was built to do. But the branch was already in
the state it exists to prevent claiming, and every subsequent `run`/`recover`
against the same config hit the identical halt — a deterministic dead end,
not a transient failure.

### Fix — narrowed to ACCEPTED, not all three states
An earlier draft of this fix (mid-session) changed `_expected_commit` to
return `latest.start_commit` for all of `VALIDATING`/`REVIEWING`/`ACCEPTED`
whenever `CommitCreated` was unwitnessed. The durability harness's
`fixture[f5-reset]` (`tests/crash/harness.py`) caught this as wrong: `VALIDATING`
and `REVIEWING` are deliberately designed to be re-runnable/re-callable
against the *produced* tree after a crash (`state/model.py`'s
`ExecutionState` comments — `VALIDATING`: "deterministic; re-runnable
against pinned tree"; `REVIEWING`: "re-callable; verdicts cacheable by
(issue, tree)"). Resetting either state to `start_commit` would validate or
review the wrong, pre-execution code on restart.

The actual collision is narrower than the state list suggests.
`CommitIntent`/`CommitCreated` are only ever legal while `state is ACCEPTED`
(`events/projections.py::_accepted_view` raises `TransitionError`
otherwise), and `EXECUTION_TRANSITIONS` (`state/transitions.py`) has no
outgoing row for `ACCEPTED` — once an execution reaches `ACCEPTED` it stays
there for the rest of the projection. So `commit_intended` can only ever be
`True` while `state is ACCEPTED`, and `check_unwitnessed_commit`'s guard
(`if not (view.commit_intended and not view.commit_created): continue`) can
only ever collide with check-3's reset for an execution in `ACCEPTED`.

`_expected_commit` now returns `latest.start_commit` only when
`latest.state is ExecutionState.ACCEPTED and not latest.commit_created`;
`VALIDATING` and `REVIEWING` keep returning `end_commit` exactly as before,
unchanged. `ExecutionView` gained a `start_commit` field (additive, no new
event, no schema change — same pattern as `base_commit`/
`pre_execution_untracked`; doc 03 already documents `start_commit` as a
required `ExecutionFinished` payload field, and `loop.py`'s single `common`
dict populates it on every real emission), captured in
`_execution_transition` and included in `StateProjection.digest()`'s canon.

### ADR check
No ADR needed under doc 08/doc 18's precedent: doc 03's event vocabulary,
transition tables, and external contracts are all unchanged — this is a
projection-side field widening (established additive pattern) plus a
narrower `_expected_commit` branch inside the reconciler's existing policy
function, not a new state, event, or schema change.

### What this does NOT change
- `VALIDATING` and `REVIEWING` still pin at `end_commit` — the pre-existing,
  tested behavior (`fixture[f5-reset]`) is untouched.
- `loop.py`'s own `reset_hard(base)` calls on the ordinary reject/retry/
  escalate paths are unchanged, same as noted in doc 18 — this fix is
  scoped to startup reconciliation only.
- Whether production should run the engine directly on `target_branch`
  versus a separate per-issue branch (which would avoid the branch-pointer
  coupling at its root) is a larger architectural question this fix does
  not attempt — it closes the specific collision without touching that
  design.

## 2. Acceptance evidence
Unit suite: 395 passed (up from 394 baseline this session — one net new
test; the ACCEPTED-only fix required both a regression test for the
narrowed case and a guard test proving REVIEWING still pins at
`end_commit`). Durability harness: `ALL 60 SCENARIOS PASSED` on both seed 42
and seed 1337, including `fixture[f5-reset]` — the fixture that caught the
overly-broad first draft of this fix.

Real LUVZ incident evidence (target repo
`C:\Projects\WebSites_Backup\Prod New Code`, branch `agent-work`):
`events.jsonl` shows `ReviewApproved` (event 36, verdict `APPROVE`) →
`CommitIntent` (event 37, target `agent-work`) → no `CommitCreated` — the
halt happened exactly at the ACCEPTED-state collision this fix addresses.
Branch tip stuck at `69b00c1141a7b53149c71ae39d1d501304987608` (unmerged),
last real witnessed commit `d0fa5d5b560a5e660c75f3b4626926505c7a17ab`.
Manual reconciliation (reset `agent-work` back to `d0fa5d5`, confirming
`69b00c1` remains reachable via `refs/attempts/L1/L1-e1`) and a retry run
against this fix are recorded in the same session's transcript.
