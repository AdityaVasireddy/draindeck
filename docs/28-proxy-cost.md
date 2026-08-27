# Doc 28 — Coding-Engine Proxy Cost (Dashboard)

**Status:** Implemented on branch `dashboard-engine-proxy-cost` (baseline clean
`master` `0bb1629`). Design/decision record for the feature specified in
`spec/coding-engine-proxy-cost.md`. `docs/27` stays frozen; this doc is the
governing record for proxy cost.

## 1. What it is

The Dashboard surfaces the coding engine's **proxy cost** — engine-reported
token usage priced at API list rates, already recorded in
`ExecutionFinished.payload.usage.dollars` (doc 03) — at every aggregation level
(execution, issue, run, repository, global). Read-side/presentation only: no
`src/runtime` change, no event-schema change, no transcript parsing, no
dependency installs.

**Proxy, not invoice.** `basis = "ENGINE_REPORTED_API_LIST_RATE_PROXY"`, stated
permanently in the API and on About & Safety. **Excluded and unknowable:**
reviewer-LLM cost, validation compute, **orchestration cost** (the Draindeck
runtime's own coordinating compute — orchestrator loop, Git operations,
recovery), subscription fees (ADR-18 Pro subscription), and usage from crashed
executions that never emitted a terminal `ExecutionFinished`. **Missing cost is
unknown, never zero.** Not surfaced on Evidence, Search, or Attention.

## 2. Metric (authoritative summary; spec §2 is the full contract)

- **Per execution:** captured from `usage` at the single *accepted*
  `ExecutionFinished` transition in `projections.py` (`_capture_usage`). A
  duplicate/out-of-order second finish never reaches that point, so cost is
  never double-counted — **decision D1**.
- **Validation:** `usage.dollars` → integer micro-USD via
  `Decimal(str(value)) * 1_000_000` with `ROUND_HALF_UP`; reject bool/negative/
  non-finite; accept finite `>= 0`; a valid `0` is metered. Tokens: non-negative
  int only (never bool). Cost and token coverage are **independent**. Dollars are
  never inferred from tokens or vice versa.
- **Aggregation:** issue = every attempt (retries/rejections/failures); run = by
  run id; repository/global = current identity generation only; only OK evidence.
- **Completeness:** COMPLETE (all metered) / PARTIAL (some) / UNAVAILABLE (none;
  also the empty scope). Partial UI copy reads "$X observed" with a visible
  **Partial** label.
- **Average per completed issue:** denominator = issues in exact state `DONE`;
  numerator = their executions' summed cost; `null` when no `DONE` issues (and
  when none of their executions carry cost — unknown, never $0.00); both
  coverages disclosed; **"Observed average"** label when partial.

## 3. Decisions

- **D1 — capture point / no double count.** Cost is read only at the single
  accepted `ExecutionFinished` transition. An execution later flagged
  `inconsistent` by a *duplicate* retains its first captured cost (the duplicate
  is discarded, not additive) — approved; discarding real metered signal would
  under-count.
- **D2 — tokens_valid requires both.** An execution meters tokens only when both
  `input_tokens` and `output_tokens` are valid — one per-execution token-metered
  notion, matching the single `tokenMeteredExecutions` count in the API shape.
- **D3 — storage grain.** Cost stored per execution in `execution_views`;
  issue/run/repo/global figures are computed by SQL aggregation, never stored
  redundantly (single source of truth).
- **D4 — async backfill, no startup scan.** The v2→v3 migration adds columns and
  flips `READY`→`REBUILDING` once; the existing lease-owned async rebuild
  backfills historical cost through PREPARING/REBUILDING/READY/ERROR.
- **D5 — additive API only.** `proxyCost`/average objects are new keys; no
  existing field changed. Backward compatibility is proven by the existing suite
  staying green.

## 4. Storage & migration

`execution_views` gains 5 columns: `proxy_micro_usd INTEGER` (nullable),
`cost_valid INTEGER NOT NULL DEFAULT 0`, `input_tokens INTEGER`,
`output_tokens INTEGER`, `tokens_valid INTEGER NOT NULL DEFAULT 0`.

`migrations.py` is now a real ordered chain (`_MIGRATIONS`): `SCHEMA_VERSION = 3`;
fresh DB applies the whole chain, a v2 DB applies only `v2→v3`. Preserved:
`BEGIN IMMEDIATE` concurrent-start safety, whole-chain rollback on failure,
newer-version refusal (`SchemaVersionError`), data preservation (additive DDL),
and the legacy `FAILED`→`ERROR` correction. Startup never scans evidence; the
`READY`→`REBUILDING` flip is one-time (inside the `v2→v3` step) and is not
re-applied on a later restart of an already-v3 database.

Durability invariants unchanged: lease ownership on rebuild/publish/`mark_error`,
generation rollover, atomic publication, old-snapshot retention, event-loop
responsiveness (writes stay on the off-thread worker), bounded per-tick work.

## 5. API — the `proxyCost` object

Additive on execution / issue / run / repository / global responses (spec §3.3):

```jsonc
proxyCost: {
  basis: "ENGINE_REPORTED_API_LIST_RATE_PROXY",
  observedMicroUsd: 1840000 | null, observedUsd: "1.840000" | null,
  completeness: "COMPLETE" | "PARTIAL" | "UNAVAILABLE",
  meteredExecutions, totalExecutions, missingCostExecutions,
  inputTokensObserved: 41200 | null, outputTokensObserved: 9800 | null,
  tokenMeteredExecutions
}
```

Plus `averageProxyCostPerCompletedIssue` (Home / repo overview) and
`topCostIssues` (Home). Lists stay bounded/paginated; per-page cost is a
fixed-query-count batched aggregate (`by_group_proxy_cost`). Cost sort places
UNAVAILABLE last in both directions with a stable id tie-break
(`cost_order_by`). Evidence/Search/Attention carry no `proxyCost`.

## 6. Placement (UI)

Home (total, observed average, coverage, top-cost chart + accessible table +
stable links), Repository Overview (total, average, coverage), Issues list +
Issue Detail (sortable cost, completeness, per-attempt breakdown), Runs list +
Run Detail, Executions list + Execution Detail, About & Safety (proxy-not-invoice
definition + full exclusion list). Copy: UNAVAILABLE → "Not observed" (never
$0.00); PARTIAL → "$X observed" + Partial label; metered $0.00 → "$0.00".

## 7. Verification (this build)

- Combined `tests/unit tests/dashboard` green (560 unit unchanged +
  495 dashboard); dependency-carveout green (no `src/runtime` touched).
- Scale/index-deferral measurement (`tests/dashboard/scale/measure_proxy_cost.py`,
  20 repos / 1k issues / 10k executions / 100k evidence): every cost aggregate
  ≤ ~7 ms against a 500 ms budget on the existing indexes — **index deferral
  stands**, no new index added.
- Live browser verification and six-axis review: Units 7–8.

Files: `proxy_cost.py`, `proxy_cost_agg.py`, `projections.py`, `migrations.py`,
`read_models.py`, `api_queries.py`, `views.py`, `app.py`, and
`static/js/{format.js, pages/*}`.
