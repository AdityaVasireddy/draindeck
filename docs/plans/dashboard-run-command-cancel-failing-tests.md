# Plan — Dashboard run-command queue-cancel: failing (RED) test inventory

Operationalises `docs/34-dashboard-run-command-cancel-outcome-matrix.md`. Every
RED test below must fail for **missing/wrong cancellation behavior**, not for an
import or collection error. The behavior under test does not exist before
implementation: `run_queue.cancel_queued_command`, the
`STATUS_CANCELLED`/`CancelError` names, the
`POST .../run-commands/{id}/cancel` route, and the `run-control.js`
`isCancellable`/`CANCEL_DIALOG_COPY`/cancel-button affordance are all new.

To keep collection valid before the symbols exist, tests import the new names
**inside the test body** (mirroring `test_run_command_acknowledge.py`), so a
pre-implementation run yields genuine behavioral/`ImportError`-*inside-the-body*
RED (an assertion or a deliberate `pytest.raises(ImportError)`-free failure),
never a collection-time crash that would mask the RED signal for the whole file.

## Group C — core queue API (`tests/dashboard/test_run_command_acknowledge.py`
sibling: `tests/dashboard/test_run_command_cancel.py`)

Fixtures reuse the acknowledge suite's `_register_ready` / `enqueue_command`
shape.

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| C-1 | C1 | Cancelling a `QUEUED` command → status `CANCELLED`; `repository_has_active_command` stays false; **no** subprocess (the test never provides an executable and asserts the command was never `CLAIMED`/`LAUNCHED`). |
| C-2 | C2–C10 | Parametrized over every non-`QUEUED` status (`CLAIMED`, `LAUNCHED`, `LAUNCH_OWNERSHIP_UNKNOWN`, `ABNORMAL_EXIT`, `ACKNOWLEDGED`, `COMPLETED`, `REFUSED`, `LAUNCH_FAILED`, `CANCELLED`) → raises `DashboardApiError` with code `CANCEL_NOT_QUEUED`; the row's status is unchanged. |
| C-3 | C5 | The `ABNORMAL_EXIT` refusal message names acknowledge/unlock (actionable steer to the doc 33 path). |
| C-4 | C14 | Two `QUEUED` commands; cancel the first → the second's `queuePosition` recomputes to 1 (FIFO preserved). |
| C-5 | C18 | Cancelling a command with a `run_id_correlation` leaves the correlated `run_views.outcome` byte-for-byte unchanged (no runtime-evidence mutation). |
| C-6 | C16, C17 | Unknown `command_id` → `NotFoundError`; a command belonging to another repository → `NotFoundError` for the mismatched repo. |
| C-7 | C13 | Two concurrent cancels (real threads + barrier) of the same `QUEUED` command → exactly one success, exactly one `CANCEL_NOT_QUEUED`; no exception escapes as a 500; final status `CANCELLED`. |
| C-8 | C11, C12 | Cancel vs. `claim_next_launchable_command` race (real threads + barrier), looped: the invariant holds every iteration — final status is `CANCELLED` **xor** `CLAIMED`; if `CANCELLED`, the concurrent claim did not claim this command; if `CLAIMED`, cancel refused `CANCEL_NOT_QUEUED`. Never `QUEUED`, never both. |
| C-9 | invariant 7 | `STATUS_CANCELLED not in _BLOCKING_STATUSES` (non-blocking terminal). |

## Group A — API / end-to-end (`tests/dashboard/test_run_command_cancel_api.py`)

