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

### Unit 4–16

Not started. Add one dated subsection per completed unit; never combine
untested partial work with a completed checkpoint.

## Final verification

- Focused tests: not run
- Dashboard suite: not run
- Combined unit + Dashboard suite: not run
- Real-browser/accessibility review: not run
- Scale/performance review: not run
- Security review: not run
- Independent reviews: not run
- Final working tree / commit list: not recorded
