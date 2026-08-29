# Implementation plan: Coding-Engine Proxy Cost

**Status:** DRAFT — pending user approval in this planning session. No `src/`
mutation until the user approves this plan + `spec/coding-engine-proxy-cost.md`
and (for an uninterrupted `/build auto` run) resolves local checkpoint-commit
authority.
**Branch:** `dashboard-engine-proxy-cost`, baseline clean `master`
`0bb16292cc4c920f2cbdf075d9b51e58015eb1c4`.
**Mutation boundary:** `src/draindeck_dashboard`, `tests/dashboard`, Dashboard
docs/task artifacts. **Never edit `src/runtime`; the event schema (doc 03) is
frozen.** No dependency installs. No transcript parsing.

## 1. Authority and gates

Order of authority:
1. Frozen runtime/observer contracts + doc 03 (event/state semantics win over
   everything).
2. Accepted ADR-25/26/27 and existing Dashboard read-model contracts (docs/19,
   docs/27).
3. `spec/coding-engine-proxy-cost.md` (this feature's contract).
4. `PRODUCT.md` / `DESIGN.md` for visual/product direction.
5. This plan and `tasks/todo.md`.

**Blast radius:** this touches Dashboard `src/` read-model behavior, a SQLite
schema-version bump, and a startup migration — **high-blast-radius**. Full
five-gate discipline, test-first, per-unit runnable checkpoints. Reversible
docs/task edits are low-blast-radius.

**Baseline gate (Unit 0):** confirm the baseline suite is green before any
mutation — `python -m pytest tests\unit tests\dashboard -q`. Record the exact
counts; every later checkpoint must not regress them.

## 2. Execution model

One `/build auto` pass of ordered units, each a runnable, test-first checkpoint.
Local per-unit checkpoint commits **only if** the user authorizes the bounded
series in the build authorization (CLAUDE.md hard rule). **Merge and push remain
prohibited** until separately, explicitly authorized. If checkpoint-commit
authority is withheld, stop at the first approval gate rather than accumulating
an unreviewable diff.

## 3. Design decisions (surfaced for approval)

- **D1 — capture point:** cost/tokens are read from `usage` only at the single
  *accepted* `EXECUTION_FINISHED` transition inside `projections.py`
  (`_apply_execution_transition`). Duplicate/out-of-order terminal events fail
  the transition and never contribute — double-count-proof by construction. A
  non-`ExecutionFinished` terminal (crash) yields no cost.
- **D2 — inconsistent-after-valid:** an execution flagged `inconsistent` by a
  later duplicate *retains* the first captured cost (spec §2.1 D1). Reviewed as a
  named edge in Unit 1 tests.
- **D3 — storage grain:** cost stored per execution in `execution_views`;
  issue/run/repo/global figures are computed by SQL aggregation, never stored
  redundantly (single source of truth, no denormalized drift).
- **D4 — backfill:** startup migration adds columns and flips `READY`→
  `REBUILDING`; the existing lease-owned async rebuild backfills. No evidence
  scan at startup.
- **D5 — additive API only:** `proxyCost`/average objects are new keys; no
  existing field changes. Backward compat is proven by the existing suite
  remaining green.

## 4. Units

### Unit 0 — Baseline & contract map (no `src/` mutation)
- Run `pytest tests\unit tests\dashboard -q`; record baseline counts.
- Confirm `ExecutionFinished` OK evidence stores `payload_json.usage` and the
  projection reaches it. Confirm dependency-carveout test present.
- **Checkpoint:** baseline green, counts recorded in `tasks/todo.md`.

### Unit 1 — Cost/token validation + projection capture (pure, most testable)
- New pure helpers (new module `proxy_cost.py` or within `projections.py`):
  `validate_dollars(value) -> Optional[int]` (micro-USD; bool/neg/non-finite →
  None; `Decimal(str(value))*1_000_000` `ROUND_HALF_UP`); `validate_tokens(value)
  -> Optional[int]` (non-negative int, not bool).
- Extend `ExecutionView` with `proxy_micro_usd`, `cost_valid`, `input_tokens`,
  `output_tokens`, `tokens_valid`.
- In `_apply_execution_transition`, when `etype is EXECUTION_FINISHED` and the
  transition is **accepted**, read `usage` from the payload and populate the
  fields. Nowhere else.
- **Tests (test-first):** validation truth table incl. adversarial decimals and
  a metered valid `0`; capture only on accepted finish; duplicate finish doesn't
  overwrite (D1/D2); crash terminal → no cost; independent cost/token coverage.
- **Checkpoint:** projection unit tests green; no schema/API change yet.

### Unit 2 — SQLite v2→v3 ordered migration chain + backfill trigger
- `migrations.py`: `SCHEMA_VERSION = 3`; refactor to an ordered step list
  (`v1→v2` unchanged, new `_apply_v2_to_v3_ddl` = `ALTER TABLE execution_views
  ADD COLUMN` ×5); runner applies all steps `from < current` in order (fresh,
  v1, v2, v3 branches). Retain `FAILED`→`ERROR` correction. `v2→v3` flips
  `READY`→`REBUILDING` (no evidence scan).
- `read_models.py`: `_write_execution_view` writes the new columns;
  `fetch`/publish/incremental paths carry them.
- **Tests:** fresh→v3 shape; v2 DB→v3 preserves all pre-existing rows;
  concurrent-start (two connections) safe; failed step rolls back whole chain;
  `version>3` refused; `READY`→`REBUILDING` flip on v2→v3; `FAILED`→`ERROR`
  retained; new columns nullable/defaulted correctly.
- **Checkpoint:** migration + read-model persistence tests green; existing
  migration/read-model tests still green.

### Unit 3 — Aggregation query layer (`api_queries.py`)
- Add cost aggregation helpers computing the `proxyCost` object for a scope
  (execution/issue/run/repo/global) and the average-per-DONE-issue object.
  Current-generation joins reused; batched fixed-query-count per page for lists
  (mirror the groupBy=issue two-query pattern).
- Cost sort columns added to the allowlists; UNAVAILABLE-last + ID tie-break
  encoded in `ORDER BY` (e.g. `proxy_micro_usd IS NULL, proxy_micro_usd DIR,
  id`).
- **No cost on excluded endpoints:** Evidence/Search/Attention query paths are
  not touched; a test asserts their responses carry no `proxyCost`.
- **No cost on excluded endpoints:** Evidence/Search/Attention query paths are
  not touched; a test asserts their responses carry no `proxyCost`.
- **Tests:** per-scope sums (all attempts incl. retries/rejections/failures);
  completeness incl. empty scope; average incl. `null`-when-no-DONE, dual
  coverage, Observed flag; sort ordering incl. null placement + tie-break;
  bounded query count on a multi-row page (assert fixed number of queries). The
  large-scale measurement itself is Unit 6.
- **Checkpoint:** query-layer tests green.

### Unit 4 — API wiring (`app.py`, `views.py`)
- Attach `proxyCost` (and average where applicable) to every §3.3 endpoint —
  overview (global), repository overview, issues list + issue detail, runs list +
  run detail, executions list + execution detail, repo issue/exec lists, Home
  top-cost issues. Additive keys only; readiness gates unchanged.
- Evidence/Search/Attention endpoints deliberately untouched.
- **Tests:** each endpoint returns the object with correct shape/invariants;
  Runs list AND Run Detail covered; existing endpoint contract tests unchanged
  (backward compat); readiness/stale labelling still applies; excluded endpoints
  asserted cost-free.
- **Checkpoint:** API tests green; full `tests\unit tests\dashboard` green.

### Unit 5 — Frontend (all placement screens)
- `format.js`: currency/coverage/completeness helpers (micro-USD → "$X.XX",
  "$X observed", "—" for unavailable, metered "$0.00").
- Screens (spec §5), each accessible + theme-aware:
  - **Home** (`pages/home.js`): total, observed average, coverage, top-cost
    issues chart (`components/chart.js`) + accessible table + stable issue links.
  - **Repository Overview** (`pages/repository-detail.js`): total, completed-issue
    average, coverage.
  - **Issues list AND Issue Detail** (`pages/issues.js`): sortable cost,
    completeness, per-execution-attempt breakdown on detail, visible Partial
    label.
  - **Runs list AND Run Detail** (`pages/runs.js`): aggregate cost, completeness,
    coverage on both.
  - **Executions list AND Execution Detail** (`pages/executions.js` + detail):
    per-execution cost and validity on both.
  - **About & Safety** (`pages/about.js`): "proxy, not invoice" definition + full
    exclusion list (reviewer / validation / **orchestration** / subscription /
    crashed-execution usage + Evidence/Search/Attention screens).
- **Tests:** JS contract tests (`tests/dashboard/js`, `test_static_js_contracts`)
  for formatting, null/partial rendering, chart-has-table, copy strings, and the
  Runs/About content.
- **Checkpoint:** JS + full suite green.

### Unit 6 — Automated suites, docs, scale measurement
- Full `tests\unit tests\dashboard -q` green; dependency-carveout green (no
  `src/runtime` touched); crash/durability posture confirmed unregressed.
- **Scale/index-deferral gate (measured):** use the existing 100k-row scale
  fixture (`tests/dashboard/scale`) to measure the cost-aggregate query on a large
  generation. Index deferral stands **only if** the measured query count/latency
  stays within the existing per-tick/response budget; otherwise add the index in
  Unit 2's migration and re-measure. Record the measurement.
- Write `docs/28-proxy-cost.md` (contract, D1–D5, migration/backfill rationale,
  compatibility, exclusions). **Keep `docs/27` frozen** — ≤1 minimal cross-ref
  line only if necessary. Update `PRODUCT.md`/`DESIGN.md` notes if needed and a
  build-evidence file separating VERIFIED vs ASSUMED.
- **Checkpoint:** all automated suites green, scale measurement + docs recorded.

### Unit 7 — Real-browser security & accessibility verification
- Live browser verification (real runtime, not code-review-only): Home / Repo
  Overview / Issues / Runs / Executions / About showing COMPLETE, PARTIAL
  ("$X observed" + visible Partial), UNAVAILABLE, and a metered `$0.00`.
- Security: no new injection/interpolation surface (cost sort uses the allowlist);
  additive JSON only; no secret/PII exposure. Accessibility: chart has a table
  equivalent + stable links, keyboard/focus, contrast, 200% text, responsive
  breakpoints for the new cost affordances.
- **Checkpoint:** browser security/accessibility evidence recorded.

### Unit 8 — Six-axis fresh-context review, fixes, final handoff
- Independent fresh-context review across six axes (correctness, readability,
  architecture, security, performance, test-coverage) focused on validation,
  double-count safety (D1/D2), migration concurrency/rollback, exclusion
  preservation, and null/partial UI honesty.
- **Every real blocking/P0/P1/P2/Important finding fixed test-first**; record the
  disposition of each finding.
- Produce the **final handoff document** (`docs/handoffs/`): objective, status,
  decisions+rationale, key files, verification evidence, next action.
- **Do not merge or push.**
- **Checkpoint:** feature complete, evidence + handoff recorded, awaiting user
  merge decision.

## 5. Risks / watch-items
- Decimal conversion edge cases (half-up rounding, tiny/large values) — covered
  by adversarial unit tests.
- Aggregate query cost on large generations — keep fixed-query-count per page;
  reuse existing indexes (`ix_execution_views_issue/_run`); add an index only if
  the Unit 6 measured need appears (surface as a decision, not silently).
- Migration flipping `READY`→`REBUILDING` briefly serves `stale`-labelled data
  during backfill — intended and honest; verify labelling.
- Backward compatibility: assert no existing response field changes; excluded
  endpoints stay cost-free.