Through the real FastAPI app + a real git worktree, mirroring
`test_run_command_recovery_api.py`.

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| A-1 | C1 | `POST .../run-commands/{id}/cancel` on a `QUEUED` command → 200, body `status == "CANCELLED"`. |
| A-2 | C15 | With an **uncommitted (dirty) `Issues.md`**, a directly-seeded `QUEUED` command is still cancelable → 200 `CANCELLED` (cancel is never blocked by launch preflight). |
| A-3 | C5 | `POST .../cancel` on an `ABNORMAL_EXIT` command → 409, code `CANCEL_NOT_QUEUED`. |
| A-4 | C16 | `POST .../cancel` for an unknown `command_id` → 404. |
| A-5 | C4/no-auto-start | After a successful cancel, the endpoint does **not** launch anything: no new `CLAIMED`/`LAUNCHED` row appears (cancel never auto-starts). |

## Group C-js — UI (`tests/dashboard/js/test_run_control_cancel_ui.mjs`, run
under node by `test_static_js_contracts.py`)

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| J-1 | UI | `isCancellable` is true only for `QUEUED`; false for every other status. |
| J-2 | UI | `CANCEL_DIALOG_COPY` states it removes only the waiting batch, never touches a running process, and does not alter runtime events. |

## Group G — architecture guard
(`tests/dashboard/test_issue_run_control_architecture.py` addition)

| RED | Asserts |
|-----|---------|
| G-1 | `cancel_queued_command`'s source (via `inspect.getsource`) contains no worktree-preflight call, no `try_launch_next`/claim/launch call, and no `events.jsonl`/git/lease/`Popen`/`kill` token — a static guard that cancel stays a pure control-plane status flip preserving the Dashboard control boundary. |

## Amendment 1 — queue pause on cancel + Resume (RED for the auto-start blocker)

New symbols (`is_queue_paused`, `resume_repository_queue`, the
`run_queue_pauses` table, `POST .../run-commands/resume`, the `queuePaused`
field, `RESUME_DIALOG_COPY`) are all new; tests import them in-body where they
are Python module symbols.

### Group P — queue pause/resume behavior (`tests/dashboard/test_run_command_queue_pause.py`)

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| P-1 | P1 | Enqueue #1,#2; cancel #1 → #1 `CANCELLED`, `is_queue_paused` true; then `try_launch_next` (repeatedly, real fake exe) leaves #2 **`QUEUED`** (never `CLAIMED`/`LAUNCHED`/`LAUNCH_FAILED`). Fails RED today: cancel does not pause, so #2 is claimed/launched. |
| P-2 | P2 | After cancel, open a **fresh** connection to the same DB file; `is_queue_paused` is still true and `claim_next_launchable_command` returns `None`. |
| P-3 | P5, P6 | After cancel (paused), `resume_repository_queue` clears the pause (`is_queue_paused` false) and `claim_next_launchable_command` can now claim #2. |
| P-4 | P7 | Cancel-vs-claim race (threads+barrier), looped: invariant holds — final #1 status is `CANCELLED` (then paused, claim got nothing) **xor** `CLAIMED` (cancel refused). Never both, never `QUEUED`. |
| P-5 | P8 | Concurrent cancel + resume (threads+barrier): no exception escapes; the final persisted `queuePaused` matches whichever serialized last; a genuine cancellation is the only writer of a pause. |
| P-6 | invariant 1 | Cancelling a paused-writing command with a `run_id_correlation` still leaves `run_views.outcome` unchanged (pause writes only `run_queue_pauses`). |
| P-7 | P10 | On a DB migrated to the current `SCHEMA_VERSION`, `run_queue_pauses` exists; on a hand-built v5 DB, `run_migrations` adds it without touching existing `run_commands` rows. |

### Group A2 — API / end-to-end (`tests/dashboard/test_run_command_cancel_api.py` additions)

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| A-6 | P1, P3 | Cancel #1 via API → 200; `GET .../run-commands` reports `queuePaused: true`; `POST .../run-commands/drain` returns `{launched: null}` and #2 stays `QUEUED`. |
| A-7 | P4 | A **new** run request (`POST .../run-commands`) while paused → 201 and the command is `QUEUED`, but nothing is launched and `queuePaused` stays true. |
| A-8 | P5 | `POST .../run-commands/resume` → 200 `queuePaused: false`; unknown repo → 404. |

