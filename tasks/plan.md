# Implementation plan: Dashboard Redesign

**Status:** ACCEPTED 2026-08-23 — user explicitly approved this plan, `docs/27-dashboard-redesign-spec.md`, and ADR-27 in `docs/08` §5i, and authorized local per-unit checkpoint commits. Merge/push remain prohibited.<br>
**Execution model:** one uninterrupted Claude Code `build-auto` run with test-first, runnable per-unit checkpoints. Local commits at those checkpoints require explicit approval in the build authorization; merge and push remain prohibited.<br>
**Branch:** `dashboard-redesign`, baseline `4052fef97dbb90b52ae91fc01832557bc348cab8`.<br>
**Mutation boundary:** `src/draindeck_dashboard`, `tests/dashboard`, Dashboard docs/design/task artifacts only. Never edit `src/runtime`.

## 1. Authority and gates

Implementation order of authority:

1. Existing runtime/observer contracts and accepted ADR-25/ADR-26.
2. Accepted ADR-27 (`docs/08` §5i) and approved `docs/27-dashboard-redesign-spec.md`.
3. `PRODUCT.md` and `DESIGN.md` plus `.impeccable/design.json`.
4. This plan and `tasks/todo.md`.
5. Existing code and tests where not superseded by an approved additive contract.

Before any source mutation, the implementing agent must read all five sources, inspect the working tree, confirm the branch/baseline, and print exactly:

```text
IMPECCABLE_PREFLIGHT: context=pass product=pass command_reference=pass shape=pass image_gate=pass mutation=open
```

The approved hybrid brief and approved north-star comp satisfy `shape=pass` and `image_gate=pass`; they do not authorize fabricated sample data. If PRODUCT/DESIGN context fails to load, the branch is wrong/dirty in an unexplained way, or the spec is not explicitly approved, stop before source changes.

## 2. Build rules

- Work through the units below in order, continuing automatically after each green checkpoint when local checkpoint commits were explicitly authorized.
- For each behavior, write/adjust a focused test first, observe it fail for the expected reason, implement the smallest passing change, then run the focused file.
- Do not merge, push, install a new dependency, or alter `src/runtime` without separate authorization. Create a local per-unit commit only if the user's build approval explicitly authorizes that bounded commit series; otherwise Unit 0 stops before mutation because `CLAUDE.md` requires runnable committed session checkpoints.
- Preserve unrelated user changes. Never reset or discard the worktree.
- Keep every SQL value parameterized. Only server-owned allowlisted sort expressions may be interpolated.
- Render observed strings with `textContent`/text nodes. Do not use untrusted `innerHTML`.
- Keep existing endpoint behavior and exact operational language unless the approved spec adds a field/route.
- Every Python test or utility that reads repository text, JSON, design, or planning artifacts must pass `encoding="utf-8"` explicitly; never depend on the Windows locale default.
- Update the version-controlled `tasks/todo.md`, `NEXT.md`, and `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md` after each completed checkpoint. Record commands/results before the local checkpoint commit so context exhaustion always has a runnable resume point.

## 3. Vertical implementation units

### Unit 0 — Baseline and executable contract map

**Files:** no source edits; `tasks/todo.md` only after verification.

1. Verify branch, baseline ancestry, working-tree status, Python version, and Dashboard optional dependencies.
2. Run `node C:\Users\adity\.agents\skills\impeccable\scripts\load-context.mjs`; confirm non-placeholder PRODUCT/DESIGN.
3. Run `draindeck-dashboard --help`, inspect `src/draindeck_dashboard/cli.py`, and record the real launch command (`--config` is required).
4. Run the baseline Dashboard suite, then combined unit+Dashboard suite. Expected baseline: 197 and 757 passing respectively; investigate any environmental drift before proceeding.
5. Inventory current API response snapshots and security headers so additive compatibility is testable.
6. Prove a callable real-browser automation/Chrome DevTools capability exists in the Claude Code environment. Open a trivial loopback page, inspect DOM/console/network, and capture one screenshot. If this cannot be done, stop before source mutation and request tooling or explicit assignment of the final browser gate to Codex.
7. Confirm whether the approval includes local per-unit checkpoint commits. If not, stop before source mutation.

**Checkpoint:** clean known baseline, explicit preflight line, browser gate proven, commit authority resolved, no unexplained failure.

