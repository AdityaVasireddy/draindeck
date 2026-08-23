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
- [ ] Unit 16 — Independent reviews, remediation, final documentation/handoff

## Definition-of-done evidence

- [ ] No file under `src/runtime` changed
- [ ] Existing API/SSE/artifact/security contract tests pass
- [ ] SQLite v1→v2 migration and projection parity pass
- [ ] All new list/search/topology operations are bounded; evidence uses keysets and offsets are capped
- [ ] Normal TORN→OK repair is incremental; unsafe OK mutation rebuild is lease-owned/off-thread
- [ ] Migration/backfill is concurrent-start safe and does not block the ASGI event loop
- [ ] Maximum 2,000-record tick persistence runs on the lease-owned worker without event-loop stall
- [ ] Lease acquire/renew writes use the same off-thread worker with priority scheduling and cannot block the ASGI loop or starve behind page/backfill jobs
- [ ] Python artifact tests open UTF-8 text/JSON explicitly rather than relying on the Windows default encoding
- [ ] Unregister removes every v2 Dashboard-owned row
- [ ] No raw evidence/payload or unsafe DOM rendering is exposed
- [ ] Every approved route and non-ideal state is implemented
- [ ] WCAG 2.2 AA keyboard/unobscured-focus/contrast/resize/reflow/reduced-motion/theme checks pass
- [ ] Forest/night surface focus, eight-color chart ramps, visible collapsed-nav labels, and WCAG 1.4.13 checks pass
- [ ] Browser checks pass at 320, 768, 1024, 1440 CSS px and 200% text resize
- [ ] Scale fixture meets documented query/latency budgets
- [ ] Focus/scroll survive targeted SSE updates
- [ ] Dashboard suite passes
- [ ] Combined unit+Dashboard suite passes
- [ ] Independent contract, security, accessibility/visual, and quality reviews close all P0/P1/P2 findings
- [ ] Final docs, screenshots, measurements, and exact test evidence are recorded
- [ ] Authorized per-unit local commits, working tree, and no-merge/no-push state are reported

## Implementation evidence log

Add dated, concise command/result entries here during build-auto; do not pre-check items based on intent.
