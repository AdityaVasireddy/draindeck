# Dashboard Redesign Build Evidence

**Status:** IN PROGRESS — Unit 0 complete<br>
**Branch:** `dashboard-redesign`<br>
**Baseline:** `4052fef97dbb90b52ae91fc01832557bc348cab8`

This tracked record is the durable build-auto evidence log. After every unit,
record the exact files, failing-first test, passing focused/full commands,
browser/performance/security evidence when applicable, findings, deviations,
`NEXT.md` update, and authorized local checkpoint commit. Intent is not
evidence; do not pre-check or report a command that was not run.

## Approval record

- ADR-27/docs/27/tasks plan approved: yes, 2026-08-23, explicit user `/build-auto` authorization message
- Local per-unit checkpoint commits authorized: yes, same message
- Merge authorized: no
- Push authorized: no
- Browser automation proven in Claude Code environment: yes, Unit 0, 2026-08-23

## Unit evidence

### Unit 0 — Baseline and gates (2026-08-23)

1. Branch: `dashboard-redesign` (confirmed via `git branch --show-current`).
   Baseline ancestry: `git merge-base --is-ancestor 4052fef97dbb90b52ae91fc01832557bc348cab8 HEAD`
   exit 0 (yes). Working tree: only the pre-existing uncommitted planning
   artifacts listed in the session's initial `git status --short --branch`
   (`.gitignore`, `CLAUDE.md`, `NEXT.md`, `docs/08...`, `.impeccable/`,
   `DESIGN.md`, `PRODUCT.md`, `docs/27...`, `docs/reviews/...`, `tasks/`) —
   no unexplained dirt. Python (repo venv): `.venv\Scripts\python.exe
   --version` → 3.14.3. Dashboard optional deps present: `pip list` shows
   `fastapi`/`uvicorn` installed under the `draindeck[dashboard]` extra;
   `draindeck` 0.1.0 installed editable from `C:\Projects\Draindeck`.
2. `node C:\Users\adity\.agents\skills\impeccable\scripts\load-context.mjs`
   → `hasProduct: true`, `hasDesign: true`, non-placeholder `PRODUCT.md`/
   `DESIGN.md` content returned, `migrated: false`.
3. `draindeck-dashboard.exe --help` → `usage: draindeck-dashboard [-h] --config CONFIG`
   (only flag is `--config`, required). Confirmed against `src/draindeck_dashboard/cli.py`:
   loads `DashboardConfig` (host fixed to `127.0.0.1`, `port`, absolute
   `db_path`, absolute `observer_executable`) via `load_dashboard_config`,
   then `uvicorn.run(app, host=cfg.host, port=cfg.port)`.
4. Baseline suites (`.venv\Scripts\python.exe -m pytest ...`):
   `tests\dashboard -q` → **197 passed**, 1 pre-existing `httpx`/starlette
   deprecation warning, 6.94s. `tests\unit tests\dashboard -q` → **757
   passed**, same 1 warning, 71.16s. Both match the recorded NEXT.md
   baseline exactly.
5. API/security inventory (read `src/draindeck_dashboard/app.py` and
   `security.py` live): routes are `GET /api/health`, `POST/GET/DELETE
   /api/repositories[...]`, `GET /api/repositories/{id}/health`, `GET
   /api/repositories/{id}/{issues|executions|runs|evidence}` (offset
   `limit`/`offset`, default 50 / max 200), `GET
   /api/repositories/{id}/executions/{execId}/{transcript|diff}`, `GET
   /api/events` (SSE). Security headers on every response (outermost
   `SecurityHeadersMiddleware`): `Content-Security-Policy: default-src
   'self'; frame-ancestors 'none'; base-uri 'self'`, `X-Frame-Options:
   DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy:
   no-referrer`. `LoopbackOnlyMiddleware` rejects non-loopback
   Host/Origin (403 `NON_LOOPBACK_HOST`/`NON_LOOPBACK_ORIGIN`).
   `MaxBodySizeMiddleware` bounds request bodies at `DEFAULT_MAX_BODY_BYTES`
   (64 KiB). Static assets are currently served via a single catch-all
   `app.mount("/", StaticFiles(...))` — Unit 6 must replace this with the
   explicit `/assets` mount + UI-route allowlist per spec §9.1 without
   dropping 404/405 behavior for unknown `/api/*` paths.
6. Real-browser automation proof: launched an isolated temp instance
   (`draindeck-dashboard.exe --config <scratchpad>\dashboard-unit0.yaml`,
   port 8422 — port 8420 was already occupied by an unrelated running
   process, left untouched) with a scratch SQLite db and the installed
   `draindeck.exe` as `observer_executable`. Via `mcp__claude-in-chrome`:
   navigated to `http://127.0.0.1:8422/`, read the live DOM
   (`read_page` returned the real shipped Part-2 shell: "Draindeck
   Dashboard" header, Repositories register form, empty
   run/issue/execution/evidence lists), read console messages (none) and
   network requests (tracked), and captured a screenshot (after one
   retried `Page.captureScreenshot` timeout) showing the real rendered
   page. Tab closed after capture; temp server process (PID 49636)
   `taskkill /F`'d afterward. This proves a callable real-browser
   automation/DevTools capability per plan Unit 0 step 6 and spec §13.4.
7. Local per-unit checkpoint commits: explicitly authorized in the user's
   2026-08-23 `/build-auto` message ("Create local checkpoint commits
   after each green implementation unit... Continue automatically from
   one green checkpoint to the next without asking for intermediate
   approval"). Merge and push remain explicitly prohibited by the same
   message.

```text
IMPECCABLE_PREFLIGHT: context=pass product=pass command_reference=pass shape=pass image_gate=pass mutation=open
```

**Checkpoint:** clean known baseline (757/757, 197/197), preflight line
printed, browser gate proven live, commit authority resolved. ADR-27
(`docs/08` §5i), `docs/27-dashboard-redesign-spec.md`, and `tasks/plan.md`
status fields updated from PROPOSED to ACCEPTED in this same checkpoint to
record the approval event. No `src/` or `tests/` file was touched during
Unit 0.

### Unit 1 — Transactional SQLite v2 migration (2026-08-23)

**Files:** `src/draindeck_dashboard/db.py`, `src/draindeck_dashboard/migrations.py`
(new), `src/draindeck_dashboard/repositories.py`,
`tests/dashboard/test_db.py`, `tests/dashboard/test_migrations.py` (new),
`tests/dashboard/test_repositories.py`.

**Test-first:** wrote `tests/dashboard/test_migrations.py` (9 tests) against
the not-yet-existing `draindeck_dashboard.migrations` module; confirmed
`ModuleNotFoundError` collection failure (RED) before implementing. Also
added `test_delete_removes_every_v2_read_model_and_attention_row` to
`test_repositories.py` and confirmed it failed (`issue_views still has
rows...`) before implementing.

**Implementation:** `migrations.py` (new) owns `schema_meta` exclusively —
`init_schema` (db.py) no longer touches it. `run_migrations()` executes
`BEGIN IMMEDIATE` before any version read (verified by a call-order spy
test), then: no row → fresh DB, create all v2 tables/indexes directly and
insert version 2; version 1 → apply the additive v1→v2 DDL and bump to 2;
version > 2 → raise `SchemaVersionError`; version == 2 → no-op. All DDL
uses `CREATE TABLE/INDEX IF NOT EXISTS`, so a concurrent second migrator
blocked by SQLite's write lock (5s busy_timeout, already in `db.py`)
converges cleanly once it acquires the lock and observes version 2 — no
second migration path. A failure mid-DDL rolls back via `except
BaseException: ROLLBACK; raise`, verified by an injected-failure test that
reopens the database afterward and confirms it is still at version 1 with
no v2 tables. `connect_and_init` now calls `init_schema(conn)` then
`run_migrations(conn)`. Added tables: `issue_views`, `run_views`,
`execution_views`, `containment_views`, `read_model_state`,
`attention_conditions`, exactly matching docs/27 §8.2's columns/composite
keys, plus the 5 new `evidence` indexes from §8.3. `attention_conditions`
uses a partial unique index (`ux_attention_conditions_open_key` on
`condition_key WHERE resolved_at IS NULL`) so a resolved-then-recurring
condition opens a new row/occurrence rather than overwriting history.
`repositories.delete_repository` now wraps every v1+v2 DELETE in one
`BEGIN IMMEDIATE`/`COMMIT` transaction (previously unwrapped/implicit) and
removes `attention_conditions`, `containment_views`, `execution_views`,
`run_views`, `issue_views`, `read_model_state` before the existing v1
cleanup. `tests/dashboard/test_db.py`'s idempotency assertion updated from
`version == 1` to `version == 2` (the only pre-existing test the migration
required changing).

**Commands run:**
- `pytest tests/dashboard/test_migrations.py -q` → 9 passed
- `pytest tests/dashboard/test_repositories.py tests/dashboard/test_db.py tests/dashboard/test_migrations.py -q` → 27 passed
- `pytest tests/dashboard -q` → **207 passed** (197 baseline + 10 new)
- `pytest tests/unit tests/dashboard -q` → **767 passed** (757 baseline + 10 new), 1 pre-existing warning, 70.94s
- Live `sqlite_master` dump against a fresh `connect_and_init()` database
  (scratch file, deleted after inspection) matches docs/27 §8.2/§8.3's
  table/index inventory exactly (verified line-by-line against the spec
  text above).

**Deviations:** none. **Checkpoint:** migration-focused tests and all
existing DB/repository tests green; `sqlite_master` inspected and matches
spec.

### Unit 2, Sub-step A — pure/persistent read models (2026-08-23)

**Files:** `src/draindeck_dashboard/projections.py`,
`src/draindeck_dashboard/read_models.py` (new),
`src/draindeck_dashboard/indexer.py`,
`tests/dashboard/test_projections.py`, `tests/dashboard/test_read_models.py`
(new), `tests/dashboard/test_indexer.py`.

**Test-first:** 9 containment-lifecycle tests added to
`test_projections.py` (RED: `AttributeError: 'ProjectionResult' object has
no attribute 'containments'`), 10 tests written in new
`test_read_models.py` (RED: `ModuleNotFoundError`), 1 end-to-end test added
to `test_indexer.py`. All confirmed failing for the stated reason before
implementation.

**Real bug caught before it propagated:** the Unit 1 migration DDL
declared `containment_views.containment_generation` as `INTEGER`, but
`runtime.engine.claude_headless.ExecutionContext.containment_generation`
and `runtime.events.projections._containment_key` both treat it as an
opaque string (e.g. `"g1"`) — confirmed by reading the real runtime
source. Corrected to `TEXT` in `migrations.py` before any Unit 2 code
depended on the wrong type. SQLite's type affinity meant this would not
have raised at runtime (a non-numeric string still stores fine in an
INTEGER-affinity column), so the bug would have been silent.

**Implementation:**
- `projections.py`: added `ContainmentGenView`, closed
  `PREPARED→ESTABLISHED→UNCONFIRMED→RELEASED` transition table (RELEASED
  reachable directly from PREPARED or ESTABLISHED, matching doc 03's "a
  matching unreleased generation" — not "must pass through UNCONFIRMED"),
  workspace_key-mismatch and duplicate-PREPARED handling (both flag
  `inconsistent`, never raise), keyed by `(execution_id,
  containment_generation)`. Refactored `build_projection` into
  `fetch_ok_evidence_rows(conn, repo_id, gen_id, *, issue_id=, execution_id=,
  run_id=)` (now supports entity-scoped filtering) +
  `apply_ok_evidence_rows(rows)` (the pure dispatch loop, unchanged
  behavior) + `build_projection` as a thin unscoped wrapper — verified
  byte-identical behavior via the full existing + new test suite.
- `read_models.py` (new): `rebuild_read_models` is the full-generation
  candidate-rebuild-and-publish primitive (one transaction: recompute via
  `build_projection`, DELETE+re-INSERT all four view tables for that
  generation, upsert `read_model_state` to READY with
  `completed_evidence_id`) — idempotent, used for backfill/forced
  rebuild. `apply_changed_entities`/`apply_changed_entities_locked`
  (public transaction-owning / lock-assuming inner variant — see below)
  is the ordinary-tick path: for each named issue/execution/run id, it
  replays ONLY that entity's own OK evidence via
  `fetch_ok_evidence_rows(..., issue_id=...)` etc. and upserts just that
  entity's row — O(that entity's evidence), never a full-generation scan.
  Because each call fully re-derives the entity from its CURRENT evidence
  rather than merging into stored state, a TORN→OK tail repair, a
  reordered append, or a previously-OK row's content changing are all
  handled correctly by construction — there is no separate
  monotonic-vs-mutation branch to get wrong, and a normal tail repair
  never triggers a full-generation rebuild (verified by
  `test_apply_changed_entities_torn_to_ok_tail_repair_applies_without_full_rebuild`
  and `test_apply_changed_entities_recomputes_run_started_valid_flag_correctly`,
  the latter proving RunView's `started_valid`/`finished_valid` anomaly
  tracking — not persisted as separate columns — is correctly re-derived
  every time by replaying the run's own evidence, not by trying to
  reconstruct hidden state). `prune_old_generation_views` deletes all
  four view tables' + `read_model_state`'s rows for every generation
  except the current one.
- **Real transaction-nesting bug caught and fixed during wiring, before
  committing:** `indexer.py`'s `ingest_repository_tick` already holds its
  own per-page `BEGIN IMMEDIATE` transaction; calling
  `apply_changed_entities` (which opens its own `BEGIN IMMEDIATE`) from
  inside it would raise `sqlite3.OperationalError: cannot start a
  transaction within a transaction` — sqlite3 does not support nested
  transactions on one connection. Fixed by splitting into
  `apply_changed_entities` (owns its transaction, for standalone
  callers/tests/the future worker) and `apply_changed_entities_locked`
  (assumes the caller already holds the write lock); `indexer.py` calls
  the `_locked` variant. `prune_old_generation_views` is called as a
  separate step AFTER the rollover's own commit (matching docs/27 SS8.4's
  "after the new state is established" wording exactly, not just working
  around the same nesting issue).
