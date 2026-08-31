# Dashboard Issue Selection and Run Control (ADR-30) — Build Evidence

**Status:** READY FOR USER REVIEW (2026-08-31, independent-review response
and blocker-resolution pass both applied). Branch
`feature/dashboard-issue-run-control`, baseline `master` `1ae07a5`. No
merge, push, or PR was performed. An independent review of the original
closeout pass (below) found ten findings, resolved test-first in a second
pass; a further independent review of that response found two remaining
blockers (the queue's process-exit status still readable as a runtime
success claim, and a real 320px document overflow the first response's own
verification had not actually triggered), resolved test-first in a third
pass. See **"Independent review response (2026-08-31)"** and
**"Blocker resolution (2026-08-31)"** near the end of this document for the
full account — read them alongside the original evidence below, which is
preserved as the historical record of what was true at
first closeout, not silently rewritten.

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

## Independent review response (2026-08-31)

A subsequent independent review of the READY-FOR-REVIEW state above found
ten findings, spanning every layer this feature touches. All ten were
resolved test-first, in dependency order, in one uninterrupted pass on this
same branch (no new branch, no rebase). This section corrects specific
claims the review flagged as stale in the text above, then summarizes each
finding's fix. Full per-finding regression tests live in the files named
below; `tasks/todo.md`'s per-unit entries were also updated at the exact
points the review superseded.

**Corrections to the text above:**
- *"The UI drains the queue on SSE refresh"* (RED 6-7's scope-boundary
  note): was true at first closeout. `src/draindeck_dashboard/
  queue_scheduler.py` (finding 4, below) now drains every registered
  repository's queue autonomously; the UI's drain-on-refresh call and the
  explicit `/run-commands/drain` route remain only as an idempotent,
  prompt-reaction trigger, not the progression mechanism.
