# Review disposition — Dashboard redesign planning findings

**Date:** 2026-08-22<br>
**Reviewed against:** baseline `4052fef`, `src/draindeck_dashboard`, runtime containment projection, ADR-25/26, `CLAUDE.md`, and the six redesign artifacts<br>
**Result:** 26 findings accepted, 1 accepted with a factual narrowing, and 1 split (one claim rejected, one unrelated claim accepted)

This record captures the disposition of Claude Code's pre-approval report. It
is not implementation evidence and does not accept ADR-27.

| # | Disposition | Document correction |
|---|---|---|
| 1 | Accepted with narrowing | Normal append repair is specifically tail `TORN → OK`; it is incremental when the new event is monotonic. `MALFORMED → OK` is not assumed normal and receives the same projectability check. Previously-OK mutation/non-monotonic evidence rebuilds. |
| 2 | Accepted | Large scans/rebuilds and new aggregate reads move off the ASGI event loop onto bounded thread work with dedicated/short-lived SQLite connections; server responsiveness is an acceptance budget. The approved evidence envelope is 100k+ total, not necessarily 2M, but the blocking risk is real. |
| 3 | Accepted | Startup migration is DDL-only and SQLite-serialized; backfill/rebuild begins only after lease acquisition, rechecks ownership before atomic publish, and discards work on lease loss. |
| 4 | Accepted | SSE `entityType` is explicitly extensible with `attention`, `repository_health`, and `read_model`; system events use repository 0. Visible time-derived attention also refreshes every 30 seconds. |
| 5 | Accepted | `Pending reconciliation`, TORN tails, and `no controlled finish observed` were removed from Attention. They remain entity facts without an alarm inference. |
| 6 | Accepted | Added surface-aware `focus-on-dark`, light/dark field-border tokens, exact contrast requirements, and updated components. Divider rules are no longer the sole interactive boundary. |
| 7 | Accepted | WCAG claim now includes 320 CSS pixel non-tabular reflow. Desktop/tablet remains the product target; narrow reflow is accessibility behavior, not a mobile feature set. |
| 8 | Accepted | Migration/plan now includes `repositories.py`; unregister transaction removes all v2 projection, containment, readiness, and attention rows. |
| 9 | Accepted | Existing scoped evidence remains oldest-first. The new UI explicitly requests newest order or uses the keyset endpoint. |
| 10 | Accepted | `repoId` is documented as a positive integer; existing invalid path values keep FastAPI's 422 shape. Only syntactically valid missing resources receive 404. Entity IDs remain opaque/bounded strings. |
| 11 | Accepted | `/api/executions?groupBy=execution|issue` now has two defined pagination-correct response modes; issue mode paginates groups server-side. |
| 12 | Accepted | Global search now includes evidence metadata identifiers only; no raw content is searched. |
| 13 | Accepted | Home recent activity is specified and sourced from newest-first cross-repository evidence metadata. |
| 14 | Accepted | Added a closed kind→severity→message→target table. v2 defines no informational attention kind but keeps the enum additive. |
| 15 | Accepted | Replaced scalar containment with `containment_views` keyed by execution and containment generation; exact state is `UNCONFIRMED`, while the event remains `ExecutionTerminationUnconfirmed`. |
| 16 | Accepted | New evidence explorer uses keyset pagination; new offset endpoints cap at 10,000 and legacy scoped evidence receives an explicit ADR-27 safety ceiling of 100,000 while retaining order/shape. |
| 17 | Accepted | Cross-repository reads must join current checkpoints, and rollover prunes old derived rows while preserving source evidence. |
| 18 | Accepted | Routing mechanism is explicit: API first, `/assets` mount, legacy asset compatibility, approved UI-route allowlist, no root StaticFiles catch-all. |
| 19 | Accepted | Bookmark stability is scoped to the same Dashboard DB and current generation; `evidenceId` remains a Dashboard row ID and cursor remains opaque. |
| 20 | Accepted | Charts/topology may use external classes or validated SVG presentation attributes only; no inline style/script/style blocks or dynamic style strings. |
| 21 | Accepted | UI page/pageSize mapping and bounds are explicit; evidence URLs use keyset IDs. |
| 22 | Accepted | Focus Not Obscured is explicit, with scroll padding/margins and sticky-plane browser tests. |
| 23 | Accepted | Added fixed light/dark categorical chart palettes plus mandatory labels/symbols/patterns/text equivalents. |
| 24 | Accepted | Proposed ADR-27 is now recorded in `docs/08` §5i; docs/27 remains its normative detailed contract. |
| 25 | Accepted | `.gitignore` now tracks only `tasks/plan.md` and `tasks/todo.md`; durable evidence also lives in tracked `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`. |
| 26 | Accepted | One-go build remains possible only as a series of runnable, test-green local checkpoint commits with `NEXT.md`/evidence updates. Explicit commit-series authority is required before mutation; merge/push remain separate. Context exhaustion has a unit-boundary resume protocol. |
| 27 | Accepted | Unit 0 must prove callable real-browser automation before source changes; absence is an early stop, not a Unit 15 surprise. |
| 28 | Split | `PRODUCT.md`'s `## Register` / `product` is required Impeccable metadata and is not a scaffolding stub, so it remains. `CLAUDE.md`'s stale counts/current task were valid and were updated. |

## Approval impact

The corrected proposal has three approval gates: proposed ADR-27 in docs/08
§5i, the detailed docs/27 contract, and the tracked tasks plan. The user's
implementation authorization must also explicitly decide whether Claude Code
may create the bounded local per-unit checkpoint commits required by the plan.
No approval grants merge, push, or `src/runtime` authority.