- `indexer.py`: `_upsert_evidence_and_detect_corrupt` now returns the
  sets of issue/execution/run ids whose OK content actually changed this
  call (never a boundary-redelivered no-op); `ingest_repository_tick`
  passes them to `apply_changed_entities_locked` in the same per-page
  transaction as the evidence upsert.

**Commands run:**
- `pytest tests/dashboard/test_projections.py -q` → 19 passed
- `pytest tests/dashboard/test_read_models.py -q` → 10 passed
- `pytest tests/dashboard/test_indexer.py tests/dashboard/test_read_models.py tests/dashboard/test_projections.py -q` → 46 passed
- `pytest tests/dashboard -q` → **227 passed**
- `pytest tests/unit tests/dashboard -q` → **787 passed**, 73.37s, 1 pre-existing warning

**Deviations:** none from the pure/persistent-model contract. Sub-step B
(lease-owned off-thread worker so no SQLite write executes on the ASGI
event loop; priority heartbeat scheduling; 16-job FIFO backpressure) is
separately tracked below and required before Unit 2 as a whole is closed.

### Unit 2, Sub-step B — lease-owned off-thread worker (2026-08-23)

**Files:** `src/draindeck_dashboard/read_model_worker.py` (new),
`src/draindeck_dashboard/scheduler.py`, `src/draindeck_dashboard/indexer.py`,
`tests/dashboard/test_read_model_worker.py` (new),
`tests/dashboard/test_scheduler.py`.

**Test-first:** 7 tests written in new `test_read_model_worker.py` (RED:
`ModuleNotFoundError`), 2 new scheduler-level safety-property tests, 5
existing `fake_tick` doubles updated to accept the new `persist=` keyword
the real call site now always passes (a genuine, necessary contract
update — the old fakes' 4-positional-arg-only signature no longer matches
how `ingest_repository_tick` is actually called in production, not a
weakening of any assertion).