- *"Every outcome-matrix row was already implemented"* ("Outcome-matrix
  coverage" above): not quite — `plan_run_all` did not check for an
  authoritative ACTIVE issue absent from the current file (finding 8,
  below), so that decision's row was not actually covered by a passing
  test at the time this claim was written, only its `plan_selected`
  counterpart was. Now covered by `test_run_all_refuses_when_an_active_
  issue_is_outside_the_file` and two companion tests in
  `tests/unit/test_issue_selection.py`.
- *"Process COMPLETED is batch completion"*: never asserted outright, but
  the distinction was not made explicit or load-bearing anywhere a
  consumer could act on it. Finding 6, below, makes it precise: `COMPLETED`
  remains exclusively a process-exit fact; the confirmed `run_id_
  correlation` it now carries is what actually lets a caller look up the
  real, event-derived outcome.
- *"Config ownership is revalidated"*: true only at registration time, not
  on every subsequent read/plan/dequeue, at first closeout. Finding 3,
  below, closes this.
- *"The 320px viewport was verified"*: this document already correctly
  disclosed this as *not* verified (see "Documented, not glossed over"
  above) — not a false claim needing correction. It has now actually been
  verified (see finding 10, below) and found to already hold; no CSS
  change was required.
- *`git diff --check` clean*: was and remains true; this pass's own diff is
  also clean (`git diff --check` on the full range, exit 0, only a benign
  CRLF-normalization notice on one file, not a whitespace-error finding).

**Findings and fixes:**

1. **Runtime-specific subprocess environment**
   (`src/draindeck_dashboard/run_launcher.py`). The launcher reused
   `observer_client.build_observer_env`, whose minimal allowlist is correct
   for a short read-only `observe` invocation but excludes the Windows
   profile/config-discovery variables (`USERPROFILE`, `HOMEDRIVE`/
   `HOMEPATH`, `APPDATA`/`LOCALAPPDATA`, `CLAUDE_CONFIG_DIR`) a real
   `draindeck run` needs, and unconditionally denylists
   `ANTHROPIC_API_KEY` — wrong for `engine.auth_mode=api_key`. New
   `build_runtime_launch_env(base_env, *, auth_mode)`: preserves those
   variables always, carries `ANTHROPIC_API_KEY` through only for
   `api_key` mode, and keeps the subscription-mode denylist (ADR-18)
   otherwise. `build_observer_env` itself is untouched. Tests:
   `test_launch_env_preserves_windows_profile_discovery_variables`,
   `test_launch_env_preserves_api_key_for_api_key_auth_mode`,
   `test_launch_env_excludes_api_key_for_subscription_auth_mode` — all
   real subprocess, real environment variables, real assertions on what a
   spawned `.bat` actually saw.

2. **Preserve the validated topological order and current dependencies**
   (`src/runtime/main.py`, `src/runtime/loop.py`). `_validate_selection`
   discarded the planner's ordered result into a plain `frozenset`, and
   `Orchestrator._next_actionable` scanned `proj.issues`' historical
   `IssueCreated`-order dict using event-sourced `deps_met`, both of which
   could diverge from a freshly re-parsed configured file's order and
   dependencies. New `SelectionPlan` dataclass carries `allowed_ids`,
   `ordered_ids`, and a current-file `dependencies` map from validation
   into `Orchestrator`; a new `_next_actionable_selected` path (used only
   when both are supplied — every pre-existing call site is byte-identical
   otherwise) resumes an ACTIVE selected issue first, then walks the
   validated order, gating each PENDING candidate against the *current*
   dependency map rather than event-sourced `depends_on`. Tests:
   `tests/unit/test_loop_issue_selection.py` (order override, dependency
   gating against a terminal-but-not-DONE dependency, ACTIVE-resume-first
   under a validated order) and updated `tests/unit/
   test_main_issue_selection.py`. Durability harness re-run both seeds,
   clean.

3. **Revalidate registered config ownership before every plan and launch**
   (`src/draindeck_dashboard/repositories.py`, `configured_issues.py`,
   `run_queue.py`). Registration validated `project.repository`/log-path
   match once; a config file edited in place afterward (same canonical
   path) could silently redirect subsequent reads/planning/launch to a
   different repository or event log. New
   `repositories.verify_config_matches_registration`, called from
   `configured_issues.get_configured_issues` (which `run_queue.plan_run`
   and `revalidate_claimed_command` already route through, so planning and
   dequeue are covered by the same one shared check without duplication).
   Registration itself now also treats a supplied `configPath` as the sole
   source of truth for `logPath`, rejecting a simultaneously supplied
   mismatching one (`LOG_PATH_CONFIG_MISMATCH`) instead of silently
   accepting it. `run_queue.revalidate_claimed_command`'s except clause
   widened from `RunPlanError` to `DashboardApiError` so a drift refusal
   fails the command closed (`REFUSED`) instead of propagating unhandled.
   Tests: `test_config_edited_to_point_elsewhere_after_registration_
   refuses_read`, `..._to_change_event_log_path_...`
   (`test_configured_issues.py`); the exact cross-repository drift
   regression with byte-identical `Issues.md`,
   `test_plan_and_dequeue_refuse_when_registered_config_drifts_to_
   another_repository` (`test_run_queue.py`); `test_config_path_with_
   mismatching_explicit_log_path_is_rejected` and its matching-path
   counterpart (`test_repositories.py`).

4. **Autonomous persisted FIFO progression**
   (`src/draindeck_dashboard/queue_scheduler.py`, new). A lightweight
   `QueueDrainScheduler` asyncio task, started with Dashboard lifespan
   alongside the existing `ChangeTailer`/ingestion `Scheduler`, calls the
   same `try_launch_next` every enqueue and the drain route already call,
   for every registered repository, on a short interval. Needs no lease —
   unlike the ingestion `Scheduler`, every Dashboard process runs it, and
   it never touches the runtime workspace lease. Tests (real `.bat`
   subprocesses, real asyncio task lifecycle, `tests/dashboard/
   test_queue_scheduler.py`): two commands enqueued directly (bypassing
   the HTTP API and any drain call entirely) run to completion purely from
   the scheduler's own tick; two different repositories progress
   concurrently; a command queued before a simulated Dashboard restart
   (fresh connection, fresh scheduler instance) still gets picked up; a
   failing repository's tick never blocks another's; clean task
   cancellation on `stop()`. Verified genuinely exercised, not vacuously
   green, by temporarily disabling the tick call and confirming 4 of 5
   tests then fail.

5. **Prevent stdout/stderr pipe deadlock** (`run_launcher.py`). The
   launcher piped stdout/stderr but only ever read them once,
   non-blockingly, via `proc.communicate(timeout=0)` after `poll()`
   reported exit — a still-running child that filled either OS pipe buffer
   (~64KB on Windows) would block forever on its own `write()`, unnoticed.
   New background daemon threads (`_drain_stream`) continuously read and
   discard each stream, retaining only a running byte count plus (stdout
   only) a small bounded head buffer used solely for finding 6's
   correlation hint — never full content. Test
   `test_multi_megabyte_stdout_and_stderr_do_not_deadlock_the_launcher`:
   a real child writes ~4MB to each stream; reproduced the genuine deadlock
   against the unfixed code (stuck at `LAUNCHED` for the full 20s bounded
   wait) before the fix, completes in under 3 seconds after it.

6. **Make batch workflow status event-derived** (`run_launcher.py`,
   `runtime/main.py`). `run_id_correlation` stayed unused (ADR-30 decision
   5 left it optional). `runtime.main._emit_run_started` now prints a
   bounded `DRAINDECK_RUN_ID=<id>` line immediately after the fsynced
   run-lifecycle-start event (spec "Frozen event schema" explicitly
   permits this: "only a correlation hint"). The launcher's stream-drain
   head buffer (finding 5) is where that hint is read from, at
   reconciliation time; it is confirmed against a real `run_views` row
   (the same current-generation join `app.py`'s `_run_metadata_field`
   uses) before ever being persisted — never trusted from stdout alone.
   Queue `status` (`COMPLETED`/`ABNORMAL_EXIT`) remains exactly what it
   always was, a process-exit fact, never a runtime workflow outcome; the
   confirmed correlation is what lets a caller look up the real outcome
   through the pre-existing, independently tested `/api/repositories/
   {id}/runs` endpoint. Tests: a confirmed-hint case (real `.bat` echoing
   the hint, a seeded matching `run_views` row, `run_id_correlation` ends
   up set), an unconfirmed-hint case (hint present, no matching row,
   correlation stays `None`), and an absent-hint case.

7. **Configured issue reader refuses run-all with an omitted active issue**
   — *(named finding 8 in the review; grouped here in fix order)*
   (`src/runtime/queue/selection.py`). `plan_run_all` computed
   `non_terminal_ids` only from issues present in the freshly parsed
   `specs`, so an authoritative ACTIVE issue absent from the current file
   entirely was silently invisible to it — `plan_selected`'s equivalent
   `omitted_active_ids` check had no run-all counterpart. Added the same
   check to `plan_run_all`; both Dashboard planning (`run_queue.plan_run`)
   and runtime revalidation (`main._validate_selection`) pick it up for
   free since both already call the one shared pure function. Tests in
   `tests/unit/test_issue_selection.py`.

8. **Explicit terminal count summaries and a clean no-op message**
   (`run_queue.py`, `static/js/pages/run-control.js`,
   `static/styles/components.css`). `plan_run`'s dict gained `toRunCount`,
   `totalTerminalCount`, and a `terminalCounts` breakdown (`DONE`/
   `NEEDS_HUMAN`/`NEEDS_DECOMPOSITION`). The UI now short-circuits before
   ever opening the confirmation dialog when a valid plan has zero
   non-terminal issues — no queue row, no process, no lifecycle event of
   any kind — and shows an accessible `role="status"` message (new
   `noRunSummaryText`, new `.state-panel--success` CSS variant) instead of
   silently returning to an unchanged "No run commands yet." queue view.
   Tests: `tests/dashboard/test_run_queue.py` (backend counts, two
   fixtures covering all three terminal states) and `tests/dashboard/js/
   test_run_control_page.mjs` (the pure summary-text function, singular/
   plural/empty-file phrasing).

9. **Add `configPath` to the existing-target registration UI**
   (`static/js/pages/repositories.js`). The "Add repository" form only
   ever accepted `projectPath`/`logPath`; there was no way to register a
   config path (and therefore no way to reach `LAUNCH_CAPABLE`) through the
   UI at all. New "Config path (optional)" field with inline explanatory
   text; new pure `buildRegistrationRequestBody` never sends `logPath`
   alongside a supplied `configPath` (matching finding 3's source-of-truth
   rule). Behavioral coverage: `tests/dashboard/js/
   test_repositories_page.mjs` (the pure request-body function, all four
   combinations) plus a real end-to-end live-browser run through a real
   uvicorn instance — filled the real form, submitted, confirmed the
   created repository's `controlCapability === "LAUNCH_CAPABLE"` and its
   derived `logPath`, zero console errors.

10. **320px responsive overflow and native keyboard verification**
    (`tests/browser/run_control_responsive_and_keyboard_check.py`, new,
    standalone, not pytest-collected — needs the optional `playwright`
    package and its Chromium browser, neither a declared project
    dependency). The original build's own evidence (above) honestly
    disclosed, rather than glossed over, that this session's
    `mcp claude-in-chrome` transport could not confirm native keyboard
    Space/Tab activation or an actual 320px viewport. This review's own
    session hit the identical transport limitation independently
    (`resize_window` reports success but `window.innerWidth` is unchanged,
    confirmed on two separate tabs/windows) — reproducing, not merely
    citing, the same tooling boundary. Rather than accept the gap a second
    time, a genuine Chromium instance under direct Playwright control (the
    fallback the review's own instructions authorized) was used instead: real
    native `Space`/`Enter`/`Shift+Tab`/`Escape` key presses against the real
    run-control page, real 320/768/1024/1440 CSS-pixel viewports. Result,
    against a real uvicorn instance and a real registered repository with
    real (long, deeply-nested-path) configured issues: **no overflow at any
    of the four widths** (`scrollWidth === clientWidth` exactly at each —
    no CSS change was needed), both run controls visible at every width;
    **native Space genuinely toggles** the checkbox and enables "Run
    selected" (not merely focuses it); **native Enter genuinely activates**
    "Run all"; the confirmation dialog autofocuses "Start run"; **Shift+Tab
    genuinely traps focus** (Start run → Cancel → wraps back to Start run,
    via real focus movement, not only the dialog's own keydown listener
    reacting); **Escape genuinely closes** the dialog and returns focus to
    the invoking button; zero console errors across a reload. Script output
    is reproduced in full in this review's own session transcript.

**Final adversarial review, this pass:** re-examined every finding above
plus the axes named for it (exact-selection widening/reordering,
current-file-vs-historical dependency data, cross-repository config drift,
event-log source mismatch, duplicate spawn windows, queue starvation/
restart, pipe/output deadlocks, credential leakage, process-state-as-
workflow-state confusion, run-correlation correctness, native keyboard/
320px). No further defect was found; the ten fixes above were judged
sufficient and complete for the findings as stated.

**Final verification, this pass (all VERIFIED live):**

```
python -m pytest tests\unit -q                    -> 636 passed
python -m pytest tests\dashboard -q                -> 654 passed
python -m pytest tests\unit tests\dashboard -q     -> 1290 passed
node tests\dashboard\js\*.mjs (every file)          -> all passed
python tests\crash\harness.py <dir> 42             -> ALL 60 SCENARIOS PASSED
python tests\crash\harness.py <dir> 1337           -> ALL 60 SCENARIOS PASSED
python tests\crash\run_control_harness.py          -> ALL RUN-CONTROL CRASH SCENARIOS PASSED
python tests\browser\run_control_responsive_and_keyboard_check.py <url> <id>
                                                    -> ALL RUN-CONTROL RESPONSIVE/KEYBOARD CHECKS PASSED
git diff --check                                   -> clean, exit 0 (one benign CRLF notice)
```

One environment-sensitive failure carried unchanged from before this pass,
confirmed identical on `master` in a temporary comparison worktree this
session (`git worktree add`, removed after use): `tests/unit/
test_windows_job.py::test_member_requested_breakaway_child_remains_in_
configured_job` (`WinError 5: Access is denied` spawning a job-object test
child) — a Windows sandbox/permission characteristic of this environment,
unrelated to ADR-30, not a regression. A second previously-reported
environment-sensitive failure
(`tests/dashboard/test_diffs.py::test_no_ext_diff_and_no_textconv_
neutralize_a_configured_driver`) did not reproduce this session, in
isolation or as part of the full suite — not chased further given it is not
currently failing.

**No merge, push, PR, event-schema change, event-log write, Git-target
mutation, or workspace-lease mutation was performed by the Dashboard** at
any point in this review-response pass, exactly as in the original build.

## Blocker resolution (2026-08-31)

A further independent review of the "Independent review response" above
found two remaining blockers. Both were resolved test-first, in one pass,
without widening scope.

**Blocker 1 — process exit was still readable as runtime batch
completion.** `run_launcher.py` sets `run_commands.status = COMPLETED` for
any confirmed exit code 0 — correct as a process-exit fact, but
`run-control.js` rendered that raw status directly, and `runtime.main`
itself documents that both the runtime's own `COMPLETED` and `INTERRUPTED`
outcomes can leave that same exit code. Showing bare `"COMPLETED"` in the
queue view was therefore readable as a runtime success claim it had no
right to make. Fix: `run_queue._resolve_runtime_outcome` (new) resolves the
real, event-derived outcome fresh on every read — never persisted, never
written to `events.jsonl` — through the same current-generation
`run_views`/`checkpoints` join `_confirm_correlated_run` and app.py's
`_run_metadata_field` already use, and only once `run_id_correlation` has
actually been confirmed; every `run_commands` dict now carries a
`runtimeOutcome` field alongside the unchanged `status`. `run-control.js`'s
`queueStatusText` now renders `COMPLETED` as `"process exited — runtime:
<outcome>"`, reusing `format.js`'s own canonical `runDisplayOutcome` (the
same helper the pre-existing event-derived `/runs` endpoint already uses)
rather than a second, hardcoded copy of its wording — so an unresolved run
is never labelled "Running" here either, and the fix is not merely a
relabeling: it is backed by a genuine, confirmed, event-derived lookup.
Tests (`tests/dashboard/test_run_queue.py`, four new): a confirmed
`INTERRUPTED` outcome is shown as `INTERRUPTED`, never as completed; no
confirmed correlation shows no outcome, never as completed; a confirmed
`COMPLETED` outcome is shown correctly; a confirmed correlation with no
`RunFinished` observed yet also shows no outcome (never fabricates one the
projection itself doesn't have). Node tests
(`tests/dashboard/js/test_run_control_page.mjs`, four new) cover the same
four cases at the display-text layer, plus a regression guard that a
non-`COMPLETED` status (e.g. `ABNORMAL_EXIT`) is unaffected. The
pre-existing `test_unresolved_run_uses_no_controlled_finish_observed_wording`
(`test_run_control_ui_contract.py`) asserted run-control.js rendered no
runtime outcome text at all — a premise this fix deliberately supersedes;
it was revised (not weakened) to
`test_unresolved_run_reuses_the_canonical_no_controlled_finish_wording`,
which now asserts the opposite of a hardcoded duplicate: that run-control.js
reuses `runDisplayOutcome` rather than reintroducing the phrase itself.

**Blocker 2 — a real 320px document overflow.** Independent direct
Playwright verification reported `scrollWidth: 326` at a 320px viewport
(`overflow: true`), naming the `NOT_INGESTED` state chip/table layout as
the reliable trigger. This session could not reproduce that exact number
against its own fixture data (even a deliberately extreme one — a ~226
character unbroken issue title, multiple dependencies, a `NOT_INGESTED`
issue with no `issue_views` row at all) — `document.documentElement.
scrollWidth` stayed exactly equal to `clientWidth` at all four required
widths throughout. Direct computed-style inspection at 320px, however,
found a real defect regardless: `.detail-meta` (the `<dl>` showing the
registered config/issue-file absolute paths) had **no CSS rule anywhere in
the codebase** — a plain browser-default `<dl>`/`<dd>` with no wrap
behavior for an unbroken Windows path, which measured `scrollWidth: 308` vs
`clientWidth: 296` on its own `<dd>` elements (a real, if not
document-tipping in this session's exact fixture, overflow) — exactly the
class of defect blocker 2 names ("Long config and issue paths must wrap").
Separately, `#main-content` (the flex-item "main content plane" every page
renders into) had `flex: 1` with no `min-width: 0` — the textbook flexbox
trap that lets a flex item refuse to shrink below its widest descendant's
unconstrained content width, which can defeat an inner `overflow-x: auto`
wrapper's containment for content just slightly longer than what this
session's fixture happened to produce. Both were fixed: `.detail-meta` now
uses CSS grid (`grid-template-columns: max-content minmax(0, 1fr)`) with
`min-width: 0` on both the container and the value column (grid items have
the identical default-`min-width: auto` trap as flex items) plus
`overflow-wrap: anywhere` on the `<dd>`; `#main-content` gained `min-width:
0`. After the fix, the same worst-case fixture's `<dd>` elements measured
`scrollWidth === clientWidth` exactly (206px each, wrapped onto multiple
lines), and `document.documentElement.scrollWidth === clientWidth` held at
320/768/1024/1440 both before and after — the fix closes a genuine,
independently-confirmed-elsewhere defect class rather than only reacting to
a number this session's own fixture happened to reproduce. No status text
was hidden or truncated to achieve this — every state chip, including
`NOT_INGESTED`, remains fully visible and fully readable; only the
*containment* of long, unrelated path text changed. Native keyboard and
dialog behavior (Space/Enter/Shift+Tab/Escape/autofocus/zero console
errors) was re-verified unaffected by both CSS changes via the same
`tests/browser/run_control_responsive_and_keyboard_check.py`, run against a
live fixture carrying the `NOT_INGESTED` issue and the extreme unbroken
title throughout.

**Verification, this pass (all VERIFIED live):**

```
python -m pytest tests\dashboard\test_run_launcher.py tests\dashboard\test_run_queue.py
  tests\dashboard\test_queue_scheduler.py tests\dashboard\test_issue_run_api.py
  tests\dashboard\test_run_control_ui_contract.py tests\unit\test_loop_issue_selection.py
  tests\unit\test_main_issue_selection.py tests\unit\test_issue_selection.py -q
                                                    -> 137 passed
node tests\dashboard\js\test_repositories_page.mjs -> 9 passed
node tests\dashboard\js\test_run_control_page.mjs  -> 14 passed
python tests\crash\run_control_harness.py          -> ALL RUN-CONTROL CRASH SCENARIOS PASSED (15/15)
python tests\browser\run_control_responsive_and_keyboard_check.py <url> 1
                                                    -> exit 0, ALL RUN-CONTROL RESPONSIVE/KEYBOARD
                                                       CHECKS PASSED, zero overflow at
                                                       320/768/1024/1440 with a NOT_INGESTED issue
                                                       and an extreme unbroken title present
python -m pytest tests\dashboard -q                -> 658 passed
python -m pytest tests\unit -q                     -> 636 passed, 1 pre-existing env failure
python -m pytest tests\unit tests\dashboard -q     -> 1294 passed, 1 pre-existing env failure
git diff --check                                   -> clean, exit 0 (one benign CRLF notice)
```

The one carried-over environmental failure
(`tests/unit/test_windows_job.py::test_member_requested_breakaway_child_
remains_in_configured_job`, `WinError 5`) is unchanged and was already
confirmed identical on `master` in the prior pass; not re-litigated here.

**No commit, merge, push, reset, checkout, or discard was performed at any
point in this pass** — every prior uncommitted change from the earlier
independent-review response remains exactly as it was, plus this pass's own
additions, all still unstaged.

**Next action is a user decision:** review this evidence and `tasks/todo.md`,
then approve merge or request further verification.
