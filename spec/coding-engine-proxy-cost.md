# Spec: Coding-Engine Proxy Cost in the Dashboard

**Status:** DRAFT — pending user approval in this planning session.
**Branch:** `dashboard-engine-proxy-cost`, baseline clean `master` at
`0bb16292cc4c920f2cbdf075d9b51e58015eb1c4`.
**Mutation boundary:** `src/draindeck_dashboard`, `tests/dashboard`, and
Dashboard docs/design/task artifacts only. **Never edit `src/runtime`.** The
event schema (doc 03) is FROZEN and untouched. No dependency installs. No
transcript parsing.

> The root `SPEC.md` is the legacy external-observer specification. It is NOT
> the active spec for this feature. THIS file is the active contract for the
> coding-engine proxy-cost feature. On any conflict between this spec and the
> Dashboard code, this spec wins (it is the intended contract); on any conflict
> touching event/state semantics, **doc 03 wins over everything** and this spec
> must be corrected rather than the runtime.

---

## 1. Objective

Expose the coding engine's **proxy cost** — the engine-reported, API-list-rate
dollar figure already recorded in `ExecutionFinished.payload.usage.dollars`
(doc 03 line 95; `total_cost_usd` at the source, see
`src/runtime/engine/claude_headless.py`) — throughout the Dashboard, at every
aggregation level, using **only data the runtime already emits**. This is a
read-side / presentation feature layered on the existing tolerant read models.

### 1.1 What this is NOT (explicit exclusions)

- **Not** a measure of true spend. It is a *proxy*: engine-reported token usage
  priced at API list rates. Reviewer-LLM cost, validation compute, **orchestration
  cost** (the Draindeck runtime's own coordinating compute — the orchestrator
  loop, Git operations, recovery — which the coding engine never reports),
  subscription fees (`claude -p` runs on a Pro subscription per ADR-18, so the
  API-list-rate figure is a proxy, not a bill), and usage from crashed executions
  that never emitted a terminal `ExecutionFinished` are all **excluded and
  unknowable** here. The API `basis` field states this permanently:
  `"ENGINE_REPORTED_API_LIST_RATE_PROXY"`.
- **Not** derived from transcripts. No transcript is opened or parsed.
- **Not** inferred. Dollars are never inferred from tokens, nor tokens from
  dollars. Missing cost is **unknown, never zero**.
- **Not** a runtime change. `src/runtime` and the event schema are untouched.
- **Not** surfaced on Evidence, Search, or Attention. Those screens and their
  endpoints (`/api/evidence*`, `/api/search`, `/api/attention*`) carry **no**
  `proxyCost` object — cost is an entity-aggregate concern (execution/issue/run/
  repository/global), not an evidence-record, search-hit, or attention-condition
  concern. This exclusion is deliberate and must be preserved.

---

## 2. Metric definition (authoritative)

### 2.1 Per-execution cost

For a single execution, proxy cost comes from the `usage` object of **the same
accepted `ExecutionFinished` event that determines the tolerant execution
projection** (`projections.py`). Concretely:

- The accepted `ExecutionFinished` is the one whose `EXECUTION_FINISHED`
  transition is actually applied to the `ExecutionView` (the first valid
  terminal transition out of `EXECUTING`). A duplicate or out-of-order second
  `ExecutionFinished` fails the transition (its `(state, EXECUTION_FINISHED)`
  has no transition function), is flagged `inconsistent`, and its `usage` is
  **never read**. This is how "never double-count duplicate/inconsistent
  terminal evidence" is enforced *by construction* — cost is captured only at
  the single accepted transition, nowhere else.
- If the accepted terminal transition is **not** an `ExecutionFinished` (e.g. an
  `ExecutionCrashed`), the execution has **no** proxy cost (`cost_valid =
  false`, `proxy_micro_usd = NULL`). Crashed executions are the excluded,
  unknowable case from §1.1.
- Only `integrity='OK'` evidence is projected (the projection already scopes to
  `integrity='OK'`), satisfying "Use only OK evidence".

**Decision D1 (execution flagged inconsistent after a valid finish):** an
execution that captured a valid cost at its accepted `ExecutionFinished`, then is
later flagged `inconsistent` by a *duplicate* terminal event, **retains** that
first captured cost. The captured value came from the single accepted event; the
duplicate is discarded, not additive. `inconsistent` marks an observed anomaly,
not "this execution's cost is void." (Rationale: discarding real, already-metered
signal because a later duplicate arrived would *under*-count honest cost. See the
identical "recover, don't permanently hide" reasoning already in
`_apply_run_started`/`_apply_run_finished`.) This decision is called out as a
review-worthy edge in the plan.