**Design decision worth recording:** the obvious-looking shortcut —
routing an entire tick (including `poll_pages`' observer-subprocess I/O)
through the worker as one job via `asyncio.run(ingest_repository_tick(...))`
— was rejected after tracing its consequence: it would serialize ALL
registered repositories' ticks onto the single worker thread, contradicting
scheduler.py's own documented and tested guarantee ("a failing or stalled
repository can never block or delay a healthy one") and defeating
poller.py's existing 4-concurrent-page global semaphore. Instead,
`ingest_repository_tick` gained an optional `persist: Optional[Callable]`
keyword (default `None` -> runs `fn(conn)` inline, byte-identical to
before for all 18 pre-existing direct-call tests) so only the per-page SQL
transaction (`_persist_page`, extracted verbatim from the prior inline
block) and the CURSOR_LOG_REPLACED rollover's SQL route through the
worker; `poll_pages`' observer I/O stays on the event loop, preserving
today's cross-repository concurrency.

**Implementation:**
- `read_model_worker.py` (new): `ReadModelWorker` owns one dedicated
  `sqlite3.Connection` (via `db.connect`) and one background thread. Two
  lanes: an unbounded priority `queue.Queue` for lease acquire/renew
  (always checked first, non-blocking), and a 16-slot-capped ordinary
  `queue.Queue` for page/backfill work (`put_nowait` fast path when there
  is room; falls back to `await asyncio.to_thread(queue.put, job)` --
  blocking the *submitting coroutine*, not the event loop -- only when
  genuinely full). Each job is `Callable[[Connection], T]`; results/
  exceptions cross back to the submitting coroutine via
  `loop.call_soon_threadsafe` setting an `asyncio.Future`.
- `scheduler.py`: added `_db_path_of(conn)` (`PRAGMA database_list`) so
  the Scheduler can open the worker's own connection to the same file
  without changing its public constructor signature. `_lease_loop` now
  submits `lease.acquire_or_renew` with `priority=True`; `_repo_loop`
  passes a `persist` callback that submits ordinary page jobs to the
  worker. `start()`/`stop()` start/stop the worker alongside the existing
  lease-loop/repo-tasks lifecycle.
- `indexer.py`: extracted the old per-page inline transaction body
  verbatim into `_persist_page(c, repo_id, identity_generation_id, page,
  last_cursor, last_hash) -> tuple` -- a pure function of its arguments
  (no outer-scope mutation), so it behaves identically whether `c` is the
  caller's own connection or the worker's. `_handle_cursor_log_replaced`
  similarly routes its generation-open/checkpoint write and its
  post-rollover prune through `persist`.

**Real bug found and fixed before committing:** the worker's `_next_job`
polled the ordinary queue with `queue.Queue.get(timeout=0.1)`, which can
only notice a newly-arrived priority job once that 0.1s blocking call
returns -- a worst-case 100ms delay before a lease-renewal job is even
picked up. Negligible against the production 2s heartbeat / 10s lease
TTL, but it caused real flakiness in this session's own scheduler tests
(written with artificially fast 0.01s test heartbeats) and was a
legitimate latency defect in the priority mechanism regardless. Fixed by
tightening the poll interval to 0.01s (still negligible CPU cost, ~10x
lower worst-case latency) rather than loosening any test's heartbeat or
sleep window.

**Live verification (real, not test-double):** launched a genuine
`draindeck-dashboard` instance (temp config, temp DB, port 8423, isolated
from the port-8420 instance already running) and registered Draindeck's
own real repository/event log (`state/events.jsonl`, read-only --
observation only, never mutated) against it. After ~5s, direct SQLite
inspection of the smoke DB confirmed: `issue_views` 102 rows,
`execution_views` 114 rows, `read_model_state` status `READY` with
`completed_evidence_id: 843` -- exactly matching NEXT.md's independently
recorded `last_event_id 843` for this same log. `GET
/api/repositories/1/issues` and `/health` both returned 200 with real
data. Server process cleanly `taskkill /F`'d and scratch files removed
afterward.

**Commands run:**
- `pytest tests/dashboard/test_read_model_worker.py -q` (x3 for flake-check) → 7 passed each run
- `pytest tests/dashboard/test_scheduler.py -q` (x3 for flake-check) → 12 passed each run
- `pytest tests/dashboard/test_indexer.py -q` → 18 passed (all pre-existing tests, default `persist=None` path, unchanged behavior confirmed)
- `pytest tests/dashboard -q` (x3 for flake-check) → **236 passed** each run
- `pytest tests/unit tests/dashboard -q` → **796 passed**, 66.97s, 1 pre-existing warning

**Unit 2 (both sub-steps) checkpoint reached:** read-model/projection/
indexer/worker/scheduler tests green; a normal TORN→OK tail repair applies
incrementally via entity-scoped recompute (Sub-step A), never a full
generation rebuild; a saturated ordinary queue cannot starve lease renewal
(proven both by a unit-level worker test and a scheduler-level integration
test); no SQLite write executes on the ASGI event loop for a real tick
(proven live). **Deviation from the spec still open:** Unit 2 does not yet
wire `rebuild_read_models`/backfill for a repository registered against a
log with *pre-existing* evidence but no prior read-model state outside of
the incremental per-tick path already covering it (the live verification
above shows this actually works today via ordinary ticking, since
`apply_changed_entities_locked` runs for every newly-upserted OK row
including a fresh repository's full backlog) -- a dedicated "lease-owned
backfill trigger on registration" job is not separately implemented, since
the existing tick-driven path already achieves the same correctness
outcome for this scale. Flagging for Unit 15/16 scale-testing to confirm
this remains acceptable at 100,000-evidence-row scale, where a fresh
registration's first tick would apply ~100k individual entity-scoped
recomputes rather than one bulk rebuild -- a potential performance gap
that scale testing should surface and, if real, be addressed by explicitly
calling `rebuild_read_models` once on first registration instead.

### Unit 3 — Attention detection history (2026-08-23)

**Files:** `src/draindeck_dashboard/attention.py` (new),
`src/draindeck_dashboard/scheduler.py`,
`tests/dashboard/test_attention.py` (new), `tests/dashboard/test_scheduler.py`.

**Test-first:** 24 tests written in new `test_attention.py` (RED:
`ImportError: cannot import name 'attention'`), 1 new scheduler
integration test, 2 pre-existing direct-`_repo_loop` tests updated to
start/stop the worker (a real, necessary contract update -- they drive
`_repo_loop` directly, bypassing `Scheduler.start()`, and `_repo_loop` now
genuinely depends on a running worker for its new attention-reconciliation
step).

**Real spec ambiguity found and resolved, documented rather than
silently guessed past:** docs/27 SS8.5 says "Only the lease-owning writer
persists attention changes," but under the CURRENT single-active-leader
architecture, a continuously-leading process's own lease read is always
"held" (it just renewed it) -- meaning a naive "derive after acquiring"
design would make `LEASE_STALE`/`LEASE_UNCLAIMED` effectively
unreachable in practice (a newly-electing process's own successful
acquisition always makes its own subsequent read show "held", never the
stale/unclaimed state it just took over from). Resolved by having
`Scheduler._reconcile_system_then_acquire` read+derive+reconcile system
conditions from the lease state observed BEFORE each attempt, then
call `acquire_or_renew` -- so a takeover is preceded by one accurate
reconciliation against the real pre-takeover state, and a genuinely fresh
database observes-then-immediately-resolves `LEASE_UNCLAIMED` on
consecutive heartbeats (a real, testable, meaningful transition instead of
dead code). The idempotent upsert-open design makes this safe without a
strict single-writer gate even if a losing competitor observes the same
transient state.

**Scoping decision, explicitly deferred (not silently dropped):** the
`LEASE_UNCLAIMED` "opens as warning only after one full 10-second TTL"
visibility gate (docs/27 SS6.4, preventing a startup flash) is
intentionally NOT enforced in `attention.py` -- the condition row opens
immediately on first detection (so its `first_detected_at` is an accurate
anchor for that gate), and the actual 10-second suppression is left to
Unit 4's `/api/attention` query layer, which is the natural owner of
"what's visible right now" filtering per the plan's own unit boundaries.
Similarly, `repository_health`-kind SSE invalidations ("repository
availability/health changes emit repository_health," SS8.5) are not
emitted by this unit -- they require diffing against a PRIOR observed
health snapshot, which is more naturally Unit 4's health/overview
endpoint work than attention.py's condition-derivation job. Both
deferrals are recorded here so they are not forgotten, not silently
dropped.

**Implementation:**
- `attention.py` (new): `Condition` dataclass; `_condition_key` (stable
  SHA-256 over repository-or-system / generation-or-none / kind /
  disambiguator) -- containment conditions fold `containment_generation`
  into the disambiguator so two generations of the same execution never
  collide into one attention row. `derive_repository_conditions` reads
  only Dashboard's own persisted checkpoint/corruptions/evidence/
  issue_views/execution_views/containment_views/run_views rows for the
  CURRENT generation and returns the closed docs/27 SS6.4 vocabulary
  exactly (12 repo-scoped kinds); `derive_system_conditions` returns
  `LEASE_STALE`/`LEASE_UNCLAIMED` (mutually exclusive, from
  `lease.read_state`). `reconcile_repository_conditions`/
  `reconcile_system_conditions` upsert-open each derived condition
  (refreshing `last_detected_at` for an already-open key, or inserting a
  new row with an incremented `occurrence` if the key was previously
  resolved and has now recurred) and resolve any previously-open row
  whose key is no longer present -- generation rollover therefore
  self-resolves stale generation-scoped conditions with no special-case
  code, since the freshly-derived current-generation set simply omits the
  old generation's keys. Exactly one `changes` table `attention`
  invalidation is recorded per open/resolve transition (never for a mere
  refresh); system-wide invalidations use the reserved
  `SYSTEM_CHANGE_REPOSITORY_ID = 0`.
- `scheduler.py`: `_repo_loop` reconciles repository conditions in a
  separate worker job right after each non-error tick commits.
  `_lease_loop` routes `_reconcile_system_then_acquire` through the
  priority lane (same job as the heartbeat itself, so system reconciliation
  never falls behind or races the acquire/renew write).

**Commands run:**
- `pytest tests/dashboard/test_attention.py -q` → 24 passed
- `pytest tests/dashboard/test_scheduler.py -q` (x3 for flake-check) → 13 passed each run
- `pytest tests/dashboard -q` → **261 passed**
- `pytest tests/unit tests/dashboard -q` → **821 passed**, 73.60s, 1 pre-existing warning

**Checkpoint:** attention/scheduler tests green; repeated reconciliation
is idempotent and does not create duplicate open occurrences (verified
directly). No `repository_health`/TTL-visibility work remains outstanding
for Unit 3 itself -- both are explicitly Unit 4 scope per above.

### Unit 4 — Bounded query layer and aggregates (2026-08-23)

**Files:** `src/draindeck_dashboard/api_queries.py` (new),
`src/draindeck_dashboard/views.py`, `src/draindeck_dashboard/errors.py`,
`tests/dashboard/test_api_queries.py` (new),
`tests/dashboard/test_app_views_api.py`.

**Test-first:** 27 tests written in new `test_api_queries.py` (RED:
`ImportError`), 1 new test in `test_app_views_api.py` for the legacy
evidence offset cap (RED: `assert 200 == 422`).

**Implementation:**
- `errors.py`: added `InvalidQueryError`, `InvalidFilterError`,
  `InvalidSortError`, `QueryTooShortError`, `PageOutOfRangeError` (422),
  `IndexPreparingError` (503) -- docs/27 SS7.5's typed codes, all
  subclasses of the existing `DashboardApiError` so the app's single
  generic exception handler picks them up automatically.
- `api_queries.py` (new): `check_offset_cap` (shared 10,000/100,000 cap
  primitive); `repository_summaries` (search/availability/hasAttention
  filters, name/createdAt/availability/latestRunAt/attentionCount sorts,
  displayName derived client-side from the final path segment);
  `overview` (cross-repo aggregate counts by availability/state/outcome/
  integrity, attention-by-severity, `projectionState` from
  `read_model_state`); `cross_repository_issues`/`_runs`/`_executions`
  (every query joins `checkpoints.identity_generation_id` so only
  current-generation rows are ever returned -- verified directly with a
  test that seeds a stale-generation row and confirms it's excluded);
  `cross_repository_executions(groupBy="issue")` paginates ISSUE groups
  server-side (not a client-page join), each with exact total/by-state
  counts and up to 5 newest execution IDs plus `executionsTruncated`;
  `evidence_keyset` (ordered by globally unique `evidence.id`, `next`/
  `previous`/`hasMore` from one over-fetch-by-one query, no `offset`
  parameter exists on the function signature at all -- a test asserts
  this structurally via `__code__.co_varnames` so a future edit can't
  quietly reintroduce one); `entity_timeline` (metadata-only columns
  only, ordered by logical `event_id` not raw evidence-arrival order,
  scoped via the entity's own id column so it never touches other
  entities' evidence); `entity_topology` (bounded node/edge caps,
  `issue|run|execution|evidence` node kinds, `run_has_execution|
  issue_has_execution|entity_has_evidence` edge kinds, `truncated=true`
  once either cap is hit, from stored identifiers only -- no physics
  layout, no whole-portfolio scope).
- `views.py`: `list_evidence` (the legacy repository-scoped endpoint) now
  calls `check_offset_cap(offset, cap=LEGACY_EVIDENCE_OFFSET_CAP)` --
  docs/27 SS7.4's one documented pre-GA narrowing of an existing range;
  order/shape otherwise unchanged.

**Real bug caught and fixed before committing:** an early draft of
`repository_summaries` left a first, broken SQL-string draft assigned to
`sql` and then immediately overwritten by a second, correct version --
dead but confusing code with ad-hoc `.replace()` string surgery on SQL
fragments. Rewritten cleanly: `where` clauses are built once with a
single named `attn_expr` (`COALESCE(ac.attention_count, 0)`) substituted
consistently into WHERE/ORDER BY/SELECT, no dead code, no string-replace
hacks.

**Deviation flagged (not hidden), for Unit 15's query-count check:**
`cross_repository_executions(groupBy="issue")` issues two additional
queries per issue group on the current page (bounded by `limit`, max
200 -- never unbounded, never a full evidence scan) rather than one
single JOIN query. This is a real, bounded N+1 relative to page size;
Unit 15's explicit query-count/N+1 acceptance check should evaluate
whether it needs collapsing into a single query at 100k-evidence scale.

**Commands run:**
- `pytest tests/dashboard/test_api_queries.py -q` → 27 passed
- `pytest tests/dashboard/test_app_views_api.py -q` → 11 passed
- `pytest tests/dashboard -q` → **289 passed**
- `pytest tests/unit tests/dashboard -q` → **849 passed**, 70.11s, 1 pre-existing warning

**Checkpoint:** query tests green on multi-repository fixtures built in
the test suite; current-generation scoping verified directly (not just
assumed); evidence keyset structurally guaranteed offset-free.

### Unit 5 — Search and REST route surface (2026-08-23)

**Files:** `src/draindeck_dashboard/search.py` (new),
`src/draindeck_dashboard/app.py`,
`tests/dashboard/test_app_redesign_api.py` (new),
`tests/dashboard/test_search.py` (new).

**Test-first:** 10 tests in new `test_search.py` (RED: `ImportError`), 18
tests in new `test_app_redesign_api.py` (RED: 15 failed with 404s for
routes that did not exist yet).

**Real bug caught and fixed before committing:** `search.py`'s first
draft of `_search_evidence` wrapped the query in a subquery aliased `e`
while the inner `FROM evidence e` used the SAME alias `e` for a different
table reference, producing `sqlite3.OperationalError: ambiguous column
name`. Simplified to a single flat query (the subquery wrapper was
unnecessary) -- caught immediately by the first test run, not discovered
later.

**Implementation:**
- `search.py` (new): `search(conn, q, *, limit)` validates 2-200 trimmed
  characters (`QueryTooShortError` otherwise), returns five grouped
  result lists (repositories/issues/runs/executions/evidence), each
  capped at `limit` (max 10). Repository/issue/run/execution matching is
  a case-insensitive substring over project_path/title/run_id/
  execution_id (SQLite's built-in `LIKE` is ASCII-case-insensitive by
  default); issues additionally match by exact ID. Evidence matching is
  limited to exactly the metadata docs/27 SS7.1 allows: Dashboard
  evidenceId, cursor substring, integer eventId, and event_type
  substring -- verified directly that no result item ever contains a
  `payload`/`recordBytes` key.
- `app.py`: added `/api/overview`, `/api/repository-summaries`,
  `/api/attention` (status/severity/repositoryId filters, closed
  severity-then-first-detected ordering), `/api/search`,
  `/api/issues`/`/api/runs`/`/api/executions` (cross-repo, `groupBy`
  supported on executions) /`/api/evidence` (keyset, confirmed via test
  that the response has no `offset` key), single-entity detail routes
  (`/api/repositories/{id}/overview`, `.../issues/{issueId}`,
  `.../runs/{runId}`, `.../executions/{executionId}` with its full
  containment-generation list, `.../evidence/{evidenceId}`), and generic
  `/api/repositories/{id}/{entityType}/{entityId}/{timeline|topology}`.
  Every route is a thin wrapper over `api_queries.py`/`search.py`/
  `attention.py` -- no business SQL added directly in `app.py` except the
  small `/api/attention` listing query (closed status/severity/
  repositoryId filter set, matching the same allowlisted-fragment
  pattern used throughout `api_queries.py`). Confirmed no route
  collision between the new generic 6-segment `{entityType}/{entityId}/
  {timeline|topology}` pattern and the existing literal
  `executions/{id}/transcript`/`.../diff` routes (different final literal
  segment, so Starlette's structural matching never conflates them) and
  between the new 5-segment single-entity routes and the new 6-segment
  generic ones (different segment counts).

**Live verification (real, not test-double), against a temporary
instance registered to Draindeck's own real 843-event log:**
`/api/overview` returned `issues.byState` exactly `{DONE: 74,
NEEDS_DECOMPOSITION: 21, NEEDS_HUMAN: 7}` and `attention.warning: 28`
(21+7, an independent cross-check that attention derivation is wired
correctly end-to-end) -- matching NEXT.md's independently recorded
backlog state exactly. `executions.byState` matched the earlier Unit 2
live check (114 total). `/api/repository-summaries`, `/api/search`,
`/api/attention`, and `/api/executions?groupBy=issue` all returned real,
correctly-shaped data. Server cleanly `taskkill /F`'d and scratch files
removed afterward.

**Commands run:**
- `pytest tests/dashboard/test_search.py -q` → 10 passed
- `pytest tests/dashboard/test_app_redesign_api.py -q` → 18 passed
- `pytest tests/dashboard -q` → **317 passed**
- `pytest tests/unit tests/dashboard -q` → **877 passed**, 75.99s, 1 pre-existing warning

**Checkpoint:** focused API/search tests and all pre-existing API tests
green; representative live JSON inspected and cross-checked against an
independent source (NEXT.md's recorded backlog counts) for exact truth
language -- no illustrative/placeholder values anywhere in the responses.

### Unit 6 — Stable UI routing and security preservation (2026-08-23)

**Files:** `src/draindeck_dashboard/app.py`,
`src/draindeck_dashboard/static/index.html`,
`tests/dashboard/test_app_ui_routes.py` (new).

**Test-first:** 10 tests in new `test_app_ui_routes.py` (RED: 4 failed --
the 18-route allowlist test, `/assets` mount test, nested-reload security
headers test, and no-JS fallback test, since none of that existed yet).

**Implementation:** Removed the old catch-all `app.mount("/",
StaticFiles(...))`. API routes were already fully registered earlier in
`create_app`; static assets now mount only at `/assets` (so an unmatched
`/api/*` path can never be swallowed by `StaticFiles`'s own 404 instead
of Starlette's routing 404 -- verified directly). An explicit allowlist
of the 18 approved UI route patterns from docs/27 §4 (home, repositories/
new/detail, attention, cross-repo and per-repo runs/issues/executions/
evidence explorers, per-entity detail routes, about) each registers a
`GET` returning the same `index.html` app shell, so a direct
reload/deep-link to any of them works -- `/repositories/new` is
registered before the parameterized `/repositories/{repo_id}` so the
literal route wins (Starlette matches in registration order). A
genuinely unknown path now falls through to FastAPI's ordinary 404 (no
catch-all left to hide it). `/styles.css` and `/app.js` get their own
explicit compatibility routes since they no longer live under a root
mount. Added a `<noscript>` fallback notice to `index.html`.

**Commands run:**
- `pytest tests/dashboard/test_app_ui_routes.py -q` → 10 passed
- `pytest tests/dashboard -q` → **327 passed**
- `pytest tests/unit tests/dashboard -q` → **887 passed**, 78.10s, 1 pre-existing warning

**Checkpoint:** nested reloads pass under TestClient with security
headers/CSP intact; existing health/security/API routes unchanged
(regression-free per the combined suite). Real browser deep-link/reload
verification deferred to Unit 7+, once the new visible shell exists --
verifying route plumbing against the still-unreplaced Part 2 UI would not
be a meaningful visual check yet.

### Unit 7 — Design tokens, shell, themes, and shared primitives (2026-08-23)

**Files:** `static/styles/tokens.css`, `base.css`, `shell.css`,
`components.css` (all new), `static/js/app.js` (rewritten), `dom.js`,
`format.js`, `state.js`, `components/shell.js` (all new),
`static/index.html`, `tests/dashboard/js/test_format.mjs`,
`test_state.mjs`, `test_shell_component.mjs` (all new),
`tests/dashboard/test_static_js_contracts.py` (new),
`tests/dashboard/test_app_shell_contract.py` (new).

**Test-first, adapted to a vanilla-JS-only stack:** since docs/27 SS10
prohibits any new dependency (no Jest/Vitest/npm install), pure JS logic
(format.js's label/date functions, state.js's theme-preference resolution,
shell.js's active-route matching) is tested via plain-Node `.mjs` scripts
using only `node:assert` -- written and run RED-then-GREEN exactly like
every Python test this build has produced (e.g. the relative-time test
failed first with `'5s ago' !== 'just now'` at an off-by-one boundary,
fixed by adjusting the test's fixture time, not the function). A new
`test_static_js_contracts.py` drives every `tests/dashboard/js/test_*.mjs`
file as a subprocess so `pytest tests/dashboard` remains the single
command that proves everything, Python and JS alike. DOM-dependent code
(actual rendering, real click/keyboard interaction) is verified live in a
real browser instead of simulated -- documented below -- since a
dependency-free in-Node DOM is not realistically available.

**Implementation:**
- `tokens.css`: every DESIGN.md palette/typography/spacing/radius/shadow
  value as a raw CSS custom property, then semantic aliases
  (`--color-canvas`, `--color-text-primary`, `--color-focus-on-paper`,
  `--color-focus-on-dark-surface`, etc.) redefined under
  `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`
  and again under `:root[data-theme="dark"]` so an explicit user choice
  always wins over the system preference in both directions. Complete
  eight-position light/dark chart sequences included verbatim.
- `base.css`: reset, the six-level typography scale as utility classes,
  surface-aware `:focus-visible` (a `.on-dark-surface` scope switches to
  `--color-focus-on-dark-surface`, since Proofreader Teal does not clear
  3:1 on Binding Forest), skip-link, `prefers-reduced-motion` global kill
  switch.
- `shell.css`: 240px rail / 72px tablet-collapsed (768-1023px, visible
  short labels retained, never tooltip-only) / compact top nav below
  768px (320px accessibility reflow, explicitly not a separate mobile
  product per DESIGN.md); sticky utility bar with `scroll-padding-top` on
  `#main-content` so a focused control is never obscured beneath it
  (WCAG 2.2 Focus Not Obscured).
- `components.css`: buttons (44px target, primary/secondary/ghost/
  destructive), status/filter chips (never color-alone -- every chip
  pairs a wash background with visible text), fields with error/hint
  states, a sticky-header ledger table with a `.sort-button`/
  `.sort-direction-text` pattern for accessible sort controls, pagination,
  dialog/backdrop, a reduced-motion-respecting skeleton shimmer, and
  error/empty state panels.
- `dom.js`: `el`/`text`/`clear` safe node builders (every attribute path
  explicitly excludes `innerHTML`/`style`/`on*`), `statusChip` (icon +
  text, never color alone), and a generalized `syncList` keyed-patch
  helper extracted from the pre-existing Part 2 `app.js`'s `syncList`
  (same in-place-update/no-clear-and-recreate behavior, now reusable by
  every future page module instead of duplicated per page).
- `format.js`: exact status vocabulary (`NO_CONTROLLED_FINISH_TEXT`,
  `RUN_METADATA_UNAVAILABLE_TEXT`, `NOT_YET_OBSERVED_TEXT`,
  `NO_INCONSISTENCY_TEXT`), `displayName` (final path segment, both
  separator styles), absolute/relative timestamp formatting (a relative
  label is never produced without also being able to render the exact
  absolute one alongside it), severity ranking, and offset/page mapping.
- `state.js`: `resolveStoredTheme`/`themeAttributeFor`/`loadThemePreference`/
  `saveThemePreference` (corrupted/absent storage defaults safely to
  "system"; a full storage quota never throws out of a preference
  change) and a minimal `createStore` pub-sub primitive.
- `components/shell.js`: renders the exact eight stable rail destinations
  (Home/Repositories/Attention/Runs/Issues/Executions/Evidence/About,
  order-verified by test), active-route highlighting via `aria-current`,
  a three-state theme control (system → light → dark cycle, persisted),
  and the tablet expand/collapse toggle.
- `app.js` (rewritten): boots only the shell chrome now; the pre-existing
  Part 2 page logic (repository registration/list/detail, still at
  `/app.js`) is intentionally left running underneath, unmodified, via
  its own legacy compatibility route -- Units 8-14 replace it
  incrementally with the real router and page modules, so the app stays
  genuinely working end-to-end at every intermediate checkpoint rather
  than going dark mid-redesign.
- `index.html`: full shell markup (skip link, `<noscript>` fallback,
  rail, utility bar with search/connection-status/theme control,
  breadcrumb landmark, `#main-content` with the unmodified Part 2 content
  still nested inside for now).

**Live browser verification (real, not simulated):** launched a temp
instance, navigated to `/`: forest rail with all 8 destinations rendered,
correct active-state highlighting on Home. Deep-linked directly to
`/repositories/5/issues/42` (an unregistered repo/issue -- proving this
is route-pattern-level, not existence-level): app shell served correctly,
"Repositories" rail item correctly active, zero console errors. Clicked
the theme control twice (system → light → dark): utility bar/rail visibly
re-themed via the token system; reloaded the page and confirmed
`localStorage` (`draindeck-dashboard-theme: "dark"`) and
`document.documentElement.dataset.theme === "dark"` both persisted.
Captured all 12 network requests on a fresh load: every new
stylesheet/JS module returned 200, zero 404s. Server cleanly
`taskkill /F`'d and scratch files removed afterward.

**Known limitation, disclosed rather than glossed over:** this session's
`resize_window` browser tool call did not change the tab's actual
`window.innerWidth` (confirmed via direct JS inspection), so the
768px/320px responsive breakpoints could not be live-verified narrow in
this unit. The CSS media queries are written and structurally reviewed,
but full multi-viewport screenshot verification (320/768/1024/1440) is
explicitly Unit 15's dedicated acceptance pass, not claimed here.

**Commands run:**
- `node tests/dashboard/js/test_format.mjs` / `test_state.mjs` / `test_shell_component.mjs` → all passed directly
- `pytest tests/dashboard/test_static_js_contracts.py -q` → 3 passed (Node subprocess wrapper)
- `pytest tests/dashboard/test_app_shell_contract.py -q` → 7 passed
- `pytest tests/dashboard -q` → **337 passed**
- `pytest tests/unit tests/dashboard -q` → **897 passed**, 69.24s, 1 pre-existing warning

**Checkpoint:** static/JS-contract tests green; no remote asset, inline
handler, unsafe HTML, or unapproved visual token (verified directly via
`test_index_html_has_no_inline_style_or_script_csp_violation`); live
browser confirms zero console errors and correct theme/routing behavior.
320px/768px breakpoint screenshots deferred to Unit 15, disclosed above.

### Unit 8 — API client, connection stream, and focus-safe reconciliation (2026-08-23)

**Files:** `static/js/api.js` (new), `static/js/stream.js` (new),
`tests/dashboard/js/test_api.mjs`, `test_stream.mjs` (both new),
`tests/dashboard/test_app_shell_contract.py`.

**Test-first:** 13 new plain-Node tests (7 for `api.js`, 6 for
`stream.js`), all against real Node globals (`fetch`, `AbortController`,
`setTimeout`/`setInterval`) rather than a simulated DOM -- Node 24 ships
these natively, so no polyfill/dependency was needed. All passed on
first real run; no bug this time, unlike most prior units' JS/SQL work.

**Implementation:**
- `api.js`: `ApiError` (typed `code`/`status` from the existing `{error:
  {code,message}}` envelope, generic fallback when a response isn't that
  shape, and a distinct `NETWORK_ERROR` code when `fetch` itself throws)
  and `createRequestCoordinator()` -- fetches keyed by an arbitrary
  string abort any still-in-flight fetch under the SAME key before
  starting a new one, and a response that resolves after being
  superseded is suppressed (returns `undefined`, not stale data or a
  spurious `AbortError`). Verified directly: two concurrent fetches under
  the same key resolve with only the second's real body; different keys
  never abort each other; `abortAll()` suppresses every in-flight key.
- `stream.js`: `CONNECTION_STATUS` + `connectionStatusLabel` (docs/27
  SS5.1's exact four states -- verified no label ever contains the word
  "running"), `SYSTEM_REPOSITORY_ID = 0` + `isSystemWideChange`,
  `createChangeCoalescer` (a burst of changes to the SAME
  `(repositoryId, entityType, entityId)` within the coalescing window
  fires the flush callback ONCE with only the latest, not once per
  change -- distinct identities in the same window all survive
  independently, including two different `repositoryId: 0` system-wide
  entity types not colliding), `createPeriodicRefresh` (the 30-second
  time-derived attention/lease refresh primitive; `stop()` verified to
  actually end ticking, not just stop being awaited), and
  `connectChangeStream` (the real `EventSource` wiring -- coalesces
  `change` events, handles `resync` by closing and reopening a fresh
  source since a resync carries no id to resume from).

**Live verification (real browser, not simulated):** `await
import('/assets/js/api.js')` and `.../stream.js')` both loaded with zero
console errors; `createRequestCoordinator().fetch('health',
'/api/health')` made a REAL fetch against the running server and
returned `{"status":"ok"}`; `connectionStatusLabel(CONNECTED)` returned
`"Updates connected"`. Server cleanly `taskkill /F`'d afterward.

**Scope note:** per the plan's own Unit 8 file list, these are
primitives only -- neither module is wired into `app.js`/`index.html`
yet, so the pre-existing Part 2 page logic (and its own inline SSE
handling) keeps running unchanged. Units 9-14 replace it page-by-page
with real modules built on `api.js`/`stream.js`/`dom.js`, at which point
the "replace the current clear(el)-inside-row pattern" item from the
plan's Unit 8 description actually applies (there is no redesigned
screen yet for it to apply to).

**Commands run:**
- `node tests/dashboard/js/test_api.mjs` / `test_stream.mjs` → both passed directly
- `pytest tests/dashboard/test_app_shell_contract.py tests/dashboard/test_static_js_contracts.py -q` → 12 passed
- `pytest tests/dashboard -q` → **339 passed**
- `pytest tests/unit tests/dashboard -q` → **899 passed**, 70.70s, 1 pre-existing warning

**Checkpoint:** deterministic JS tests green; a focused live-browser probe
confirms both modules load and execute correctly against the real
server. The "browser probe proves focus remains on an updated row
control" acceptance bullet is deferred with `dom.js`'s `syncList` (Unit 7)
to whichever Unit 9+ page first uses it against live SSE-driven data,
since there is no redesigned live-updating screen to probe yet.

### Correction — client-side router.js (2026-08-23, before Unit 9)

**Files:** `static/js/router.js` (new), `static/js/app.js`,
`tests/dashboard/js/test_router.mjs` (new),
`tests/dashboard/test_app_shell_contract.py`.

**Gap found and fixed before it could block Unit 9:** `tasks/plan.md`'s
Unit 6 file list names `static/js/router.js (new)`, but Unit 6's actual
work (this build evidence log's own Unit 6 entry) only built the
SERVER-SIDE half -- the explicit FastAPI route allowlist serving
`index.html` for a direct reload/deep-link. No CLIENT-SIDE History-API
router existed yet to intercept link clicks for SPA-style navigation or
to tell a page module which route is active. Building Unit 9's actual
page content without this would have meant either full page reloads on
every navigation (defeating docs/27 SS9.2's "same-origin clicks enhance
through History API") or duplicating ad hoc routing logic per page.
Fixed now, before Unit 9, rather than silently discovering it mid-page-build.

**Implementation:** `router.js`'s `matchRoute(pathname, routes)` is a
pure function (Node-tested, 7 tests, all passed on first run) matching
the exact same 18 approved patterns as `app.py`'s server-side allowlist
-- a dedicated test asserts every one of those 18 literal example paths
resolves to a client match, and that the literal `/repositories/new`
wins over the parameterized `/repositories/:repoId` (same
registration-order-wins rule as the server side). `createRouter`
intercepts only a plain same-origin left-click on an `a[href]` (never a
modified click, a `download` link, or a `target="_blank"` link -- native
open-in-new-tab/copy-link behavior is preserved), calls
`history.pushState`, and dispatches to `onNavigate(match, location)` on
boot, on click-navigation, and on `popstate`. Wired into `app.js`: the
rail's active-state and `document.title` now update on every navigation;
`#page-root`'s actual per-route content remains the Part 2 markup until
Units 9-14 replace it.

**Live verification (real browser):** planted a `window.__navMarker`
sentinel, clicked the Executions rail link -- URL became `/executions`,
title updated to `"executions — Draindeck Dashboard"`, the rail's
`aria-current="page"` moved to the Executions link, and the sentinel
SURVIVED (proving no full page reload occurred -- a real pushState
navigation, not a normal link follow). Browser back button correctly
triggered `popstate` back to `/` with the same no-reload/marker-survives
proof and zero console errors.

**Commands run:**
- `node tests/dashboard/js/test_router.mjs` → 7 passed
- `pytest tests/dashboard -q` → **340 passed**
- `pytest tests/unit tests/dashboard -q` → **900 passed**, 70.48s, 1 pre-existing warning

### Unit 9 — Home, repository registry, add flow, and repository overview (2026-08-23)

**Files:** `static/js/pages/home.js`, `repositories.js`,
`repository-detail.js` (all new), `static/js/app.js` (rewritten dispatch),
`static/js/dom.js` (bug fix), `static/index.html` (Part 2 markup
retired), `static/styles/pages.css` (new),
`tests/dashboard/js/test_home_page.mjs`,
`test_repositories_page.mjs` (both new),
`tests/dashboard/test_app_shell_contract.py`.

**Test-first:** pure view-model/query-parsing functions tested via
plain-Node scripts (5 for `home.js`'s `buildHomeViewModel`, 5 for
`repositories.js`'s `parseRegistryQuery`/`registryQueryToUrl`), all
passed on first run; full page behavior (data fetching, DOM rendering,
form submission, dialog interaction) verified live in a real browser
instead, since DOM-dependent code isn't Node-testable without a
disallowed new dependency (jsdom).

**Real bug caught and fixed while building this unit's pages, before it
could spread further:** `dom.js`'s `el()` helper set most attributes via
plain property assignment (`node[key] = value`). For `colspan` this is
silently wrong -- the DOM property is `colSpan` (camelCase); the
lowercase assignment creates an inert ad-hoc property that never reflects
to the actual HTML attribute, so a table cell's colspan would just not
work. There was also a latent boolean-attribute bug: `setAttribute(name,
"false")` still means the attribute is PRESENT (true) per HTML's
presence-based boolean-attribute semantics, so `{disabled: false}` would
have incorrectly disabled a control instead of leaving it enabled. Fixed
by switching `el()`'s default path to `setAttribute` (correct for
`colspan`/`rowspan`/`value`/etc.) with an explicit allowlist of
presence-based boolean attributes (`disabled`, `required`, `checked`,
etc.) that are only set when truthy. This is a foundational primitive
every later page unit depends on -- worth catching now rather than
inheriting a silent per-page workaround.

**Second real issue caught and fixed live, mid-unit:** retiring the old
`/app.js` (which owned the only SSE-connection-status wiring) without
replacing that responsibility left `#connection-status` permanently
stuck on "Connecting…" -- a genuine regression from previously-working
Part 2 behavior. Fixed by wiring Unit 8's `stream.js` primitives
(`connectChangeStream`/`connectionStatusLabel`) into the new `app.js`
boot, with `onInvalidate` re-running the current route's own render (a
correct, if not maximally surgical, baseline -- each page's own
coordinator-backed fetches already supersede any still-in-flight
request). Live-verified afterward: status correctly read "Updates
connected".

**Third issue found and correctly diagnosed as NOT a code bug:** two
separate `computer` tool physical clicks (the Add-repository submit
button, then the Unregister confirm button) appeared not to fire their
handlers. Rather than assume the application code was broken, isolated
the cause with a direct `element.click()` call (a real, trusted DOM
click dispatch, not a bypass) -- both fired correctly and the underlying
flows worked. Traced the actual submit-button non-response separately to
an ambiguous `document.querySelector('form')` in one of MY diagnostic
scripts matching the header's global-search form (also a `<form>`) ahead
of the page's own form in document order -- a real reminder that this
page now has two forms, not evidence of an application defect.

**Implementation:**
- `home.js`: `buildHomeViewModel` is a pure transform (Node-tested) from
  four real API responses into a view-model; `render()` shows the
  cross-repository ledger, an attention preview (capped at 5, with a
  "View all" link when the real total exceeds that), an analytics band
  (text/table equivalents per category -- SVG chart visuals are
  explicitly Unit 13's "final chart/topology polish" per the plan's own
  unit naming, not silently skipped), and recent observed activity in
  evidence-ID-order with paired absolute+relative timestamps. Separates
  "no repositories registered" from "registered; no data yet" per docs/27
  SS6.1.
- `repositories.js`: the registry is a real `<table>` (never a card
  grid), with search/availability/attention filters and page-size/sort
  state round-tripped through the URL (`parseRegistryQuery`/
  `registryQueryToUrl`, Node-tested for exact round-trip fidelity and
  safe fallback on invalid/out-of-range values). `renderAdd()` is the Add
  Repository form -- required project path, optional log path, inline +
  form-level typed error rendering, redirects to the new repository's
  overview on success.
- `repository-detail.js`: identity block, health panel (availability,
  reduced-confidence, corrupt/unknown-type counts, lease status),
  attention panel (linked to each condition's target), navigation into
  the not-yet-built Runs/Issues/Executions/Evidence sub-views, and the
  unregister flow -- a real `role="alertdialog"` with the EXACT docs/27
  SS6.2 confirmation copy, Escape-to-close, and delete-then-redirect on
  confirm.
- `app.js`: route-name-to-page-module dispatch table; a route the router
  matches but with no registered page module yet renders an honest "not
  available yet" state rather than a blank page or an error. Focus moves
  to `#main-content` on every non-initial navigation (WCAG landing
  behavior), skipped on first load so it doesn't steal focus from
  wherever the browser already placed it.
- `index.html`/`pages.css`: the old Part 2 static markup and its
  `/styles.css`/`/app.js` `<link>`/`<script>` references are removed
  (the legacy compatibility ROUTES themselves, required by Unit 6, still
  serve those files if requested directly -- only the references from
  the live page are gone, since old `styles.css` defined colliding
  class names like `.field`/`.register-form` that would have silently
  overridden the new token-based `components.css` rules).

**Live verification (real browser, extensive, not simulated):**
registered Draindeck's own real repository end-to-end through the actual
Add Repository form; confirmed the resulting Repository Overview page
showed real identity/health/attention data (5 real current conditions:
3× `ISSUE_NEEDS_DECOMPOSITION`, 2× `ISSUE_NEEDS_HUMAN`, matching every
earlier independent check this build has made); confirmed Home's
repository ledger, attention preview, and analytics band (74 DONE / 21
NEEDS_DECOMPOSITION / 7 NEEDS_HUMAN issues, 843 OK evidence -- exact
matches again) and recent-activity feed (real commit/review/validation
events from Draindeck's own history with correct relative+absolute
timestamps) all rendered correctly; ran the full unregister flow
(dialog open → exact confirmation text → Escape closes it → reopen →
confirm → real DELETE → redirect to `/repositories` → registry
correctly shows 0 repositories again). Zero console errors throughout
every step. Confirmed the sticky utility bar's mid-scroll screenshot
oddity was a capture-timing artifact, not a real rendering bug (DOM
inspection showed exactly one rail/utility bar element throughout).

**Commands run:**
- `node tests/dashboard/js/test_home_page.mjs` / `test_repositories_page.mjs` → both passed
- `pytest tests/dashboard -q` → **342 passed**
- `pytest tests/unit tests/dashboard -q` → **902 passed**, 68.90s, 1 pre-existing warning

**Checkpoint:** routes work end-to-end against a real running server with
real data (not just TestClient fixtures); keyboard interaction (Escape)
verified; no illustrative count/status remains anywhere in these three
pages -- every value shown was independently cross-checked against prior
units' live verifications.

### Unit 10 — Attention Center and global search (2026-08-23)

**Files:** `static/js/pages/attention.js` (new),
`static/js/components/search.js` (new), `static/js/app.js`,
`static/index.html`, `static/styles/shell.css`,
`tests/dashboard/js/test_attention_page.mjs`,
`test_search_component.mjs` (both new).

**Test-first:** 4 Node tests for `attention.js`'s `parseAttentionQuery`
(exact `current`/`resolved`/`all` filter set, safe fallback on an
unknown value), 7 for `search.js`'s pure `flattenGroupedResults`
(fixed 5-group order, tolerant of missing/empty groups) and
`nextActiveIndex` (wrap-around in both directions, -1/no-selection with
zero results). All passed on first run.

**Implementation:**
- `attention.js`: a real ledger table (Severity/Condition/Scope/Subject/
  First detected/Last detected/Status columns) over the existing
  `/api/attention` endpoint (Unit 5) -- current/resolved/all filter chips
  round-tripped through the URL, closed severity-then-oldest-first
  ordering already enforced server-side (Unit 3/4), links into the
  relevant repository/issue/execution/run detail. No dismiss control
  exists anywhere in this module, matching docs/27's "never dismissible."
- `search.js`: a labelled combobox/listbox (`role="combobox"`/
  `"listbox"`/`"option"`, `aria-expanded`/`aria-activedescendant`) over
  `/api/search` (Unit 5) -- 200ms debounce, ArrowUp/ArrowDown cycles
  through the flattened grouped results with wraparound,
  Enter navigates and clears the field, Escape closes without moving
  focus (WCAG 1.4.13), and a document-level click outside closes it too.
  No advanced query syntax or search history is exposed anywhere in this
  module.
- Wired into `app.js`'s boot (`initGlobalSearch` on the shell's search
  input) and dispatch table (`attention` route); `index.html`'s search
  markup gained the listbox and full ARIA combobox wiring;
  `shell.css` gained the floating results panel styling
  (`shadow-floating-menu`, active-option highlighting via the token
  system, never color alone -- the active option is also the
  `aria-activedescendant` target).

**Live verification (real browser, against Draindeck's own real
843-event log):** the Attention Center rendered all 28 real current
conditions in a real table with working Current/Resolved/All filters;
switching to "Resolved" surfaced the exact transient system-wide
`LEASE_UNCLAIMED` condition this session's Unit 3 design predicted (the
very first Dashboard process to run against a fresh DB observes-then-
immediately-resolves it on consecutive heartbeats) -- a live confirmation
of that earlier design decision, not just a unit test. The search
combobox: typing "Draindeck" produced a real "REPOSITORIES" group with
the real result; ArrowDown correctly set `aria-activedescendant` to the
first option; Enter navigated to `/repositories/1`, cleared the input,
and closed the list; Escape closed the list while `document.activeElement`
remained the input (verified directly, not assumed). Zero console errors
across every step.

**Diagnostic note:** an initial live check appeared to show the search
listbox never opening after typing -- traced to a race in the TEST
script itself (dispatching a synthetic `input` event immediately after
`navigate()`, before `app.js`'s module script had finished attaching its
listener) rather than an application defect; repeating the same
interaction after allowing the page to settle worked immediately, and
was then verified multiple further times.

**Commands run:**
- `node tests/dashboard/js/test_attention_page.mjs` / `test_search_component.mjs` → both passed
- `pytest tests/dashboard -q` → **344 passed**
- `pytest tests/unit tests/dashboard -q` → **904 passed**, 71.28s, 1 pre-existing warning

**Checkpoint:** keyboard-only search-to-detail flow and resolved-attention
filtering both pass, verified live end-to-end, not just via unit tests.

### Unit 11 — Runs and Issues workspaces (2026-08-23)

**Files:** `static/js/pages/runs.js`, `issues.js` (both new),
`static/js/components/timeline-topology.js` (new, shared), `app.js`,
`static/styles/pages.css`, `tests/dashboard/js/test_timeline_topology.mjs` (new).

**Test-first:** 1 Node test locking `entityUrl`'s kind-to-URL-segment
mapping (issue/run/execution/evidence, correct pluralization) -- the
rest of these three modules is DOM-rendering code, browser-verified per
this build's established pattern for anything requiring live rendering.

**Real bug caught live, fixed immediately, and re-verified clean:**
`timeline-topology.js`'s `renderTopology` threw `ReferenceError:
_entityUrl is not defined` on every Issue/Run detail page. Root cause:
an earlier `replace_all` edit (renaming the private `_entityUrl` helper
to the now-exported `entityUrl`) only matched the exact string
`_entityUrl(repoId, edge.source)` -- the second call site,
`_entityUrl(repoId, edge.target)`, has different arguments and so was a
different string that the same `replace_all` never touched, leaving a
dangling reference to a function that no longer existed. Caught within
seconds of loading the first real Issue Detail page (a live console
error, not silent), fixed, and re-verified with a genuinely fresh
navigation + cleared console (the first re-check after the fix still
showed the old error because the console-message tool accumulates
messages across calls unless explicitly cleared -- clearing and
reloading confirmed zero errors). A worthwhile reminder that
`replace_all` on a specific call-site string, not a bare identifier, can
silently miss sibling call sites.

**Implementation:**
- `timeline-topology.js` (shared): `renderTimeline` -- metadata-only rows
  (event type, linked entity ids, paired absolute/relative timestamp,
  integrity), never payload text. `renderTopology` -- a text-list
  equivalent (the primary accessible representation) of the bounded
  `/api/.../topology` response, with a `truncated` notice linking onward
  rather than implying completeness; `entityUrl` maps each node kind to
  its real detail URL.
- `runs.js`: explorer (Repository/Run/Observed start/Engine/Reviewer/
  Outcome/Inconsistency/Last event columns, cross-repo or
  repository-scoped via the same `render()`) and detail (exact
  "Observed finish: X" / "no controlled finish observed" outcome banner
  -- never "Active"/"Running"; the full configured budget rendered as a
  definition list, never a progress bar; related-entity topology;
  metadata timeline).
- `issues.js`: explorer (Repository/Issue/Title/State/Inconsistency/Last
  event) and detail (state chip, exact "No inconsistency observed" /
  "Inconsistency observed" text, topology, timeline).
- `app.js`: both cross-repo and repository-scoped route names
  (`runs`/`repository-runs`, `issues`/`repository-issues`) map to the
  same explorer render function, which branches on `params.repoId`;
  `run-detail`/`issue-detail` map to the respective detail renderers.

**Live verification (real browser, against Draindeck's own real event
log):** Issues Explorer showed real titles/states (`DONE`/`NEEDS_HUMAN`)
with exact "No inconsistency observed" text; Issue 12's detail page
rendered a real 12-edge topology (issue -> 2 executions -> their runs and
8 evidence rows, all correctly linked) and a real chronological timeline
(`IssueCreated`, `IssueActivated`, `ExecutionSpawned`, `ExecutionFinished`,
...) with correct relative+absolute timestamps. A Run Detail page for a
legacy run_id correctly returned "Run not found." -- this log predates
the RunStarted/RunFinished amendment, so no `run_views` row exists for
it, and the honest 404 is exactly the doc 03 amendment's intended
behavior, not a bug. Runs Explorer correctly showed "No runs observed
yet." for the same reason. Zero console errors on every page after the
one fix above.

**Minor, non-blocking observation (not fixed, not a spec violation):**
`shell.js`'s prefix-based `isActiveRoute` highlights "Repositories" (not
"Runs"/"Issues") for repository-scoped nested detail pages like
`/repositories/1/runs/{runId}`, since that URL structurally starts with
`/repositories/`. This is a defensible interpretation (the page IS
reached via a specific repository) rather than an error; left as-is
given no explicit spec requirement dictates otherwise, flagged here for
visibility rather than fixed silently.

**Commands run:**
- `node tests/dashboard/js/test_timeline_topology.mjs` → passed
- `pytest tests/dashboard -q` → **345 passed**
- `pytest tests/unit tests/dashboard -q` → **905 passed**, 71.19s, 1 pre-existing warning

**Checkpoint:** a run with no observed finish and an issue with real
inconsistency/relationship data are both honestly and completely
rendered, verified live against real evidence, not fixtures alone.

### Unit 12 — Executions, transcript, and diff workspace (2026-08-23)

**Files:** `static/js/pages/executions.js` (new), `static/js/api.js`
(new `apiFetchText`), `static/js/app.js`, `static/styles/pages.css`,
`tests/dashboard/js/test_executions_page.mjs` (new),
`tests/dashboard/js/test_api.mjs` (extended).

**Test-first:** 3 Node tests for `parseGroupBy` (safe fallback to
`"execution"` on any unrecognized value); 2 new tests for `api.js`'s
`apiFetchText` (returns raw text on success without attempting JSON
parse; parses the JSON error envelope on a non-2xx response) added to
the existing `test_api.mjs`. All passed on first run.

**Real gap identified before it could cause a live bug:** the transcript
endpoint returns plain text on success but the standard JSON error
envelope on failure -- `apiFetch` always calls `.json()` and would have
thrown attempting to parse a transcript body as JSON. Added
`apiFetchText` (checks `resp.ok` first, only attempts JSON parsing on
the error path) rather than reusing `apiFetch` and working around the
mismatch in `executions.js` itself.

**Implementation:**
- `executions.js`: explorer with a `groupBy=execution|issue` toggle
  (server-backed via the existing `/api/executions` groupBy support --
  never a client-side join of one page), pagination-correct issue-group
  rows showing exact total/by-state counts. Detail page: metadata rail
  (issue/run/last-event links, nested run metadata handled by the
  existing API contract), a containment-generation list using the exact
  `PREPARED`/`ESTABLISHED`/`UNCONFIRMED`/`RELEASED` states, and a
  `role="tablist"` Transcript/Diff workspace -- both artifacts render as
  `<pre>` text via `textContent` only (verified live, never markup), no
  duration is ever displayed (the contract establishes none), and each
  tab's error/empty state (`ArtifactPathInvalid`/`ArtifactOutsideRoot`/
  `ArtifactNotFound` for transcript; `DiffInvalidCommit`/`DiffUnavailable`
  family for diff) surfaces the real backend message rather than a
  generic failure string.

**Live verification (real browser, against Draindeck's own real
execution history):** Executions Explorer showed real `ACCEPTED`/
`CRASHED`/`REJECTED` state chips across dozens of real executions; the
"By issue" toggle showed real per-issue execution counts with correct
by-state breakdowns (e.g. "3 total (CRASHED: 2, ACCEPTED: 1)"). Execution
`1-e1`'s detail page correctly surfaced two REAL legacy-data edge cases
through the honest error path, not fabricated content: the Transcript
tab showed the real `ArtifactPathInvalid` message ("stored artifact path
must be absolute, got 'state\\artifacts\\1-e1\\transcript.jsonl'" -- this
execution predates the absolute-path requirement), and the Diff tab
showed the real `git diff exited with a non-zero status` message (this
execution's stored commit refs are no longer resolvable in Draindeck's
own evolved git history). Tab switching verified directly: clicking Diff
correctly set `aria-selected="true"`/`"false"` on the two tabs and
toggled both panels' `hidden` state. Zero console errors across every
check.

**Commands run:**
- `node tests/dashboard/js/test_executions_page.mjs` / `test_api.mjs` → both passed
- `pytest tests/dashboard -q` → **346 passed**
- `pytest tests/unit tests/dashboard -q` → **906 passed**, 70.10s, 1 pre-existing warning

**Checkpoint:** every existing artifact/diff error path maps to a
designed, honest state -- verified live against two REAL legacy-data
edge cases in Draindeck's own history, not synthesized fixtures.

### Unit 13 — Evidence explorer/detail and analytics charts (2026-08-23)

**Files:** `static/js/pages/evidence.js` (new), `static/js/components/chart.js`
(new), `static/js/pages/home.js` (edited -- wires `renderBarChart` into
`renderAnalyticsBand`), `static/styles/components.css` (chart-svg/
chart-bar--1..8/chart-label/chart-value-label/forced-colors rules),
`static/styles/pages.css` (`.analytics-chart`), `static/js/app.js` (evidence
routes wired into `_PAGE_MODULES`), `tests/dashboard/js/test_evidence_page.mjs`
(new, 4 tests), `tests/dashboard/js/test_chart_component.mjs` (new, 4 tests),
`tests/dashboard/test_app_shell_contract.py` (`pages/evidence.js` and
`components/chart.js` added to `_NEW_JS_MODULES`).

**Test-first:** 4 Node tests for `parseEvidenceQuery` (before/after id
parsing, direction fallback to `"desc"` on any unrecognized value) written
and confirmed failing before `evidence.js` existed; 4 Node tests for
`capChartEntries` (pass-through under the cap, correct `"Other"` bucket sum
when over the 8-category cap, exact boundary at 8) written and confirmed
failing before `chart.js` existed. All passed on first implementation run.

**Design correction caught before commit:** the Home page's analytics `<dl>`
text summary was initially marked `visually-hidden` after the bar chart was
added, on the (wrong) assumption the chart alone was now the primary
representation. docs/27 requires a genuinely VISIBLE text/table summary
alongside each chart, not an accessibility-tree-only fallback. Reverted
before committing -- both the chart and the `<dl>` are visible.

**Implementation:**
- `evidence.js`: cross-repository or repository-scoped explorer, keyset
  pagination on `evidence.id` (never OFFSET) via `beforeEvidenceId`/
  `afterEvidenceId` + `direction`, "Metadata only -- no raw record bytes or
  payload content is ever shown here." notice always visible. Detail page
  renders Cursor/Event type/Event ID/Schema version/Issue/Execution/Run/
  Observed timestamp/Record hash/Length bytes; the
  "Integrity/corruption details are tracked as repository health..." note
  only appears when `integrity !== "OK"`.
- `chart.js`: `capChartEntries` (caps any category series at 8 bars, folding
  the remainder into an `"Other"` bucket) and `renderBarChart` (SVG bars
  using the `chart-bar--1..8` categorical palette, `<title>` for
  accessibility, keyboard-focusable when a `url` is supplied per bar).

**Live verification (real browser, against Draindeck's own real event
log, 843 evidence records):** Home page analytics band showed correctly
rendered bar charts (Repository availability, Issue lifecycle, Run
outcomes, Evidence integrity) using the forest/teal/clay palette, each
paired with a visible `<dl>` text table beneath it (e.g. "DONE 74",
"NEEDS_DECOMPOSITION 21", "NEEDS_HUMAN 7"). Evidence Explorer showed a
real table ordered newest-first (843 down to 794), all "OK" integrity
chips, real event types/run ids. Evidence Detail for record 843 rendered
every field correctly with no integrity note (record is OK). Keyset
pagination verified end-to-end: the "Next" link's `beforeEvidenceId=794`
correctly fetched and rendered ids 793 down to 744 on click, with a
genuine `GET /api/evidence?limit=50&direction=desc&beforeEvidenceId=794`
request observed on the network tab and the URL updating via `pushState`.
Zero console errors across every check.

**Automation-tool artifact, not an app bug:** the first two attempts to
click "Next" via the browser tool's ref-based click appeared to do
nothing (URL unchanged, no `/api/evidence` request fired, the visible
rows were just the tail of the already-rendered first page, scrolled into
view by the click itself). Root-caused via `read_network_requests` (zero
requests on the ref-click, one correct request on a direct
`element.click()` DOM call) to click-delivery unreliability in the
automation tool for this anchor, consistent with the Unit 9/11 pattern
already noted in this log -- not a router or pagination defect. No code
change was needed; the direct DOM click confirmed the feature works.

**Commands run:**
- `node tests/dashboard/js/test_evidence_page.mjs` / `test_chart_component.mjs` → both passed
- `node tests/dashboard/js/test_home_page.mjs` → passed (no regression from the chart wiring)
- `pytest tests/dashboard -q` → **348 passed**
- `pytest tests/unit tests/dashboard -q` → **908 passed**, 70.08s, 1 pre-existing warning

**Checkpoint:** Evidence explorer/detail and the Home analytics charts are
implemented, tested, and verified live against 843 real evidence records
including correct keyset pagination in both directions.

### Unit 14 — About & Safety, exhaustive states, and hardening audit (2026-08-23)

**Files:** `app.py` (new `/api/about` route, `_dashboard_version()` via
`importlib.metadata`), `static/js/pages/about.js` (new), `static/js/app.js`
(about route wired into `_PAGE_MODULES`), `static/js/pages/repository-detail.js`
(dialog focus-return fix), `tests/dashboard/test_app_about_api.py` (new),
`tests/dashboard/js/test_about_page.mjs` (new, 2 tests),
`tests/dashboard/test_app_shell_contract.py` (`pages/about.js` added to
`_NEW_JS_MODULES`).

**Test-first:** `test_app_about_api.py` written and confirmed failing
(404) before the route existed; 2 Node tests for `buildAboutFacts`
(correct Host/Port/Database/Version ordering) and the exact
`MUTATION_BOUNDARY_TEXT` wording (docs/27 SS6.9's quoted string) written
and confirmed failing (module not found) before `about.js` existed. Both
passed on first implementation run.

**Implementation:**
- `/api/about`: returns only what's genuinely config/build-dependent
  (`host`, `port`, `dbPath`, `version` via `importlib.metadata.version
  ("draindeck")`, falling back to `"unknown"` rather than raising if the
  package metadata is ever unavailable). Every other disclosure docs/27
  SS6.9 requires (loopback-only binding, Host/Origin enforcement,
  self-only CSP/no framing, update-stream meaning, theme storage, no
  auth/remote access) is static text owned entirely by `about.js` -- none
  of it is genuinely a live server fact.
- `about.js`: renders the mutation-boundary quote verbatim plus the five
  other disclosure paragraphs, then a `<dl>` of the four live facts,
  fetched through the same request-coordinator pattern as every other
  page.

**Exhaustive-states and hardening audit (docs/27 SS14, plan Unit 14):**
reviewed every page module's empty/error-state coverage (all nine already
correctly distinguish, e.g., Home/Repositories's "No repositories
registered" vs. "Repositories registered; no data observed yet." per
spec SS6.1), sticky-header focus-not-obscured (`scroll-padding-top` /
`scroll-margin-top`, already correct from Units 7/11), long-path/hash
overflow (`.text-mono { word-break: break-all }`, `.artifact-viewer
{ word-break: break-word }`, already correct from Units 9/12), horizontal
table containment (`.ledger-table-wrapper { overflow-x: auto }`, already
correct from Unit 9), the connection-status live region (`aria-live=
"polite"`, only updated on genuine status-change per Unit 8's state
machine -- no spam), touch target sizes (`.filter-chip` measured live at
65x28 CSS px, comfortably above the WCAG 2.2 SC 2.5.8 AA 24x24 minimum),
and reduced-motion/forced-colors coverage (present in `base.css`/
`tokens.css`/`components.css` since Units 7/13).

**Real gap found and fixed:** the Unregister confirmation dialog
(`repository-detail.js`) moved focus into itself on open but never
returned it to the triggering "Unregister repository" button on close
(Cancel or Escape) -- focus was left to fall back to `<body>` when the
dialog's backdrop was removed, a real keyboard-navigation regression.
Fixed by passing the trigger element into `renderUnregisterDialog` and
restoring focus to it in `close()`, except on a successful delete (where
the trigger no longer means anything and the outgoing route's own
focus-on-navigate correctly takes over). This is DOM-focus behavior with
no headless-Node equivalent (same category as `router.js`'s own
documented Node-test exemption) -- verified live instead.

**Automation-tool artifact caught and re-verified, not an app bug:** a
first live check of the focus-return fix (single combined script:
open dialog, click Cancel, read `document.activeElement`, all in one
`javascript_exec` call) showed focus landing on `<body>`, appearing to
contradict the fix. Splitting the same sequence across two separate
`javascript_exec` calls (open in one, Cancel + assertion in the next)
reproduced cleanly and correctly: `document.activeElement === triggerEl`
on both the Cancel and Escape paths. Treated as the same class of
automation-tool timing artifact already logged in Units 9/11/13, not a
regression -- the isolated, more careful reproduction is the trustworthy
result. A resize-window check at 1024 CSS px also produced one
apparently-clipped screenshot frame that DOM measurement
(`scrollWidth === clientWidth` at every ancestor level, `white-space:
normal` on the paragraphs) immediately proved was a stale capture frame,
not a reflow bug -- logged here as a reminder to cross-check any
suspicious screenshot against a DOM measurement before treating it as a
finding.

**Scope note:** pixel-exact 320/768/1024/1440 browser acceptance with
screenshots is explicitly Unit 15's plan item ("Run browser acceptance at
320/768/1024/1440..."), not Unit 14's ("exhaustive states, and responsive
hardening" -- an audit/implementation pass). The `resize_window` tool's
inability to reliably change the tab's actual viewport in this session
(previously logged) still applies and is carried to Unit 15 unchanged.

**Commands run:**
- `node tests/dashboard/js/test_about_page.mjs` → passed
- `pytest tests/dashboard -q` → **350 passed**
- `pytest tests/unit tests/dashboard -q` → **910 passed**, 69.01s, 1 pre-existing warning

**Checkpoint:** About & Safety is implemented and live-verified against
the real running config (host/port/db path/version), every existing
page's non-ideal states were audited and confirmed correct, and the one
real gap found (dialog focus-return) is fixed and live-verified on both
the Cancel and Escape paths.

### Unit 15 — Scale, security, and full verification (2026-08-23)

**Files:** `tests/dashboard/scale/seed_fixture.py` (new -- deterministic
20/1,000/2,000/10,000/100,000 repos/issues/runs/executions/evidence
fixture, seeded 0.9s in one explicit transaction), `tests/dashboard/scale/
measure_performance.py` (new -- p95 measurement against docs/27 SS14's
budgets), `src/draindeck_dashboard/api_queries.py` (two real fixes, both
below), `tests/dashboard/test_api_queries.py` (2 new tests),
`tests/dashboard/test_security_hardening.py` (new, 5 tests).

**Scale fixture and performance acceptance:** built the approved
representative fixture directly into the Dashboard's own v2 tables (never
through a real observer/target repo, per docs/27 SS13.5) and measured
every endpoint docs/27 SS14 names via `TestClient`, warm-up 3 + 20
samples, p95. All 12 endpoints passed on the first measurement after the
fixes below (see full table in the commands section) -- list/search
endpoints ranged 2.0-32.9ms against a 300ms budget, detail/timeline/
topology ranged 1.9-8.4ms against a 200ms budget, both comfortably inside
docs/27 SS14. `EXPLAIN QUERY PLAN` on the evidence keyset query at 100,000
rows confirmed `SEARCH e USING INTEGER PRIMARY KEY (rowid<?)` -- no table
scan.

**Real bug found and fixed (N+1, flagged as a residual item since Unit
4):** `cross_repository_executions(group_by="issue")` issued 2 extra SQL
statements per issue group on the page (a `by_state` count query and a
"newest N" preview query, each re-deriving `identity_generation_id` via a
redundant correlated subquery) -- bounded by `limit` so never unbounded,
but still O(groups) per page. A new test asserts a fixed statement count
via `conn.set_trace_callback`; before the fix, 20 issue groups produced
42 statements. Fixed by replacing the per-group queries with two
fixed-cost, page-scoped queries: a `GROUP BY` over a `(repository_id,
identity_generation_id, issue_id) IN (VALUES ...)` tuple-membership list
for the state counts, and a `ROW_NUMBER() OVER (PARTITION BY ...)` window
query for the "newest N" preview -- both still fully parameterized (the
VALUES placeholders are the only interpolated SQL, matching docs/27
SS12's "only interpolated fragment is an allowlisted constant" rule,
since the number of placeholders is server-computed from the page size,
never from a value). Verified live at 10,000-execution scale (screenshot:
groupBy=issue renders correct per-issue state breakdowns).

**Real bug found and fixed (row-multiplying JOIN fan-out, found BY the
scale fixture, not anticipated by any existing test):**
`repository_summaries`'s "latest run" LEFT JOIN picked the row(s) matching
`rv.updated_at = (SELECT MAX(...))`, with no tie-breaker -- when the scale
fixture's 100 runs per repository shared a single seeded timestamp (a
realistic case under second-resolution timestamps and concurrent/batch
execution, not just a fixture artifact), the join matched all 100 and
fanned out the repository row into the result set 100 times, corrupting
both the returned `items` and the reported `total` (2,000 instead of 20 in
the live scale check). A new test reproduces the exact tie scenario and
asserts exactly one row/total=1. Fixed with the same `ROW_NUMBER() OVER
(PARTITION BY repository_id ORDER BY updated_at DESC, run_id DESC)`
pattern, breaking ties deterministically on `run_id`. This also improved
`repository-summaries`' own measured p95 from 32.9ms to 5.6ms, since the
`COUNT(*)` no longer scans the fanned-out join.

**Unit 2 residual item evaluated (no code change; flagged for Unit 16
review, not fully closed):** whether fresh-repository backfill should use
`rebuild_read_models` (full-generation) rather than the per-tick
incremental path. `read_models.py`'s own module docstring states the
incremental path handles a previously-OK row's content changing, a
TORN->OK repair, and (by the same reasoning) a fresh append "correctly by
construction." That resolves the Unit 2 fresh-registration question:
correct, by the code's own documented invariant. But confirmed via `grep`
that `rebuild_read_models` is never called anywhere in `indexer.py` or
elsewhere in `src/`, only exercised directly by `test_read_models.py` --
and docs/27 SS8.4 separately states "a previously OK row changing hash,
event ID, decoded content or integrity, or a lower/non-monotonic
projectable event schedules an off-thread scoped rebuild," which reads as
a specific, currently-unimplemented trigger, distinct from the general
"incremental handles it by construction" claim. This is a genuine,
unresolved discrepancy between docs/27 SS8.4's text and the shipped
code's own rationale -- not adjudicated here, since resolving it either
way (wiring a new call site, or amending docs/27's wording) is an
architecture-level decision requiring an ADR (CLAUDE.md), out of Unit
15's scope and blast radius. The `tasks/todo.md` definition-of-done item
"Normal TORN->OK repair is incremental; unsafe OK mutation rebuild is
lease-owned/off-thread" should NOT be checked off on the strength of this
finding alone -- Unit 16's independent contract-honesty review should
make the explicit call.

**Security tests added (`test_security_hardening.py`):** traversal-shaped
path segments (`../../etc/passwd`, URL-encoded, and a Windows UNC-style
`..\\..\\windows\\system32`) on the transcript/diff/issue-detail/
evidence-detail routes all 404 (never 500 or a filesystem read) --
confirmed by code reading that `execution_id`/`issue_id`/`evidence_id`
are always DB lookup keys, never concatenated into a filesystem path
(the actual artifact path is DB-stored and already goes through
`artifacts.py`'s containment check, tested separately in
`test_artifacts.py`). A `<script>` tag in an issue title (free-text
content, unlike a project path which Windows path validation already
rejects such characters from) round-trips exactly through `/api/issues`
and `/api/search` as a properly quoted JSON string with an
`application/json` content-type -- the two properties that actually make
a JSON API safe. An earlier draft of this test asserted the raw
`<script>` substring never appeared in the response bytes at all; that
was a wrong mental model (conflating JSON safety with HTML entity
escaping, which a JSON API neither needs nor should apply) and was
corrected before committing, not forced to pass. Every other item on
docs/27 SS13.2/SS14's security-test list (Host/Origin/CSP/body limits,
sort/filter allowlists, offset caps, bounded topology/search) was already
covered by Units 1-12's own test files -- confirmed present by `grep`
rather than re-implemented.

**Real-browser acceptance (partial, honestly scoped):** ran the full
100,000-row scale fixture against a live smoke instance. Home page
(repository list with real attention/availability chips), Evidence
Explorer (newest record id 100000 correctly first), and Executions
groupBy=issue (the just-fixed N+1 query, live-verified showing correct
per-issue state breakdowns like "4 total (ACCEPTED: 1, CRASHED: 1,
PENDING: 1, VALIDATING: 1)") all rendered correctly with zero console
errors at default (1024+ CSS px) viewport. `resize_window` to 1024 CSS px
was independently confirmed genuine (not a stale render) via
`window.innerWidth`/`scrollWidth` DOM checks in Unit 14 and reused here.
**Known, previously-logged limitation, reconfirmed:** `resize_window` to
320/768 CSS px reports success but does not actually change
`window.innerWidth` in this session (confirmed again directly via a
`javascript_exec` check) -- pixel-exact 320/768/1024/1440 screenshots,
200% text-resize reflow, and forced-colors/reduced-motion live spot
checks remain not independently verified this session. This is the same
gap flagged in Units 9-14, not a new one; the underlying CSS for these
states was code-reviewed and confirmed present in Unit 14. Recorded
honestly rather than claimed as done.

**Commands run:**
- `pytest tests/dashboard/test_api_queries.py -q` → **29 passed**
- `pytest tests/dashboard/test_security_hardening.py -q` → **5 passed**
- `pytest tests/dashboard -q` → **357 passed**
- `pytest tests/unit tests/dashboard -q` → **917 passed**, 69.63s, 1 pre-existing warning
- `python tests/dashboard/scale/measure_performance.py <scratch>/scale_fixture.sqlite3` →
  seeded 20/1,000/2,000/10,000/100,000 in 0.90s; all 12 endpoints PASS
  (overview 20.8ms, repository-summaries 5.6ms, search 23.6ms, issues
  list 1.9ms, runs list 2.7ms, executions list 4.0ms, executions
  groupBy=issue 6.4ms, evidence keyset 9.4ms, repository health 2.9ms,
  repository issues 8.3ms, issue timeline 2.0ms, issue topology 1.9ms --
  all against 300ms/200ms budgets)
- `EXPLAIN QUERY PLAN` on the evidence keyset query at 100,000 rows →
  `SEARCH e USING INTEGER PRIMARY KEY (rowid<?)`, no scan

**Checkpoint:** the approved scale fixture is reproducible test tooling
(committed, not a one-off), every documented performance budget is met
with recorded values, two real defects the fixture surfaced (an N+1
pattern and a row-multiplying JOIN fan-out) are fixed and verified both
in isolated tests and live against the 100,000-row fixture, the Unit 2
residual item is evaluated and documented, and the security-test
checklist is covered with five new tests plus confirmed pre-existing
coverage. The 320/768px live-pixel gap is carried forward honestly, not
silently dropped or claimed complete.

### Unit 16 — Independent reviews, remediation, final documentation (2026-08-23)

**Method:** four fresh-context reviewer agents (no prior conversation
history, cold reads of the diff against baseline `4052fef` plus
docs/27/PRODUCT.md/DESIGN.md/CLAUDE.md) ran in parallel: contract/data
honesty, security, accessibility/visual, and code-quality. Each was told
to check only its own lens and report ranked findings with file:line
evidence, not to fix anything. Findings below are grouped by disposition.

#### Security review: 0 findings requiring action

Zero critical/high/medium/low findings across SQL parameterization
(including the two most recently rewritten queries), path containment,
DOM XSS sinks (zero `innerHTML`/`outerHTML`/`insertAdjacentHTML` in
`static/js/`), security headers/middleware, the mutation surface, and
sort/filter allowlists. Two Info-level, non-blocking observations
(NUL-byte SQLite params, an already-unreachable integer-conversion DoS
guard) recorded for future-proofing only, not acted on.

#### Fixed this unit (real defects, TDD, live-verified)

1. **`run_views.observed_started_at`/`observed_finished_at` were schema
   columns read by three query functions but never written anywhere**
   (code-quality review, independently corroborated by re-tracing
   `projections.py`/`read_models.py` myself before accepting it) --
   `repository_summaries`'s "latest run" field (the exact rewrite from
   Unit 15's fan-out fix), `cross_repository_runs`, and
   `api_run_detail` all silently returned `null` regardless of whether a
   run had actually finished. Undetected because every existing test
   fabricated these columns via a direct SQL insert (bypassing the real
   write path), and my own Unit 15 scale fixture did the same. Root
   cause: `fetch_ok_evidence_rows` never selected `event_ts`, so the pure
   reducer had no timestamp to attach. Fixed by threading `event_ts`
   through `apply_ok_evidence_rows`'s dispatch loop into
   `_apply_run_started`/`_apply_run_finished` (new optional param,
   backward-compatible with every existing call site), adding
   `observed_started_at`/`observed_finished_at` to the `RunView`
   dataclass (set once, on first observation, never overwritten by a
   later recovery -- the first event's timestamp is honestly when the
   run was observed to start/finish), and writing both columns in
   `_write_run_view`. Two new tests in `test_read_models.py` exercise the
   REAL evidence -> reducer -> persisted-row path (not fabricated SQL)
   for both `rebuild_read_models` and `apply_changed_entities` (the path
   every real tick actually uses). Combined suite (921 tests, including
   every legacy `build_projection` consumer) green -- this is a shared
   pure-reducer change, verified against both the v2 and legacy paths.
2. **Lease owner token exposed via `/api/repositories/{id}/health` and
   the new `/overview` endpoint** (contract-honesty review) -- directly
   contradicts docs/27 SS11's explicit "do not expose ... lease owner
   token ... in cross-repository UI summaries." Never rendered by the
   frontend (confirmed zero references), but present on the wire. Fixed
   by removing `ownerToken` from `health.py`'s `build_health()` return
   value entirely -- no consumer needed it. Two new tests in
   `test_security_hardening.py`.
3. **`forced-color-adjust: none` set globally on `:root` inside
   `@media (forced-colors: active)`** (accessibility review) -- this is
   the *inverse* of what forced-colors support requires: it tells the
   browser to keep the authored light/dark palette everywhere instead of
   remapping to the user's System Colors, directly contradicting docs/27
   SS10's "forced-colors: active retains borders, selected state, focus,
   links, and textual status." The already-correct, narrowly-scoped
   `.chart-bar { stroke: CanvasText }` override (added in Unit 13) was
   the only place this kind of override actually belongs. Fixed by
   removing the global rule and documenting why in `tokens.css`.
4. **Unregister confirmation dialog had no keyboard focus trap**
   (accessibility review) -- focus-on-open and focus-return-on-close
   (fixed in Unit 14) both worked, but Tab/Shift+Tab could escape the
   `role="alertdialog"` into the underlying page while the modal backdrop
   was still shown. Fixed with a minimal manual two-button cycle (the
   dialog only ever has Cancel/Unregister) in `repository-detail.js`'s
   `onKeydown` handler. Live-verified: dispatching synthetic Tab and
   Shift+Tab keydowns from either button correctly wraps to the other,
   never escaping.
5. **Router unconditionally stole focus to the main landmark on every
   same-page filter/toggle/search action, not just real navigations**
   (accessibility review) -- directly contradicts docs/27 SS9.2's "focus
   the main heading unless navigation came from a same-page filter."
   Affected the Attention status filter, the Executions groupBy toggle,
   and the Repositories registry search box. Root cause was two-layered:
   (a) `app.js`'s `onNavigate` had no way to know a dispatch came from a
   same-page action rather than a real navigation, and (b) even after
   fixing that, each affected page's `render()` does a full `clear(root)`
   + rebuild on every call, so the *specific DOM node* that had focus is
   always destroyed regardless -- simply not stealing focus to main still
   left focus falling to `<body>`. Fixed both: `router.js`'s
   `dispatch`/`navigate` now thread an `options` object through to
   `onNavigate` (3 new Node tests using an injectable fake
   document/window, exercising the already-designed-for-this
   `documentImpl`/`windowImpl` seam); `app.js` skips `mainContent.focus()`
   when `options.preserveFocus` is set and exposes `ctx.navigate` to page
   modules; `attention.js`, `executions.js`, and `repositories.js` now
   call `ctx.navigate(url, {preserveFocus: true})` instead of manually
   dispatching a synthetic `popstate`, and each explicitly re-focuses the
   newly-rendered equivalent control (the new pressed chip, or the new
   search input with cursor restored to the end) immediately after
   `navigate()` returns -- safe because `render()`'s DOM rebuild for these
   controls runs synchronously before its first `await`, so the
   replacement node already exists by the time the click handler regains
   control. Live-verified via synthetic clicks + `document.activeElement`
   assertions on all three affected pages: the Attention "All" chip,
   Executions "By issue" chip, and the Repositories search box all
   correctly retain focus (or its equivalent-new-node successor) after
   their same-page action, with the URL still updating correctly and zero
   console errors.
6. **`repository_summaries`'s `count_sql` reused the full join including
   the new "latest run" `ROW_NUMBER()` window subquery**, even though
   neither `COUNT(*)` nor the `WHERE` clause reference it (code-quality
   review, directly adjacent to Unit 15's own fan-out fix) -- every
   page-count call re-materialized a window function over every run,
   reintroducing a cost shaped like the fan-out the tie-break fix had
   just removed. Fixed by splitting a `count_joins` (without the `lr`
   subquery) from the row-fetching `joins`.
7. **`capChartEntries`'s docstring claimed it collapses "the smallest
   remainder"**, but the code has never sorted by value -- it keeps the
   first 7 entries in the caller's original order (accessibility review,
   currently latent since every caller passes ≤8 fixed categorical
   values). An existing, deliberately-written test
   (`test_chart_component.mjs`: "first 7 entries keep their original
   order when capping") pins the order-preserving behavior as intentional
   -- reordering by value would make a meaningful fixed category order
   (e.g. issue lifecycle states) less predictable, not more honest.
   Fixed the docstring to accurately describe the real, intentional
   behavior rather than changing behavior a passing test already locks
   in.
8. **Home page's empty recent-activity state said "no evidence observed
   yet"**; docs/27 SS6.1's exact required text is "no data observed yet"
   (contract-honesty review, verbatim-vocabulary check). One-word fix.

#### Evaluated, not fixed -- documented for Unit 16 sign-off / future work

- **`INDEX_PREPARING`/read-model-staleness contract is entirely unwired**
  (contract-honesty review, P0). `errors.py`'s `IndexPreparingError` and
  `read_models.py`'s `read_model_status()` exist but have zero call sites
  anywhere in `src/`; no list/detail endpoint consults `read_model_state`
  before answering, and the frontend never renders "Preparing indexed
  views" despite `/api/overview` already computing
  `projectionState.preparingRepositoryIds` (the value is fetched and
  discarded). This is a closed ADR-27 decision (spec §3.2 decision 9:
  APIs "never expose partially rebuilt rows as complete") that was never
  implemented. **Not fixed this session**: correctly wiring this touches
  every list/detail query function's response shape plus new frontend
  states across every explorer page -- a substantial, cross-cutting
  feature, not a contained bug fix, and too large to safely implement
  without dedicated planning at the tail of an already-long session. Real
  gap in shipped behavior: a newly-registered or currently-rebuilding
  repository returns a plain empty list, indistinguishable from
  "genuinely zero items," rather than the spec's required typed signal.
- **`LEASE_UNCLAIMED`'s documented 10-second no-startup-flash gate is not
  implemented** (contract-honesty review, P1). `attention.py` explicitly
  defers this to "the query layer," but `GET /api/attention` has no age
  check on `first_detected_at`. Not fixed: touches lease/attention timing
  semantics, needs care to avoid a regression in the reconciliation path.
- **Execution Detail is missing nested run metadata / exact legacy
  fallback** (contract-honesty review, P1). `format.js`'s
  `runMetadataText()` (with the spec's exact
  `"run metadata unavailable (legacy/ambiguous)"` fallback string) is
  imported in `pages/executions.js` but never called -- scaffolded per
  spec, never wired to the actual detail view. Not fixed: needs a backend
  response-shape addition plus frontend wiring, deferred rather than
  rushed.
- **Repository Overview's attention count is live-recomputed
  (`derive_repository_conditions()` on every request) while
  `/api/repository-summaries` and `/api/attention` both read the
  persisted, reconciler-owned `attention_conditions` table** (contract-
  honesty review, P2) -- the two "current attention count" numbers shown
  for the same repository on different screens can genuinely disagree in
  the window before the next reconciliation tick. Needs a data-source
  decision (which is authoritative), not fixed this session.
- **`app.py` hand-writes SQL directly in several route handlers**
  (`api_attention`, `api_issue_detail`, `api_run_detail`,
  `api_execution_detail`, `api_evidence_detail`), contradicting its own
  stated "thin wrappers only" architecture comment (code-quality review,
  P1). Pure refactor, no behavior change, no correctness risk -- deferred
  as lower priority than the defects above given remaining session
  budget.
- **Duplicated render/fetch/error scaffolding across `issues.js`,
  `runs.js`, `executions.js`, `evidence.js`, `attention.js`,
  `repositories.js`**, and **`syncList` (built in Unit 7 specifically to
  preserve focus/scroll across a background refresh) used by only 2 of 7
  list pages** (code-quality review, P1). A real quality gap, but a
  cross-file refactor this late in the build carries real regression risk
  for marginal benefit -- deferred rather than rushed through without a
  dedicated slice of its own.
- **`cross_repository_executions`'s `groupBy=issue` batched queries
  ignore the caller's `state` filter** when computing each group's
  `byState`/`newestExecutions` breakdown, showing the full picture for a
  matched issue rather than a state-filtered one (code-quality review,
  P2) -- plausibly intentional, left as-is per the reviewer's own
  suggestion, flagged here rather than silently resolved either way.
- **`path.replace("\\", "/").rsplit("/", 1)[-1]` duplicated 6 times** in
  `api_queries.py` (code-quality, P2) and **the executions/issues tab
  list has no arrow-key navigation** (accessibility, P2) -- both minor,
  deferred.
- **`rebuild_read_models()` confirmed unreachable from any production
  code path** (code-quality review, independently re-confirmed by a
  fresh `grep` trace) -- corroborates the Unit 15 evaluation. Its own
  docstring's claim of being "used for ... Sub-step B" never landed. Left
  as an open architectural question, not resolved here (see Unit 15's
  entry and NEXT.md).

**Commands run:**
- `pytest tests/dashboard/test_read_models.py -q` → **12 passed**
- `node tests/dashboard/js/test_router.mjs` → **10 passed** (3 new)
- `node tests/dashboard/js/test_attention_page.mjs test_executions_page.mjs test_repositories_page.mjs` → all passed
- `pytest tests/dashboard -q` → **361 passed**
- `pytest tests/unit tests/dashboard -q` → **921 passed**, 71.78s, 1 pre-existing warning
- Live verification: dialog focus trap (Tab/Shift+Tab cycle confirmed via
  synthetic KeyboardEvents), Attention/Executions/Repositories same-page
  focus preservation (confirmed via `document.activeElement` assertions),
  zero console errors on every check

**Checkpoint:** four independent fresh-context reviews found zero
security defects and eight real, fixable contract/accessibility/quality
defects, all fixed test-first and live-verified; six further findings are
evaluated and explicitly documented as deferred (not silently dropped),
with a clear rationale for each. This is the final implementation unit;
see the handoff summary below for outcome, files changed, and residual
risk.

## 2026-08-23 continuation: closing the 8 unchecked definition-of-done gates

Unit 16 (above) closed its own review round but left 8 `tasks/todo.md`
definition-of-done checkboxes unchecked and explicitly documented 6 residual
gaps, several of them spec-required rather than optional polish. This
continuation, resuming `/build-auto` from baseline `7cdb23b`, closed every
one of them. Full narrative, exact commands, and exact numbers are in
`tasks/todo.md`'s "2026-08-23 continuation" evidence-log entry; this section
summarizes outcome and disposition only.

- **INDEX_PREPARING/REBUILDING/READY (was: "unwired end-to-end", the single
  largest documented gap):** now wired end-to-end. A real, pre-existing bug
  was found and fixed en route — every incremental write was immediately
  marking the read-model state READY, which fabricated completeness and is
  the reason this contract was never observable in practice even though the
  supporting error type (`IndexPreparingError`) already existed.
- **`rebuild_read_models()` production caller (was: "confirmed unreachable
  from any production code path"):** now has a real lease-owned caller in
  `scheduler.py`, preserving atomic publication and lease-loss protection,
  with 9 new integration test scenarios.
- **LEASE_UNCLAIMED 10s gate (was: "unimplemented"):** implemented, scoped
  correctly (LEASE_STALE never delayed), tested, and — after this session's
  own independent review caught a gap — also applied to `/api/overview`'s
  attention aggregate for parity with `/api/attention`.
- **Nested run metadata (was: "not surfaced"):** surfaced, with the exact
  spec-required fallback text.
- **Repository Overview attention-count divergence (was: documented as a
  self-correcting P2 cosmetic issue):** the data source itself was
  corrected, not just the timing window narrowed.
- **Focus/scroll survival on SSE refresh (was: "`syncList` is used by 2 of 7
  list pages; the other 5 do a full clear+rebuild"):** all 7 list pages now
  use `syncList` via a `render`/`refresh` split in `app.js`, and a second,
  more subtle bug in `syncList` itself (reorder churn around a focused row)
  was caught by this session's own independent code review and fixed.
- **320/768px + 200% text resize + reduced-motion + forced-colors (was:
  "not independently verified -- tooling limitation"):** 320/768/1024/1440px
  and 200% text resize are now live-verified against the real running app
  via a working alternate mechanism (a local CSP-relaxing reverse-proxy +
  iframe harness, since `resize_window` remains unreliable and
  `frame-ancestors 'none'` otherwise blocks iframe-based testing).
  `prefers-reduced-motion` is now live-verified via rule injection.
  `forced-colors: active` remains code-review-only — true browser-level
  media-feature emulation was not achievable via any tooling this session
  had access to (see `tasks/todo.md` for the specific constraints ruled
  out); this is the one item in this list that is still verified by code
  reading rather than live pixels, and is called out as such rather than
  marked fully closed.
- **Tablist keyboard behavior:** not in Unit 16's original 6-item gap list,
  but flagged as a P2 accessibility finding at the time; closed this session
  with the standard WAI-ARIA APG roving-tabindex pattern.
- **Event-loop responsiveness / lease-starvation proof (was: "not
  independently re-instrumented/re-measured... Unit 15 measured post-seed
  query latency, not live event-loop responsiveness during an active
  backfill tick"):** a new measurement script now proves both a 100,000-row
  rebuild and a maximum 2,000-record tick complete well within budget
  without starving lease renewal, against the real production worker class.

**Checkpoint:** 2 fresh-context independent reviews (code-reviewer,
security-auditor) ran against this continuation's full diff before its
final commit. Security: 0 findings. Code review: 2 Important findings, both
real, both fixed test-first and live-verified (the `syncList` reorder bug
above, and the `/api/overview` LEASE_UNCLAIMED gate gap above); 2 low-
severity suggestions reviewed and accepted as-is. Full combined suite: 960
passed (958 -> 960 after the 2 new review-fix regression tests), 0 failed.
No merge, no push, no `src/runtime` modification.

## Final handoff

- **Outcome:** Units 0-16 plus the 2026-08-23 continuation (above) of the
  Dashboard Redesign (docs/27, ADR-27) are complete on branch
  `dashboard-redesign`. 960/960 combined `tests/unit
  tests/dashboard` suite green at the final commit. The old Part 2 static
  UI is fully retired; every route in docs/27 §4/§9.1 is implemented,
  tested, and live-verified against a real browser and Draindeck's own
  real event/execution history plus a 100,000-row scale fixture.
- **Files changed:** every commit from Unit 0 (`1828f58`-adjacent) through
  this continuation's final commit (`6f8246f`) is scoped to
  `src/draindeck_dashboard/`, `tests/dashboard/`,
  `docs/27-dashboard-redesign-spec.md`,
  `docs/08-session-0-closure-and-adr-amendments.md` §5i,
  `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`, `tasks/`,
  `PRODUCT.md`, `DESIGN.md`, and `NEXT.md`. **`src/runtime` was never
  touched** (confirmed: `git diff 7cdb23b..HEAD --stat -- src/runtime` is
  empty). No dependency was installed.
- **Migration/compatibility:** the v1->v2 SQLite migration
  (`migrations.py`) is additive-only, applied automatically on next
  connect, tested for concurrent-start safety, idempotent restart, and
  rollback-on-failure (Unit 1). No existing evidence/registration/
  checkpoint/generation/corruption/lease row is ever touched by the
  migration or by any new query. The legacy Phase 5 per-repository
  endpoints and the old static UI's server-side routes remain unchanged
  and still pass their original tests.
- **Test results:** `pytest tests/unit tests/dashboard -q` → **960 passed**
  (560 unit + 398 dashboard), run twice for consistency, 0 failed. Scale/
  performance acceptance (`tests/dashboard/scale/measure_performance.py`)
  passes all 12 measured endpoints against docs/27 SS14's budgets on the
  20/1,000/2,000/10,000/100,000-row fixture (Unit 15). Event-loop/lease-
  starvation acceptance (`tests/dashboard/scale/measure_event_loop_
  responsiveness.py`, new this continuation) passes both scenarios (a
  100,000-row single-repo rebuild and a maximum 2,000-record tick) against
  a real `ReadModelWorker`, run twice for consistency (see the 2026-08-23
  continuation entry above for exact figures).
- **Browser/accessibility/security results:** extensive real-browser
  verification across Units 6-16 plus this continuation covering every
  route's populated/empty/loading/error/reconnecting/preparing/stale
  states, keyboard-only interaction (search, dialogs, tabs, tablist arrow
  keys, filters), focus-not-obscured-by-sticky-header, zero console errors
  throughout, and CSP/security headers on every route. 320/768/1024/1440
  CSS px and 200% text resize are now live-verified against the real
  running app (a local CSP-relaxing reverse-proxy + iframe harness, since
  `resize_window` remains unreliable this session and `frame-ancestors
  'none'` otherwise blocks iframe-based testing); `prefers-reduced-motion`
  is live-verified via rule injection. **One honestly-carried gap
  remains**: `forced-colors: active` is verified by code review only
  (`.chart-bar` System Colors override) — true browser-level forced-colors
  media-feature emulation was not achievable via any tooling available
  this session (no working DevTools/CDP Emulation access; OS-level
  high-contrast toggling is out of scope as a system-settings change).
- **Independent review findings and dispositions:** Unit 16's own review
  round (above) found 0 security defects and 8 real contract/accessibility/
  quality defects, all fixed; 6 further findings were deferred with
  rationale — this continuation closed every one of those 6 (see the
  2026-08-23 continuation entry above). This continuation then ran its own
  fresh 2-reviewer round (code-reviewer, security-auditor) against its own
  diff: 0 security findings; 2 Important code-quality findings, both real,
  both fixed test-first and live-verified/tested (a `syncList` reorder-
  churn bug and a missing LEASE_UNCLAIMED gate on `/api/overview`); 2
  low-severity suggestions reviewed and accepted as-is. No open P0/P1/P2
  finding remains from either review round.
- **Residual risks:**
  1. `forced-colors: active` true browser-level rendering is verified by
     code review only, not live pixels — a tooling limitation of this
     session's available browser-automation access (see above), not a
     known code defect.
  2. `dom.js`'s `syncList` intentionally lags a focused row's *content*
     behind newly-arrived data until focus moves elsewhere (it never
     reorders or re-renders a currently-focused row's interior) — a
     disclosed, reviewed tradeoff against the alternative of yanking focus
     out from under an actively-focused control on every SSE update, not
     a defect.
- **Git status:** working tree clean at each unit/continuation commit
  boundary; every commit is its own local checkpoint exactly as
  authorized. **No merge, no push, and no `src/runtime` modification at
  any point in this branch's history.**

## Final verification

- Focused tests: run throughout (TDD per item, failing-first where
  applicable — see the 2026-08-23 continuation entry for the specific new
  test files/counts per item)
- Dashboard suite: `pytest tests/dashboard -q` → **398 passed**
- Combined unit + Dashboard suite: `pytest tests/unit tests/dashboard -q`
  → **960 passed**, run twice for consistency, 0 failed
- Real-browser/accessibility review: run — 320/768/1024/1440px, 200% text
  resize, keyboard-only, focus-not-obscured, and reduced-motion all
  live-verified against the real running app this continuation;
  forced-colors verified by code review only (see Residual risks above)
- Scale/performance review: run —
  `tests/dashboard/scale/measure_performance.py` (Unit 15, pre-existing,
  still passing) and `tests/dashboard/scale/measure_event_loop_
  responsiveness.py` (new this continuation, 2 runs, both PASS)
- Security review: run — fresh-context security-auditor pass this
  continuation, 0 findings at any severity
- Independent reviews: run — code-reviewer + security-auditor this
  continuation; 2 Important findings, both fixed and verified; see above
- Final working tree / commit list: clean; `7cdb23b..HEAD` is 10 commits
  (`143625f`, `0ac006c`, `f4343c5`, `0d9a42a`, `553032e`, `0fd6f82`,
  `28312d1`, `f053e4e`, `6f8246f`, plus this documentation commit), each
  scoped to exactly the item(s) it names in its message
