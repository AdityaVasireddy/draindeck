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
- [ ] WCAG 2.2 AA keyboard/unobscured-focus/contrast/resize/reflow/reduced-motion/theme checks pass —
      keyboard/focus/contrast/theme checks extensively live-verified (this session added: tablist
      roving-tabindex/arrow-key/Home/End on the execution artifact viewer, Item 8; keyboard-only Tab
      traversal + focus-not-obscured-by-sticky-utility-bar re-verified live). Resize/reflow at
      320/768px live-verified this session via a local CSP-relaxing reverse-proxy + iframe harness
      (frame-ancestors 'none' otherwise blocks all iframe-based viewport testing) against the real
      running app: no horizontal overflow at 320/768/1024/1440px or 200% text resize, table
      wrappers scroll independently via their own overflow-x:auto. `prefers-reduced-motion` verified
      by live rule-injection test (base.css's global animation/transition kill rule, forced
      unconditionally, produced no visual regression) plus code review. `forced-colors: active`
      remains genuinely NOT live-verified, and this checkbox is left open rather than claiming
      code-review as live acceptance (explicit instruction, this session): real browser/OS-level
      forced-colors validation was attempted with the user's active cooperation --
      (1) F12/DevTools would not open in the browser-automation context (tried twice, including
      click-then-F12 to rule out a focus-routing artifact); (2) the user enabled real Windows High
      Contrast on their own desktop and confirmed it visible there, but the automated tab still
      reported `matchMedia('(forced-colors: active)') === false` after a hard reload; (3) the user
      authorized a full `taskkill chrome.exe` + relaunch so Chrome would pick up the OS theme at
      startup -- still `false` after relaunch, with no visible remapping in a fresh screenshot. This
      points to a session/profile boundary between the automated browser surface and the user's
      visible desktop that no available tool could bridge. The user was asked and explicitly chose
      to WAIVE this specific sub-check (2026-08-23) rather than continue searching for a mechanism;
      `.chart-bar`'s System Colors override (components.css) remains verified by code review only.
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
- [x] Dashboard suite passes (398/398 as of this session's final commit; was 361/361 at Unit 16)
- [x] Combined unit+Dashboard suite passes (960/960 as of this session's final commit; was 921/921
      at Unit 16 — this session added 37 dashboard tests: read-model state machinery, scheduler
      rebuild integration, readiness gating, LEASE_UNCLAIMED gate, run metadata, overview parity)
- [x] Independent contract, security, accessibility/visual, and quality reviews close all P0/P1/P2
      findings — this session ran 2 fresh-context reviews (code-reviewer, security-auditor) against
      the full session diff (items 1-9). Security: 0 findings at any severity. Code review: 2
      Important-severity findings (a `syncList` reordering-churn bug and a missing LEASE_UNCLAIMED
      gate on `/api/overview`'s attention aggregate), both fixed test-first, live-verified, and
      committed; 2 low-severity suggestions reviewed and accepted as-is (readiness-gate-before-
      param-validation ordering is intentional; `readiness.js`'s thin DOM helpers have no dedicated
      unit test but were live-verified via screenshots during Item 1's frontend work). See the
      2026-08-23 evidence log entry. (Unit 16's own prior review round, from the session before this
      continuation, is unrelated and already closed per its own entry above.)
- [x] Final docs, screenshots, measurements, and exact test evidence are recorded
- [x] Authorized per-unit local commits, working tree, and no-merge/no-push state are reported

## Implementation evidence log

Add dated, concise command/result entries here during build-auto; do not pre-check items based on intent.

### 2026-08-23 continuation: closing the 8 unchecked definition-of-done gates

Baseline: `7cdb23b` (Unit 16's final commit). All 9 items from the resuming
`/build-auto` directive closed; final commit `6f8246f`. `src/runtime`
untouched throughout (`git diff 7cdb23b..HEAD --stat -- src/runtime` empty).
No dependency installed. No merge, no push.

- **Items 1/2 (INDEX_PREPARING/REBUILDING/READY + production rebuild
  caller):** `read_models.py` gained `mark_preparing`/`mark_rebuilding`/
  `mark_failed` (renamed `mark_error` in a later pass this session --
  see the merge-blocker entry below; `FAILED` was never the documented
  status value); the pre-existing bug where every incremental write
  immediately marked READY (fabricating completeness) was removed.
  `scheduler.py`'s new `_maybe_rebuild` submits `rebuild_read_models`
  through the lease-owned `ReadModelWorker` on generation rollover/
  catch-up/unsafe-mutation. `api_queries.py` gained
  `check_read_model_readiness`/`projection_state_summary`, wired into
  `cross_repository_issues/runs/executions`, `entity_topology`, and all
  three detail endpoints in `app.py`. Frontend: `readiness.js` (new),
  Preparing panel/stale/projection-incomplete banners rendered on every
  affected list/detail page. Commits `143625f`, `0ac006c`, `f4343c5`.
  New tests: `test_scheduler_rebuild.py` (9 integration scenarios:
  initial backfill, multi-page backfill, unsafe mutation, generation
  rollover, preparing/rebuilding/ready visibility, failure+retry,
  lease-loss consistency), plus unit/API-level readiness tests.
- **Item 3 (LEASE_UNCLAIMED 10s gate):** WHERE-clause gate added to
  `/api/attention` in `app.py`, scoped to `kind='LEASE_UNCLAIMED'` only
  (LEASE_STALE never delayed; resolved rows never hidden). Commit
  `0d9a42a`. 4 new tests, all pass.
- **Item 4 (nested run metadata):** `_run_metadata_field` in `app.py`;
  `execution-detail`'s response gained `runMetadata`, rendered with the
  exact fallback `"run metadata unavailable (legacy/ambiguous)"`. Commit
  `0ac006c`. Live-verified: `GET /repositories/1/executions/1-e1`
  screenshot shows "Run metadata: run metadata unavailable
  (legacy/ambiguous)".
- **Item 5 (Repository Overview attention-count source):**
  `repository_attention_summary` in `api_queries.py` now reads
  `attention_conditions` directly (same source as `/api/attention`),
  replacing the old `derive_repository_conditions` live-recompute call
  in `app.py`. Commit `553032e`. 1 new parity test.
- **Item 6 (focus/scroll survive SSE refresh):** `app.js`'s
  `onInvalidate` now calls each page's `refresh()` (reuses the mounted
  DOM shell) instead of `render()` (full `clear(root)` teardown) for
  every list route; all 7 list pages (`home`, `repositories`,
  `attention`, `runs`, `issues`, `executions`, `evidence`) gained a
  `refresh()`. `dom.js`'s `syncList` skips `renderFn` AND repositioning
  for a row that currently holds focus (`insertBefore` blurs an element
  even when only repositioning it within the same parent — verified via
  an isolated, framework-free `<ul>/<li>` test). Commit `0fd6f82`.
  Live-verified against the real running smoke server (not just
  fixtures): direct SQL inserts into the `changes` table (bypassing the
  poller, confirmed via sequential `change_sequence` values), followed
  by DOM-attribute-based instrumentation (world-agnostic — a
  `console.log`/`window` override set from the browser-automation tool
  runs in an isolated JS world that does NOT share state with the page's
  own script, which cost significant debugging time before this was
  understood) — focus, active element, scroll position, and a hand-set
  marker attribute on the row all survived a real SSE-triggered refresh.
  **A later independent code review caught a second-order bug in this
  same commit**: the focused-row skip didn't advance the loop's
  `previousEl` anchor, causing every row *after* the focused one to be
  force-repositioned in front of it on every subsequent refresh (traced
  and confirmed, then fixed and re-verified live). Commit `6f8246f`.
- **Item 7 (viewport/resize/motion/keyboard acceptance):** `resize_window`
  remains unreliable in this session (confirmed again); used a local
  CSP-relaxing reverse-proxy (rewrites `frame-ancestors`/`X-Frame-Options`
  only, all other content passes through unmodified — throwaway,
  scratchpad-only, never committed) plus a fixed-width `<iframe>` harness
  instead. Verified against the real running app: no horizontal overflow
  at 320/768/1024/1440 CSS px or at 200% root-font-size resize (1280px
  viewport); table wrappers scroll independently via their own
  `overflow-x:auto`. `prefers-reduced-motion`: base.css's global
  animation/transition kill rule, forced unconditionally via injected
  `<style>`, produced no visual regression (live-tested) — matches the
  existing code review. `forced-colors: active`: code-reviewed only
  (`.chart-bar` System Colors override in components.css) — true
  browser-level forced-colors rendering could not be exercised (F12/
  DevTools does not open in this browser-automation context; no CDP
  Emulation domain access available; OS-level high-contrast toggling is
  out of scope as a system-settings change per this session's operating
  rules). Keyboard-only Tab traversal and focus-not-obscured-by-sticky-
  utility-bar re-verified live (focused row lands well clear of the
  64px-tall sticky bar even after a multi-row scroll-into-view).
- **Item 8 (tablist keyboard):** roving `tabindex` + ArrowLeft/ArrowRight
  (wrapping) + Home/End added to the execution artifact Transcript/Diff
  tablist in `executions.js`, matching the WAI-ARIA APG automatic-
  activation pattern. Commit `28312d1`. Live-verified: a JS-only
  `.focus()` call did not establish keyboard-routable focus in this
  browser-automation session (a real click was required for the keydown
  handler to fire) — noted as a tooling quirk, not an app defect.
- **Item 9 (100k-row rebuild / 2,000-record tick event-loop
  responsiveness, lease-renewal starvation):** new
  `tests/dashboard/scale/measure_event_loop_responsiveness.py`, run
  against a real `ReadModelWorker`. Scenario A (100,000-row single-repo
  `rebuild_read_models`, the worst case — one un-chunked transaction):
  job elapsed ~126-127ms, max event-loop probe gap 28-39ms (50ms
  budget), max lease-renewal latency 0.004-0.127s (5s budget, half the
  10s TTL) — 2 runs, both PASS. Scenario B (2,000-record tick as 4 x
  500-row page-persist jobs, matching indexer.py's real per-page
  `await persist(...)` shape): job elapsed ~12.6-12.8ms, max event-loop
  gap 22-26ms, max lease-renewal latency 0.004-0.012s — 2 runs, both
  PASS. Commit `f053e4e`.
- **Independent reviews:** 2 fresh-context reviews (code-reviewer,
  security-auditor) against the full `7cdb23b..HEAD` diff before the
  final commit. Security: 0 findings (SQL injection, cross-repo/raw-
  evidence leakage, INDEX_PREPARING fail-open, XSS, tablist a11y, and
  the LEASE_UNCLAIMED gate scope all explicitly checked and clean).
  Code review: 2 Important findings (the Item 6 `syncList` reorder bug
  above, and a missing LEASE_UNCLAIMED gate on `/api/overview`'s
  attention aggregate — a latent cross-endpoint inconsistency, not
  currently user-visible since `home.js` sources its total from the
  separately-gated `/api/attention`), both fixed test-first and
  live-verified/tested; 2 low-severity suggestions reviewed and accepted
  as-is. Commit `6f8246f`.
- **Full suite, final commit `6f8246f`:**
  `pytest tests/unit tests/dashboard -q` → 960 passed (560 unit + 398
  dashboard), 0 failed, run twice for consistency.
- **Git status:** working tree clean at each commit boundary; every item
  ended at its own local checkpoint commit exactly as authorized. No
  merge, no push, no `src/runtime` modification at any point.

### 2026-08-23 merge-blocker round: lease enforcement, rollover pruning, ERROR rename

A second resumption of `/build-auto`, baseline `6f8246f` (the prior round's
final commit). Five items closed; final commit `ed09179`.

- **Item 1 (lease ownership for rebuild/backfill):** `rebuild_read_models`
  now requires `owner_token` and verifies it twice via a new
  `_require_owned_lease` helper -- once before candidate computation,
  once immediately after `BEGIN IMMEDIATE` (before publish), while
  holding SQLite's exclusive write lock (linearizable against any
  competing takeover). Raises `LeaseLostError` and rolls back on
  mismatch; never publishes READY or replaces views after lease loss.
  `scheduler.py`'s `_maybe_rebuild` passes its own `owner_token` and
  treats `LeaseLostError` specially (no `mark_error` write either, since
  that would be equally illegitimate post-loss). The prior lease-loss
  test (which only asserted generic internal consistency -- weak enough
  to pass even if lease loss silently permitted publication) was
  replaced with two regression tests asserting the actual required
  property: no READY status, no view rows, no `mark_error` call, after
  lease loss. Commit `55a8960`.
- **Item 2 (generation-rollover pruning timing):** `prune_old_generation_
  views` is no longer called immediately after a rollover opens the new
  generation (while it's still PREPARING) -- that destroyed the old
  generation's complete snapshot before the new one ever reached READY.
  Pruning now happens INSIDE `rebuild_read_models`'s own atomic
  transaction, only after the new generation's own successful publish.
  New tests prove old-generation rows survive a failed rebuild attempt,
  a lease-loss rejection, a retry (right up until the retry itself
  commits), and a scheduler cancellation mid-rollover. Commit `55a8960`.
- **Item 3 (FAILED -> ERROR rename):** docs/27 SS8.4's frozen contract is
  explicit: "Status is PREPARING|READY|REBUILDING|ERROR." Renamed
  everywhere: the stored literal, `mark_failed` -> `mark_error`, every
  caller, every status-tuple check, every test. Commit `982b046`.
- **Fresh independent reviews** (code-reviewer, security-auditor) ran
  against Items 1-3's diff: 0 critical/important code-quality findings
  (2 harmless suggestions addressed with clarifying comments); security
  found 1 MEDIUM (fail-open gating: `check_read_model_readiness`/
  `projection_state_summary` denylisted PREPARING/ERROR instead of
  allowlisting READY/REBUILDING, so an unrecognized status value --
  including a legacy `'FAILED'` row this exact codebase wrote before the
  rename, never migrated -- silently passed as complete) and 1 LOW
  (`mark_error`'s write was not lease-checked). Both fixed test-first:
  the readiness gate now fails CLOSED (allowlist), a new idempotent data
  migration corrects any existing `'FAILED'` row to `'ERROR'` on next
  startup, and `mark_error` now takes `owner_token` and re-checks lease
  ownership immediately before its write, same pattern as
  `rebuild_read_models`'s decisive check. Commit `ed09179`.
- **Item 5 (forced-colors live acceptance):** genuinely attempted with
  the user's active cooperation, not resolved, explicitly waived by the
  user rather than left unresolved-and-unmarked. Attempt log: (1)
  F12/DevTools would not open in the browser-automation context, tried
  twice including a click-then-F12 sequence to rule out a focus-routing
  artifact; (2) the user enabled real Windows High Contrast on their own
  desktop and confirmed it visibly active there, but the automated tab
  still reported `matchMedia('(forced-colors: active)') === false` after
  a hard reload; (3) the user authorized a full `taskkill chrome.exe` +
  relaunch (Chrome PID list captured in this session's tool output) so
  Chrome would pick up the OS theme at startup -- still `false` after
  relaunch, with no visible remapping in a fresh screenshot. This points
  to a session/profile boundary between the automated browser surface
  and the user's visible desktop that no available tool could bridge.
  Asked directly, the user chose to WAIVE this one sub-check rather than
  continue searching for a mechanism. The relevant `tasks/todo.md`
  checkbox is left OPEN with this full log, per explicit instruction not
  to mark code-review-only verification as live acceptance.
- **Item 4 (this documentation correction):** this entry; `NEXT.md`
  updated to the current test count/state; `docs/reviews/DASHBOARD_
  REDESIGN_BUILD_EVIDENCE.md`'s header changed from IN PROGRESS to
  reflect actual completion status; `git diff --check 4052fef..HEAD`
  clean (one pre-existing trailing-whitespace line in a Unit-0-era
  planning doc, from before this session, fixed as part of this pass).
- **Full suite, final commit `ed09179`:** `pytest tests/unit
  tests/dashboard -q` → **970 passed** (560 unit + 410 dashboard), 0
  failed. Event-loop/lease-starvation measurement
  (`tests/dashboard/scale/measure_event_loop_responsiveness.py`) re-run
  twice: Scenario A (100k-row rebuild) job elapsed 135.9-137.9ms, max
  event-loop gap 30.5-31.4ms (50ms budget), max lease-renewal delay
  0.137-0.139s (5s budget); Scenario B (2,000-record tick) job elapsed
  21.8-23.2ms, max event-loop gap 27.3-30.8ms, max lease-renewal delay
  0.013-0.016s. Both scenarios PASS both runs.
- **Git status:** working tree clean at each commit boundary; every item
  ended at its own local checkpoint commit exactly as authorized. No
  merge, no push, no `src/runtime` modification at any point
  (`git diff 6f8246f..HEAD --stat -- src/runtime` empty). No dependency
  installed.