### 2.2 Validation and conversion (`usage.dollars` → micro-USD)

`usage.dollars` is validated **independently** of tokens:

- **Reject** (cost invalid, `proxy_micro_usd = NULL`, `cost_valid = false`):
  `bool` (Python `True`/`False`; note `isinstance(True, int)` is `True`, so bool
  must be excluded explicitly and first), negative values, and non-finite values
  (`NaN`, `±Inf`).
- **Accept** (cost valid, metered): any finite numeric (`int` or `float`, not
  `bool`) `>= 0`. **A valid `0` is metered** — it counts as a metered execution
  with `proxy_micro_usd = 0`, not as missing cost.
- **Convert:** `Decimal(str(value))` (string constructor, to avoid binary float
  artifacts) `* Decimal(1_000_000)`, quantized to an integer with
  `ROUND_HALF_UP` (deterministic), yielding **integer micro-USD**. Stored as an
  integer; a valid zero stores `0`.

### 2.3 Tokens (`usage.input_tokens` / `usage.output_tokens`)

Validated **independently** of cost and of each other's coverage grouping:

- Each of `input_tokens`, `output_tokens`: accept **non-negative integers only**
  (`int`, not `bool`). Reject bool, negatives, floats, non-numeric.
- **Token coverage is independent from cost coverage.** An execution may have
  valid tokens but invalid/missing dollars, or vice versa. `tokens_valid` is a
  separate flag from `cost_valid`. Token counts are summed only over executions
  with valid tokens (`tokenMeteredExecutions`).
- Dollars are never inferred from tokens; tokens are never inferred from dollars.

### 2.4 Aggregation scopes

- **Issue:** sum over **every** execution attempt belonging to the issue —
  including retries, rejections, and validation failures. (Every `ExecutionView`
  with that `issue_id` in the current generation; membership is not filtered by
  execution outcome. Executions without a valid cost contribute to
  `totalExecutions`/`missingCostExecutions` but add `0` to the sum.)
- **Run:** sum over every execution carrying that `run_id`.
- **Repository / global:** sum over the current identity generation only
  (existing `checkpoints.identity_generation_id` join, exactly as every other
  aggregate does — a post-rollover repo never leaks a stale generation).
- **Execution:** the single execution's own values.

### 2.5 Completeness

Over the executions in scope:

- `COMPLETE` — **all** included executions have valid dollar cost.
- `PARTIAL` — **some but not all** have valid dollar cost.
- `UNAVAILABLE` — **none** have valid dollar cost.

Empty scope (zero included executions) is `UNAVAILABLE` with
`observedMicroUsd = null` (there is nothing observed; not `COMPLETE` of nothing).

### 2.6 Average proxy cost per completed issue

- Denominator: issues in **exact** state `DONE` (`IssueState.DONE`) in scope.
- Numerator: summed proxy cost of the executions belonging to those `DONE`
  issues (all their attempts, per §2.4).
- **Return `null`** when there are **no** completed (`DONE`) issues.
- Always disclose **both** coverage figures: how many `DONE` issues exist and how
  many of the included executions are cost-metered (issue coverage and usage
  coverage are distinct — a `DONE` issue can still have partial cost).
- If **any** included cost is partial (completeness ≠ `COMPLETE`), the average is
  labelled **"Observed average"** in UI copy and flagged in the API payload.

---

## 3. API contract

### 3.1 The `proxyCost` object (backward-compatible, additive)

Attach this object to `execution`, `issue`, `run`, `repository`, and `global`
responses **where applicable** (see §3.3). It is purely additive — no existing
field is renamed, removed, or retyped, so every current consumer/test is
unaffected.

```jsonc
proxyCost: {
  basis: "ENGINE_REPORTED_API_LIST_RATE_PROXY",   // constant, always present
  observedMicroUsd: 1840000 | null,               // integer micro-USD, or null when UNAVAILABLE
  observedUsd: "1.840000" | null,                 // decimal string, 6 dp, or null; derived from micro-USD
  completeness: "COMPLETE" | "PARTIAL" | "UNAVAILABLE",
  meteredExecutions: 2,                            // executions with valid dollar cost
  totalExecutions: 3,                             // all included executions in scope
  missingCostExecutions: 1,                       // totalExecutions - meteredExecutions
  inputTokensObserved: 41200 | null,              // sum over token-metered execs, or null if none
  outputTokensObserved: 9800 | null,              // sum over token-metered execs, or null if none
  tokenMeteredExecutions: 2                        // executions with valid tokens (independent of cost)
}
```

