# Doc 33 — Dashboard run-command recovery + clean-worktree preflight: outcome matrix

Status: PROPOSED (pre-implementation gate for
`DASHBOARD-QUEUE-RECOVERY-001` / clean-worktree preflight). Frozen contracts
that govern this work: doc 03 (event/state semantics — **`state/events.jsonl`
is the sole authoritative runtime state**), ADR-30
(`docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md`, the
Dashboard-owned `run_commands` queue), and CLAUDE.md's blast-radius rules.

This document is the pre-committed outcome matrix required before any `src/`
change. The RED-test inventory that operationalises it is
`docs/plans/dashboard-run-command-recovery-failing-tests.md`.

## Problem statement (reproduced case)

An operator selected a run from the Dashboard. The spawned `draindeck run`
child exited quickly with `RunFinished` outcome `CHECKOUT_FAILED` because the
target's `Issues.md` was untracked (a dirty worktree the runtime's checkout
refused to clobber). `run_launcher.reconcile_launched_command` observed the
non-zero exit and set the queue command to `ABNORMAL_EXIT`.

`ABNORMAL_EXIT` is deliberately a *blocking* status (`run_queue._BLOCKING_STATUSES`):
it fail-closes the repository so later commands do not cascade launches on an
uncertain outcome. But there is currently **no operator-visible, safe way to
acknowledge that failure and release the queue**, so a later `QUEUED`
recovery-planning command is blocked forever. The only "fix" today would be to
hand-edit the Dashboard SQLite — which is exactly what we refuse to tell an
operator to do.

Two gaps, addressed together:

- **A. Dirty-worktree protection (prevent the failure).** The Dashboard should
  refuse to launch a run against a dirty target worktree *before* spawning a
  subprocess, with a typed, actionable reason — rather than letting the child
  fail `CHECKOUT_FAILED` and block the queue.
- **B. Safe abnormal-exit recovery (recover from the failure).** When a command
  is nonetheless `ABNORMAL_EXIT`, give the operator a safe, gated
  *acknowledge/unlock* action that releases the repository for a **fresh,
  explicitly-requested** command — never an automatic retry.

## Hard safety invariants (must hold in every row below)

1. **No runtime-state mutation.** Recovery never writes/repairs
   `state/events.jsonl`, never synthesises a `RunFinished`, never mutates a
   workspace lease, never touches the target git tree, and never deletes queue
   rows. It only advances a Dashboard-owned `run_commands.status`.
2. **Dashboard never reads/writes `events.jsonl`.** Runtime outcome is resolved
   only through the already-materialised, current-generation `run_views` +
   `checkpoints` join (`run_queue._resolve_runtime_outcome`), the same evidence
   the `/runs` endpoint and `run_launcher._confirm_correlated_run` already use.
3. **Acknowledgement metadata is Dashboard-only.** The new `ACKNOWLEDGED`
   status lives solely in `run_commands`; it is never emitted as an event.
4. **Acknowledge unlocks, never retries.** A successful acknowledge does not
   enqueue, claim, launch, or expand the original selection. The operator must
   make a fresh explicit selection/run request afterward. The original
   command's `issue_ids_json` is left byte-for-byte unchanged.
5. **Fail-closed on ambiguity.** If process ownership, runtime event state, or
   target configuration cannot be proven safe, the command stays blocked.
6. **FIFO / one-active-batch-per-repository preserved.** A blocked
   `ABNORMAL_EXIT` command keeps `repository_has_active_command` true; only its
   transition to the (non-blocking) `ACKNOWLEDGED` releases the repository, at
   which point the next `QUEUED` command becomes claimable in id order.

## Part A — clean-worktree preflight (`WORKTREE_NOT_CLEAN`)

