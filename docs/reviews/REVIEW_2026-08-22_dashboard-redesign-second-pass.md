# Review disposition — Dashboard redesign second pass

**Date:** 2026-08-22<br>
**Result:** R1–R7 accepted; lease severity decided deliberately

| Finding | Disposition and correction |
|---|---|
| R1 | Accepted. Focus is surface-aware: light paper uses `#006E75`; forest/night surfaces use `#6EDAE0` in either theme. The rail therefore clears 3:1. |
| R2 | Accepted. Recent activity uses global `evidenceId DESC`, the same stable keyset order as `/api/evidence`; `stored_at` is not treated as immutable arrival time. |
| R3 | Accepted. Both chart themes now define all eight positions, covering seven controlled outcomes plus the no-finish observation. |
| R4 | Accepted. Dedicated chart sequences alternate luminance, retain direct labels/patterns/table equivalents, and collapse overflow into labelled “Other.” |
| R5 | Accepted. Schema version is read only after `BEGIN IMMEDIATE`; a concurrent follower acquires the lock and then observes the committed version. |
| R6 | Accepted. Observer fetch remains bounded at 500 records/page and four pages/tick; each page's evidence/upsert/incremental projection/attention transaction runs on the lease-owned off-thread write worker, not the ASGI loop. |
| R7 | Accepted. Collapsed navigation retains short visible labels; no tooltip is load-bearing. Any supplementary custom tooltip must be dismissible, hoverable, and persistent under WCAG 1.4.13. |

## Lease severity decision

`LEASE_STALE` is critical because it invalidates freshness across the entire
Dashboard. `LEASE_UNCLAIMED` becomes a warning only after one full 10-second
lease TTL has elapsed since Dashboard observation, avoiding a startup flash
while still surfacing persistent lack of an indexer. Both are system-scoped
and their timestamps remain explicitly Dashboard detection times.
