# Dashboard Issue Selection and Run Control (ADR-30) — Build Evidence

**Status:** READY FOR USER REVIEW (2026-08-31, closeout pass). Branch
`feature/dashboard-issue-run-control`, baseline `master` `1ae07a5`. No
merge, push, or PR was performed.

## Scope and boundary

ADR-30 (`docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md`, also
`docs/08` §5l) narrowly extends ADR-26/27's read-only Dashboard boundary: a
registered repository with a validated canonical `.draindeck/config.local.yaml`
can be planned and launched from the Dashboard. The Dashboard still never
opens, parses, or repairs `events.jsonl`, mutates target Git state or
source, or acquires/repairs the runtime workspace lease itself — the
launched runtime process remains sole owner of all of that. `src/runtime`
gained only: `runtime/queue/selection.py` (the pure planner, new), an
optional `Orchestrator.allowed_issue_ids` filter, and `--issue`/
`--all-issues`/`--issues-digest` on `runtime.main run` — no event schema
change, no `RunStarted`/`RunFinished` payload field, verified mechanically
(RED 0, re-verified this pass).

## Local checkpoint-commit series

**11 commits**, `270f9cb` (Unit 0: ADR-30 accepted, planning artifacts
recovered) through `b051e97` (Unit 9: crash harness + adversarial-review
fixes), on `feature/dashboard-issue-run-control`, `Draindeck` repository:

```
270f9cb plan: Unit 0 - accept ADR-30, dashboard issue selection and run control
265825b test: Unit 1 (RED 0) - ADR-30 architecture and frozen-contract gate
9aaff26 feat: Unit 2 (RED 1) - registration owns a validated canonical config path
be5cb0e feat: Unit 3 (RED 2) - configured issue reader reuses the existing parser
56b8452 feat: Unit 4 (RED 3) - pure selection and dependency planner
e5d5019 feat: Unit 5 (RED 4) - runtime exact-selection CLI and filtered orchestrator
5245ca6 docs: NEXT.md pointer for ADR-30 in-progress state (Units 0-5 of 10)
13d8d48 feat: Unit 6 (RED 5) - strict, race-safe run-request API
83a9c92 feat: Unit 7 (RED 6-7) - FIFO queue, atomic claim, and safe launcher
07da7cf feat: Unit 8 (RED 8) - selection/run-control UI, live-browser verified
b051e97 test: Unit 9 (RED 9 part 1) - queue crash harness + adversarial review fixes
```

**No merge or push has occurred.** This document and the remaining
NEXT.md/README/PRODUCT.md updates are Unit 10's own closeout content.

## `git diff --check` on the full range

`git diff --check 1ae07a5..HEAD` — clean, exit 0. (Verified at every
individual commit during the build, not only at the end.)

## Verification performed (all VERIFIED live this session)

```
python -m pytest tests\unit -q                    -> 631 passed
python -m pytest tests\dashboard -q                -> 629 passed
python -m pytest tests\unit tests\dashboard -q     -> 1264 passed
node tests\dashboard\js\test_run_control_page.mjs  -> 7 passed (direct)
python tests\crash\harness.py <dir> 42             -> ALL 60 SCENARIOS PASSED
python tests\crash\harness.py <dir> 1337           -> ALL 60 SCENARIOS PASSED
python tests\crash\run_control_harness.py          -> ALL RUN-CONTROL CRASH SCENARIOS PASSED (15/15)
```

Baseline before this feature (verified live at Unit 0): 589 unit + 515
dashboard = 1104 combined. Net new: 42 unit + 114 dashboard = 156 tests
(the growth also includes 4 fixes to pre-existing tests whose literal
`SCHEMA_VERSION` pins went stale from the two additive migrations this
feature required — not a weakening, the same category of change any schema
bump requires).

The durability harness was run twice during the build (after the
`runtime.main`/`loop.py` change in Unit 5, and again at this final
closeout) — both seeds green both times.

## Real-browser verification (this session)