Invariants: `missingCostExecutions == totalExecutions - meteredExecutions`;
`completeness == UNAVAILABLE` iff `meteredExecutions == 0`; `completeness ==
COMPLETE` iff `meteredExecutions == totalExecutions > 0`; `observedMicroUsd`/
`observedUsd` are `null` iff `UNAVAILABLE`. `observedUsd` is derived from
`observedMicroUsd` (micro-USD `/ 1_000_000` as a fixed 6-dp decimal string),
never re-derived from floats.

### 3.2 The average object (Home / Repository Overview)

```jsonc
averageProxyCostPerCompletedIssue: {
  basis: "ENGINE_REPORTED_API_LIST_RATE_PROXY",
  observedMicroUsd: 920000 | null,      // null when no DONE issues
  observedUsd: "0.920000" | null,
  observed: true | false,               // true => label "Observed average" (some cost partial)
  completedIssues: 2,                   // count of DONE issues (issue coverage)
  costMeteredExecutions: 3,             // usage coverage across those issues' executions
  totalExecutions: 4
}
```

### 3.3 Placement matrix (which responses carry which object)

| Endpoint | `proxyCost` | average |
|---|---|---|
| `GET /api/overview` (global/Home) | ✅ global | ✅ |
| `GET /api/repositories/{id}/overview` | ✅ repo | ✅ (repo-scoped) |
| `GET /api/issues` (list items) | ✅ per issue | — |
| `GET /api/repositories/{id}/issues/{issue_id}` (detail) | ✅ issue | — |
| `GET /api/runs` (list items) | ✅ per run | — |
| `GET /api/repositories/{id}/runs/{run_id}` (detail) | ✅ run | — |
| `GET /api/executions` (list items) | ✅ per execution | — |
| `GET /api/repositories/{id}/executions/{execution_id}` (detail) | ✅ execution | — |
| `GET /api/repositories/{id}/issues` (repo issue list) | ✅ per issue | — |
| `GET /api/repositories/{id}/executions` (repo exec list) | ✅ per execution | — |
| Home "top-cost issues" data | ✅ per issue (bounded) | — |

Lists stay **bounded/paginated** exactly as today; `proxyCost` is computed only
for the page's rows (fixed-cost batched aggregate over the page's ids, mirroring
the existing `cross_repository_executions` groupBy=issue two-query pattern —
never one query per row).

**Explicitly excluded endpoints (no `proxyCost`):** `/api/evidence`,
`/api/repositories/{id}/evidence`, `/api/repositories/{id}/evidence/{evidence_id}`,
`/api/search`, `/api/attention`, `/api/repositories/{id}` attention summary, and
the timeline/topology endpoints. These are unchanged by this feature.

### 3.4 Cost sorting

Where a cost sort is offered (issues list, executions list, top-cost issues):

- Ascending or descending by `observedMicroUsd`.
- **`UNAVAILABLE` (null cost) always sorts last**, in both directions.
- Stable **ID tie-breaker** (issue_id / execution_id) so equal costs and the
  null group have a deterministic order across pages.
- Sort keys come from the existing server-side allowlist pattern
  (`_*_SORT_COLUMNS`), never interpolated from caller input.

### 3.5 Errors and readiness

Cost aggregates ride on the existing read-model readiness gates
(`check_read_model_readiness` / `projectionState`). A repository whose read model
is `PREPARING`/`ERROR` still raises `IndexPreparingError`; a `REBUILDING` repo is
served labelled `stale` — cost included. No new error class is introduced.

---

## 4. Storage and migration

### 4.1 Read-model columns (execution_views)

Add nullable columns to `execution_views` (the per-execution grain where cost is
captured; issue/run/repo/global sums are computed by aggregation, never stored
redundantly):

- `proxy_micro_usd INTEGER` — nullable; the metered integer micro-USD, or NULL.
- `cost_valid INTEGER NOT NULL DEFAULT 0` — 0/1; independent of tokens.
- `input_tokens INTEGER` — nullable observed input tokens, or NULL.
- `output_tokens INTEGER` — nullable observed output tokens, or NULL.
- `tokens_valid INTEGER NOT NULL DEFAULT 0` — 0/1; independent of cost.

