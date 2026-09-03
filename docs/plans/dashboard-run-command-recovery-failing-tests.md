# RED-test inventory — Dashboard run-command recovery + clean-worktree preflight

Companion to `docs/33-dashboard-run-command-recovery-outcome-matrix.md`. Each
group below is a focused behavioral RED test that must fail for a *behavioral*
reason (a missing function / wrong outcome), never a collection/import error,
before any production `src/` change. Matrix rows in parentheses.

> **Amendment (doc 34 Amendment 2).** RED A-7 below still holds as a *race
> defense* (a worktree that turns dirty in the claim→spawn window still
> `REFUSED`s at `revalidate_claimed_command`). The *ordinary* dirty case is now
> handled **before** the claim in `try_launch_next` (deferred, command stays
> `QUEUED`), so it is no longer claimed-then-`REFUSED`. The new RED tests for
> that pre-claim deferral live with the cancel/pause suite — see
> `docs/plans/dashboard-run-command-cancel-failing-tests.md` Amendment 2 (Groups
> D-unit / D-int / J3). RED A-7 is deliberately kept unchanged here.

## Backend — Part A: clean-worktree preflight (`tests/dashboard/test_worktree_preflight.py`)

- **RED A-1** `evaluate_worktree_preflight` reports **clean** when the injected
  probe returns a clean `WorktreeStatus`. (A1/A5)
- **RED A-2** reports **not clean** when the probe returns untracked-only
  (untracked `Issues.md`). `clean is False`, `untrackedCount == 1`. (A2)
- **RED A-3** reports **not clean** when the probe returns blocking
  (tracked/staged) changes. (A3)
- **RED A-4** fail-closed: a probe that raises (`RepoError`/not a git repo) →
  not clean, never an exception out of the evaluator. (A7)
- **RED A-5** `enqueue_command` with an injected **dirty** probe raises
  `WorktreeNotCleanError` and creates **no** `run_commands` row. (A2)
- **RED A-6** `enqueue_command` with an injected **clean** probe behaves exactly
  as today (row created). (A1)
- **RED A-7** `revalidate_claimed_command` with an injected **dirty** probe →
  command `REFUSED` with a `WORKTREE_NOT_CLEAN` reason; slot released. (A4)
- **RED A-8** the default (no-arg) queue calls skip the check (existing suite
  compatibility): `enqueue_command`/`revalidate_claimed_command` without a probe
  behave exactly as before. (regression)

## Backend — Part A API (`tests/dashboard/test_run_command_recovery_api.py`, real git)

- **RED A-9** `POST /run-commands` against a **dirty** real target worktree
  (untracked `Issues.md`) → HTTP 409 `WORKTREE_NOT_CLEAN`; no row created. (A2)
- **RED A-10** after committing `Issues.md`, the same request succeeds
  (row created). (B12 first half)
- **RED A-11** `GET /run-commands/…` unaffected; and
  `GET /api/repositories/{id}/worktree-preflight` returns `clean:false` +
  the exact preflight copy when dirty, `clean:true` when clean. (A6/A8)

## Backend — Part B: acknowledge/unlock (`tests/dashboard/test_run_command_acknowledge.py`)

- **RED B-1** happy path: an `ABNORMAL_EXIT` command with `process_pid`/
  `creation_time`, injected identity probe → `DEAD`, no correlation → acknowledge
  succeeds; status `ACKNOWLEDGED`; `repository_has_active_command` becomes
  `False`; `issue_ids_json` unchanged. (B1)
- **RED B-2** a non-`ABNORMAL_EXIT` command (e.g. `LAUNCHED`, `COMPLETED`,
  `QUEUED`) → `ACK_NOT_ABNORMAL`. (B2)
- **RED B-3** a `LAUNCH_OWNERSHIP_UNKNOWN` command → `ACK_NOT_ABNORMAL`
  (not acknowledgeable). (B3)
