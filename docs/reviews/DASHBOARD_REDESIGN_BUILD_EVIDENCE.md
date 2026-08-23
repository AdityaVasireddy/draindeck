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

### Units 2–16

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
