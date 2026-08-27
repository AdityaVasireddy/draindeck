# Build Evidence — Coding-Engine Proxy Cost

**Branch:** `dashboard-engine-proxy-cost`, baseline clean `master` `0bb1629`.
**Spec:** `spec/coding-engine-proxy-cost.md`. **Design record:** `docs/28-proxy-cost.md`.
**Status header:** feature build COMPLETE through Unit 6; Units 7 (real-browser
security/accessibility) and 8 (six-axis review + final handoff) follow. No merge,
no push, no dependency install, no `src/runtime` edit.

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

## ASSUMED (not re-run this build)

- Crash/durability harness (`tests\crash\harness.py`, `run_lifecycle_harness.py`)
  not re-run this build. Rationale: no `src/runtime` file was touched (verified by
  the unchanged 560-test unit suite and the dependency-carveout test), and the
  feature adds no new write path or lease holder. To be executed/confirmed in the
  Unit 7/8 close-out if required by the reviewer.
- Live-browser rendering of the cost affordances (COMPLETE / PARTIAL "$X
  observed" + Partial / UNAVAILABLE / metered $0.00) across Home / Repository
  Overview / Issues / Runs / Executions / About — Unit 7.

## Commits (this build, chronological)

`docs: proxy-cost feature spec/plan/todo; archive redesign` → Unit 0 → Unit 1 →
Unit 2 → Unit 3 → Unit 4 → Unit 5. Each unit is a runnable, test-first
checkpoint; the full suite is green at each. Merge/push remain prohibited.