Performed live against a real `uvicorn` instance (`127.0.0.1:8420`), three
registered repositories seeded with a real git-shaped worktree, real
`.draindeck/config.local.yaml`, and real `Issues.md` files, and a
controlled fake `.bat` "draindeck executable" (`@echo off` + a marker write
or a chosen exit code) — no paid engine, no real target-repository
mutation, driven via `mcp__claude-in-chrome__*`.

Covered: mixed `PENDING`/`ACTIVE`/`DONE`/`NEEDS_HUMAN`/`NOT_INGESTED`
rendering; the bulleted-`Depends-On:` and active-issue-outside-file
warnings; a `Run selected` refusal (omitted ACTIVE issue) rendering a
focusable error summary with focus moved to it (confirmed via
`document.activeElement.id`), narrowing correctly as the selection is
corrected, down to the one truly-unresolvable case (an ACTIVE issue no
longer in the file, which has no selectable row by design — an intentional
hard block per doc 31, not a UI gap); a `Run all` refusal (unfinished
dependency outside the run-all set) naming the exact blocker; a genuinely
valid `Run all` opening a confirmation dialog with repository path, mode,
ordered issue list/count, terminal exclusions, and run-level budget all
present, autofocus on "Start run", a working Tab/Shift+Tab focus trap, and
Escape closing with focus returned to the invoking button; confirming that
enqueued, auto-claimed, and **launched a real subprocess**, the queue
showing `LAUNCHED`; an `UNAVAILABLE` repository (no read model yet) with
every run control `disabled`; and zero console errors/exceptions across the
entire session.

**Documented, not glossed over:** native keyboard activation (Tab moving
focus, Space toggling a native checkbox) did not fire via this session's
CDP-synthesized key events, and `resize_window` to 320px did not visibly
change the live viewport. Both were diagnosed systematically before being
accepted as tooling/session limitations rather than page defects: the
dialog's own JS-level keydown listener (Escape, Shift+Tab) responded
correctly to the identical synthesized events; the checkbox's `tabIndex`
(0), `aria-label`, and `disabled` state are all structurally correct; mouse/
pointer activation of the identical control works and fires the real
`change` handler; and no code anywhere intercepts or prevents default
keyboard behavior. This mirrors the project's own established precedent for
the `forced-colors: active` gap recorded in
`docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md` — a session/tooling
boundary no available mechanism could bridge, waived rather than silently
claimed. The table was defensively wrapped in `.ledger-table-wrapper`
(matching every other table in this codebase) given the resize gap, and
this page otherwise reuses the exact CSS framework/breakpoints already
live-verified for 320/768/1024/1440 and 200% text elsewhere in this app.

## Real defects found and fixed this session (not merely reviewed — all fixed test-first before commit)

1. **Route collision (Unit 6).** The first draft registered the new
   enqueue/list routes at `/api/repositories/{repoId}/runs`, silently
   shadowing the pre-existing runtime-run-history routes at that same path
   (FastAPI matches registration order). Caught by the full regression
   suite (`test_app_views_api.py`/`test_app_redesign_api.py` run-history
   tests broke), not by this feature's own new tests. Renamed to
   `/run-commands` throughout.
2. **`"ALLnull"` in the queue display (Unit 8, live-browser-found).** A
   ternary `null` (no `refusalReason`) was passed to native
   `Element.append()`, which stringifies non-Node arguments
   (`String(null) === "null"`). Fixed by extracting
   `queueModeSummaryText`/`queueStatusText` as pure, unit-tested functions.
3. **Missing horizontal-scroll wrapper (Unit 8, live-browser-found).** The
   configured-issues table had no `.ledger-table-wrapper`
   (`overflow-x: auto`), unlike every other table in this codebase — a
   narrow viewport would have forced page-level horizontal scroll. Fixed by
   wrapping it to match the established pattern exactly.
