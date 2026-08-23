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
- [ ] Normal TORN→OK repair is incremental; unsafe OK mutation rebuild is lease-owned/off-thread —
      NOT fully closed: `rebuild_read_models()` (the "unsafe OK mutation" rebuild primitive) is
      confirmed unreachable from any production code path (Units 15/16). The incremental path's own
      docstring claims it handles this safely by construction regardless, but this is an unresolved
      discrepancy against docs/27 SS8.4's specific wording, not adjudicated this session — see Unit
      16's evidence log entry.
- [x] Migration/backfill is concurrent-start safe and does not block the ASGI event loop
- [ ] Maximum 2,000-record tick persistence runs on the lease-owned worker without event-loop stall —
      not independently re-instrumented/re-measured this session (Unit 15 measured post-seed query
      latency, not live event-loop responsiveness during an active backfill tick); see Unit 2's
      original implementation evidence for its structural basis.
- [ ] Lease acquire/renew writes use the same off-thread worker with priority scheduling and cannot
      block the ASGI loop or starve behind page/backfill jobs — same caveat as above, not
      re-instrumented this session.
- [x] Python artifact tests open UTF-8 text/JSON explicitly rather than relying on the Windows default encoding
- [x] Unregister removes every v2 Dashboard-owned row
- [x] No raw evidence/payload or unsafe DOM rendering is exposed
- [ ] Every approved route and non-ideal state is implemented — the `INDEX_PREPARING` staleness
      state (docs/27 §3.2 decision 9) is a real, confirmed gap: unwired end-to-end (Unit 16).
- [ ] WCAG 2.2 AA keyboard/unobscured-focus/contrast/resize/reflow/reduced-motion/theme checks pass —
      keyboard/focus/contrast/theme checks extensively live-verified; resize/reflow at 320/768px and
      a live reduced-motion/forced-colors toggle were NOT independently verified (tooling limitation,
      not a known defect beyond the forced-colors CSS bug found and fixed in Unit 16).
- [x] Forest/night surface focus, eight-color chart ramps, visible collapsed-nav labels, and WCAG 1.4.13 checks pass
- [ ] Browser checks pass at 320, 768, 1024, 1440 CSS px and 200% text resize — 1024/1440 verified
      live repeatedly; 320/768px and 200% text resize NOT independently verified this session (the
      `resize_window` automation tool does not reliably change the tab's actual viewport in this
      session, confirmed repeatedly across Units 9-15).
- [x] Scale fixture meets documented query/latency budgets
- [ ] Focus/scroll survive targeted SSE updates — only partially true: `syncList` (built for exactly
      this) is used by 2 of 7 list pages; the other 5 do a full clear+rebuild on every SSE
      invalidation (Unit 16 code-quality finding, not fixed this session).
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
