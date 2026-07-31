# Session Handoff — Group R recovery signal banked; run-vs-recover overrun merged issue-10 for real

## Objective
Witness item-9 orphan-crash recovery against real StockPhotoAgent: Group R (startup
recovery of the frozen `10-e2` fixture) then Group S (live orphan witness via the layered
discriminator), per `docs/15-item9-outcome-matrix.md` §6. Group R was authorized and run
this session; Group S was not reached.

## Current Status
- Completed: Group R's recovery signal — `ExecutionCrashed(10-e2)` (event 78) with a
  non-null `residue_ref` (`refs/attempts/10/10-e2`, resolves to `368136e...`, message
  "crash residue 10-e2"), ordered before any fresh retry spawn. This is the first non-null
  live residue this project has produced and satisfies both R-1 (crash-before-respawn) and
  R-2 (non-null residue) as defined in §6. This finding stands; it does not need re-running.
- Completed: process-fix commit `628ecd5` — recover-vs-run entrypoint discipline written
  into both `docs/15-item9-outcome-matrix.md` §6 and `CLAUDE.md`.
- In Progress: nothing mid-flight.
- Blocked: Group S cannot proceed against the `10-e2` fixture — it no longer exists as a
  dangling execution (see Outstanding Issues). A fresh fixture must be built first, and
  that fixture-build is itself gated on Adi's explicit go-ahead (high-blast-radius: real
  repository mutation).

## Decisions & Rationale
- Let StockPhotoAgent's issue-10 completion stand rather than roll it back — Adi's call.
  Unwinding a real merge commit plus the live event log's terminal events (`IssueCompleted`
  etc.) is itself a higher-blast-radius action than the overrun that produced them, and
  the underlying work (the `debug_logs_dir` config fix) is legitimate, reviewed, and
  approved content.
- Entrypoint scope pinned in two places before any further fixture work: `§6` (matrix,
  scoped to this item-9 effort) and `CLAUDE.md`'s Hard Rules (project-wide, so the mistake
  can't recur on any future gated phase, not just item-9).

## Key Files
- `C:\Projects\issue-runtime\docs\15-item9-outcome-matrix.md` — §6 now carries both the
  Group R/S witness plan and the new "Entrypoint discipline (LOAD-BEARING)" subsection
  documenting this session's failure of record.
- `C:\Projects\issue-runtime\CLAUDE.md` — Hard Rules section gained the "Entrypoint scope
  (recover vs run)" rule, placed immediately after the blast-radius scoping rules.
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — sentinel +
  layered-discriminator work from the prior session, still uncommitted. Untouched this
  session. Must stay uncommitted until Group S passes.
- `C:\Projects\issue-runtime\state\events.jsonl` — now at 85 events (was 77 at prior
  handoff); events 78-85 cover the Group R recovery signal (78) followed by the unauthorized
  continuation (79-85).

## Next Action
Build a fresh dangling-execution fixture for Group S (a new issue, crashed mid-execution,
frozen exactly as `10-e2` was) — high-blast-radius setup work, gated on Adi's explicit
go-ahead. Any gated recovery-only step in that process must use `python -m runtime.main
recover`, never `run`, per the rule committed this session.

## Knowledge Captured
- `python -m runtime.main run` is the full orchestrator loop: it crash-recovers dangling
  executions and then continues — ingesting, spawning fresh executions, running real
  engine children, validating, reviewing, and merging. It does not stop after recovery.
  `python -m runtime.main recover` is the correct entrypoint for any phase whose contract
  is "recover, then hard stop" — recovery-only, prints a report, spawns nothing. This
  distinction was not previously written down anywhere in the project's docs; it is now
  in both `§6` and `CLAUDE.md`.