### Unit 1 — Transactional SQLite v2 migration

**Primary files (≤5):**

- `src/draindeck_dashboard/db.py`
- `src/draindeck_dashboard/migrations.py` (new)
- `src/draindeck_dashboard/repositories.py`
- `tests/dashboard/test_db.py`
- `tests/dashboard/test_migrations.py` (new)

**Test first:** v1→v2 schema, version read only after `BEGIN IMMEDIATE`, simultaneous process start, busy-timeout failure, restart idempotency, newer-version refusal, rollback on injected failure, one-row `schema_meta`, evidence preservation, required indexes, and unregister cleanup of every new table.

**Implement:** explicit schema-version validation and short transactional DDL creating `issue_views`, `run_views`, `execution_views`, `containment_views`, `read_model_state`, `attention_conditions`, and evidence indexes exactly as spec §8. Do not scan/backfill evidence in `init_schema`. Extend `delete_repository` transactionally for all new rows.

**Checkpoint:** migration-focused tests and all existing DB tests green; inspect `sqlite_master` output against the spec.

### Unit 2 — Lease-owned persistent tolerant read models

**Primary files (≤5):**

Sub-step A (pure/persistent model):

- `src/draindeck_dashboard/read_models.py` (new)
- `src/draindeck_dashboard/projections.py`
- `src/draindeck_dashboard/indexer.py`
- `tests/dashboard/test_read_models.py` (new)
- `tests/dashboard/test_projections.py`

Sub-step B (lease/off-thread publish):

- `src/draindeck_dashboard/read_model_worker.py` (new)
- `src/draindeck_dashboard/scheduler.py`
- `src/draindeck_dashboard/lease.py`
- `tests/dashboard/test_read_model_worker.py` (new)
- `tests/dashboard/test_scheduler.py`

**Test first:** parity over legal lifecycle and per-generation containment, unknown/illegal/out-of-order/duplicate/malformed evidence, legacy runs, boundary redelivery, normal TORN→OK incremental apply, MALFORMED→OK monotonic check, previously-OK mutation rebuild, generation rollover/pruning, readiness states, concurrent process start, lease loss before publish, priority heartbeat renewal under a full worker queue, atomic visibility, retry, and event-loop responsiveness.

**Implement:** keep a pure deterministic reducer; model containment by `(executionId, containmentGeneration)` with exact `UNCONFIRMED`; apply safe monotonic inserts and TORN-tail repair incrementally. Route each bounded observer page (maximum 500 records; four pages/tick) through the lease-owned off-thread worker's 16-job FIFO for evidence/upsert/corruption/projection/checkpoint/attention/change persistence; producers await capacity. Route lease acquire/renew writes through the same worker/connection with priority scheduling so the heartbeat cannot wait behind the bounded page/backfill queue; no SQLite write may run on the ASGI loop. Queue unsafe mutations/non-monotonic evidence for a complete candidate rebuild on the same worker, re-check lease ownership, atomically publish, prune old-generation view rows, update readiness, and emit one `read_model` invalidation. Persist observed run timestamps without inventing duration.

**Checkpoint:** read-model/projection/indexer/worker tests green; a normal tail repair does not rebuild, lease loss cannot publish, a saturated worker cannot starve lease renewal, API/SSE probes remain responsive during a 100k backfill, and a test fails if any list request still requires full projection replay.

### Unit 3 — Attention detection history

**Primary files (≤5):**

- `src/draindeck_dashboard/attention.py` (new)
- `src/draindeck_dashboard/indexer.py`
- `src/draindeck_dashboard/scheduler.py`
- `tests/dashboard/test_attention.py` (new)
- `tests/dashboard/test_scheduler.py`

**Test first:** open, refresh, resolve, recur, generation rollover, critical system-wide stale lease, warning unclaimed lease only after one 10-second TTL, per-generation `UNCONFIRMED`/unreleased containment, exact closed severity/kind/message/target mapping, attention/health SSE invalidations, 30-second client refresh contract, absence of pending/no-finish/TORN conditions, and “detected by Dashboard” timestamp semantics.

**Implement:** reconcile the closed condition vocabulary from spec §6.4 after repository indexing and relevant lease changes. Never add dismiss mutation or claim original runtime onset time.

**Checkpoint:** attention/scheduler tests green; repeated reconciliation is idempotent and does not create duplicate open occurrences.

