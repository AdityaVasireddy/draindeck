# Doc 34 — Dashboard run-command queue-cancel: outcome matrix

Status: PROPOSED (pre-implementation gate for a safe Dashboard queue-cancel
action). Frozen contracts that govern this work: doc 03 (event/state semantics
— **`state/events.jsonl` is the sole authoritative runtime state**), ADR-30
(`docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md`, the
Dashboard-owned `run_commands` queue), doc 33 (the acknowledge/unlock +
clean-worktree preflight this builds beside), and CLAUDE.md's blast-radius
rules.

This document is the pre-committed outcome matrix required before any `src/`
change. The RED-test inventory that operationalises it is
`docs/plans/dashboard-run-command-cancel-failing-tests.md`.

## Problem statement

An operator selected several run batches from the Dashboard. Only one batch can
be active per repository at a time (ADR-30 one-active-batch-per-repository), so
the later batches sit `QUEUED` in FIFO id order behind the active one. Today the
only way to remove a still-waiting batch an operator no longer wants is to
hand-edit the Dashboard SQLite — exactly what we refuse to tell an operator to
do.

There is deliberately **no** cancel for a claimed/launched/abnormal/terminal
command: a `CLAIMED`/`LAUNCHED` command owns (or is about to own) a real
subprocess and workspace, and an `ABNORMAL_EXIT`/`LAUNCH_OWNERSHIP_UNKNOWN`
command is a safety-blocked state that must be resolved through the doc 33
acknowledge/unlock path, never silently discarded. Cancel is scoped to the one
state where nothing has run and nothing is owned: **exact status `QUEUED`**.

## Hard safety invariants (must hold in every row below)

1. **No runtime-state mutation.** Cancellation never writes/parses/repairs
   `state/events.jsonl`, never synthesises a `RunFinished`, never mutates a
   workspace lease, never touches the target git tree, never kills a process,
   and never deletes queue rows. It only advances a Dashboard-owned
   `run_commands.status` from `QUEUED` to the new terminal `CANCELLED`.
2. **Dashboard never reads/writes `events.jsonl`.** Cancel resolves nothing
   from the runtime; it is a pure control-plane status flip on one row.
3. **Cancellation metadata is Dashboard-only.** The new `CANCELLED` status lives
   solely in `run_commands`; it is never emitted as an event and is a
   Dashboard-only terminal status, exactly like `ACKNOWLEDGED` (doc 33).
4. **Cancel never retries and never auto-starts.** A successful cancel does not
   enqueue, claim, launch, re-plan, or expand any selection, and never triggers
   `try_launch_next` for the repository. It touches only the one cancelled row;
   no other command's `issue_ids_json`, status, or selection changes.
5. **Not blocked by launch preflight.** Cancellation is state-safe and is
   permitted even while the target worktree is dirty. It never calls the
   clean-worktree probe (doc 33 Part A). A dirty worktree must not prevent an
   operator from removing a waiting batch.
6. **Fail-closed on anything but exact `QUEUED`.** Only a command in exact
   status `QUEUED` is cancelable. Every other status is refused with a typed,
   actionable reason and no state change.
7. **FIFO / one-active-batch-per-repository preserved.** `CANCELLED` is
   deliberately **not** in `run_queue._BLOCKING_STATUSES`, so it never keeps a
   repository closed and never releases one that a `CLAIMED`/`LAUNCHED`/
   `ABNORMAL_EXIT` command was holding. Queue position is computed on read
   (`COUNT(*) WHERE status IN ('QUEUED','CLAIMED') AND id <= ?`), so a cancelled
   row drops out of the FIFO ordering automatically and every remaining
   `QUEUED` command's position recomputes correctly on the next read.

## Concurrency contract (cancel vs. claim; cancel vs. cancel)

Cancel and `claim_next_launchable_command` are **atomic competitors** for the
same row. Both serialize through `BEGIN IMMEDIATE`; cancel's linearization
point is a single conditional `UPDATE ... WHERE id = ? AND status = 'QUEUED'`
whose affected-row count decides the outcome.

- **Cancel wins the race** → the row is `CANCELLED`; a subsequent claim reads it
  as no longer `QUEUED` and either claims a different `QUEUED` row or returns
  `None`. **The cancelled command never launches.**
- **Claim wins the race** → the row is `CLAIMED`; cancel's conditional UPDATE
  matches zero rows and refuses `CANCEL_NOT_QUEUED`. Cancel never kills,
  signals, or otherwise interferes with the process the claim is about to spawn.
