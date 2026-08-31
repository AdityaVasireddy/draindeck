# Implementation plan: Dashboard issue selection and run control

**Status:** Documentation checkpoint complete 2026-08-30; `src/` implementation
not yet started. Governing ADR: ADR-30
(`docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md`, also §5l of
`docs/08-session-0-closure-and-adr-amendments.md`).
**Normative contract:** `spec/dashboard-issue-run-control.md`.
**Outcome prediction gate:** `docs/31-dashboard-issue-run-control-outcome-matrix.md`.
**RED test inventory:** `docs/plans/dashboard-issue-run-control-failing-tests.md`.

## Architecture decisions

- A single pure selection/dependency planner (no filesystem, subprocess,
  SQLite, or browser access) is shared verbatim by Dashboard API admission and
  runtime re-validation. It is the only place batch-admission logic is
  implemented.
- `runtime.config.load_config`, `runtime.config.resolve_event_log_path`, and
  `runtime.queue.issues_md.parse` are the only config/issue-file readers.
  This feature implements none of that logic a second time.
- Runtime workflow state is read only through the existing observer/indexed
  event projection. The configured issue file never supplies state.
- Doc 03's event schema is frozen: no event type, schema version, or
  `RunStarted`/`RunFinished` payload field is added by this feature.
- Dashboard SQLite gains queue/idempotency/launcher-correlation state,
  explicitly separated from event-derived workflow truth; none of it is ever
  written to `events.jsonl`.
- The launcher uses a fixed argv vector with `shell=False`; no browser value
  ever chooses the executable, config path, or shell syntax.
- Ambiguous crash windows (spawn intent recorded, spawn outcome unknown) are
  fail-closed (`LAUNCH_OWNERSHIP_UNKNOWN`), never auto-retried.

## Units (dependency order; each unit is one RED group from the failing-tests
doc, turned green before the next begins)

- [x] **Unit 0 — Documentation checkpoint.** Accept ADR-30, recover and verify
      the outcome matrix and RED test inventory, write this plan/todo and the
      spec, preserve ADR-29's plan/todo under
      `docs/plans/dashboard-target-configuration-{plan,todo}.md`, confirm
      dependency-branch conclusion (current `master` has everything ADR-30
      needs), verify baseline (589 unit / 515 dashboard / 1104 combined,
      confirmed live), commit before any `src/` edit.
- [ ] **Unit 1 (RED 0) — Architecture and frozen-contract gate.** Tests that
      lock the boundary itself: no `src/runtime` import of FastAPI/Dashboard,
      Dashboard never touches `events.jsonl` directly or mutates Git/lease,
      no new `RunStarted`/`RunFinished` payload key, launcher uses fixed argv
      without a shell.
- [ ] **Unit 2 (RED 1) — Registration owns a validated canonical config
      path.** Additive SQLite migration adding a config-path column;
      registration validates absolute/exists/regular/parseable/
      same-repository before committing, atomically, with legacy rows
      observation-only until repaired.
- [ ] **Unit 3 (RED 2) — Configured issue reader.** Read-only Dashboard
      service/API that resolves the issue file against `project.repository`
      (never Dashboard CWD), delegates to `runtime.queue.issues_md.parse`
      with no second parser, returns a SHA-256 file revision, and reflects
      `NOT_INGESTED`/unavailable-projection honestly.
- [ ] **Unit 4 (RED 3) — Pure selection and dependency planner.** The shared
      pure function: exact allowlist semantics for Run Selected, full
      non-terminal-chain semantics for Run All, topological order with file
      order as tie-breaker, complete blocker/cycle reporting.
- [ ] **Unit 5 (RED 4) — Runtime exact-selection CLI.** `--issue`/
      `--all-issues` on `runtime.main run`; re-read/re-parse/digest-check/
      re-validate after ownership+recovery and before `RunStarted`; orchestrator
      scheduling restricted to the validated allowlist.
- [ ] **Unit 6 (RED 5) — Strict run-request API.** `extra=forbid` request
      models, bounded sizes, typed blocker envelopes, loopback/CORS/security
      header coverage, injection-shaped-value regression tests.
- [ ] **Unit 7 (RED 6) — Persistent FIFO queue.** Dashboard-owned SQLite
      queue table, atomic per-repository claim, required `Idempotency-Key`
      handling, dequeue revalidation.
- [ ] **Unit 8 (RED 7) — Safe launcher and event-derived status.** argv-vector
      subprocess launch, bounded/redacted diagnostics, crash-window handling
      exactly as ADR-30 §4, status derived only from observed events.
- [ ] **Unit 9 (RED 8) — Selection/run-control UI.** Configured-issues page,
      accessible selection controls, confirmation dialog, error summary,
      SSE-safe selection, live-browser verification.
- [ ] **Unit 10 (RED 9) — Crash/durability/regression closeout.** Targeted
      `tests/crash/run_control_harness.py` cases, full unit+dashboard+combined
      suites, both durability-harness seeds, fresh-context adversarial review,
      documentation/NEXT.md closeout.

**Verification:** all commands in `tasks/todo.md`; `git diff --check` clean at
every commit; final evidence distinguishes VERIFIED from ASSUMED.