- **RED B-4** identity probe `LIVE_MATCH` → `ACK_PROCESS_NOT_TERMINAL`. (B4)
- **RED B-5** identity probe `PID_REUSED` (foreign) → `ACK_PROCESS_NOT_TERMINAL`. (B5)
- **RED B-6** identity probe `UNKNOWN`, and null pid/creation-time →
  `ACK_PROCESS_NOT_TERMINAL`. (B6)
- **RED B-7** correlated run present but non-terminal (`run_views` row with
  `outcome` NULL) → `ACK_RUN_NOT_TERMINAL`. (B7)
- **RED B-8** correlated run present and **terminal** (`outcome`
  `CHECKOUT_FAILED`) → acknowledge succeeds. (B8/B12)
- **RED B-9** config/issues no longer revalidate (issues file deleted) →
  `ACK_TARGET_UNVERIFIABLE`. (B9)
- **RED B-10** acknowledge never mutates runtime evidence: the `run_views`
  row's `outcome` and the `events`-derived outcome are unchanged after a
  successful acknowledge; `issue_ids_json` unchanged. (safety invariant 1/4)
- **RED B-11** idempotent repeat: acknowledging an already-`ACKNOWLEDGED`
  command returns success with `alreadyAcknowledged: true`, no state change. (B11)

## Backend — Part B concurrency (`tests/dashboard/test_run_command_acknowledge.py`)

- **RED B-12** two threads acknowledge the same `ABNORMAL_EXIT` command
  concurrently (separate connections, all gates pass): exactly one reports a
  fresh success, the other reports `alreadyAcknowledged: true`; the row ends
  `ACKNOWLEDGED` exactly once; no `sqlite3.IntegrityError`/500. (B10)

## Backend — Part B API (`tests/dashboard/test_run_command_recovery_api.py`)

- **RED B-13** `POST /run-commands/{id}/acknowledge` for an `ABNORMAL_EXIT`
  command (identity probe injected as DEAD) → 200, status `ACKNOWLEDGED`. (B1)
- **RED B-14** the same endpoint for a non-abnormal command → 409
  `ACK_NOT_ABNORMAL`. (B2)
- **RED B-15** end-to-end reproduced flow: dirty enqueue refused → commit
  `Issues.md` → acknowledge the pre-existing `ABNORMAL_EXIT` → repository
  unlocked → a fresh explicit `POST /run-commands` is admitted. (B12)

## Architecture / wiring (`tests/dashboard/test_issue_run_control_architecture.py` addition)

- **RED B-16** the API's `create_run_command` path injects a real worktree
  probe into `enqueue_command` (enforcement cannot silently disappear), and the
  Dashboard never imports an `events.jsonl` parser for recovery. (invariant 2)

## Frontend (`tests/dashboard/js/test_run_control_page.mjs`)

- **RED C-1** when the preflight endpoint reports `clean:false`, the page shows
  a persistent alert containing the exact copy and disables Run selected / Run
  all / Select-all. (A8)
- **RED C-2** when the preflight reports `clean:true`, no alert; controls follow
  the existing readModelStatus gate. (A1)
- **RED C-3** an `ABNORMAL_EXIT` queue row renders an "Acknowledge failed
  command and unlock queue" button; a `LAUNCH_OWNERSHIP_UNKNOWN` row does not,
  and shows its blocked explanation. (B/C)
- **RED C-4** confirming the acknowledge dialog POSTs to the acknowledge
  endpoint and the dialog copy states it unlocks only and does not retry. (C)

## Genuine-RED confirmation method

Each RED test is run before implementation. A test is accepted as genuinely RED
only when its failure is an `AttributeError`/`ImportError`-free behavioral
assertion or a `TypeError`/missing-attribute from the not-yet-existing
production symbol it targets (e.g. `acknowledge_abnormal_command`,
`evaluate_worktree_preflight`, `WorktreeNotCleanError`,
`STATUS_ACKNOWLEDGED`) — captured in the session's RED output. Import-only
collection failures do not count and are fixed before the RED bar is claimed.