- **Two concurrent cancels** → exactly one conditional UPDATE affects the row
  (transitions `QUEUED → CANCELLED`); the other affects zero rows and returns an
  honest `CANCEL_NOT_QUEUED` conflict (409). Never a double transition, never a
  500.

## Outcome matrix

New: `run_queue.cancel_queued_command(conn, repo_id, command_id) -> dict` and
`POST /api/repositories/{id}/run-commands/{command_id}/cancel`.

| # | Situation | Outcome |
|---|-----------|---------|
| C1 | Command status is exactly `QUEUED` | **Success**: status → `CANCELLED` (Dashboard-only, non-blocking, terminal). No subprocess is spawned, now or later, for this command. Runtime events/outcome, workspace lease, git target, and every other command's `issue_ids_json`/status are unchanged. **No retry, no auto-start.** |
| C2 | Command status is `CLAIMED` | Refused `CANCEL_NOT_QUEUED` (409): already claimed for launch; cancellation never touches a claimed/running command. No state change. |
| C3 | Command status is `LAUNCHED` | Refused `CANCEL_NOT_QUEUED` (409): a real subprocess is running; cancel never kills it. No state change. |
| C4 | Command status is `LAUNCH_OWNERSHIP_UNKNOWN` | Refused `CANCEL_NOT_QUEUED` (409): an ambiguous spawn window resolved through startup reconciliation, not cancel. No state change. |
| C5 | Command status is `ABNORMAL_EXIT` | Refused `CANCEL_NOT_QUEUED` (409), message points the operator at **acknowledge/unlock** (doc 33 Part B), never cancel. No state change. |
| C6 | Command status is `ACKNOWLEDGED` | Refused `CANCEL_NOT_QUEUED` (409): already a terminal Dashboard state; nothing to cancel. No state change. |
| C7 | Command status is `COMPLETED` | Refused `CANCEL_NOT_QUEUED` (409): the process already exited. No state change. |
| C8 | Command status is `REFUSED` | Refused `CANCEL_NOT_QUEUED` (409): already terminally refused at dequeue. No state change. |
| C9 | Command status is `LAUNCH_FAILED` | Refused `CANCEL_NOT_QUEUED` (409): terminal launch failure; not a waiting batch. No state change. |
| C10 | Command status is already `CANCELLED` | Refused `CANCEL_NOT_QUEUED` (409): already cancelled; no action needed. No state change. |
| C11 | Cancel vs. claim race, cancel wins | Row `CANCELLED`; the concurrent claim gets a different `QUEUED` row or `None`. The cancelled command never launches. |
| C12 | Cancel vs. claim race, claim wins | Row `CLAIMED`; cancel refuses `CANCEL_NOT_QUEUED`. No process is killed or interfered with. |
| C13 | Two concurrent cancels of the same `QUEUED` command | Exactly one succeeds (`CANCELLED`); the other refuses `CANCEL_NOT_QUEUED` (409). No 500, no double transition. |
| C14 | Cancel one of two `QUEUED` commands | The cancelled row → `CANCELLED`; the remaining `QUEUED` command's `queuePosition` recomputes down (FIFO preserved). One-active-batch state unchanged. |
| C15 | Cancel while the target worktree is dirty | **Allowed**: cancel never runs the clean-worktree preflight (invariant 5). Both currently-queued commands are cancelable regardless of worktree cleanliness. |
| C16 | Unknown `command_id` | `NotFoundError` (404). |
| C17 | `command_id` exists but belongs to a different repository than `repo_id` in the path | `NotFoundError` (404) — the command is not found *for that repository* (no cross-repository cancel). |
| C18 | Cancel does not mutate runtime evidence | After cancelling a command that carries a `run_id_correlation`, the correlated `run_views` outcome row is byte-for-byte unchanged. |

## UI / documentation

- Run issues page: each `QUEUED` queue row gains a **"Cancel queued command"**
  button (only `QUEUED` — no other status shows it), behind a confirmation
  dialog stating that cancellation **removes only the waiting batch, never
  touches a running process, and does not alter runtime events**. On confirm,
  the queue is re-fetched so positions refresh correctly. The button is
  independent of the dirty-worktree run-control gate — an operator can cancel a
  waiting batch even when the run controls are disabled for a dirty worktree.