### Group J2 — UI (`tests/dashboard/js/test_run_control_cancel_ui.mjs` additions)

| RED | Asserts |
|-----|---------|
| J-3 | `CANCEL_DIALOG_COPY` now also states the remaining queue is paused until Resume is selected. |
| J-4 | `RESUME_DIALOG_COPY` states that resuming permits the next waiting command to start. |
| J-5 | `queuePausedNoticeText`/`isQueuePaused` helper: true only when the queue response says paused. |

### Group G2 — architecture guard (`test_issue_run_control_architecture.py`)

| RED | Asserts |
|-----|---------|
| G-2 | `claim_next_launchable_command` source references the pause check (`is_queue_paused`/`run_queue_pauses`) so the launch chokepoint can never silently stop honoring the pause; and `run_queue_pauses` is a Dashboard-only table (never referenced from `src/runtime`). |

## Amendment 2 — deferred progression on a dirty worktree (RED for the lost-batch bug)

New symbols: `has_launchable_command` (run_queue), the pre-claim preflight in
`try_launch_next`, `progressionDeferred` on the resume response, and
`resumeStatusText`/updated `RESUME_DIALOG_COPY` (JS).

### Group D-unit — the shared `try_launch_next` mechanism (`tests/dashboard/test_run_command_queue_pause.py` additions; fake-git fixtures + an injected probe)

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| D-U1 | D2/D3 mechanism | `try_launch_next` with an always-dirty injected probe leaves the sole `QUEUED` command `QUEUED` — never `CLAIMED`/`REFUSED` — and writes no pause. Fails RED today: current code claims then `REFUSED`s. |
| D-U2 | D5 | Race defense: a stateful probe (clean at the pre-claim check, dirty at the post-claim revalidation) still ends the command `REFUSED` (no spawn). |
| D-U3 | guard | `has_launchable_command` is False when the repo is active, paused, or has no `QUEUED` row; True only when free + unpaused + a `QUEUED` row waits. |

### Group D-int — real-git integration (`tests/dashboard/test_run_command_cancel_api.py` additions)

| RED | Matrix rows | Asserts |
|-----|-------------|---------|
| D-1 | D1 | Paused + dirty + `POST .../run-commands/resume` → 200, `queuePaused:false`, `progressionDeferred:true`; the waiting command stays `QUEUED` (not `REFUSED`). |
| D-2 | D3 | Dirty + `POST .../drain` → `{launched:null}`; the command stays `QUEUED`. |
| D-3 | D2 | Dirty + `QueueDrainScheduler(...).tick()` leaves the command `QUEUED`. |
| D-4 | D4 | After committing (clean), a `drain` claims the same command (status leaves `QUEUED`). |
| D-5 | D6 | A direct new run request while dirty still creates no queue row (409 `WORKTREE_NOT_CLEAN`). |

### Group J3 — UI (`tests/dashboard/js/test_run_control_cancel_ui.mjs` additions)

| RED | Asserts |
|-----|---------|
| J-6 | `RESUME_DIALOG_COPY` states that a dirty target defers execution and preserves waiting commands. |
| J-7 | `resumeStatusText({progressionDeferred:true})` returns a deferred message (mentions dirty/clean + preserved/queued); `{progressionDeferred:false}` returns null. |

## Genuine-RED confirmation method

Run each new test file **before** implementation:
- Group C / A / G: `pytest` collects the files (top-level imports are only the
  already-existing `run_queue`/app symbols); the new-symbol imports live in test
  bodies, so failures are behavioral (`AttributeError`/`ImportError` raised from
  the call site, or an assertion on absent behavior), captured and reported as
  RED, never a collection crash.
- Group C-js: the `.mjs` imports `isCancellable`/`CANCEL_DIALOG_COPY` from
  `run-control.js`; before implementation node exits non-zero (undefined
  export), which `test_static_js_contracts.py` surfaces as a failing
  parametrized case.
