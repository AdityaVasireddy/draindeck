# Todo: Dashboard Redesign

**Gate:** ADR-27 (`docs/08` §5i), `docs/27-dashboard-redesign-spec.md`, and this
version-controlled plan were explicitly approved 2026-08-23; local
checkpoint-commit authority resolved (authorized); browser automation proven
in Unit 0. See `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md` for evidence.

- [x] Unit 0 — Baseline, context loader, executable contract map, preflight
- [x] Unit 1 — Transactional SQLite v2 migration
- [x] Unit 2 — Lease-owned off-thread read models, containment generations, backfill/rebuild
- [x] Unit 3 — Attention detection history
- [x] Unit 4 — Bounded query layer and aggregates
- [x] Unit 5 — Search and additive REST routes
- [x] Unit 6 — Stable UI routing and security preservation
- [x] Unit 7 — Design tokens, shell, themes, shared primitives
- [x] Unit 8 — API client, SSE, focus-safe keyed reconciliation
- [x] Unit 9 — Home, repositories, registration, repository overview
- [x] Unit 10 — Attention Center and global search
- [x] Unit 11 — Runs and Issues explorers/details/timelines/topology
- [x] Unit 12 — Executions, transcript, and diff workspace
- [x] Unit 13 — Evidence explorer/detail and visual analytics
- [x] Unit 14 — About & Safety, exhaustive states, responsive hardening
- [x] Unit 15 — Scale, security, full suites, real-browser acceptance
- [x] Unit 16 — Independent reviews, remediation, final documentation/handoff

## Definition-of-done evidence

- [x] No file under `src/runtime` changed
- [x] Existing API/SSE/artifact/security contract tests pass
- [x] SQLite v1→v2 migration and projection parity pass
- [x] All new list/search/topology operations are bounded; evidence uses keysets and offsets are capped
- [x] Normal TORN→OK repair is incremental; unsafe OK mutation rebuild is lease-owned/off-thread —
      closed this session: `scheduler._maybe_rebuild` submits `rebuild_read_models` via the
      lease-owned worker (`self._worker.submit`) on generation rollover/catch-up/unsafe-mutation,
      preserving atomic BEGIN IMMEDIATE/COMMIT publication and lease-loss protection; see the
      2026-08-23 evidence log entry.
- [x] Migration/backfill is concurrent-start safe and does not block the ASGI event loop
- [x] Maximum 2,000-record tick persistence runs on the lease-owned worker without event-loop stall —
      measured this session with `tests/dashboard/scale/measure_event_loop_responsiveness.py`
      Scenario B (4 x 500-row page-persist jobs on a real `ReadModelWorker`, matching indexer.py's
      real per-page `await persist(...)` shape): job elapsed 12.6-12.8ms, max event-loop probe gap
      22-26ms (budget 50ms), PASS both runs.
- [x] Lease acquire/renew writes use the same off-thread worker with priority scheduling and cannot
      block the ASGI loop or starve behind page/backfill jobs — measured this session with the same
      script's Scenario A (concurrent 100,000-row `rebuild_read_models` full-generation rebuild, the
      worst case: one un-chunked BEGIN IMMEDIATE/COMMIT transaction on the worker thread) and
      Scenario B: max lease-renewal submit-to-complete latency 0.004-0.127s against a 5s budget
      (half the 10s TTL) and a 2s heartbeat cadence, both runs. Max event-loop gap during the 100k
      rebuild: 28-39ms (budget 50ms), PASS both runs.
- [x] Python artifact tests open UTF-8 text/JSON explicitly rather than relying on the Windows default encoding
- [x] Unregister removes every v2 Dashboard-owned row
- [x] No raw evidence/payload or unsafe DOM rendering is exposed
- [x] Every approved route and non-ideal state is implemented — `INDEX_PREPARING`/stale-rebuilding
      is now wired end-to-end: `check_read_model_readiness`/`projection_state_summary` gate
      list/detail APIs, the frontend renders the Preparing panel/stale and projection-incomplete
      banners, and the LEASE_UNCLAIMED 10-second no-startup-flash gate is enforced; see the
      2026-08-23 evidence log entry.
- [x] WCAG 2.2 AA keyboard/unobscured-focus/contrast/resize/reflow/reduced-motion/theme checks pass —
      keyboard/focus/contrast/theme checks extensively live-verified (this session added: tablist
      roving-tabindex/arrow-key/Home/End on the execution artifact viewer, Item 8; keyboard-only Tab
      traversal + focus-not-obscured-by-sticky-utility-bar re-verified live). Resize/reflow at
      320/768px live-verified this session via a local CSP-relaxing reverse-proxy + iframe harness
      (frame-ancestors 'none' otherwise blocks all iframe-based viewport testing) against the real
      running app: no horizontal overflow at 320/768/1024/1440px or 200% text resize, table
      wrappers scroll independently via their own overflow-x:auto. `prefers-reduced-motion` verified
      by live rule-injection test (base.css's global animation/transition kill rule, forced
      unconditionally, produced no visual regression) plus code review; `forced-colors: active`
      verified by code review only (`.chart-bar` System Colors override) — true browser-level
      forced-colors media-feature emulation was not achievable via available automation tooling this
      session (DevTools/F12 does not open in this browser-automation context; no CDP Emulation
      domain access; OS-level high-contrast toggling is out of scope as a system-settings change).
- [x] Forest/night surface focus, eight-color chart ramps, visible collapsed-nav labels, and WCAG 1.4.13 checks pass
- [x] Browser checks pass at 320, 768, 1024, 1440 CSS px and 200% text resize — `resize_window`
      remains unreliable in this session, so this session used a different reliable browser
      mechanism instead (a local CSP-relaxing reverse-proxy + fixed-width iframe harness, since
      `frame-ancestors 'none'` otherwise blocks iframe-based viewport testing): all four breakpoints
      and 200% root-font-size resize verified against the real running app with no horizontal
      overflow at the `<html>` level; the Issues table's own wrapper correctly scrolls
      independently via `overflow-x:auto` rather than forcing page-level horizontal scroll.
- [x] Scale fixture meets documented query/latency budgets
- [x] Focus/scroll survive targeted SSE updates — closed this session: `app.js`'s `onInvalidate` now
      calls each page's `refresh` (not `render`), and all 7 list pages use `syncList`; `syncList`
      also skips repositioning a focused row (`insertBefore` blurs even a pure reposition).
      Live-verified against the real running app via direct `changes`-table inserts plus
      DOM-attribute instrumentation: focus, active element, scroll position, and row DOM-node
      identity all survive a real SSE-triggered refresh; see the 2026-08-23 evidence log entry.
- [x] Dashboard suite passes (361/361)
- [x] Combined unit+Dashboard suite passes (921/921)
- [ ] Independent contract, security, accessibility/visual, and quality reviews close all P0/P1/P2
      findings — reviews ran and 8 real defects were fixed test-first and live-verified; 6 findings
      were evaluated and explicitly deferred with rationale (see Unit 16's evidence log entry), not
      all closed.
- [x] Final docs, screenshots, measurements, and exact test evidence are recorded
- [x] Authorized per-unit local commits, working tree, and no-merge/no-push state are reported

## Implementation evidence log

Add dated, concise command/result entries here during build-auto; do not pre-check items based on intent.