### Unit 4 — Bounded query layer and aggregates

**Primary files (≤5):**

- `src/draindeck_dashboard/api_queries.py` (new)
- `src/draindeck_dashboard/views.py`
- `src/draindeck_dashboard/errors.py`
- `tests/dashboard/test_api_queries.py` (new)
- `tests/dashboard/test_app_views_api.py`

**Test first:** repository summaries, overview/readiness aggregates, recent activity in immutable evidence-ID order despite TORN completion updating `stored_at`, cross-repo current-generation filters/sorts/totals, 10k new-route and 100k legacy-evidence offset caps, evidence keysets, execution `groupBy` response shapes, valid-ID 404 versus existing invalid-repoId 422, timeline scoping, evidence additive fields/oldest-first compatibility, topology bounds/truncation, deterministic tie-breakers, and query-count/offload ceilings.

**Implement:** parameterized, projection-backed queries on short-lived read connections through bounded thread offload. Centralize capped offset, evidence keyset, and closed sort/filter parsing. Join current checkpoints in every cross-repository view. Keep existing repository-scoped item shapes/defaults compatible; add only approved fields.

**Checkpoint:** query tests green on a representative multi-repository fixture; SQL tracing shows no N+1 and no per-request full evidence projection.

### Unit 5 — Search and REST route surface

**Primary files (≤5):**

- `src/draindeck_dashboard/search.py` (new)
- `src/draindeck_dashboard/app.py`
- `tests/dashboard/test_app_redesign_api.py` (new)
- `tests/dashboard/test_search.py` (new)
- `tests/dashboard/test_app_views_api.py`

**Test first:** every new endpoint, response schema, 2–200 character search validation, all five groups including evidence metadata, group caps, positive integer repository IDs, bounded opaque entity IDs, filter/sort/keyset errors, metadata-only guarantee, existing endpoint/422 snapshots, and 404/405 behavior.

**Implement:** thin FastAPI routes over Units 3–4; no business SQL in route functions. Do not change transcript, diff, or SSE contracts.

**Checkpoint:** focused API/search tests and all pre-existing API tests green; inspect representative JSON for exact truth language.

### Unit 6 — Stable UI routing and security preservation

**Primary files (≤5):**

- `src/draindeck_dashboard/app.py`
- `src/draindeck_dashboard/static/index.html`
- `src/draindeck_dashboard/static/js/router.js` (new)
- `tests/dashboard/test_app_ui_routes.py` (new)
- `tests/dashboard/test_app_health.py` or a new focused security-route test

**Test first:** direct reload for every approved nested route, explicit UI route allowlist, `/assets` mount, legacy `/styles.css` and `/app.js` compatibility, unknown UI route not-found behavior, `/api/*` isolation, security headers, hostile Host/Origin, and no inline script/style CSP regression.

**Implement:** register API first, mount only `/assets`, and return the semantic app shell from explicit approved UI route patterns before any catch-all behavior. Preserve unknown FastAPI/API 404/405 shapes, legacy asset URLs, no-JS identification, and an accessible main landmark.

**Checkpoint:** nested reloads pass under TestClient; existing health/security/API routes remain unchanged.

### Unit 7 — Design tokens, shell, themes, and shared primitives

**Primary files (≤5 per sub-step):**

Sub-step A:

- `static/styles/tokens.css` (new)
- `static/styles/base.css` (new)
- `static/styles/shell.css` (new)
- `static/index.html`
- `static/js/app.js`

Sub-step B:

- `static/styles/components.css` (new)
- `static/js/dom.js` (new)
- `static/js/format.js` (new)
- `static/js/state.js` (new)
- `static/js/components/shell.js` (new)

**Test first:** theme preference parse/fallback, exact status labels, safe text rendering, 3:1 field boundaries and surface-aware focus (including rail focus in light theme), complete contrast-alternating eight-color chart sequences/Other overflow, visible compact rail labels, WCAG 1.4.13 behavior for any supplementary tooltip, skip-link/landmark/heading structure, focus-not-obscured scroll offsets, and 320px component/shell reflow contracts.

**Implement:** DESIGN.md tokens including separate divider/control-boundary/focus/chart tokens, 240px/72px forest rail, compact <768px accessibility navigation, utility bar, breadcrumbs, system/light/dark theme control, forced-colors/reduced-motion rules, typography, buttons, fields, chips, tables, dialogs, skeletons, errors, empty states, offset/keyset pagination, and sticky-plane scroll padding.