- The overrun's own process-tree snapshot (`Get-CimInstance Win32_Process` for `python.exe`/
  `cmd.exe`) was captured too late — by the time it was taken, the run had already
  completed (exit 0) and any transient engine-child process had already exited. It shows
  only the orchestrator's own two-process shape (a parent and what appears to be the venv
  interpreter's internal redirector child, both running the same `runtime.main run`
  command line), not a `claude` engine child or shim. This does not resolve the
  interpreter-shape question below — it only shows there was no live child left to sample
  at the moment of capture.

## Assumptions
- MED confidence: the "no `claude` shim visible" reading of the late process-tree snapshot
  is the correct explanation (child already exited) rather than the child never having
  spawned a shim at all this run — not independently confirmed either way this session.

## Outstanding Issues
- The `10-e2` fixture is consumed. What was meant to be a frozen, re-usable dangling-
  execution witness for Group R was, by design, a one-shot state (crash-recover it and the
  dangling condition resolves) — but the overrun additionally drove issue 10 all the way to
  completion, which was not part of even a correctly-scoped Group R. Net effect: no dangling
  fixture remains for issue 10, and issue 10 itself is done, so it cannot be reused as a
  crash target either. Group S needs an entirely new issue/fixture.
- The interpreter-shape question for Group S's discriminator is still open: the durability
  harness passed 60/60 both seeds under the project venv interpreter
  (`C:\Projects\issue-runtime\.venv\Scripts\python.exe`), but the Layer-1 leaf-worker
  resolution logic was proven correct (per the prior session's handoff) against a
  `C:\Python314\python.exe`-based process chain, specifically to avoid the venv's
  redirector-stub behavior (the venv python.exe spawns an internal second process per
  invocation, per the prior handoff's own finding). Group S's real orphan witness will run
  under whatever interpreter `cmd_run` actually uses in production — this session did not
  confirm whether that shape matches what Layer 1 was validated against. This must be
  resolved as part of Group S's S-A step (pre-kill witness), not assumed.

## User Constraints
- No StockPhotoAgent `cmd_run` (or any real orchestrator run against it) without Adi's
  explicit, per-run go-ahead — held for the Group R run itself (which was authorized) but
  the entrypoint used exceeded that authorization's intended scope.
- `claude_headless.py`'s sentinel/discriminator work stays uncommitted until Group S
  passes — held this session (file untouched).
- No commit without explicit, per-commit authorization — held for both doc commits this
  session (`cfa088b`, `628ecd5`).

## Runtime & System State
- Commit at handoff: `628ecd5` (issue-runtime), plus this handoff's own commit on top,
  reported after saving.
- StockPhotoAgent: branch `agent-work`, clean, at merge commit `b66e795` (issue 10
  completed and merged). Not touched again after the overrun was discovered.
- Background processes: none left running from this session.
- Dev servers / ports: none started or stopped. Ollama reviewer endpoint
  (`http://localhost:11434`) used read-only during the Group R run's health check, as in
  prior sessions.
- Memory files updated: none this session.

## Deferred Work
- Group S itself (S-A through S-E per §6) — deferred until a fresh fixture exists and
  Adi gives explicit go-ahead for that fixture-build.
- Resolving the interpreter-shape question (venv redirector-stub vs. the shape Layer-1 was
  validated on) — deferred to Group S's S-A step, per Outstanding Issues above.
- ADR-19's kill-criteria verdict — still needs a 20-issue sample; current real-issue count
  remains small (this session added one more real completion, issue 10, via the overrun,
  but the sample-size gate itself was not re-evaluated this session).

## Open Questions
**Needs User Input**
- None outstanding — Adi already gave the disposition for the overrun (completion stands,
  no rollback) and authorized both doc commits this session.

**Model Uncertainty**
- Whether the "no visible engine child" reading of the late process-tree snapshot reflects
  a child that already exited vs. one that never spawned a shim this run (see Assumptions).
- Whether the venv interpreter's process shape (as run in production via `cmd_run`) matches
  or differs from the `C:\Python314\python.exe` shape Layer-1 was validated against — not
  settled this session.
