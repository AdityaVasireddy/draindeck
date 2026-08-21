# Dashboard Part 2 specification

**Status:** Accepted (ADR-26 accepted 2026-08-20). Phases 1-6 below may
proceed under this acceptance. The Phase 7 run-lifecycle section
("Run lifecycle compatibility") still requires the separate frozen Doc 03
amendment, its own review, and explicit acceptance before any source change,
per ADR-26's "Required Doc 03 amendment before implementation."

## Purpose and dependency boundary

Draindeck Dashboard is a local FastAPI/Uvicorn application with a static
vanilla HTML/CSS/JavaScript UI in a separate `draindeck_dashboard` package.
ADR-26 authorizes those frameworks only for that package; core `src/runtime`
remains framework-free. SSE uses Starlette `StreamingResponse`, not another
SSE dependency. The package lives at `src/draindeck_dashboard`; FastAPI and
Uvicorn are declared under `[project.optional-dependencies].dashboard`, so a
core-only Draindeck install does not pull the web stack.

Dashboard consumes ADR-25 only through an operator-configured absolute
observer executable. It invokes `observe events --log <absolute> --limit 500
--format json` with `shell=False` and a minimal allowlisted child environment
that excludes `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
`ANTHROPIC_BASE_URL`, and unrelated credentials. It never parses
`events.jsonl` directly, opens a Draindeck mutex, repairs a log, or invokes Git
through its observer adapter.

## Local web security

The unauthenticated server binds only to `127.0.0.1` by default and refuses
non-loopback Host/Origin values; CORS is disabled. Remote binding is out of
scope and requires a future authentication/TLS ADR. Responses set a restrictive
self-only Content-Security-Policy, `frame-ancestors 'none'`, nosniff, and
referrer-policy headers. API body, path, pagination, and SSE connection counts
are bounded. SQLite uses parameterized statements only. UI renders all event,
path, and error text via `textContent`, never untrusted `innerHTML`.

## Registration and polling

`POST /api/repositories` accepts `projectPath` and `logPath`. `logPath` must
be absolute; absence is valid and becomes NOT_INITIALIZED, while an existing
non-regular file is rejected. `projectPath` must be an absolute, existing Git
work-tree directory. Canonical `logPath` is unique across registrations; one
projectPath may have distinct logs. Dashboard never loads target config.yaml
or reproduces `resolve_event_log_path`.

`observe status --format json` is registration diagnostics only. Hot polling
uses only `observe events --format json`: global concurrency four, 10-second
timeout and 2-second AVAILABLE/EMPTY interval. OFFLINE and NOT_INITIALIZED use
exponential backoff from 2 to 60 seconds. Availability comes from the events
response `metadata.availability`. Catch-up processes at most four 500-record pages per
tick and never drains `hasMore` in an unbounded loop.

Observer output is untrusted and schema-validated. Exit-1 JSON errors
(`CURSOR_INVALID`, `CURSOR_LOG_REPLACED`, `LOG_PATH_NOT_ABSOLUTE`,
`LOG_PATH_NOT_REGULAR_FILE`, `LIMIT_OUT_OF_RANGE`), exit-2 argparse text,
timeout, executable-not-found, non-UTF8 output, and non-JSON stdout map into
`{ "error": { "code", "message", "details?" } }` without exposing raw child
environment or unsafe stderr.

## SQLite, lease, and identity generations

SQLite uses WAL and a 5-second busy timeout. Exactly one Dashboard process
owns the indexer lease; followers serve API/SSE reads but do not index. API
writes and one observed page are each one short transaction. The lease has an
opaque owner token, 2-second heartbeat, 10-second TTL, and atomic conditional
takeover after expiry. Followers surface fresh/missing/expired lease state.

Each observed `(contentLineage, fileGeneration)` opens an identity generation.
If `fileGeneration.available` is false, identity is lineage-only and the UI
surfaces reduced confidence. `CURSOR_LOG_REPLACED` is not itself proof of
replacement because transient open failures use the same error. Back off as
OFFLINE and perform an `after=None` identity probe. Roll generation only when
a successful AVAILABLE/EMPTY probe differs; same identity retains the
checkpoint, and an unavailable probe never rolls generation.

## Cursor, idempotency, and integrity

The durable checkpoint is `(lastRecordCursor, recordHash, contentLineage,
fileGeneration)`, never `nextCursor` alone. Page `nextCursor` is exclusive only
for limit-based `hasMore`; at a TORN/OVERSIZED tail it is pinned inclusively to
the delivered incomplete record, and it is null when caught up. Each record
cursor is inclusive.
The boundary record is therefore intentionally re-delivered on the next poll.
Idempotent upsert keyed by `(repository, identityGeneration, recordCursor)` is
a steady-state requirement.

CORRUPT applies only when two `integrity == "OK"` records sharing the same
non-null integer `eventId` have different `recordHash` values within one
identity generation. TORN,
MALFORMED, and OVERSIZED evidence may change at the same cursor and never
triggers CORRUPT. Unknown complete event types remain evidence.

OVERSIZED is retained and then terminally halts indexing for that repository:
ADR-25 exposes no safe cursor beyond it. The API/UI must say why progress
stopped and require operator remediation; it must not spin on `hasMore`.

Deleting a registration removes only Dashboard-owned rows, never the log,
artifacts, or repository. A log deleted after registration becomes
NOT_INITIALIZED while prior evidence remains available.

## REST API, SSE, and UI states

Initial resources are:

- `POST`/`GET /api/repositories`
- `GET`/`DELETE /api/repositories/{id}` and `GET .../{id}/health`
- `GET /api/repositories/{id}/issues`
- `GET /api/repositories/{id}/executions`
- `GET /api/repositories/{id}/evidence`
- `GET /api/events` (SSE)

Lists are paginated. One indexed monotonic `change_sequence` is the only SSE
cursor and event ID. The latest 10,000 changes are retained; replay is capped
at 1,000 per connection. An expired or over-limit cursor returns
`CHANGE_RESYNC_REQUIRED` before streaming so the client performs a REST
refresh. SSE emits `retry: 3000` and a 15-second heartbeat. Each process has
one database tailer fanned out in memory to subscribers.

ADR-25 hardcodes writerState UNKNOWN, so every EXECUTING execution is
**Pending reconciliation** in Part 2 and Running is unreachable. Dashboard
must not invent a liveness probe. UI states include NOT_INITIALIZED, EMPTY,
AVAILABLE, OFFLINE, CORRUPT, OVERSIZED-halted, unknown-event-type, reduced
identity confidence, and empty repository/issue/execution views. Followers
show a stale-indexer banner when the lease is missing or expired. DOM changes
are incremental and keyed by stable API row ID; polling never rebuilds the
whole page and destroys focus/scroll.

## Artifacts and diffs

Artifact root is `<resolved log parent>/artifacts`, never a hard-coded
`.draindeck/state/artifacts`. A non-absolute stored `transcript_path` is
rejected safely. Root and candidate are canonicalized to final filesystem
paths, including symlinks, Windows junctions, and 8.3 aliases, before
containment. Outside-root access is 403; contained-but-missing is 404.

Derived Git diff uses `--no-pager`, `--no-ext-diff`, and `--no-textconv`, a
strict output cap, `shell=False`, and no repository-controlled external diff.

## Run lifecycle compatibility

Historical events already carry legacy timestamp-only `run_id` values but no
RunStarted. Projections accept both ID formats, never claim legacy IDs are
collision-free, and render `run metadata unavailable (legacy/ambiguous)`
instead of an empty provider/model panel.

After the separate Doc 03 amendment, RunStarted is emitted before checkout
and ingestion, and RunFinished covers CHECKOUT_FAILED, REVIEWER_UNREACHABLE,
BASELINE_FAILED, INGEST_FAILED, COMPLETED, HALTED, and INTERRUPTED. Abrupt
death has no fabricated finish. Provider/model and config digest appear only
after this core change passes its focused tests and both durability seeds.

## Verification

Tests cover registration uniqueness, observer invocation/error mapping,
bounded catch-up, terminal OVERSIZED behavior, inclusive-cursor idempotency,
identity replacement, OK-only corruption, lease takeover, WAL readers, SSE
resume/resync/heartbeat, every UI state, artifact canonicalization, and diff
hardening. Any core event change additionally runs the complete unit suite and
crash harness seeds 42 and 1337.
