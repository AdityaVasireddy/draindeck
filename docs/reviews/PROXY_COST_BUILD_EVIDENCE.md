# Build Evidence — Coding-Engine Proxy Cost

**Branch:** `dashboard-engine-proxy-cost`, baseline clean `master` `0bb1629`.
**Spec:** `spec/coding-engine-proxy-cost.md`. **Design record:** `docs/28-proxy-cost.md`.
**Status header:** feature build COMPLETE through Unit 8 (all units done). Units
7 (real-browser security/accessibility) and 8 (six-axis review + fixes + final
handoff) completed 2026-08-28; two real UI findings fixed test-first and
re-verified live. No merge, no push, no dependency install, no `src/runtime`
edit. Awaiting user merge decision.

Honesty discipline (CLAUDE.md): VERIFIED = ran it and saw the result this build;
ASSUMED = not independently re-run this build.

## VERIFIED

- **Baseline (Unit 0):** `.venv\Scripts\python.exe -m pytest tests\unit
  tests\dashboard -q` → **970 passed** (560 unit + 410 dashboard) before any
  mutation.
- **Combined suite (post-Unit-5):** `tests\unit tests\dashboard` →
  **1055 passed** (560 unit unchanged + 495 dashboard). Unit suite unchanged at
  560 confirms no `src/runtime` impact; dependency-carveout test green.
- **Unit 1 validation/capture:** 38 tests — Decimal/ROUND_HALF_UP conversion on
  adversarial values, bool/negative/non-finite rejection, metered zero, tokens,
  accepted-only capture, duplicate no-overwrite (D1), crash→no cost, independent
  cost/token coverage.
- **Unit 2 migration:** 11 tests — fresh→v3, v2→v3 data preserved + columns
  added, concurrent-start converges on v3, injected-failure rollback stays at v2,
  version>3 refused, READY→REBUILDING one-time flip (not re-flipped on v3
  restart), defaults/nullability, read-model persistence (rebuild + incremental).
  Updated 5 pre-existing version-literal assertions to the `SCHEMA_VERSION`
  constant (contract deliberately moved 2→3).
- **Unit 3 aggregation:** 24 tests — per-scope sums (all attempts), completeness
  incl. empty/zero, average (null-when-none, partial→Observed, null-when-no-
  metered), current-generation isolation, batched groups, cost sort (UNAVAILABLE
  last both directions + stable tie-break).
- **Unit 4 API wiring:** 11 tests — proxyCost/average shape+invariants on
  overview (global+avg+topCostIssues), repo overview, cross-repo issues + issue
  detail (executionAttempts breakdown), cross-repo runs + run detail, cross-repo
  executions + execution detail, repo-scoped lists; cost sort places UNAVAILABLE
  last; **exclusions** (Evidence/Search/Attention cost-free) asserted;
  backward-compat (existing fields unchanged) asserted.
- **Unit 5 frontend:** JS node tests — format (6), home view-model (+2), about
  content (+2, incl. orchestration term). `node --check` clean on all 6 pages +
  format.js; static-js-contract suite green (17); `el()` `on*`-attribute contract
  respected (addEventListener).
- **Unit 6 scale/index-deferral:** `tests\dashboard\scale\measure_proxy_cost.py`
  on 20 repos / 1,000 issues / 10,000 executions / 100,000 evidence —
  global_proxy_cost 1.3 ms, average 0.9 ms, top_cost_issues 5.3 ms,
  issues sort=cost page 6.8 ms, by_group 100-issue page 0.8 ms; all ≪ 500 ms
  budget on existing indexes. **Index deferral stands; no new index added.**

## VERIFIED — Unit 7 (real-browser security & accessibility, 2026-08-28)

Method: launched the real server (`draindeck-dashboard --config …`, port 8422)
against a purpose-seeded read-model DB (`scratchpad/seed_unit7.py`, the
established Dashboard-owned direct-seed pattern) with one repository whose rows
exercise every proxy-cost state, so the real API aggregation
(`proxy_cost_agg`/`api_queries`) computed the objects and the shipped JS rendered
them. Data path first confirmed via the real API (loopback `TestClient`), then
each screen inspected live via `mcp__claude-in-chrome` (real DOM/computed-style
reads + screenshots).

- **All four states render correctly on every placement.** Home global
  (`$3.26 observed`, `4 of 6 executions metered`, Partial chip; observed average
  `$1.09 observed`, Observed-average chip); Repository Overview (same, repo
  scope); Issues list + Issue Detail (`$2.34` / `$0.92 observed`+Partial /
  `$0.00` / `Not observed`; detail per-execution-attempt breakdown incl. a
  REJECTED attempt showing `Not observed`); Runs list + Run Detail
  (`$2.34` / `$0.92 observed`+Partial / `Not observed`); Executions list +
  Execution Detail (`$1.84`/`$0.50`/`$0.92`/`Not observed`/`Not observed`/
  `$0.00`; CRASHED execution → `Not observed`); About & Safety (full
  "proxy, not an invoice" definition, basis constant, "unknown, never as
  $0.00", and the complete exclusion list — reviewer / validation /
  orchestration + runtime coordinating-compute description / subscription /
  crashed-execution usage + Evidence/Search/Attention screens).
- **Copy rules honoured live:** UNAVAILABLE → "Not observed" (never $0.00);
  PARTIAL → "$X observed" + visible Partial chip; metered valid $0.00 → "$0.00".
- **Exclusions live:** `/api/evidence`, `/api/search`, `/api/attention` all
  return 200 with NO `proxyCost` key.