4. **Double-click idempotency race (Unit 9, fresh-context adversarial
   review).** `enqueue_command` could raise an uncaught
   `sqlite3.IntegrityError` (a 500) when two concurrent requests with the
   same `Idempotency-Key` both passed the SELECT-based check before either
   committed its INSERT. Reproduced reliably (7 of 8 racing threads failed
   on every one of 3 runs against the un-fixed code). Fixed: the INSERT is
   now wrapped to catch `IntegrityError` and fall back to the row
   `ux_run_commands_repo_idempotency` (the real enforcement point) shows
   actually won, re-raising only if the constraint fired for an unrelated
   reason. A regression test using 8 real threads and a `Barrier` confirmed
   failing against the reverted code and passing after the fix.

Two related coverage gaps were also closed with no defect found: a
same-connection atomic-claim test was strengthened with a genuine
two-thread/two-connection version (confirmed `BEGIN IMMEDIATE` correctly
serializes real concurrent claimants), and cross-repository command-id
read (`404`, correctly) and the `/run-commands/drain` route's loopback
enforcement (`403`, correctly — it wasn't covered by RED 5's security tests,
which predate that route) were both explicitly tested.

## RED-plan reconciliations (documented deviations, not overclaims)

A small number of the 150+ RED-inventory tests were satisfied by reference
to already-existing, already-tested code rather than a new duplicate test,
or reconciled to a later/narrower scope than originally listed. Each is
recorded inline in `tasks/todo.md` at the point it occurs; the categories
are: (a) architecture-invariant guards that already held before any feature
code existed (RED 0, 5 of 6 tests); (b) assertions already covered by
pre-existing tests for unrelated features that happen to prove the same
property (e.g. `RunStarted`'s closed-payload-key test, the observer/
no-downgrade compatibility tests); (c) one test
(`test_unregister_deletes_queue_control_rows_but_never_target_files`)
implemented only for its currently-testable half in Unit 2, extended once
the queue table existed in Unit 7; (d) `run_id_correlation` intentionally
left unused — ADR-30 decision 5 makes the stdout correlation line
explicitly optional ("may be added"), and workflow status continues to come
only from the pre-existing, independently-tested `/runs` endpoint.

## Outcome-matrix coverage

Every row of `docs/31-dashboard-issue-run-control-outcome-matrix.md`'s
"Locked decisions" and "Outcome matrix" tables has a corresponding
implemented behavior and passing test, cross-referenced from `tasks/todo.md`'s
per-RED-group entries. No falsifier condition was observed to hold.

## Independent review

This build's fresh-context adversarial review (RED 9) was performed by the
same session that implemented the feature, working from the finished code
with the review axes as an explicit checklist (runtime durability/
allowlist, event-schema freeze, queue atomicity/idempotency, spawn
dual-write crash windows, injection surfaces, loopback security, Git/log/
lease non-ownership, accessibility/state honesty) rather than by a
separately-spawned reviewer session. It found and fixed one genuine,
reliably-reproducing concurrency bug (above). The user may wish to
commission an additional review by a fresh context/session before merge,
as was done for some earlier features in this repository's history.

## VERIFIED vs ASSUMED summary

**VERIFIED live this session:** every test count and durability-harness
result above; the four real defects and their fixes; the real-browser
scenarios listed, including one genuine end-to-end subprocess launch;
`git diff --check` clean throughout.

**ASSUMED / not independently re-verified this session:** correctness of
`src/runtime` code paths this feature did not touch (relied on the existing,
independently-passing test suite and durability harness rather than
re-deriving from first principles); that a future background-scheduler
integration (the documented "no timer drains the queue automatically"
scope boundary, `tasks/todo.md` RED 6-7) will compose cleanly with the
existing lease-gated `Scheduler` — not attempted or evaluated this session.

**Genuinely open, by design not omission:** native-keyboard and
viewport-resize browser-automation verification (tooling limitation, see
above); the queue-draining background timer (explicit, documented scope
boundary); a dedicated UI/API action to clear a `LAUNCH_OWNERSHIP_UNKNOWN`
or `ABNORMAL_EXIT` repository (currently an operator/DB-level action only,
per ADR-30's own text: "requires explicit operator resolution" without
specifying the mechanism).

**Next action is a user decision:** review this evidence and `tasks/todo.md`,
then approve merge or request further verification.