A valid zero cost stores `proxy_micro_usd = 0`, `cost_valid = 1` (distinct from
NULL/`cost_valid = 0`). The `ExecutionView` dataclass gains the matching
nullable fields; `_write_execution_view` persists them; both the full-rebuild
and incremental paths populate them from the same projection reducer.

### 4.2 SCHEMA_VERSION 2 → 3, real ordered chain

`migrations.py` becomes a **real ordered fresh/v1/v2/v3 chain**, not a single
step:

- `SCHEMA_VERSION = 3`.
- A migration registry/list of ordered steps: `v1→v2`
  (`_apply_v1_to_v2_ddl`, unchanged) and new `v2→v3` (`_apply_v2_to_v3_ddl`,
  the `ALTER TABLE execution_views ADD COLUMN` set above).
- The runner applies **every** step whose `from < current_version` in order:
  - **fresh DB** (no `schema_meta` row): apply the full chain to reach v3, then
    stamp version 3.
  - **v1 DB** (hypothetical): v1→v2 then v2→v3.
  - **v2 DB** (current production): v2→v3 only.
  - **v3 DB:** no-op.
- **Concurrent-start safety:** unchanged `BEGIN IMMEDIATE` write-lock discipline
  — the version read happens after the exclusive lock, a loser blocks on
  `busy_timeout` then observes the post-migration version. Whole chain commits in
  one transaction; any failure rolls back the entire chain (**rollback**).
- **Newer-version refusal:** `version > SCHEMA_VERSION` still raises
  `SchemaVersionError` (never silently downgraded).
- **Data preservation:** every step is additive (`ALTER TABLE ... ADD COLUMN`
  with defaults / new tables / new indexes). No existing evidence, registration,
  checkpoint, generation, corruption, lease, or view row is dropped or rewritten
  by DDL.
- **Legacy `FAILED`→`ERROR` correction is retained** — the idempotent
  `UPDATE read_model_state SET status='ERROR' WHERE status='FAILED'` still runs
  every startup, unchanged.

### 4.3 Startup migration must not scan evidence; async backfill instead

The migration adds columns but **must not** scan/replay evidence to populate
them (startup stays O(1) in evidence). Instead, upon applying `v2→v3`, mark every
repository's read model for the **existing lease-owned asynchronous rebuild**:
flip `read_model_state.status` from `READY` to `REBUILDING` (a one-time action
inside the v2→v3 step, not an evidence scan). The scheduler's existing
`_maybe_rebuild` then treats `REBUILDING` as urgent and runs a real
full-generation `rebuild_read_models` on its next tick, backfilling
`proxy_micro_usd`/tokens honestly from OK evidence, transitioning
`PREPARING`/`REBUILDING` → `READY` (or `ERROR` on failure). Rows that were not
`READY` (already `PREPARING`/`ERROR`/absent) are already scheduled for rebuild by
the existing logic and need no flip. Historical cost thus appears only once a
genuine complete snapshot has been rebuilt — never fabricated at startup.

### 4.4 Durability invariants preserved (unchanged, must not regress)

Lease-ownership checks on rebuild/publish/`mark_error`, generation rollover,
atomic publication, old-snapshot retention until the new one publishes,
event-loop responsiveness (writes stay on the off-thread worker), and bounded
per-tick work all remain exactly as they are. The cost feature adds columns and
read-side aggregation only; it introduces no new write path and no new lease
holder.

---

## 5. Dashboard placement (UI)

Built on the existing vanilla-JS page/component structure
(`static/js/pages/*`, `components/chart.js`, `format.js`), accessible and
theme-aware per DESIGN.md, matching the redesign's existing patterns.

- **Home (`pages/home.js`, `/api/overview`):** total observed proxy cost,
  observed average per completed issue, coverage disclosure, a **top-cost issues
  chart** plus an **accessible data table** equivalent (the chart is not the only
  representation) with **stable links** to each issue.
- **Repository Overview (`pages/repository-detail.js`,
  `/api/repositories/{id}/overview`):** total, completed-issue average, and
  coverage for that repository.
- **Issues list/detail (`pages/issues.js`):** sortable cost column, completeness
  indicator, and — on detail — **per-execution-attempt** cost breakdown. A
  **Partial** label is visible whenever completeness is `PARTIAL`; partial copy
  reads as an amount *observed*, e.g. **"$1.84 observed"**, never as a definitive
  total.
- **Runs list/detail (`pages/runs.js`):** aggregate proxy cost, completeness, and
  coverage for each run — on both the **Runs list** (per-run row) and **Run
  Detail**. Same copy/Partial rules.