- `ABNORMAL_EXIT` rows keep only the doc 33 "Acknowledge failed command and
  unlock queue" action; they never show a cancel button. The two actions are
  distinct: **Cancel** removes a never-started `QUEUED` batch; **Acknowledge**
  releases a repository blocked by a failed (`ABNORMAL_EXIT`) run.
- README gains a "Queue controls" section explaining Cancel queued command vs.
  Acknowledge failed command and unlock queue.

## Amendment 1 — queue pause on cancel + explicit Resume (fixes the auto-start blocker)

**Defect fixed.** The first cut satisfied "cancel does not itself call
`try_launch_next`", but `QueueDrainScheduler` calls `try_launch_next` for every
repository every ~2 s. So cancelling `QUEUED` command #1 released the head of
the FIFO and the very next scheduler tick could claim and launch command #2 —
an auto-start the cancel contract forbids (invariant 4). A cancel that "removes
only the waiting batch" must not, as a side effect, promote the next batch.

**Contract.** A successful cancel now atomically (a) flips the command
`QUEUED → CANCELLED` **and** (b) writes a persisted, Dashboard-owned
per-repository **queue pause**, in one SQLite transaction. While a repository is
paused, *every* launch path — scheduler tick, explicit `/drain`, and the
enqueue-triggered `try_launch_next` — refuses to claim or launch any command for
that repository, because the single atomic claim
(`claim_next_launchable_command`) checks the persisted pause **inside its
existing `BEGIN IMMEDIATE` transaction, before selecting a `QUEUED` row**. The
pause is a row in a new `run_queue_pauses` table (presence ⇒ paused); it
survives a Dashboard restart because it is on disk, not in memory.

The pause is cleared **only** by an explicit operator **Resume queue** action
(`resume_repository_queue` / `POST /api/repositories/{id}/run-commands/resume`),
which deletes the pause row. Resume is permission to proceed: after it succeeds,
ordinary FIFO scheduler progression resumes and the next `QUEUED` command may be
claimed and launched normally. A new explicit run request is still accepted and
queued while paused (enqueue is unaffected), but it does **not** launch and does
**not** silently clear the pause — only Resume does.

Cancellation still never touches events.jsonl, a lease, Git, a process, or any
other command's selection; the pause is a pure control-plane row. Cancel and
Resume are both control-plane operations and stay usable while the target
worktree is dirty; the authoritative clean-worktree preflight still blocks the
actual dequeue/spawn at launch time (doc 33 Part A), so Resume permits
progression but a dirty worktree can still refuse the resulting launch.

| # | Situation | Outcome |
|---|-----------|---------|
| P1 | Cancel `QUEUED` #1 while `QUEUED` #2 waits | #1 → `CANCELLED` **and** the repository is paused, in one transaction. Repeated scheduler ticks / drains do **not** claim or launch #2. |
| P2 | Pause durability | The pause row is on disk; a fresh Dashboard/database connection still observes the repository paused (no claim/launch) until Resume. |
| P3 | Explicit `/drain` while paused | Returns `{launched: null}` — no claim, no launch. |
| P4 | New run request while paused | Accepted and enqueued (`QUEUED`), but not launched and the pause is unchanged; only Resume can clear it. |
| P5 | Resume | Deletes the pause row; the repository is no longer paused. Ordinary FIFO progression resumes; the next `QUEUED` command becomes claimable/launchable. |
| P6 | Resume is the only clearer | Nothing but an explicit Resume clears the pause — not a cancel, not a new enqueue, not a scheduler tick, not a drain. |
| P7 | Cancel-vs-claim race under the pause rule | Both serialize on `BEGIN IMMEDIATE`. If claim wins, it claims #1 (no pause yet) and cancel refuses `CANCEL_NOT_QUEUED` (status no longer `QUEUED`). If cancel wins, it writes the pause and the claim then reads the pause inside its own transaction and claims nothing. |
| P8 | Concurrent cancel + resume | Serialized; the final persisted state is consistent (either paused-then-resumed = not paused, or resumed-then-cancelled = paused). Never a partial write, never a 500. Only a genuine cancellation writes a pause; a losing/refused cancel writes none. |
| P9 | Resume of a repository that is not paused | Idempotent no-op success (`queuePaused: false`); unknown repository → 404. |
| P10 | Migration on an existing database | Additive `run_queue_pauses` table created by the v5→v6 step; no existing row is touched; a database with no pauses is simply unpaused. |