**Checkpoint:** static tests green; no remote asset, inline handler, unsafe HTML, or unapproved visual token.

### Unit 8 — API client, connection stream, and focus-safe reconciliation

**Primary files (≤5):**

- `static/js/api.js` (new)
- `static/js/stream.js` (new)
- `static/js/dom.js`
- `static/js/state.js`
- `tests/dashboard/test_static_js_contracts.py` (new or established JS harness)

**Test first:** typed/framework fetch errors, abort/stale response suppression, SSE state transitions including attention/health/read-model types and system repository 0, 30-second time-derived refresh, invalidation coalescing, targeted refetch, preparing/stale projection states, keyed child patch, unobscured focus retention, and unaffected scroll preservation.

**Implement:** `AbortController`, small cache/state, EventSource invalidation, reconnection/resnapshot state, and keyed DOM helpers. Replace the current `clear(el)`-inside-row pattern on redesigned screens.

**Checkpoint:** deterministic JS tests green and a focused browser probe proves focus remains on an updated row control.

### Unit 9 — Home, repository registry, add flow, and repository overview

**Primary files (split into ≤5-file sub-steps):** page modules for `home`, `repositories`, `repository-detail`; shared table/chart/filter components; `pages.css`; focused tests.

**Test first:** populated/empty/filtered-empty/error/loading, real overview values, chart text equivalents/links, registry pagination/sorting, registration validation, unregister confirmation/copy, and post-mutation navigation.

**Implement:** the approved north-star composition using real data. Repository registry is a table. Availability and independent health facts remain distinct. Add/unregister copy matches the spec exactly.

**Checkpoint:** routes work end-to-end with TestClient fixture data and keyboard navigation; no illustrative count/status remains.

### Unit 10 — Attention Center and global search

**Primary files:** `attention` page, search component, attention/table/filter shared component, `pages.css`, focused tests (split if >5).

**Test first:** closed severity ordering/mapping, current/resolved filters, links, first/last-detected labels, no dismissal, exclusion of pending/no-finish/TORN, combobox semantics, repository/issue/run/execution/evidence group caps, keyboard interaction, Escape, and no-results/error states.

**Implement:** cross-repository Attention Center and simple top-bar search. Do not expose advanced syntax or search history.

**Checkpoint:** keyboard-only search-to-detail flow and resolved-attention filtering pass.

### Unit 11 — Runs and Issues workspaces

**Primary files:** run explorer/detail page modules, issue explorer/detail modules, timeline/topology components, `pages.css`, focused tests (split into two ≤5-file sub-steps).

**Test first:** exact states/outcomes, no-running language, budget definition list, metadata-only timeline, pagination, stable detail links, topology keyboard/text equivalent, and truncated topology fallback.

**Implement:** dense explorers and full detail pages. Use observed timestamps only. Include direct evidence/execution relationships and exact legacy/inconsistency language.

**Checkpoint:** run with no finish and issue with inconsistent/partial evidence are both honestly and completely rendered.

### Unit 12 — Executions, transcript, and diff workspace

**Primary files:** execution explorer/detail modules, artifact viewer component, diff styles, focused tests (split into ≤5-file sub-steps).

**Test first:** pagination-correct `groupBy=execution|issue` views, per-generation containment states using exact `UNCONFIRMED`, nested run metadata/fallback, transcript success/403/404, diff success/empty/binary/truncated/timeout/invalid refs/command failure, copy behavior, and safe text rendering.

**Implement:** aligned execution table and full detail page with Transcript and Diff tabs/panels plus metadata rail. Never render transcript/diff as markup and never invent duration.

**Checkpoint:** every existing artifact/diff error maps to a designed state with recovery/navigation action.

### Unit 13 — Evidence explorer/detail and final chart/topology polish

**Primary files:** evidence explorer/detail modules, shared table/filter/topology/chart components, `pages.css`, focused tests (split into ≤5-file sub-steps).

**Test first:** evidence ID/run ID, keyset next/previous URLs, legacy scoped oldest-first order, explicit newest sort, filters, metadata-only detail, exact integrity states, corrupt-as-health separation, same-DB/current-generation bookmark scope, long values/copy, fixed labelled/patterned chart palette, CSP-safe SVG attributes/classes, chart navigation, and forced-colors fallback.

