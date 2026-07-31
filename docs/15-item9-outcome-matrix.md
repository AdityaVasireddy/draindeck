# Item-9 Outcome Matrix — orphan-crash recovery, pre-committed predictions

**Status: DESIGN GATE. Pre-committed BEFORE any fault injection. No crash has been run
against this matrix yet — every cell below is a mechanical projection from source, not
an observation.** Produced per CLAUDE.md's high-blast-radius discipline (real
repository mutation / recovery behavior) — this doc is issue-runtime-side only; nothing
in this commit touches `C:\Projects\StockPhotoAgent`.

Builds on the prior turn's source trace (reap-path confirmed, not re-litigated here):
`EXECUTION_SPAWNED` fsync'd (`loop.py:186`) before `engine.run` (`loop.py:212`); check 1
(`reconciler.py:83-98`) unconditionally precedes check 3 (`reconciler.py:101-111`);
check 3's `already` guard (`bindings.py:92-93`) makes its own archival step a no-op once
check 1 has already recorded the residue ref, and its `reset_hard` only cleans the tree,
it does not destroy evidence.

## 0. Two premise corrections (verified against current HEAD this turn)

**item-14 is FIXED, not open.** `loop.py:342` calls `delete_attempt_ref(issue,
ex.execution_id)` — execution-scoped — not the issue-scoped `delete_attempt_refs(issue)`
NEXT.md item 14 describes. The issue-scoped method no longer exists in `src/` (removed
entirely per the fix commit). Fixed by `9c071ed` ("fix(repo): scope attempt-ref GC to
the completing execution (ADR-15 Amendment 1)", 2026-07-27 20:29:01), documented in
`docs/08-session-0-closure-and-adr-amendments.md` §5e. `NEXT.md` item 14 had never been
updated to reflect this — a doc-staleness gap — **corrected this session**: item 14's
"Fix: NOT designed or implemented" line is now struck with a dated 2026-07-29 correction
note appended in place (append-only pattern, original text preserved/annotated, not
rewritten). **Row B below predicts on current source: the crashed sibling's residue ref
SURVIVES a later same-issue `IssueCompleted`.**

**Scenario D's real discriminator is in `reap_orphans`, not in `recover()`'s check 1.**
`reconciler.py:86-87`'s `continue` (skip a genuinely-alive execution) is unreachable via
either CLI entrypoint at current HEAD: `cmd_run` always runs `reap_orphans`
(`main.py:184`) before `recover()` (`main.py:196`), and `reap_orphans` unconditionally
unlinks the pidfile for everything it globs (`claude_headless.py:359`) whether or not the
kill actually raced — so `is_execution_alive` (which reads that same pidfile,
`claude_headless.py:369-372`) is structurally `False` by the time check 1 asks. `cmd_recover`
(`main.py:74-76`) passes no `is_execution_alive` override at all (defaults to `lambda
_xid: False`). The real GAP-1 liveness discriminator is `_alive_by_record(rec)`
(`claude_headless.py:447-452`), consulted inside `reap_orphans` itself
(`claude_headless.py:353`). Row D predicts against that, not against `reconciler.py:86-87`.

## 1. Confidence legend

- **VERIFIED** — mechanically confirmed against current source this session (file read,
  line-cited), or will be settled by a command whose output is unambiguous.
- **INFERRED** — follows from source structure but depends on a timing/ordering property
  not yet witnessed live (see GAP-1 below); stated as a prediction, not a settled fact.
- **NOT-OBSERVABLE** — no artifact exists that could confirm or falsify this claim through
  the live-run mechanism available; labeled rather than smuggled in as a pass.

**GAP-1 (carried, not resolved by this matrix):** `reap_orphans` completing its kill
*before* `recover()`'s check 1 evaluates `is_execution_alive` is a **timing property**.
Source order guarantees the *call* to `reap_orphans` (`main.py:184`) precedes the *call*
to `recover()` (`main.py:196`) — that part is VERIFIED (it's just line order in one
synchronous function). Whether the OS has actually finished tearing down the killed
process tree by the time `recover()` runs is INFERRED, not VERIFIED, until witnessed live
with an independent `tasklist` snapshot bracketing both sides. **Every row below that
depends on `reap_orphans` having already neutralized a live child inherits INFERRED for
that specific sub-claim**, even where the rest of the row's prediction is source-certain.

## 2. Locked context recap

- Start state (previous turn, re-verified mechanically): StockPhotoAgent `agent-work` /
  clean / `45e545acb3ef15c9970b1668731ca710e3a50381`; `Issues.md` = issues 7/8/9;
  `refs/attempts` empty; reviewer `localhost:11434` serving `qwen2.5-coder:14b`;
  issue-runtime `state/events.jsonl` at 45 events, last event `IssueCompleted` for issue 5.
- **The real run reuses this same event log.** `config.yaml:70` — `event_log.path:
  state/events.jsonl` — is not scoped per target repo. Any real item-9 run appends to
  the SAME file already at 45 events; new records are expected starting at `event_id 46`.
- Issue base-commit chaining (`loop.py:151-156`, `_activate`): `base_commit =
  adapter.head_of(self.target)` — the branch head **at activation time**, not a fixed
  pre-run snapshot.
- Sequential-only scheduling (`loop.py:112-122`, `_next_actionable`): an ACTIVE issue is
  always returned before any PENDING issue is even considered — comment at
  `loop.py:114`, "finish it before starting another, sequential per doc 01". Only one
  issue can be ACTIVE at a time under this design.
- `_expected_commit` canonical current source (`bindings.py:130-147`, exact lines as read
  from disk this session — cited in full to avoid the stale-shifted rendering from the
  prior turn's trace):
  ```
  130  def _expected_commit(
  131      proj: StateProjection, adapter: RepositoryAdapter, target_branch: str
  132  ) -> Optional[str]:
  133      """The commit the workspace should sit at, from the log's last pinned
  134      expectation (docs/11 §2.3 table)."""
  135      iid = _active_issue(proj)
  136      if iid is not None:
  137          latest = proj.latest_execution(iid)
  138          if latest is not None:
  139              if latest.state in (ExecutionState.VALIDATING,
  140                                  ExecutionState.REVIEWING,
  141                                  ExecutionState.ACCEPTED):
  142                  return latest.end_commit
  143              if latest.state in (ExecutionState.REJECTED, ExecutionState.CRASHED):
  144                  return proj.issue_base_commit.get(iid)
  145          # active issue, no execution yet → sit at the issue base
  146          return proj.issue_base_commit.get(iid)
  147      return adapter.head_of(target_branch)
  ```
- Attempt-ref key format (both writers agree): `refs/attempts/<issue_id>/<execution_id>`
  (`bindings.py:32`, `git_adapter.py:241`).

## 3. The matrix

### Row A — Single crashed execution, issue does NOT later complete (isolated reap)

**Scenario.** Kill lands after `loop.py:186-187` (`ExecutionSpawned` fsync'd) and during
`loop.py:212` (`self.engine.run(...)`) — the child is mid-edit, uncommitted. The issue
is never retried to completion in this observation window (retry may be pending but not
yet resolved).

**Predicted event-log delta** (appended in this order, starting at `event_id 46`):
1. `IssueCreated` ×3 (issues 7, 8, 9), `IssueActivated` for the crashed issue — pre-crash.
2. `ExecutionSpawned` for `<issue>-e1` — pre-crash (`loop.py:186`), durable before kill.
3. *(kill happens here — nothing further written this run)*
4. On restart: `ExecutionCrashed` for `<issue>-e1`, payload `residue_ref:
   "refs/attempts/<issue>/<issue>-e1"`, `last_known_state: "EXECUTING"`
   (`reconciler.py:89-96`).
5. No `CommitIntent`/`CommitCreated`/`IssueCompleted` for this execution (it never
   reached the commit sequence).

**Predicted ref state.** `refs/attempts/<issue>/<issue>-e1` present, pointing at a commit
whose message is `"crash residue <issue>-e1"` (`bindings.py:35`), authored via `git add
-A` + `git commit --no-verify` on whatever branch was checked out at kill time
(`issue/<n>`, per `loop.py:204`).

**Predicted tree state.** After `recover()` returns: `HEAD` == `expected` from
`_expected_commit` — since the execution is now `CRASHED`
(`bindings.py:143-144`, `latest.state in (REJECTED, CRASHED) → issue_base_commit`), tree
is reset (`bindings.py:102`) to the issue's own base commit — **issue-base class**, not
residue, not agent-work's tip.

**Witnessing artifact.**
- `tail -n +46 state/events.jsonl` (or `grep '"event_id":' state/events.jsonl | tail`) —
  raw JSON lines, settles the event-log delta claim character-for-character.
- `git for-each-ref refs/attempts/<issue>` in `C:\Projects\StockPhotoAgent` — settles ref
  presence/key.
- `git cat-file -p <residue_sha>` / `git log -1 --format=%s <residue_sha>` — settles the
  `"crash residue <execution_id>"` message claim.
- `git rev-parse HEAD` compared against the `ExecutionCrashed` event's issue and the
  `IssueActivated.base_commit` for that issue (grep the log) — settles tree-state class.

**Falsifier.** Any of: `ExecutionCrashed` absent after restart; `residue_ref` present in
the event but `git rev-parse` on that ref fails; `HEAD` after recovery is neither the
residue commit nor the issue base (e.g. still `agent-work`'s tip, or mid-branch).

**Confidence.** INFERRED (depends on GAP-1 — reap_orphans having fully killed the child
before check 1 runs; if the child were still writing to the tree during check 1's
`snapshot_commit`, the residue captured would be a race-torn partial state, not
necessarily the exact kill-moment tree).

---

### Row B — Crashed execution, SAME issue later reaches `IssueCompleted` (item-14 path)

**Scenario.** Same kill point as Row A (`loop.py:212`, mid-`e1`), but the retry (`e2`)
subsequently succeeds and the issue completes (`ISSUE_COMPLETED` emitted at
`loop.py:339`).

**Predicted event-log delta** (in order): `ExecutionSpawned(e1)` → *(kill)* →
`ExecutionCrashed(e1)` (on restart, residue_ref set) → `ExecutionSpawned(e2)` →
`ExecutionFinished(e2)` → `ValidationPassed(e2)` → `ReviewApproved(e2)` →
`CommitIntent(e2)` → `CommitCreated(e2)` → `IssueCompleted`.

**Predicted ref state — CORRECTED from the task's stated premise (§0 above).** Per
current source (`loop.py:342`, `git_adapter.py:240-245`), `IssueCompleted`'s GC call is
`delete_attempt_ref(issue, ex.execution_id)` — scoped to `e2` (the completing execution)
**only**. Prediction: `refs/attempts/<issue>/<issue>-e2` is **deleted** (GC'd, redundant —
its content is already reachable via the merge commit); `refs/attempts/<issue>/<issue>-e1`
(the crashed sibling's residue) **SURVIVES**, indefinitely, per doc 08 §5e ("Residue
lifecycle... Not by this mechanism, and not automatically at all under this amendment").

**Predicted tree state.** Unaffected by the GC step itself (`delete_attempt_ref` only
touches refs, never the worktree) — same as whatever the post-`IssueCompleted` state
otherwise is (`agent-work`, since `_commit_sequence` runs after `checkout_branch` in the
normal loop, not mid-recovery).

**Witnessing artifact.**
- `git for-each-ref refs/attempts/<issue>` immediately after `IssueCompleted` appears in
  the log — expect exactly one line, the `e1` residue ref; `e2`'s ref absent.
- `git rev-parse refs/attempts/<issue>/<issue>-e1` — expect success (exit 0), a real sha.
- `git fsck --unreachable` — expect the `e1` residue commit NOT listed as dangling (it's
  anchored by the surviving ref).
- Cross-check against `git merge-base --is-ancestor <e2 end_commit> agent-work` — expect
  exit 0 (the commit-message's own stated safety argument for why `e2`'s ref is safe to
  drop).

**Falsifier.** `refs/attempts/<issue>/<issue>-e1` absent or `git rev-parse` on it fails
after `IssueCompleted` — this would mean item-14 regressed. (The task's original
framing — predicting the residue ref is deleted — is the thing this row explicitly
does NOT predict, per the §0 correction; if the ref IS gone, that falsifies THIS row's
prediction and reopens item-14, it does not confirm the old NEXT.md text.)

**Confidence.** VERIFIED for the GC-scope mechanism itself (read directly from current
`loop.py`/`git_adapter.py` source, matches the fix commit's own pre-committed re-test
description in its commit message) — but that commit message's gate results (117/117
unit, 60/60 harness, scratch re-test) are the **prior session's self-report**, not
independently re-run by me this turn; treat the GC-scope *code path* as VERIFIED-by-
reading, the *prior test run* as reported-not-reproduced. The `ExecutionCrashed(e1)`
piece of this row inherits Row A's INFERRED (GAP-1).

---

### Row C — Kill lands after `CommitIntent`, before `CommitCreated` (check-2 territory)

**Scenario.** Kill lands after `loop.py:313-316` (`CommitIntent` emitted, fsync'd) and
before `loop.py:330-333` (`CommitCreated` emitted) — i.e., during or after
`adapter.merge_to`/`find_merge_commit` at `loop.py:320-329`, or in the gap between the
merge finishing and the fact event being appended.

**Predicted behavior.** This execution is in the `ACCEPTED`/commit-sequence state, NOT
`EXECUTING` — `proj.open_executions()` (`projections.py:75-79`) filters on
`ExecutionState.EXECUTING` only, so check 1 does **not** touch this execution at all (no
`ExecutionCrashed`, no residue archival for it). Check 2 (`check_unwitnessed_commit`,
`bindings.py:41-76`) is the relevant path: `view.commit_intended and not
view.commit_created` is `True` (`bindings.py:48`) → asks `adapter.is_ancestor(end,
target)` (`bindings.py:54`).
- **If the merge itself completed before the kill** (git's `update-ref` at
  `git_adapter.py:236` landed): `is_ancestor` → `True` → `find_merge_commit` locates the
  existing merge commit (`bindings.py:55-64`) → emits `CommitCreated` with
  `backfilled: true` (`bindings.py:65,69-75`).
- **If the merge did NOT complete** (kill landed mid `merge_to`, before `update-ref`):
  `is_ancestor` → `False` → check 2 **redoes** the merge via `adapter.merge_to` itself
  (`bindings.py:67`) → emits `CommitCreated` with `backfilled: false`.

Either sub-case: exactly one `CommitCreated` event, no duplicate merge commit (check-then-
act via `is_ancestor` before deciding), tree ends on `agent-work` at the (possibly new)
merge commit.

**Predicted event-log delta.** `..., CommitIntent(e), CommitCreated(e, backfilled=<true|
false>), ...` — no `ExecutionCrashed` anywhere for this execution.

**Predicted ref state.** No new attempt-ref activity from checks 1/2 for this execution
(check 1 never sees it; check 2 emits no ref writes, only the merge/commit).

**Predicted tree state.** `agent-work` at the merge commit — same class as `_expected_commit`
would compute if this issue's latest execution were `ACCEPTED` (`bindings.py:141-142`,
`return latest.end_commit`) — but note `_execution_transition` never advances this
execution past whatever state the log shows; check 3, if it runs afterward, would find
`head == expected` (already reset/settled by check 2's own merge/checkout side effects
on `agent-work`) and be a no-op for this issue, PROVIDED `agent-work` was the branch
current at that point — `checkout_branch` runs only at `main.py:215`, after `recover()`
returns, so whatever branch check 2's `merge_to` operated `update-ref` against is
`agent-work` directly (`git_adapter.py:236`, `refs/heads/{target_branch}`) regardless of
what's checked out — the working tree itself may still be sitting on `issue/<n>` until
step 7b's checkout runs.

**Witnessing artifact.**
- `state/events.jsonl` tail — exact event type/order/`backfilled` value.
- `git log agent-work -1 --format="%H %P"` — confirms a merge commit (two parents) landed,
  and which second-parent sha it carries (should equal `CommitIntent.end_commit`).
- `git branch --show-current` immediately post-`recover()`-pre-`checkout_branch` (would
  require an instrumented pause — otherwise only observable indirectly via the stdout
  ordering of `[startup] checked out agent-work` vs. any check-3 repair line).

**Falsifier.** Two `CommitCreated` events for the same execution; `backfilled` value that
doesn't match whether the merge commit pre-existed; a duplicate merge commit (two merge
commits both carrying the same `end_commit` as second parent) — `check_unwitnessed_commit`
raises `_tamper` (`bindings.py:61-64`) rather than forging in the one case it can detect
(end is on target but no merge commit witnesses it) — that raised `ReconcilerTamperError`
would itself be the observation, visible as a crash/traceback on restart rather than a
clean `[recovery]` line.

**Confidence.** VERIFIED — both the branch logic (pure source read, no timing dependency;
unlike checks 1/3, check 2 has no `is_execution_alive` involved at all) and the precise
sub-case (pre- vs. post-merge kill). Resolving the earlier draft's self-contradiction:
there is no artifact that directly observes "the kill landed one instruction before
`update-ref` vs. one instruction after," but none is needed — the `backfilled` flag in
the emitted `CommitCreated` event (`bindings.py:65` `True` / `bindings.py:68` `False`)
*is* the settling artifact for exactly that question, by construction (`is_ancestor` at
`bindings.py:54` is the same check the sub-case split hangs on). VERIFIED-observable-
via-`backfilled`, not NOT-OBSERVABLE.

---

### Row D — Genuinely live child at reap time (GAP-1 discriminator, corrected location)

**Scenario.** The orchestrator process is killed (parent only, no `/T`, per the
session-24 method) while the `claude -p` child is still actively running. On restart,
before `recover()` is ever called, `main.py:184`'s `engine.reap_orphans()` runs.

**Predicted behavior (in `reap_orphans`, `claude_headless.py:338-360`, not in
`reconciler.py`).** For the pidfile at `<artifacts_dir>/<execution_id>/pid`:
`_read_pidfile` (`claude_headless.py:440-444`) returns the recorded `{"pid": ..., image:
...}`. `_alive_by_record(rec)` (`claude_headless.py:447-452`) — VERIFIED alive iff the OS
still reports a process at that pid AND its image matches what was recorded at spawn
(defeats PID reuse). If True: `_kill_tree(rec["pid"])` (`claude_headless.py:354`,
`taskkill /F /T` on Windows) runs, and the repair string `"reaped orphan engine
<execution_id> (pid <pid>)"` is appended (`claude_headless.py:355-358`) and printed as
`[startup] reaped orphan engine ... (pid ...)` (`main.py:185`). The pidfile is then
unlinked unconditionally either way (`claude_headless.py:359`). By the time
`recover()`'s check 1 runs, `is_execution_alive` for this execution is `False`
regardless (pidfile gone) — check 1 proceeds exactly as Row A, `preserve_residue` +
`ExecutionCrashed`, never taking the `continue` branch.

**Predicted event-log delta.** Identical to Row A (`ExecutionCrashed` on restart) — Row D
differs from Row A only in what it proves about the PRE-check-1 window, not in the
post-check-1 event shape.

**Predicted ref/tree state.** Same as Row A.

**Witnessing artifact — the part that actually discriminates "genuinely live" from
"already dead by restart":**
- **Independent, out-of-band `tasklist /FI "PID eq <pid>"`** run by the test harness
  AFTER killing the orchestrator but BEFORE invoking the resume `cmd_run` — this is the
  only artifact that proves the child was alive at reap time; it must be captured before
  resume, because resume's own reap step destroys the evidence (kills the process) as a
  side effect of checking it.
- Presence of the `"[startup] reaped orphan engine <id> (pid <pid>)"` stdout line on
  resume — printed ONLY inside the `if _alive_by_record(rec):` branch
  (`claude_headless.py:353-358`), so its presence is a (weaker, in-band) proxy: if the
  child had already exited on its own before resume, the pidfile would still be found
  but `_alive_by_record` would return `False` (`claude_headless.py:453` region — no
  match), the `if` body would be skipped, and NO `"reaped"` line would print (only the
  unconditional unlink at line 359, silent).
- Absence of the `"reaped orphan"` line combined with presence of `ExecutionCrashed`
  would mean: the child had already exited by itself (not genuinely killed by reap) —
  still a valid crash-recovery observation, but NOT evidence that GAP-1's live-kill path
  was exercised.

**Falsifier.** `tasklist` (pre-resume) shows the pid absent (child already dead before
reap ran) while the run is being reported as "GAP-1 witnessed" — that would falsify the
live-kill claim specifically, independent of whether recovery itself still worked.

**Confidence.** The kill mechanism and pre-resume `tasklist` witness are VERIFIED-
witnessable (this is literally what session 24 already did once: "the real child was
confirmed alive via `tasklist` immediately after the orchestrator was terminated").
Whether `_alive_by_record` inside `reap_orphans` returns `True` at the moment it's
consulted (a few hundred ms to seconds after that `tasklist` snapshot, not simultaneous
with it) is INFERRED, not identical to the `tasklist` snapshot's own instant — the
`"reaped orphan"` stdout line is the closer-to-source-of-truth artifact and should be
treated as primary; `tasklist` is corroborating, not identical.

---

### Row E — Issues 8 & 9 share `iptc_embed.py`; crash on issue 8's execution

**Scenario.** Kill lands mid-execution on issue 8 (`loop.py:212`, during `e1`'s
`engine.run`), before issue 8 reaches any terminal state.

**Predicted behavior — sequential scheduling forecloses concurrency.**
`_next_actionable` (`loop.py:112-122`) returns an ACTIVE issue before considering any
PENDING one (`loop.py:118-119` precedes `120-121` in the same loop iteration, and only
one issue can be ACTIVE at a time under this design — `_activate` is the only path to
ACTIVE and `_next_actionable` won't reach a PENDING issue while one is already ACTIVE).
**Issue 9 therefore has NOT activated at crash time** — `proj.issue_base_commit` has no
entry for `"9"` yet; `IssueActivated` for issue 9 has not been emitted.

- **If issue 8 later recovers via retry and completes:** issue 9 activates only after
  issue 8 reaches `DONE`. `_activate`'s `base = adapter.head_of(self.target)`
  (`loop.py:152`) reads `agent-work`'s tip AFTER issue 8's merge has landed — issue 9's
  `base_commit` **includes** issue 8's fix to `iptc_embed.py`. Its execution branch
  (`issue/9`, `loop.py:204`, `create_from=base`) therefore starts from a tree where the
  hardcoded-`EXIFTOOL_PATH` defect (issue 8) is already fixed.
- **If issue 8 instead escalates without completing** (retry cap or duplicate-feedback
  guard, `loop.py:161-164`): issue 9 still only activates once issue 8 is terminal
  (`ESCALATED` is terminal for the issue row), but `agent-work`'s tip at that point does
  **not** include issue 8's fix — issue 9's base predates it.

Either way: issue 9's `base_commit` and issue 8's crash/retry history are NOT
independent random draws — they are causally ordered by the same `head_of(agent-work)`
read, strictly after issue 8's issue-level resolution, never concurrently.

**Predicted event-log delta.** `IssueActivated(8, base=B0)`, `ExecutionSpawned(8-e1)`,
*(kill)*, `ExecutionCrashed(8-e1)`, `ExecutionSpawned(8-e2)`, ... terminal event for issue
8 (`IssueCompleted` or `IssueEscalated`) — **then, and only then**, `IssueActivated(9,
base=B1)` where `B1` is `agent-work`'s tip at that later point. No interleaving of
issue-9 events between issue-8's spawn and issue-8's terminal event.

**Predicted ref state.** `refs/attempts/8/8-e1` (residue, survives per Row B's corrected
mechanism if 8 later completes via `8-e2`); no `refs/attempts/9/*` exists until issue 9
itself activates and executes — issue 9 has no attempt refs at crash time by definition
(it hasn't started).

**Predicted tree state.** At the moment of the crash, only `issue/8` (or `agent-work`,
post-recovery) is relevant; `issue/9` branch does not exist yet (`checkout_branch(...,
create_from=base)` for issue 9 has never run).

**Witnessing artifact.**
- `state/events.jsonl` — confirm zero issue-9 events appear between issue-8's
  `ExecutionSpawned` and issue-8's terminal event (grep by `"issue_id":"9"` positions
  relative to `"issue_id":"8"` positions, by `event_id` order).
- `grep '"issue_id":"9"' state/events.jsonl | grep IssueActivated` for the `base_commit`
  payload value, then `git merge-base --is-ancestor <issue-8's merge commit sha>
  <that base_commit>` in StockPhotoAgent — exit 0 confirms chaining (issue 8's fix
  included); exit 1 (or the base predating issue 8 entirely) confirms the
  escalation-without-completion sub-case.
- `git show <issue-9 base_commit>:src/agencies/alamy/iptc_embed.py` vs. `git show
  agent-work:src/agencies/alamy/iptc_embed.py` (pre-run, `45e545a`) — diff presence
  confirms whether issue 8's fix is textually present at issue 9's base.

**Falsifier.** Any issue-9 event (`IssueActivated` or later) with an `event_id` lower
than issue-8's terminal event's `event_id` — would falsify the sequential-scheduling
claim itself, a much bigger finding than this row (would mean `_next_actionable`'s
stated invariant is violated in practice).

**Confidence.** VERIFIED for the scheduling logic (pure source read, `loop.py:112-122`,
no timing dependency — it's a projection query, not a race). The specific
completes-vs-escalates branch content inherits Row A/B's respective INFERRED/VERIFIED
labels for their own sub-claims.

## 4. Cross-cutting falsifiers (any row)

- `ReconcilerTamperError` raised on restart (`bindings.py:150-156`, `_tamper` call
  sites at `bindings.py:53,61-64`) — would abort recovery entirely; visible as a Python
  traceback / nonzero exit on `cmd_run`, not a clean `[recovery]` stdout block. Any row
  predicting a clean recovery is falsified if this fires instead.
- Any duplicate `event_id` or non-monotonic `event_id` in `state/events.jsonl` post-crash
  — would indicate the log's single-writer append guarantee broke, invalidating every
  row's "exact order" predictions simultaneously (a log-layer failure, not a
  reconciler-logic failure).

## 5. What this matrix does not cover

- The actual fault-injection commands/timing (kill signal, wait windows, harness
  scripting) — explicitly deferred to the next design step, not authored this turn.
- Independent re-run of the 117/117 unit + 60/60 harness gates commit `9c071ed` claims —
  those are the prior session's self-report in this turn, not reproduced by me.
- `NEXT.md` item 14's stale text — flagged in §0; corrected this session (see the
  `NEXT.md` diff accompanying this commit) — no longer out of scope, closed.

## 6. Group R/S execution phases (pre-committed witness plan)

**Status: pre-committed execution plan, NOT yet run. Promoted from HANDOFF_2026-07-31
Knowledge Captured, verbatim.**

Run Group R (startup recovery on the `10-e2` fixture) then Group S (live orphan witness
using the layered discriminator) against real StockPhotoAgent — gated on Adi's explicit
go-ahead.

- **Group R** = startup recovery of the 10-e2 fixture. PASS requires BOTH:
    (1) ExecutionCrashed(10-e2) appears in the event log ordered BEFORE any fresh
    ExecutionSpawned retry for the same issue — crash-and-preserve precedes re-spawn;
    (2) that ExecutionCrashed carries residue_ref NON-null (a real refs/attempts ref that
    git rev-parse resolves) — the first non-null residue this project has witnessed live,
    contrasting 10-e1's correct null (empty-tree stdin-starvation death, §6 below). HARD
    STOP after Group R; Group S does not begin until Group R passes.
- **Entrypoint discipline (LOAD-BEARING):**
  - Group R (and any gated recovery-only phase) MUST use `python -m runtime.main recover`
    — recovery-only, prints a report, spawns NO fresh executions, satisfies HARD STOP by
    construction.
  - `python -m runtime.main run` is the FULL orchestrator loop: it crash-recovers dangling
    executions AND THEN continues — spawning fresh executions, running real engine children,
    and merging real completions into the target. It does NOT stop after recovery and MUST
    NOT be used for any phase whose contract is "recover, then hard stop."
  - Session-25 failure of record: Group R was run with `run`; it recovered 10-e2 correctly
    (event 78, non-null residue — signal valid) but then spawned 10-e3 and merged issue-10
    to agent-work (b66e795), an unauthorized real mutation. Disposition: completion stands;
    10-e2 fixture consumed; Group S requires a fresh fixture.
- The recorded `child_pid` (the `claude.CMD` shim, image `cmd.exe`) reliably exits shortly
  after handing off to the real worker while work continues on disk — witnessed three
  separate times this session and the prior one. Group S must use `leaf_worker_pid` (Layer
  1) plus work-liveness via `capture_work_liveness` (Layer 2) as the orphan discriminator;
  `child_pid` alone is not a valid witness.
- Group S's planned witness sequence, as designed and promoted into this matrix:
  - **S-A** (pre-kill): both layers alive/advancing — `leaf_worker_pid` present in
    `tasklist`, and `capture_work_liveness` on the live edit target shows movement.
  - **S-B**: crash witnessed post-kill (the kill target is the **orchestrator** pid, `/F`,
    explicitly **no** `/T` — the opposite of the reset-kill's tree-kill — so the leaf worker
    is orphaned, not killed directly).
  - **S-C**: reap + residue preserved on resume.
  - **S-D**: no work repeated (no duplicate execution spawned for the same unit of work
    (issue/execution pair)).
  - **S-E**: no double-commit (merge commit's second-parent content check, same technique
    used in the earlier real-run session's fixture verification).
  - An ambiguous result on only one layer (e.g., leaf process gone but the work file still
    shows fresh activity, or vice versa) is a **STOP**, not an orphan claim — both layers
    must agree.
- `10-e1`'s crash produced `residue_ref: null` in its `ExecutionCrashed` event — not a bug.
  Confirmed via source read this session: `bindings.py`'s `preserve_residue` hits its own
  documented "b1: nothing happened" branch when `snapshot_commit` finds a clean tree, which
  is exactly what happened — `10-e1` died from stdin starvation (the pre-fix bug) before it
  ever touched the workspace. `10-e2` is different in kind: it holds a real, verified
  uncommitted edit (`config.ini.example`, +1 line), so the next recovery pass should
  produce a non-null residue ref for the first time this project has witnessed live.

Maps to matrix Row A/D. HARD STOP after Group R.

---
*Produced as a design-gate artifact, item 9 (orphan-crash recovery witness), following
the prior turn's `recover()`/`bindings.py` source trace. No StockPhotoAgent write, no
ingest, no `cmd_run`, no crash code authored this turn.*