- **Accessibility:** top-cost chart is `role="img"` + aria-label, with an
  accessible data-table equivalent (Issue/Repository/Observed proxy cost/
  Coverage) and stable per-issue links (`/repositories/{id}/issues/{id}`, tabindex
  0); chart bars are keyboard-focusable (`.chart-bar-group:focus-visible`).
  Cost-sort controls are native `<button>`s (tabindex 0); real Enter keypress
  activates and re-renders correctly (Issue cell is a proper `<th scope="row">`).
  `:focus-visible { outline: 2px solid }` ring defined (with a dark-surface
  variant). Reduced motion handled (`@media (prefers-reduced-motion: reduce)`
  rules present; bar `transition-duration: 0s`). Reflow-safe: list tables sit in
  `.ledger-table-wrapper { overflow-x: auto }`; Home cost affordances show no body
  horizontal overflow at 200% zoom and at a 360px width, no clipping.
- **Both themes:** cost affordances legible in light and dark — Partial chip
  contrast 5.00:1 (light) / 8.67:1 (dark); total-cost number 14.12:1 (dark);
  both ≥ WCAG AA.
- **Security:** cost-carrying responses keep the full header set
  (`Content-Security-Policy: default-src 'self'; frame-ancestors 'none';
  base-uri 'self'`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`); JSON is additive with no `<script>`/
  `javascript:` content. Cost sort is strictly allowlisted: valid
  `sort=cost&direction=asc|desc` → 200; `direction=DESC;--`,
  `direction=asc) UNION SELECT`, and `sort=<injection>`/`sort=notacolumn` → 422.
  `cost_order_by` interpolates only fixed internal column literals; no
  injection/interpolation surface introduced.

## VERIFIED — Unit 8 (six-axis review, fixes, durability, 2026-08-28)

Fresh adversarial read of the full source diff from baseline `0bb1629`
(`proxy_cost.py`, `proxy_cost_agg.py`, `projections.py`, `migrations.py`,
`read_models.py`, `api_queries.py`, `app.py`, `views.py`, `static/js/*`) across
correctness, readability, architecture, security, performance, test quality.

- **Correctness confirmed by construction:** `_capture_usage` sets
  `cost_valid=True` only when `validate_dollars` returns non-None, so the
  aggregation-critical invariant `cost_valid=1 ⟹ proxy_micro_usd NOT NULL` holds
  (a COMPLETE/PARTIAL scope can never emit a null amount). A duplicate/out-of-
  order finish is flagged inconsistent before capture (D1), and the incremental
  read-model path (`apply_changed_entities_locked`) re-fetches and replays each
  execution's COMPLETE OK evidence — so cost is re-derived, never carried as a
  DB delta and never wiped by a later inconsistency write (D1 holds on both the
  full-rebuild and incremental paths). Migration runner is lock-first
  concurrency-safe, applies only steps above the DB version, does the
  READY→REBUILDING flip once inside `v2→v3` (not re-run on a v3 restart), refuses
  version>3, rolls back the whole chain on failure, retains FAILED→ERROR.
- **Architecture / security / performance / test quality:** no blocking findings
  — additive API only (D5), cost computed by aggregation not stored redundantly
  (D3), no new write path or lease holder, allowlisted sort, fixed-query-count
  per page on existing indexes.
- **Two real findings, both FIXED test-first, both re-verified live:**
  - **Finding A (readability, correctness-of-presentation) — Home top-cost chart
    value labels rendered raw micro-USD (`2340000`) instead of formatted USD.**
    Fix: `chart.js` gained a pure `chartValueText(entry)` (per-entry `valueText`
    override, falling back to `String(value)` for count charts), used for both the
    visible value label and the `<title>`; `home.js` gained a pure
    `buildTopCostChartEntries()` that sets `valueText = proxyCostText(...)` while
    keeping micro-USD as the numeric bar magnitude. RED-then-GREEN via new
    `tests/dashboard/js/test_proxy_cost_render.mjs`. Live after fix: labels read
    `$2.34` / `$0.92 observed` / `$0.00`.
  - **Finding B (spec §5 conformance) — Run Detail omitted the visible "Partial"
    chip** (present on Home, Runs list, Issue Detail). Fix: `runs.js` gained an
    exported `runProxyCostDd(proxyCost)` that appends the `chip chip--warn`
    "Partial" label when `isPartialCost`, used by `renderDetail`. RED-then-GREEN
    in the same test file. Live after fix: `$0.92 observed — 1 of 2 executions
    metered` **+ Partial chip**.
- **Regression + scale re-run after the fixes:** `tests\unit tests\dashboard -q`
  → **1056 passed** (560 unit unchanged + 496 dashboard; +1 is the new JS-contract
  case, +8 assertions inside it). `node --check` clean on all edited JS.
  Proxy-cost scale measurement re-run: global 1.2 ms, average 0.8 ms, top-cost
  5.5 ms, issues sort=cost page 6.8 ms, by_group 0.8 ms — all ≪ 500 ms budget;
  index deferral stands.
- **Durability (crash) gate — VERIFIED this session:** `tests\crash\harness.py`
  on seed 42 and seed 1337 (see the Unit-8 evidence-log entry in
  `tasks/todo.md` for the exact result line). Converts the Unit-6 ASSUMED item to
  VERIFIED. `src/runtime` remains untouched (git `diff --name-only` from baseline
  shows no `src/runtime` file; dependency-carveout test green).

## DEFERRED / WAIVED

- **None.** Every Unit 7/8 gate the plan named was met by an available mechanism
  (real server + real browser automation). No `forced-colors`-style unreachable
  sub-check arose for the cost affordances. No item is waived.

## Commits (this build, chronological)

`docs: proxy-cost feature spec/plan/todo; archive redesign` → Unit 0 → Unit 1 →
Unit 2 → Unit 3 → Unit 4 → Unit 5. Each unit is a runnable, test-first
checkpoint; the full suite is green at each. Merge/push remain prohibited.
