# Todo: Coding-Engine Proxy Cost

**Gate:** `spec/coding-engine-proxy-cost.md` + `tasks/plan.md` pending user
approval this session. No `src/` mutation until approved and (for `/build auto`)
checkpoint-commit authority resolved. Merge/push prohibited until separately
authorized. Branch `dashboard-engine-proxy-cost`, baseline `0bb1629`.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done (with evidence).

## Unit 0 — Baseline & contract map
- [x] `pytest tests\unit tests\dashboard -q` baseline green — **970 passed**
      (560 unit + 410 dashboard) via `.venv\Scripts\python.exe`, 2026-08-26
- [x] Confirmed: OK evidence stores `payload_json` (incl. ExecutionFinished
      `usage`); `apply_ok_evidence_rows` reaches it; `_finish` transition reads
      `outcome`, `usage` is a sibling key; dependency-carveout test present

## Unit 1 — Validation + projection capture (pure) ✅
- [x] `validate_dollars` / `validate_tokens` helpers (`proxy_cost.py`, test-first)
- [x] `ExecutionView` gains proxy_micro_usd/cost_valid/input_tokens/
      output_tokens/tokens_valid
- [x] Capture only at accepted EXECUTION_FINISHED transition (`_capture_usage`)
- [x] Tests: validation truth table (bool/neg/non-finite/decimals/zero), tokens,
      accepted-only capture, duplicate no-overwrite (D1/D2), crash → no cost,
      independent cost/token coverage — 38 new, dashboard suite 448 passed
      (410→448), no regressions. Decision: tokens_valid requires BOTH input and
      output valid (single per-execution token-metered notion, matches the
      single `tokenMeteredExecutions` count in the API shape).

## Unit 2 — Migration v2→v3 chain + backfill trigger ✅
- [x] `SCHEMA_VERSION = 3`; ordered `_MIGRATIONS` step chain (fresh/v1/v2/v3)
- [x] `_apply_v2_to_v3_ddl`: ALTER execution_views ADD COLUMN ×5
- [x] Retain FAILED→ERROR correction; v2→v3 flips READY→REBUILDING one-time
      (no evidence scan); not re-flipped on later v3 restart
- [x] `_write_execution_view` carries new columns (rebuild + incremental)
- [x] Tests: fresh→v3, v2→v3 data preserved, concurrent-start, rollback→v2,
      version>3 refused, READY→REBUILDING flip, defaults/nullability, read-model
      persistence (11 new). Updated 5 pre-existing version-literal assertions
      (test_migrations ×4, test_db ×1) to the SCHEMA_VERSION constant. Dashboard
      suite 448→459, no regressions.

## Unit 3 — Aggregation query layer ✅
- [x] Pure builders (`proxy_cost.py`): `build_proxy_cost_object`,
      `build_average_object`, `micro_to_usd_str`, `BASIS`
- [x] SQL aggregation (`proxy_cost_agg.py`): scope (execution/issue/run/repo/
      global), `by_group_proxy_cost` (one fixed query per page), average per
      DONE issue
- [x] Cost sort `cost_order_by`: UNAVAILABLE (NULL) last both directions +
      stable ID tie-break; direction allowlisted
- [x] Tests: per-scope sums (all attempts), completeness incl. empty/zero,
      average (null-when-none, partial→Observed, extra null-when-no-metered),
      current-generation isolation, batched groups, sort/null placement — 24 new
      (11 pure + 13 SQL). Dashboard suite 459→483. (Exclusions asserted in
      Unit 4; large-scale measurement in Unit 6.)

## Unit 4 — API wiring ✅
- [x] Attach proxyCost/average to every §3.3 endpoint (additive only):
      overview (global+avg+topCostIssues), repo overview (repo+avg), cross-repo
      issues + issue detail (with executionAttempts breakdown), cross-repo runs +
      run detail, cross-repo executions + execution detail, repo issue/exec/run
      lists (via build_projection in-memory aggregate)
- [x] Cost sort added: issues list (LEFT JOIN aggregate) + executions list
      (row column), UNAVAILABLE last both directions
- [x] Evidence/Search/Attention left untouched (cost-free) — asserted
- [x] Tests: shape/invariants per endpoint incl. Runs list AND Run Detail;
      backward-compat (existing fields unchanged; updated 1 exact-dict assertion);
      exclusions asserted — 11 new. Dashboard suite 483→494.

## Unit 5 — Frontend (all placement screens) ✅
- [x] `format.js` helpers: formatMicroUsd, proxyCostText, isPartialCost,
      coverageText, averageCostText, PROXY_COST_UNAVAILABLE_TEXT
- [x] Home: total, observed avg, coverage, top-cost chart + accessible table +
      stable links (view-model Node-tested)
- [x] Repository Overview: total, avg, coverage
- [x] Issues list (cost column + Partial chip + cost-sort toggle) AND Issue
      Detail (proxy cost + per-execution-attempt breakdown table)
- [x] Runs list (cost column + Partial chip) AND Run Detail (cost + coverage)
- [x] Executions list (cost column + Partial chip) AND Execution Detail (cost)
- [x] About & Safety: "proxy, not invoice" definition + full exclusion list
      incl. orchestration (Node-tested for all excluded terms)
- [x] Tests: JS contracts (format 6, home +2, about +2); el() on*-attribute
      contract respected (addEventListener); node --check on all pages; static
      contract 17. Combined suite 1055 (560 unit unchanged + 495 dashboard).

## Unit 6 — Automated suites, docs, scale measurement ✅
- [x] Full `tests\unit tests\dashboard -q` green — 1055 (560 unit unchanged +
      495 dashboard); dependency-carveout green (no src/runtime touched)
- [x] Scale/index-deferral gate: `measure_proxy_cost.py` on 20 repos/1k
      issues/10k execs/100k evidence — all cost aggregates ≤6.8 ms vs 500 ms
      budget on existing indexes → **index deferral stands, no index added**
- [x] `docs/28-proxy-cost.md` written; docs/27 gets a single cross-ref line only;
      NEXT.md updated; `docs/reviews/PROXY_COST_BUILD_EVIDENCE.md` (VERIFIED vs
      ASSUMED)
- [ ] Crash/durability harness (ASSUMED unregressed — no src/runtime touched; to
      confirm at Unit 8 close-out if reviewer requires)

## Unit 7 — Real-browser security & accessibility
- [ ] Live browser: COMPLETE / PARTIAL / UNAVAILABLE / metered $0.00 across
      Home / Repo Overview / Issues / Runs / Executions / About
- [ ] Security (no new injection surface; additive JSON; no PII) + accessibility
      (chart-has-table, keyboard/focus, contrast, 200% text, responsive) evidence

## Unit 8 — Six-axis review, fixes, final handoff
- [ ] Fresh-context six-axis review (correctness, readability, architecture,
      security, performance, test-coverage)
- [ ] Every blocking/P0/P1/P2/Important finding fixed test-first (record each)
- [ ] Final handoff document in docs/handoffs/
- [ ] Do NOT merge/push — hand off for user merge decision

## Evidence log
- (append dated VERIFIED/ASSUMED entries here as units complete)
