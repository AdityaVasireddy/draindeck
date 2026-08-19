# Doc 26 — recovery's redo-merge path can collide with `merge_to`'s
# checked-out-target guard (2026-08-19)

Status: SCOPE NOTE ONLY — for Adi's sign-off. No code changes made. Surfaced
in the same live LUVZ retry that followed doc 25's fix, immediately after
this session's manual `git reset --hard d0fa5d5` on the LUVZ target repo
severed the unmerged commit from `agent-work`'s ancestry (see
`docs/handoffs/HANDOFF_2026-08-19_adr25-accepted-only-fix-merge-to-blocker.md`).
Not yet investigated to a fix; this doc records the investigation and the
recommended direction only.

## 1. Problem

`recover()`'s reconciler check 2, `check_unwitnessed_commit`
(`src/runtime/recovery/bindings.py:53-88`), redoes a merge via
`adapter.merge_to(target, end, ...)` (line 79) whenever it finds a
`CommitIntent` with no matching `CommitCreated` and `end` is **not** already
an ancestor of `target`. `merge_to` (`src/runtime/repo/git_adapter.py:290-321`)
refuses outright if `target_branch` is the currently checked-out branch:

```python
def merge_to(self, target_branch: str, commit: str, message: str) -> str:
    target_head = self.head_of(target_branch)
    if target_head is None:
        raise RepoError(f"merge_to: target branch {target_branch!r} does not exist")
    cur = self._git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if cur == target_branch:
        raise RepoError(
            f"merge_to: HEAD is on {target_branch}; moving a checked-out "
            f"branch's ref desyncs index and worktree"
        )
    ...
```

The guard is protecting a real invariant: `merge_to` never touches the
worktree (`git_adapter.py:4`) — it computes the merge purely in the object
DB (`merge-tree`, `commit-tree`) and CAS-advances the branch ref with
`update-ref`. If that ref is also HEAD's current branch, the index and
worktree are left stale against the newly-advanced ref; every file in the
merge diff would show as locally modified. The guard is correct and should
not be weakened.

### Why this is reachable without manual intervention

`checkout_branch(...)` (real, non-`init`, non-abstract call sites — raw
`grep -rn "checkout_branch(" src/`):

```
src\runtime\loop.py:215:        self.adapter.checkout_branch(f"issue/{issue}", create_from=base)
src\runtime\main.py:321:        adapter.checkout_branch(cfg.project.branch)
src\runtime\main.py:392:                adapter.checkout_branch(cfg.project.branch)
src\runtime\repo\adapter.py:122:    def checkout_branch(self, branch: str, *, create_from: Optional[str] = None) -> None:
src\runtime\init\command.py:80:    `checkout_branch(..., create_from=X)` compiles to `git checkout -B
src\runtime\init\command.py:86:        adapter.checkout_branch(branch, create_from=head, allow_untracked=True)
src\runtime\init\command.py:88:        adapter.checkout_branch(branch, allow_untracked=True)
src\runtime\repo\git_adapter.py:212:    def checkout_branch(
```

Filtering out the two method *definitions* (`repo/adapter.py:122`,
`repo/git_adapter.py:212`) and the two `draindeck init`-time calls
(`init/command.py:86,88` — a one-shot setup command, not the run/recover
loop), only **two call sites check out `target_branch` specifically**:
`main.py:321` and `main.py:392`. The only other real call site,
`loop.py:215`, checks out a per-issue branch (`issue/{issue}`), not
`target_branch` — confirmed via `git blame` as present since the original
`loop.py` commit (`2608ac7`, 2026-07-12), unchanged since. During an active
execution (spawn → validate → review → commit), HEAD is always on
`issue/{issue}`; it is never on `target_branch` while an issue is in
flight. (This corrects doc 25 §"Root cause", which states production "runs
the engine directly on the checked-out `target_branch`" — that claim does
not match the code and predates this investigation; doc 25's fix and
evidence are unaffected, only its stated mechanism is wrong.)

`main.py:321` checks out `target_branch` at startup, **after** recovery but
**before** the run loop/ingest begins. `main.py:392` restores `target_branch`
in the `finally` block, **after** the loop ends or halts. Together these mean
`target_branch` checked out is the repo's normal **at-rest state** — true
whenever the orchestrator is not actively mid-loop on some issue, which is
most of the time between runs.

Critically, `_open_startup_recovery` (`main.py:146-175`) calls `recover(...)`
(line 169) — and therefore `check_unwitnessed_commit` → `merge_to` —
**before** `main.py:321`'s checkout. The comment at `main.py:318-319` states
this ordering is deliberate: *"Recovery intentionally precedes checkout: its
bound seams repair the current crash residue before checkout's dirty-workspace
guard runs."* So recovery always inherits whatever branch was checked out by
the **previous** process — which, per the at-rest convention above, is
routinely `target_branch` itself (left there by a prior clean shutdown's
restore-checkout, or by a crash inside the narrow window between
`main.py:321`'s startup checkout and the first issue's `loop.py:215`
checkout).

For the LUVZ incident specifically, the proximate trigger was the operator's
manual `git reset --hard d0fa5d5`, performed while `agent-work` was checked
out. But the state it produced — target_branch checked out going into
recovery — is not a manual-only anomaly; it is the same state production's
own startup/shutdown checkout convention leaves the repo in between any two
ordinary runs. A crash timed inside that startup-checkout-to-first-issue-
checkout window would reach the identical collision with zero manual
intervention.

## 2. Recommended fix direction

Not "execution should never happen on a checked-out `target_branch`" — it
already never does (per §1, `loop.py:215` always moves HEAD to `issue/{issue}`
before an execution runs). And not a change to `merge_to`'s guard — the
invariant it protects is real and the guard should stay strict.

**Recommendation: `check_unwitnessed_commit` (`bindings.py:53-88`) must
detect that `target_branch` is the checked-out branch before calling
`merge_to`, and handle it — most likely by checking out something else
(e.g. detached at `target_head`, or back onto whatever the in-flight
execution's own branch would be) immediately before attempting the redo-
merge, mirroring the same "check-then-act, no worktree mutation from
`merge_to` itself" discipline the rest of the adapter already follows.**
An alternative — deferring the redo-merge until *after* `main.py:321`'s own
checkout runs — was considered but rejected as the first-choice direction:
it would mean reordering "recovery precedes checkout" (an existing,
deliberate design boundary per the `main.py:318-319` comment, presumably
protecting other invariants this note has not audited), which is a larger
change than teaching one reconciler seam to check HEAD before it calls a
function that already tells it, precisely, why it refuses.

This note does not attempt the fix. Scope, blast radius (this touches
`src/runtime/recovery/bindings.py`, a high-blast-radius file per CLAUDE.md —
real repository mutation / recovery behavior), and whether an ADR is
required beyond this scope note are all open for Adi's call before any
code changes.

## 3. Open questions for sign-off
- Confirm the recommended direction (checkout-away-first inside
  `check_unwitnessed_commit`) versus the rejected alternative (reorder
  recovery after checkout) versus any third option Adi prefers.
- Whether "checkout away" should land on a scratch/detached ref, or on the
  in-flight execution's own `issue/{issue}` branch reconstructed from
  `ExecutionView.base_commit` — needs a decision before implementation,
  not assumed here.
- Whether this warrants a full ADR (docs/08 process) or can proceed as a
  gated `/resolve-item` pass like doc 25, given it touches recovery
  behavior (high-blast-radius) but is a narrow, single-seam fix similar in
  shape to doc 25's.