**Implement:** metadata ledger and detail. Make no request for raw lines/payload. Finish accessible chart/topology styling using actual aggregate/relationship responses.

**Checkpoint:** evidence workflows remain usable with 100,000-row seeded DB and default page fetches remain bounded.

### Unit 14 — About & Safety, exhaustive states, and responsive hardening

**Primary files:** about page, state components, all design CSS as needed, focused tests (split mechanically to ≤5-file review groups).

**Test first:** exact safety wording, update-stream meaning, theme facts, every state matrix entry, 320/768/1024/1440 layouts, 200% text resize, non-tabular reflow, sticky focus-not-obscured, reduced motion, and forced colors.

**Implement:** About & Safety and any missing non-ideal states. Audit long paths/IDs, sticky regions, horizontal table containment, dialog focus return, live-region noise, and touch targets.

**Checkpoint:** complete state matrix with a reproducible fixture/route for each material state.

### Unit 15 — Scale, security, and full verification

**Files:** tests/fixtures or test utilities, documentation/evidence only; production edits only for defects found and must repeat focused TDD.

1. Generate deterministic Dashboard-owned test data at 20/1,000/10,000/100,000 scale without touching target repositories.
2. Measure endpoint p95/query counts and browser interaction trace against spec §14.
3. Run security tests for Host/Origin/CSP/body limits, query allowlists, encoded IDs, XSS strings, path containment, and bounded topology/search/pagination.
4. Run focused changed tests, `tests/dashboard`, then `tests/unit tests/dashboard`.
5. Run browser acceptance at 320/768/1024/1440 and 200% text resize in light/dark/reduced-motion/forced-colors modes. Capture screenshots and console/network/accessibility evidence, including tabbing beneath sticky planes.
6. Prove a 100,000-row backfill/rebuild and maximum 2,000-record tick do not stall the SSE heartbeat/API event loop, normal TORN→OK repair does not rebuild, evidence uses indexed keysets, and capped offsets reject deep work.

**Checkpoint:** every definition-of-done item has concrete evidence; no waiver is inferred.

### Unit 16 — Independent reviews and handoff

Use fresh-context independent reviews before declaring completion:

1. Contract/data honesty review against ADR-25/26 and docs/19/27.
2. Security review of all new routes, SQL, DOM sinks, routing fallback, transcript/diff, and mutations.
3. Accessibility/visual review against PRODUCT/DESIGN at every target viewport/theme.
4. Code-quality/simplification review for duplicate render/query logic, oversized modules, stale code, and unnecessary abstraction.
5. Fix findings test-first and repeat impacted focused/full/browser checks.

Update docs/08 status only if acceptance/implementation evidence warrants it, plus docs/27, `NEXT.md`, `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`, and tracked task evidence. End at a runnable local checkpoint commit only when that commit series was explicitly authorized. Never merge or push.

## 4. Stop conditions

Build-auto stops and asks the user only if:

- a change under `src/runtime` appears necessary;
- an existing ADR/API/SSE/security contract must be broken or reinterpreted;
- raw evidence/payload, target mutation, authentication/remote access, a new dependency/framework, or a destructive migration becomes necessary;
- baseline or unrelated worktree changes cannot be reconciled safely;
- an approval-gated destructive/external action is required;
- real-browser automation or local checkpoint-commit authority is absent at Unit 0;
- three evidence-based attempts at the same blocking condition fail and no safe alternative exists.

Context pressure is handled at the next unit boundary: finish/revert to the runnable unit checkpoint, update `NEXT.md` and the tracked build-evidence record, create the authorized local checkpoint commit, and resume in a fresh context. It is not permission to leave an untested partial unit. Ordinary test failures, CSS iteration, refactoring, or additional Dashboard-only files are not stop conditions.

## 5. Completion report format

The implementing agent's final handoff must lead with outcome and include:

- routes/features delivered and any explicitly deferred item;
- exact files/modules added or materially changed;
- migration/API compatibility statement;
- focused, Dashboard, combined, browser, accessibility, performance, and security results with commands/counts;
- screenshots/evidence locations;
- independent review findings and resolutions;
- `git status --short`, per-unit local commit list, diff summary, and confirmation that no merge/push occurred;
- any residual risk or spec deviation requiring user decision.