- **Executions list/detail (`pages/executions.js` + execution detail):**
  per-execution cost and validity, on both the list and the detail view.
- **About & Safety (`pages/about.js`, `/api/about`):** a plain-language
  **"proxy, not invoice"** definition — the figure is engine-reported token usage
  priced at API list rates (basis `ENGINE_REPORTED_API_LIST_RATE_PROXY`), **not**
  a bill — and the **full exclusion list**: reviewer-LLM cost, validation compute,
  **orchestration cost** (the runtime's own coordinating compute), subscription
  fees, crashed-execution usage, and the excluded screens
  (Evidence/Search/Attention). "Missing cost is unknown, never zero."

**Copy rules:** `UNAVAILABLE` → an explicit "not observed"/"—" affordance, never
"$0.00". `PARTIAL` → "$X observed" + visible Partial label. `COMPLETE` → the
amount plainly. A metered valid `$0.00` is shown as `$0.00` (it is observed), not
as unavailable.

**Excluded screens:** the Evidence, Search, and Attention screens show **no**
cost affordance — consistent with the endpoint exclusion in §1.1/§3.3.

## 5a. Documentation

The design/decision record for this feature lives in a new
`docs/28-proxy-cost.md` (contract, decisions D1–D5, migration/backfill rationale,
compatibility statement). **`docs/27` stays frozen** — at most a single minimal
cross-reference line pointing to `docs/28`, added only if genuinely necessary for
discoverability; no other `docs/27` edits.

---

## 6. Acceptance criteria

1. `proxyCost` object present with the exact §3.1 shape and invariants on every
   endpoint in the §3.3 matrix; all existing fields unchanged (backward compat
   proven by the existing suite staying green).
2. Validation (§2.2/§2.3) unit-proven: bool/negative/non-finite dollars rejected;
   finite `>= 0` accepted; valid `0` metered; `Decimal(str())` + `ROUND_HALF_UP`
   conversion exact on adversarial values (e.g. `0.0000005`, `1.8400005`); tokens
   bool/negative/float rejected, non-negative int accepted; cost/token coverage
   independent.
3. Per-scope sums correct: execution, issue (all attempts incl. retries/
   rejections/validation failures), run, repository (current generation),
   global; duplicate/inconsistent terminal evidence never double-counted (D1).
4. Completeness (COMPLETE/PARTIAL/UNAVAILABLE incl. empty scope) correct; average
   per `DONE` issue correct, `null` when no `DONE` issues, dual coverage
   disclosed, "Observed average" when partial.
5. Migration: fresh→v3, v2→v3, and the ordered chain each verified; concurrent
   start safe; rollback on failure; newer-version refusal; data preserved;
   `FAILED`→`ERROR` retained; **no evidence scan at startup**; async rebuild
   backfills through PREPARING/REBUILDING/READY/ERROR.
6. Durability §4.4 invariants unregressed (existing crash/durability posture
   intact; no `src/runtime` file touched — dependency-carveout test stays green).
7. Cost sorting: UNAVAILABLE last in both directions, stable ID tie-break; lists
   remain bounded/paginated; aggregate cost is fixed-query-count per page.
8. UI placements all present, accessible (chart has a table equivalent + stable
   links), theme-aware, with the exact copy rules (§5) including the visible
   Partial label and "$X observed" wording:
   - **Home:** total, observed average, coverage, top-cost issues chart+table.
   - **Repository Overview:** total, completed-issue average, coverage.
   - **Issues list AND Issue Detail:** sortable cost, completeness, and a
     per-execution-attempt breakdown on detail.
   - **Runs list AND Run Detail:** aggregate proxy cost, completeness, coverage.
   - **Executions list AND Execution Detail:** per-execution cost and validity.
   - **About & Safety:** the "proxy, not invoice" definition plus the full
     exclusion list (reviewer / validation / **orchestration** / subscription /
     crashed-execution usage + Evidence/Search/Attention screens).
9. **Exclusions preserved:** Evidence, Search, and Attention endpoints/screens
   carry no `proxyCost` object (asserted by test).
10. Full `tests/unit tests/dashboard` suite green at every checkpoint; new
    behavior test-first. Index deferral (spec §4.1 / plan §5) is accepted **only
    if** a measured query-count/scale check passes; otherwise the needed index is
    added under the same migration.
11. Independent adversarial review: every real blocking/P0/P1/P2/Important
    finding is fixed **test-first**; a final handoff document is produced.