The pause is exposed to the UI additively on `GET
/api/repositories/{id}/run-commands` as `queuePaused`. The Run issues page shows
a persistent "Queue paused" notice with a **Resume queue** button (confirmation
copy: resuming permits the next waiting command to start), and the Cancel
confirmation copy now states that cancelling pauses the remaining queue until
Resume is selected.

## Amendment 2 — deferred progression on a dirty worktree (Resume must not lose a batch)

**Defect fixed.** Amendment 1's Resume endpoint (and the scheduler/drain/enqueue
launch paths) called `try_launch_next`, which **claimed** the head `QUEUED`
command and only then ran the clean-worktree preflight in
`revalidate_claimed_command` — so on a dirty worktree the claimed command was
marked **`REFUSED`** at dequeue. No process started, but the waiting batch was
silently lost. Resuming a queue while the target worktree happened to be dirty
therefore destroyed the very command the operator wanted to keep.

**Contract.** The clean-worktree preflight now runs **before** the atomic claim,
in the single `try_launch_next` orchestration path, guarded so it only runs when
a launch could actually happen (`has_launchable_command`: repository free, not
paused, a `QUEUED` row waiting). If the worktree is dirty, `try_launch_next`
returns a no-launch result **without claiming, refusing, cancelling, or
otherwise changing any command** — the waiting batch stays `QUEUED`, progression
is deferred until the worktree is clean. This one behavior is shared by every
caller: Resume, the `QueueDrainScheduler` tick, the explicit `/drain` route, and
the enqueue-triggered launch.

The pre-existing **post-claim** preflight in `revalidate_claimed_command` is
kept as a **race defense**: if the worktree was clean at the pre-claim check but
turned dirty in the narrow claim→spawn window, the claimed command is still
`REFUSED` before any subprocess spawns (fail-safe; a genuinely rare race, not
the ordinary dirty case). Direct new run requests against an already-dirty
worktree are still refused **before** any queue row is created (`enqueue_command`
`WORKTREE_NOT_CLEAN`, unchanged). No pause/cancel/acknowledge/process-ownership/
event-log/Git/lease/selection rule is weakened.

Resume stays an explicit operator action that clears the pause. When it defers
because the worktree is dirty, the API response says so (`progressionDeferred:
true`) and the UI status/confirmation copy states that a dirty target defers
execution and preserves waiting commands. Once the worktree is clean, the next
scheduler tick / drain claims and launches the next command in normal FIFO order
(the operator already resumed).

| # | Situation | Outcome |
|---|-----------|---------|
| D1 | Paused queue + dirty worktree + Resume | Pause cleared; `try_launch_next` defers (no claim); the next command stays `QUEUED` (never `CLAIMED`/`REFUSED`); no subprocess. Response `progressionDeferred: true`. |
| D2 | Dirty worktree + scheduler tick | Deferred before claim; the `QUEUED` command stays `QUEUED`. |
| D3 | Dirty worktree + explicit `/drain` | Deferred before claim (`{launched: null}`); the `QUEUED` command stays `QUEUED`. |
| D4 | Worktree becomes clean, then scheduler/drain pass | Ordinary FIFO progression resumes: the next `QUEUED` command is claimed and launched (or, only under the claim→spawn race, `REFUSED`). |
| D5 | Worktree clean at pre-claim, dirty before spawn | Post-claim `revalidate_claimed_command` still refuses (`REFUSED`, `WORKTREE_NOT_CLEAN`); no subprocess. Race defense preserved. |
| D6 | New run request while dirty | Refused `WORKTREE_NOT_CLEAN` before any queue row is created (unchanged). |
| D7 | Clean worktree + free repo + a `QUEUED` command | Normal claim + launch, exactly as before (the pre-claim preflight is clean and transparent). |

## Non-goals / explicitly out of scope

- No cancel for any non-`QUEUED` status (no force-cancel of a running process,
  no discard of an `ABNORMAL_EXIT`/`LAUNCH_OWNERSHIP_UNKNOWN` safety state).
- No new event types, no changes to doc 03, no runtime `src/runtime` behavior
  change, no schema migration (`status` is unconstrained `TEXT`; `CANCELLED` is
  a new Python-level constant only).
- No automatic retry, re-plan, selection expansion, or auto-start of the next
  command on cancel.
- No worktree/lease/Git/process interaction of any kind at cancel time.
