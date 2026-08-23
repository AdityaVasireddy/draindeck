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

### Unit 3–16

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