Reuses `runtime.repo.git_adapter.GitCliAdapter.worktree_status()` (already the
project's only worktree-status witness). "Clean" ≡ `not is_dirty()` ≡ no
tracked/staged/deleted/renamed/conflicted entries **and** zero untracked files.
An untracked `Issues.md` (untracked-only) is dirty and therefore blocks — this
is the reproduced case.

Enforcement is injected at the API layer (`app.py` always supplies the real
`GitCliAdapter`-backed probe). The queue functions accept the probe as an
optional dependency (default `None` = skip) purely so the existing queue unit
suite — which registers fake `.git` directories — stays valid; production
always injects it. An architecture test asserts the wiring so enforcement can
never silently disappear.

| # | Situation | Surface | Outcome |
|---|-----------|---------|---------|
| A1 | Target worktree clean | run request (enqueue) | Proceeds normally (queue row created / no-op / refusal exactly as today). |
| A2 | Target worktree dirty — untracked `Issues.md` only | run request (enqueue) | **Refused before any row is created**: typed `WORKTREE_NOT_CLEAN` (HTTP 409), message names that all changes incl. `Issues.md` must be committed/cleaned. No subprocess. |
| A3 | Target worktree dirty — tracked/staged/deleted/renamed | run request (enqueue) | Same as A2. |
| A4 | Worktree became dirty *after* enqueue, before dequeue | dequeue revalidation (`revalidate_claimed_command`) | Command → `REFUSED` (`WORKTREE_NOT_CLEAN` reason), slot released, **no subprocess spawned**. |
| A5 | Worktree clean at both gates | dequeue | Proceeds to launch exactly as today. |
| A6 | Advisory query for the UI | `GET /api/repositories/{id}/worktree-preflight` | Returns `{clean, blocking, untrackedCount, message}`; on dirty, message is the exact preflight copy. Read-only; never gates by itself. |
| A7 | Git status cannot be determined (not a git repo / git error) | any gate | Fail-closed: treated as **not launchable** (typed reason), never as "clean". |
| A8 | UI with dirty preflight | Run issues page | Persistent alert (`role="alert"`) with copy *"Commit or clean all tracked and untracked changes, including Issues.md, before running issues."*; Run selected / Run all / Select-all disabled. Client state is advisory; the backend gates A2–A4 are authoritative. |

## Part B — safe abnormal-exit acknowledge/unlock

New: `run_queue.acknowledge_abnormal_command(conn, repo_id, command_id, *,
identity_probe, ...)` and `POST
/api/repositories/{id}/run-commands/{command_id}/acknowledge`. All gates must
pass or the command stays blocked; the final status flip is atomic.

| # | Situation | Outcome |
|---|-----------|---------|
| B1 | Command status is `ABNORMAL_EXIT`, child probes `DEAD`, correlated run terminal (or no correlation), config/issues revalidate OK | **Success**: status → `ACKNOWLEDGED` (Dashboard-only, non-blocking, terminal). Repository released; a later `QUEUED` command becomes claimable. Runtime events/outcome, workspace lease, git target, and original `issue_ids_json` all unchanged. **No retry.** |
| B2 | Command status is not `ABNORMAL_EXIT` (`QUEUED`/`CLAIMED`/`LAUNCHED`/`COMPLETED`/`REFUSED`/`LAUNCH_FAILED`) | Refused `ACK_NOT_ABNORMAL` (409). Only an abnormal-exit command may be acknowledged. |
| B3 | Command status is `LAUNCH_OWNERSHIP_UNKNOWN` (ambiguous spawn window) | Refused `ACK_NOT_ABNORMAL` (409) — deliberately *not* acknowledgeable; remains visibly blocked with its explanation. |
| B4 | Recorded child probes `LIVE_MATCH` (still running, same identity) | Refused `ACK_PROCESS_NOT_TERMINAL` (409). Never acknowledge a live child. |
| B5 | Recorded child probes `PID_REUSED` (PID now a **foreign** process) | Refused `ACK_PROCESS_NOT_TERMINAL` (409). Foreign/ambiguous ownership per the safety list. |
| B6 | Recorded child probes `UNKNOWN`, or `process_pid`/`process_creation_time` is null/malformed | Refused `ACK_PROCESS_NOT_TERMINAL` (409). Unknown ownership is never released. |
| B7 | A correlated runtime run exists (`run_id_correlation` set) but is **not** terminal (no `RunFinished` observed in current-generation `run_views`, outcome resolves `None`) | Refused `ACK_RUN_NOT_TERMINAL` (409). Runtime event state must be terminal first. |
| B8 | No correlated runtime run (`run_id_correlation` is null) | The runtime-terminal gate is vacuously satisfied — there is no Dashboard-confirmed run to be non-terminal. Other gates still apply. |
| B9 | Target config/issues no longer revalidate (config drift, issues file missing/unreadable/parse error) | Refused `ACK_TARGET_UNVERIFIABLE` (409), carrying the underlying typed configured-issues reason. |
| B10 | Two concurrent acknowledge requests for the same command, all gates pass | **Exactly one** flips `ABNORMAL_EXIT → ACKNOWLEDGED` (atomic conditional UPDATE). The other observes the row already `ACKNOWLEDGED` and returns an **idempotent success** (`alreadyAcknowledged: true`) — never a double transition, never a 500. |
| B11 | Repeat acknowledge of an already-`ACKNOWLEDGED` command | Idempotent success (`alreadyAcknowledged: true`); no state change. |
| B12 | Reproduced end-to-end case | (1) Untracked `Issues.md` → enqueue refused `WORKTREE_NOT_CLEAN` (A2). (2) After committing `Issues.md`, an `ABNORMAL_EXIT` command left by the earlier failure can be acknowledged (B1); the repository unlocks and a **fresh, explicitly-requested** command is admitted (never auto-retried). |

## UI / documentation (Part C)

- Run issues page gains: (A8) the persistent dirty-worktree alert + disabled
  run controls; (B) an **"Acknowledge failed command and unlock queue"** action
  on each `ABNORMAL_EXIT` queue row, behind a confirmation dialog that states it
  **unlocks only and does not retry** the prior batch. `LAUNCH_OWNERSHIP_UNKNOWN`
  and other blocked rows stay visibly blocked with their explanation and no ack
  button.
- README gains a "Before running an issue" section: the target git worktree
  must be clean, including committing `Issues.md`, before launching.

## Amendment (doc 34 Amendment 2) — preflight moves *before* the claim

Rows A4/A5 above described the clean-worktree preflight as running only at
**dequeue revalidation** (`revalidate_claimed_command`), i.e. *after* the atomic
claim — so a dirty worktree marked the just-claimed command `REFUSED`. That is
now corrected: the preflight runs **before** the claim in the single
`try_launch_next` path (guarded by `has_launchable_command`), so a dirty worktree
**defers** progression and the waiting command stays `QUEUED` — it is no longer
claimed-then-`REFUSED`. See docs/34 Amendment 2 for the full deferred-progression
contract.

- **A4 is superseded.** A worktree that is dirty *before* the claim no longer
  produces `REFUSED`; `try_launch_next` returns a no-launch/deferred result and
  the command stays `QUEUED`. Every launch path (Resume, scheduler tick,
  `/drain`, enqueue-triggered) shares this behavior.
- **The post-claim preflight in `revalidate_claimed_command` is retained as a
  race defense only:** if the worktree was clean at the pre-claim check but
  turned dirty in the claim→spawn window, the claimed command is still `REFUSED`
  before any subprocess spawns.
- **A2/A3 (enqueue-time refusal) and A6/A7/A8 are unchanged:** a direct new run
  request against an already-dirty worktree is still refused *before* any queue
  row is created, and the advisory endpoint/UI alert are unchanged.

## Non-goals / explicitly out of scope

- No automatic retry, no re-planning, no selection expansion on acknowledge.
- No new event types, no changes to doc 03, no runtime `src/runtime` behavior
  change (git_adapter is *read* via its existing public `worktree_status()`).
- No repair of `LAUNCH_OWNERSHIP_UNKNOWN` (a distinct, separately-owned state).
- No Windows-mutex probing at acknowledge time; the `DEAD` process proof is the
  workspace-ownership witness for the spawned child.
