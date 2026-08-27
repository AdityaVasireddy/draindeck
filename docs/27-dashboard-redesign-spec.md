# Dashboard Redesign — Product, Interface, and Proposed ADR-27

**Status:** ACCEPTED 2026-08-23 — implementation authorized (Units 0-16, local per-unit checkpoint commits authorized; merge/push remain prohibited)<br>
**Date:** 2026-08-22<br>
**Baseline:** `dashboard-redesign` at `4052fef97dbb90b52ae91fc01832557bc348cab8`<br>
**Scope owner:** `src/draindeck_dashboard` only; `src/runtime` contracts remain untouched

> Cross-reference: the coding-engine **proxy cost** feature (SQLite v2→v3,
> `proxyCost` API, cost UI) is specified separately in
> `spec/coding-engine-proxy-cost.md` and recorded in `docs/28-proxy-cost.md`.
> This document (docs/27) is otherwise unchanged by that feature.

## 1. Objective

Replace the single plain Dashboard page with a production-quality desktop/tablet-focused operator application that showcases and makes navigable every Dashboard-supported Draindeck feature: repository registration and health, attention triage, runs, issues, executions, containment generations, transcripts, diffs, evidence, connection state, and local-safety facts. Non-tabular content still reflows to 320 CSS pixels for WCAG 2.2 AA; this accessibility behavior does not expand v1 into a mobile-specific product.

The landing page is an operator home—not marketing—and fuses cross-repository health with current attention. Every entity receives a linked, bookmarkable screen. The redesign remains honest about observation boundaries, scales to approximately 20 repositories / 1,000 issues / 10,000 executions / 100,000+ evidence rows, and meets WCAG 2.2 AA.

Implementation remains vanilla HTML, CSS, and JavaScript. React or another client framework is neither required nor authorized. Additive FastAPI endpoints, indexes, and Dashboard-owned SQLite projections are authorized only after this proposal is approved; core runtime modules, events, state transitions, locks, repositories, logs, and artifacts are out of scope.

## 2. Binding product and visual sources

- `PRODUCT.md` defines users, purpose, voice, anti-references, and design principles.
- `DESIGN.md` defines the machine-readable visual tokens and six-section visual system.
- `.impeccable/design.json` supplies component snippets, tonal ramps, motion, shadows, and breakpoints.
- The approved north-star comp is currently stored outside the repository at `C:\Users\adity\.codex\generated_images\01a02712-d394-77d0-81b1-05ba0dec2259\exec-fa4c0002-557b-43b2-a32e-5fdfabda34c4.png`. It is a visual reference only; its sample values and labels are not API contracts.
- `docs/19-dashboard-part-2-spec.md`, ADR-25, and ADR-26 remain authoritative wherever this proposal does not explicitly add a Dashboard-only contract.

### 2.1 Mock fidelity inventory

| Mock element | Fidelity | Implementation rule |
|---|---|---|
| Forest rail, cream workspace, editorial typography | Production target | Implement from `DESIGN.md` tokens. |
| Global search, theme control, update status | Production target | Back with the contracts in this document. |
| Repository table and Attention Center | Production target | Use real aggregates/current conditions; never hard-code sample counts. |
| Lower charts and mini topology | Directional layout | Render only the bounded metrics/relationships defined here. |
| Names, counts, dates, statuses, chart shapes | Illustrative sample data | Replace entirely with API data and defined empty/error states. |
| “Live,” “running,” percentage progress, verification language | Rejected | Use the exact honest vocabulary in §5. |

## 3. Proposed ADR-27 — Dashboard read models and multi-screen shell

### 3.1 Context

The existing Dashboard deliberately shipped a small static UI and list APIs. Its issue, execution, and run views rebuild the entire current-generation projection in memory on each request. That is correct at Part 2 scale but cannot support cross-repository search, attention history, aggregate charts, stable detail pages, and the approved 100,000-row evidence envelope without repeated full scans or incomplete client-side joins.

### 3.2 Decision

1. Keep `src/runtime` frozen. All new code and database state live inside `src/draindeck_dashboard` and its tests/static assets.
2. Add Dashboard-owned, current-generation materialized read models for issues, executions, runs, and containment generations. They are derived caches, not new runtime truth. Evidence remains the source of truth.
3. Add a Dashboard-owned attention-condition history derived from repository health and projection facts. It records when Dashboard first/last detected a condition and when it resolved; it is not an event-log warning stream and is never dismissible.
4. Add bounded REST endpoints for overview, repository summaries, current/resolved attention, simple grouped search, entity details, metadata-only timelines, scoped topology, and aggregates. Existing endpoints and response fields remain valid.
5. Add semantic client-side routing with server fallback for approved UI routes. API routes and static assets remain distinct; unknown UI routes render a not-found screen with HTTP 404 where practical, never an API-shaped false success.
6. Keep SSE as invalidation, not data transport. A change event identifies affected repository/entity; the client refetches the smallest relevant REST resource and patches keyed subnodes without replacing focused controls. The event envelope/resume rules remain unchanged, while `entityType` is explicitly an extensible string: v2 adds `attention`, `repository_health`, and `read_model`; repository-scoped changes carry the real repository ID and system-wide changes use reserved `repositoryId: 0` (repository IDs begin at one).
7. Use no new browser or Python dependency. Charts and topology use semantic HTML/SVG; icons are inline SVG; themes use CSS custom properties and local storage.
8. Keep request-serving work responsive. Potentially expensive reads run through a bounded thread offload using a short-lived SQLite connection; migration DDL remains a small startup transaction, while projection backfill/rebuild runs only after lease acquisition in a dedicated worker with its own connection. The event loop never performs a full evidence scan or projection rebuild.
9. Store per-repository-generation read-model readiness. APIs either serve the last complete snapshot labelled `stale/rebuilding` or return typed `INDEX_PREPARING` when no complete snapshot exists; they never expose partially rebuilt rows as complete.

### 3.3 Alternatives rejected

- **Client-side joins over existing paginated lists:** incomplete whenever related entities fall on a different page and expensive across repositories.
- **Full projection rebuild per request:** repeated O(evidence) work and poor latency at the approved scale.
- **Large startup backfill inside `init_schema`:** blocks every ASGI response and races across Dashboard processes before lease election.
- **Direct browser or server reads of target JSONL:** violates ADR-25/26's observer and indexed-read boundary.
- **Raw evidence/payload endpoint:** unnecessarily exposes observed content and creates a sanitization/size contract not required for this redesign.
- **Warning inbox with dismiss:** no runtime warning entity exists; dismissal would introduce unexplained mutable semantics.
- **Framework migration:** adds build/runtime surface without solving a requirement the current stack cannot satisfy.

### 3.4 Consequences

- SQLite schema advances additively from v1 to v2 through a short transactional, idempotent DDL migration. The migration never deletes or rewrites evidence. Derived-row backfill is a separate lease-owned background operation, not part of `init_schema`.
- Projection code becomes both pure/testable and persistable. Normal new evidence applies incrementally. A repaired tail `TORN → OK` row is append-equivalent when the prior row contributed no lifecycle state and the new event remains monotonic; it does not force a rebuild. A previously `OK` row whose hash/event ID/content changes, an `OK → non-OK` transition, or a non-monotonic newly projectable row triggers a deterministic lease-owned rebuild of only the affected repository generation.
- Attention timestamps mean “first/last detected by this Dashboard database,” not when the underlying runtime condition originally began.
- Existing consumers keep working. New fields may be added to existing item objects only when additive; existing endpoint shapes are not repurposed.
- ADR-27 is not accepted merely because this file exists. Source implementation begins only after explicit review/approval of this document and `tasks/plan.md`.

## 4. Information architecture and routes

The shell contains a persistent navigation rail, top utility bar, breadcrumbs, main content landmark, and one polite global status region. Primary destinations are Home, Repositories, Attention, Runs, Issues, Executions, Evidence, and About.

| Screen | UI route | Primary job |
|---|---|---|
| Operator Home | `/` | Cross-repository health, active attention, recent observed activity, and navigation into filtered records. |
| Repository Registry | `/repositories` | Search, sort, paginate, add, inspect, and unregister repositories. |
| Add Repository | `/repositories/new` | Register absolute project/log paths with validation and precise safety copy. |
| Repository Overview | `/repositories/{repoId}` | Availability, health facts, attention, identity generation, lease facts, and repository aggregates. |
| Attention Center | `/attention` | Cross-repository current/resolved detected conditions sorted by severity. |
| Runs Explorer | `/runs` and `/repositories/{repoId}/runs` | Cross-repository or scoped paginated run comparison. |
| Run Detail | `/repositories/{repoId}/runs/{runId}` | Observed run metadata, exact outcome, related executions, metadata timeline, and scoped topology. |
| Issues Explorer | `/issues` and `/repositories/{repoId}/issues` | Cross-repository or scoped issue lifecycle browsing. |
| Issue Detail | `/repositories/{repoId}/issues/{issueId}` | State, title, inconsistency, chronological metadata timeline, executions, and mini topology. |
| Executions Explorer | `/executions` and `/repositories/{repoId}/executions` | Filtered comparison with By execution / By issue presentation. |
| Execution Detail | `/repositories/{repoId}/executions/{executionId}` | State and run metadata plus transcript/diff workspaces and evidence timeline. |
| Evidence Explorer | `/evidence` and `/repositories/{repoId}/evidence` | Integrity-aware, metadata-only ledger with pagination and filters. |
| Evidence Detail | `/repositories/{repoId}/evidence/{evidenceId}` | Exact stored metadata and links to related entities; no raw text/payload. |
| About & Safety | `/about` | Local-only, mutation-boundary, connection, database, and version facts. |

Query parameters may encode only shareable list state: `page`, `pageSize`, `sort`, `direction`, and named filters. For offset-paginated APIs, UI `page` is one-based and maps to `offset = (page - 1) × pageSize`, with both values checked against the bounds in §7. Global search uses `q`. Evidence uses keyset URL parameters (`beforeEvidenceId` / `afterEvidenceId`) rather than an arbitrarily deep page number. The application does not promise restoration of scroll position, open drawers, column widths, or transient disclosure state.

“Stable/bookmarkable” means stable inside the same Dashboard SQLite database while the registration and current identity generation still exist. Repository unregistration or identity-generation rollover may legitimately make an old entity/evidence URL return 404. `evidenceId` is the Dashboard-owned SQLite row ID; `record_cursor` remains the observer-owned opaque resume key and is not repurposed as a friendly URL identifier.

## 5. Language and truth model

### 5.1 Connection and lease

- “Updates connected” means only that the browser's SSE update stream is connected.
- Other browser states are “Connecting to updates,” “Reconnecting to updates,” and “Refreshing snapshot.”
- “Signal lost 4s ago” may use a browser timer based on the last stream event/error.
- Indexer lease is a separate fact: claimed/fresh, stale, or unclaimed. It never describes a Draindeck runtime process as running.

### 5.2 Repository health

Base availability is exactly `AVAILABLE`, `EMPTY`, `NOT_INITIALIZED`, `OFFLINE`, or initial `null` (“Not yet observed”). Independent health facts are `haltedOversized`, `reducedConfidence`, identity generation details, `corruptCount`, `unknownEventTypeCount`, and lease status. `TORN` and `MALFORMED` are evidence integrity values, not repository availability.

### 5.3 Entities

- Issues: `PENDING`, `ACTIVE`, `DONE`, `NEEDS_HUMAN`, `NEEDS_DECOMPOSITION`.
- Executions: `Pending reconciliation`, `VALIDATING`, `REVIEWING`, `ACCEPTED`, `REJECTED`, `CRASHED`.
- Evidence integrity: `OK`, `TORN`, `MALFORMED`, `OVERSIZED`.
- Runs: `CHECKOUT_FAILED`, `REVIEWER_UNREACHABLE`, `BASELINE_FAILED`, `INGEST_FAILED`, `COMPLETED`, `HALTED`, `INTERRUPTED`, or exact display text `no controlled finish observed`.
- Legacy/ambiguous execution run metadata uses exact text `run metadata unavailable (legacy/ambiguous)`.
- `inconsistent: false` renders “No inconsistency observed,” never “verified,” “valid,” or “cryptographically consistent.”

### 5.4 Derived data labels

Every aggregate response includes `basis` and, where time applies, `window`. UI sections label data as “Derived from indexed evidence” or “Detected by this Dashboard.” Run budgets are configured limits, not consumption; they render as a definition list, never as a progress bar. Timeline entries are observed metadata records and never include fabricated heartbeats, duration, or payload descriptions.

## 6. Screen requirements

### 6.1 Operator Home

- Header: page title, simple global search, Updates status, theme control.
- Repository ledger: repository name/path, availability, independent health summary, latest observed run outcome/time, open attention count, and direct repository link.
- Attention preview: highest severity current conditions across repositories with View all.
- Analytics band: repository availability distribution, issue lifecycle distribution, run outcomes, and evidence integrity distribution. Each chart includes a text summary and links to the corresponding filtered explorer.
- Recent observed activity: the newest metadata-only evidence across current generations, sourced from `GET /api/evidence?direction=desc` in `evidenceId DESC` keyset order, with repository/entity links and no payload preview. `stored_at` is an upsert-observation timestamp and may change when a TORN tail completes, so it is not used as immutable arrival order.
- Empty state separates “No repositories registered” from “Repositories registered; no data observed yet.”

### 6.2 Repository Registry and Add Repository

- Registry is a table, not a card grid. It supports search, availability/attention filters, sorting, page-size choice (25/50/100), and Previous/Next controls.
- Add flow contains required absolute Project path and optional absolute Log path. No browser Browse control is shown unless a future native/backend path chooser is separately specified.
- Submit copy is “Add repository.” Typed API validation appears inline and in a form-level alert.
- Unregister is in the repository overflow/detail action and requires confirmation: it deletes Dashboard-owned registration, indexed evidence, projections, and attention rows only; it never deletes or modifies the repository, event log, transcripts, diffs, or artifacts.

### 6.3 Repository Overview

- Identity block: project path, optional log path, created time, availability, identity generation, reduced-confidence explanation, indexer lease fact.
- Health & attention panel: corruption count, unknown event types, oversized halt, current attention, and remediation copy.
- Aggregates and recent runs use observed/derived values only.
- Unregister remains reachable but visually separated from primary navigation.

### 6.4 Attention Center

- Columns: Severity, Condition, Repository/System scope, Subject, First detected, Last detected, Status, Action.
- Default view is current conditions sorted critical → warning → informational, then oldest first. Resolved conditions are available through a filter.
- Initial kinds: repository offline, indexing halted oversized, corrupt evidence detected, malformed evidence observed, reduced identity confidence, unknown complete event types, system-wide lease stale/unclaimed, issue needs human, issue needs decomposition, execution containment unconfirmed/unreleased, and inconsistent issue/execution/run evidence. Missing/truncated artifact is an execution-detail request state, not a persistent attention condition.
- `Pending reconciliation`, a TORN tail, and `no controlled finish observed` remain honest observed states on their entity screens but are not attention conditions. Without a liveness signal or an independently justified age policy, none of them establishes that operator action is needed.
- Conditions are not dismissible. Resolution comes only from a later projection/health reconciliation.
- Attention and repository-health reconciliation emits additive SSE invalidations. The visible Home/Attention screen also performs a low-frequency 30-second snapshot refresh so time-derived lease state cannot remain stale if an invalidation is missed.

The condition-to-severity mapping is closed for v2; implementers may not invent or escalate severities:

| Kind | Severity | Exact message template / target |
|---|---|---|
| `INDEXING_HALTED_OVERSIZED` | critical | “Indexing halted at an oversized record; operator remediation required.” → repository Evidence/Health |
| `CORRUPT_EVIDENCE` | critical | “Conflicting OK records share event ID {eventId}.” → repository Evidence/Health |
| `CONTAINMENT_UNCONFIRMED` | critical | “Termination could not be confirmed for containment {generation}.” → execution detail |
| `CONTAINMENT_UNRELEASED` | critical | “Terminal execution retains unreleased containment {generation}.” → execution detail |
| `REPOSITORY_OFFLINE` | warning | “Registered log is currently offline.” → repository Overview |
| `MALFORMED_EVIDENCE` | warning | “Malformed complete evidence is present in the current generation.” → filtered Evidence |
| `REDUCED_IDENTITY_CONFIDENCE` | warning | “Identity generation is lineage-only; file-generation identity unavailable.” → repository Overview |
| `UNKNOWN_EVENT_TYPES` | warning | “{count} unknown complete event types retained as evidence.” → filtered Evidence |
| `LEASE_STALE` | critical | “Indexer lease expired; Dashboard freshness is not advancing.” → About & Safety / affected system summary |
| `LEASE_UNCLAIMED` | warning | “Indexer lease remains unclaimed.” → About & Safety / affected system summary |
| `ISSUE_NEEDS_HUMAN` | warning | “Issue requires human intervention.” → issue detail |
| `ISSUE_NEEDS_DECOMPOSITION` | warning | “Issue requires decomposition.” → issue detail |
| `INCONSISTENT_ISSUE` | warning | “Inconsistent issue lifecycle evidence observed.” → issue detail |
| `INCONSISTENT_EXECUTION` | warning | “Inconsistent execution lifecycle evidence observed.” → execution detail |
| `INCONSISTENT_RUN` | warning | “Inconsistent run lifecycle evidence observed.” → run detail |

The API retains `information` as an allowed future severity for additive compatibility, but v2 defines no informational attention kind. Base availability, pending reconciliation, no-finish observations, and TORN tail integrity remain visible outside Attention. `LEASE_STALE` is deliberately critical because it invalidates freshness across every repository view. `LEASE_UNCLAIMED` opens as warning only after one full 10-second lease TTL has elapsed since Dashboard first observed the unclaimed state, preventing a startup flash while detecting persistent lack of an indexer.

### 6.5 Runs

- Explorer columns: Repository, Run, Observed start, Engine, Reviewer, Outcome, Inconsistency, Last event.
- Detail displays provider/model, full configured budget object, config digest, exact outcome, last event ID, and observed start/finish timestamps when evidence exists.
- Related executions and metadata timeline are paginated when needed.
- The outcome banner uses “Observed finish” or “No controlled finish observed”; never “Active” or “Running.”
- Mini topology links run → executions → issues/evidence using stored identifiers only.

### 6.6 Issues

- Explorer columns: Repository, Issue, Title, State, Inconsistency, Last event.
- Detail includes issue summary, direct entity links, chronological metadata-only event timeline, execution table, and issue → executions → evidence mini topology.
- Timeline item fields are event type, event timestamp, event ID, integrity, execution/run links when present, and evidence link. Payload text is not exposed.

### 6.7 Executions

- Explorer supports By execution and By issue presentation over the same server-filtered result. Grouping is server-backed/pagination-correct, never a join of only the current client page.
- Detail metadata includes issue, state, independent containment-generation list, inconsistency, last event, run link, and nested run metadata or exact legacy fallback. Each containment is keyed by `(executionId, containmentGeneration)` and exposes workspace key plus exact state `PREPARED`, `ESTABLISHED`, `UNCONFIRMED`, or `RELEASED`. The event is named `ExecutionTerminationUnconfirmed`; the projected state is `UNCONFIRMED`. These are observed facts, never process-liveness claims.
- Transcript and diff are first-class tabs/panels backed by the existing endpoints. Handle 403 containment failure, 404 absence, invalid refs, timeout, command failure, binary files, output truncation, and successful empty diff.
- No duration appears because the contract does not establish one.

### 6.8 Evidence

- Explorer fields: Evidence ID, cursor, integrity, event ID, event type, schema version, issue, execution, run, timestamp, record hash, length bytes.
- Filters: repository, integrity, event type, issue ID, execution ID, run ID. The redesigned screen explicitly requests newest stored evidence with stable evidence-ID tie-break; this does not change the legacy repository-scoped endpoint's oldest-first default.
- Detail is metadata only. It does not show raw event lines, payload JSON, invented damaged text, or a `CORRUPT` integrity badge. Corruption links to the relevant repository health/attention condition.

### 6.9 About & Safety

Use exact spirit: “Draindeck Dashboard does not modify registered repositories, event logs, transcripts, diffs, or artifacts. It writes its own local SQLite database for registration and indexed views.” Also disclose loopback-only serving, Host/Origin checks, self-only CSP/no framing, update-stream meaning, theme preference storage, and no authentication/remote exposure support.

## 7. REST API contract (additive proposal)

Two bounded pagination profiles exist:

- Repositories, attention, issues, runs, executions, and metadata timelines use `limit` (default 50, 1–200) plus `offset` (0–10,000) and return `{items, limit, offset, total}`. UI `page/pageSize` maps deterministically to these values and cannot exceed the offset cap.
- The new cross-repository evidence explorer uses keyset pagination ordered by globally unique `evidence.id`: `limit` plus optional `beforeEvidenceId`/`afterEvidenceId` and `direction=asc|desc`, returning `{items, limit, next, previous, hasMore, total}`. It never performs a deep SQL OFFSET. The legacy repository-scoped evidence endpoint retains `limit/offset` and its oldest-first default, but ADR-27 explicitly adds a safety ceiling of 100,000 to that legacy offset; the redesigned UI requests an additive explicit sort or uses the cross-repository keyset endpoint filtered by repository. This is the one documented pre-GA narrowing of an existing query range, not a silent order/shape change.

Sort/filter parameters use closed enums; unknown values on new routes receive the typed error envelope. `repoId` is a positive integer. Issue, run, execution, cursor, and filter identifiers are path/query decoded, length-bounded opaque strings. Existing endpoints remain unchanged unless an additive field is noted.

### 7.1 Cross-repository endpoints

#### `GET /api/overview`

Returns:

```json
{
  "repositories": {"total": 0, "byAvailability": {"AVAILABLE": 0, "EMPTY": 0, "NOT_INITIALIZED": 0, "OFFLINE": 0, "NOT_OBSERVED": 0}},
  "attention": {"current": 0, "critical": 0, "warning": 0, "information": 0},
  "issues": {"total": 0, "byState": {}},
  "runs": {"total": 0, "byDisplayOutcome": {}},
  "executions": {"total": 0, "byState": {}},
  "evidence": {"total": 0, "byIntegrity": {}},
  "basis": "current identity generation per registered repository",
  "projectionState": {"complete": true, "staleRepositoryIds": [], "preparingRepositoryIds": []}
}
```

#### `GET /api/repository-summaries`

Parameters: standard pagination; `q`; `availability`; `hasAttention`; `sort` in `name|createdAt|availability|latestRunAt|attentionCount`; `direction` in `asc|desc`. Each item contains the existing repository fields plus `displayName` (final path segment), `health`, `latestRun` (nullable observed run summary), and `attentionCount`.

#### `GET /api/attention`

Parameters: standard pagination; `status=current|resolved|all`; `severity=critical|warning|information`; `repositoryId`; `scope=repository|system|all`; `kind`; `sort=severity|firstDetectedAt|lastDetectedAt`; `direction`. Items contain `conditionId`, `kind`, `severity`, nullable `repository` (null means system-wide and renders “All repositories”), nullable `subject {type,id,label}`, exact `message`, `firstDetectedAt`, `lastDetectedAt`, nullable `resolvedAt`, and `targetUrl`. Lease conditions are one system-wide occurrence, never duplicated once per repository.

#### `GET /api/search?q={text}&limit={1..10}`

Requires trimmed `q` length 2–200. Returns grouped `repositories`, `issues`, `runs`, `executions`, and `evidence`; maximum `limit` items per group. Each result has `type`, `repositoryId`, `id`, `label`, optional `context`, and `url`. Evidence matching is limited to Dashboard `evidenceId`, cursor, integer event ID, and exact/substring event type metadata. Other matching is case-insensitive substring over stored identifiers, issue titles, and project paths. No raw evidence payload, record bytes, transcript/diff content, or advanced query syntax is searched.

#### Cross-repository explorers

- `GET /api/issues`
- `GET /api/runs`
- `GET /api/executions`
- `GET /api/evidence`

The first three accept offset pagination; evidence accepts keyset pagination. All accept optional `repositoryId`, entity-specific closed filters, and closed sorting. Every cross-repository query joins `checkpoints.identity_generation_id` and therefore returns current-generation rows only. They return the same item shape as the corresponding repository-scoped endpoint with additive `repository {id, displayName}` and, for evidence, `evidenceId` and `runId`.

`GET /api/executions` adds `groupBy=execution|issue` (default `execution`). `execution` returns the flat execution page. `issue` paginates issue groups—not a client page join—and each group returns the issue summary, exact total/by-state execution counts, at most five newest execution summaries, `executionsTruncated`, and a URL/filter for the complete issue execution list.

### 7.2 Repository and entity detail endpoints

- `GET /api/repositories/{repoId}/overview` returns registration, current health, current attention counts/items preview, and repository aggregates.
- `GET /api/repositories/{repoId}/issues/{issueId}` returns one persisted issue projection plus related counts.
- `GET /api/repositories/{repoId}/runs/{runId}` returns one persisted run projection plus related counts and observed timestamps.
- `GET /api/repositories/{repoId}/executions/{executionId}` returns one persisted execution projection, every containment generation for that execution, and nested run metadata/fallback.
- `GET /api/repositories/{repoId}/evidence/{evidenceId}` returns one metadata-only evidence record scoped to the current identity generation.

Every detail endpoint returns `404 NOT_FOUND` when a syntactically valid positive repository ID or current-generation entity does not exist. Historical generations are not silently searched. Existing FastAPI path-type validation remains backward compatible: a non-integer `repoId` receives the framework's current 422 validation response rather than the Dashboard 404 envelope.

### 7.3 Timeline and topology endpoints

#### `GET /api/repositories/{repoId}/{entityType}/{entityId}/timeline`

`entityType` is separately routed as `issues`, `runs`, or `executions`; bounded offset pagination and `direction=asc|desc` apply. Each item contains only `evidenceId`, `cursor`, `integrity`, `eventId`, `eventType`, `schemaVersion`, `issueId`, `executionId`, `runId`, `ts`, `recordHash`, and `lengthBytes`. The endpoint never returns `payload_json` or raw record bytes.

#### `GET /api/repositories/{repoId}/{entityType}/{entityId}/topology`

Returns bounded `{nodes, edges, truncated, limits, basis}`. Node kinds are `issue|run|execution|evidence`; edges are only `run_has_execution`, `issue_has_execution`, `entity_has_evidence`, derived from stored IDs in the current identity generation. Default hard caps are 100 nodes and 200 edges. When capped, `truncated=true` and the UI links to filtered explorers instead of implying completeness.

### 7.4 Additive changes to existing endpoints

- Existing repository-scoped evidence list items gain `evidenceId` and `runId`. Its default order remains oldest-first. Optional closed `sort=id|storedAt|eventId` and `direction=asc|desc` parameters are additive; the UI explicitly requests newest-first. Its offset is capped at 100,000 as the explicit ADR-27 boundedness tightening above.
- Existing issue/run/execution list shapes remain valid; optional `observedStartedAt`/`observedFinishedAt` may be added to run items.
- Existing transcript and diff endpoints are unchanged.
- Existing `/api/events` event shape and resume rules are unchanged. `entityType` gains the additive values `attention`, `repository_health`, and `read_model`; `repositoryId: 0` is reserved for a system-wide invalidation.

### 7.5 Errors and validation

All explicitly mapped errors remain `{ "error": { "code", "message", "details"? } }`. New API parsing uses codes `INVALID_QUERY`, `INVALID_FILTER`, `INVALID_SORT`, `QUERY_TOO_SHORT`, `PAGE_OUT_OF_RANGE`, `INDEX_PREPARING`, and `INDEX_REBUILDING` as applicable. Existing FastAPI 422 path/body validation shapes remain unchanged unless a later compatibility ADR explicitly normalizes them. Body size, path containment, diff time/output caps, and 403/404 distinctions remain as specified by docs/19. Unexpected exceptions do not echo SQL, paths beyond already registered values, payloads, or stack traces to the browser.

## 8. SQLite v2 read model

### 8.1 Migration contract

- `SCHEMA_VERSION` becomes 2.
- `init_schema` executes `BEGIN IMMEDIATE` before reading `schema_meta.version`; the locked transaction then reads exactly one schema row, rejects versions newer than supported, and applies only the small v1→v2 DDL. SQLite serializes concurrent starters: the winner migrates; the follower acquires the lock only after that commit and then reads v2 inside its own transaction. A busy timeout produces a clean startup failure/retry, never a second migration path.
- Migration is idempotent under restart/concurrent process start and creates only Dashboard-owned tables/indexes.
- Existing evidence, registrations, identity generations, checkpoints, corruptions, changes, and lease rows are preserved.
- `init_schema` never scans evidence or backfills projections. After the scheduler acquires/renews the indexer lease, it queues current-generation backfills on one dedicated projection worker using its own connection. The worker verifies lease ownership before work and immediately before its atomic publish; lease loss discards the candidate snapshot without publishing.
- Backfill/rebuild scans run off the ASGI event loop. API aggregate/list queries also use bounded thread offload with short-lived read connections. Each observer page's evidence upsert, corruption detection, incremental lifecycle/containment projection, checkpoint, attention reconciliation, change-row transaction, and lease acquire/renew write runs through the same lease-owned off-thread write worker and connection; no SQLite write executes on the ASGI event loop. Its FIFO queue is capped at 16 pending jobs; repository tasks await capacity rather than accumulating memory. Lease renewal jobs receive priority over ordinary page/backfill work so a bounded queue cannot starve the 2-second heartbeat. `poll_pages` remains bounded at 500 records per page and four pages (2,000 records) per repository tick. Read-only SSE cursor queries may remain synchronous only when measured below the server-side 50ms budget.
- A post-migration backfill is safe to retry and does not emit duplicate entity changes. It marks `read_model_state` as preparing/rebuilding, builds a complete candidate off-thread, swaps rows in one short transaction, marks ready, then emits one `read_model` invalidation.

### 8.2 New tables

`issue_views(repository_id, identity_generation_id, issue_id, state, title, inconsistent, last_event_id, updated_at)` with composite primary key and indexes for repository/state/title.

`run_views(repository_id, identity_generation_id, run_id, engine_provider, engine_model, reviewer_provider, reviewer_model, budget_json, config_digest, outcome, inconsistent, last_event_id, observed_started_at, observed_finished_at, updated_at)` with composite primary key and indexes for repository/outcome/start time.

`execution_views(repository_id, identity_generation_id, execution_id, issue_id, state, inconsistent, last_event_id, run_id, updated_at)` with composite primary key and indexes for repository/state/issue/run.

`containment_views(repository_id, identity_generation_id, execution_id, containment_generation, workspace_key, state, inconsistent, last_event_id, updated_at)` with composite primary key `(repository_id, identity_generation_id, execution_id, containment_generation)` and indexes for execution/state. It consumes only the four existing containment event types, uses exact states `PREPARED|ESTABLISHED|UNCONFIRMED|RELEASED`, and remains independent from execution lifecycle state.

`read_model_state(repository_id, identity_generation_id, status, completed_evidence_id, started_at, completed_at, error_code)` with one current row per repository. Status is `PREPARING|READY|REBUILDING|ERROR`; it contains no exception text or sensitive payload.

`attention_conditions(id, condition_key, occurrence, repository_id, identity_generation_id, kind, severity, subject_type, subject_id, message, target_url, first_detected_at, last_detected_at, resolved_at)` with nullable `repository_id` for system conditions, unique `(condition_key, occurrence)`, a partial unique index allowing only one unresolved row per `condition_key`, and indexes for current severity, repository/status, and subject.

`condition_key` is a stable Dashboard-owned hash or canonical string over `(repository_id-or-system, identity_generation_id-or-none, kind, subject_type-or-none, subject_id-or-none)`. `occurrence` starts at one and increments when a resolved condition recurs. A generation rollover resolves generation-scoped open conditions; repository conditions may use no generation, and global lease conditions use system scope.

`delete_repository` is updated in the same transaction to remove `attention_conditions`, `containment_views`, `execution_views`, `run_views`, `issue_views`, and `read_model_state` before deleting existing Dashboard-owned rows and the registration. No target path is touched.

### 8.3 New indexes on evidence

- `(repository_id, identity_generation_id, issue_id, id)` for issue timeline.
- `(repository_id, identity_generation_id, execution_id, id)` for execution timeline.
- `(repository_id, identity_generation_id, run_id, id)` for run timeline/topology.
- `(repository_id, identity_generation_id, integrity, id)` and `(repository_id, identity_generation_id, event_type, id)` for filters/aggregates.

### 8.4 Projection maintenance

- Keep the tolerant transition semantics from `projections.py`; unknown, illegal, malformed, duplicate, and out-of-order evidence never crashes the Dashboard.
- A pure reducer remains the reference implementation and supports deterministic rebuilds.
- On newly inserted monotonic OK evidence, apply the relevant row incrementally inside the indexer's database transaction. Integrity-only records update aggregates/attention but not lifecycle state.
- Boundary redelivery with identical identity/cursor/hash is a no-op. A tail row changing from `TORN` to `OK` is applied incrementally when its new integer event ID is greater than the last projected event; the prior TORN row contributed no lifecycle/containment state. A `MALFORMED → OK` change is not assumed to be a normal append and follows the same monotonic/projectability check. A previously OK row changing hash, event ID, decoded content or integrity, or a lower/non-monotonic projectable event schedules an off-thread scoped rebuild.
- Generation rollover resolves generation-scoped attention, queues the new generation, and deletes old-generation rows from `issue_views`, `run_views`, `execution_views`, `containment_views`, and `read_model_state` after the new state is established. Source evidence/history remains preserved. Every cross-repository read also joins the current checkpoint generation as defense in depth.
- List/detail/aggregate endpoints read persisted views and SQL aggregates; they never invoke a full `build_projection` per request.

### 8.5 Attention reconciliation

After a repository tick and after lease-state transitions, derive the current condition set, upsert/open matching keys, update `last_detected_at`, and resolve previously open keys no longer present. `first_detected_at` is retained across a continuous occurrence. A condition that resolves and later recurs increments `occurrence` and opens a new row so history is not overwritten. The UI labels these timestamps as Dashboard detection times. Exact containment state `UNCONFIRMED` is an attention condition whenever observed. “Containment unreleased” is derived separately for every containment generation only when the execution has reached `ACCEPTED`, `REJECTED`, or `CRASHED` and that generation remains `PREPARED`, `ESTABLISHED`, or `UNCONFIRMED`; a merely pending/validating/reviewing execution does not produce that derived claim.

Only the lease-owning writer persists attention changes. It records one `attention` invalidation per opened/resolved condition and one reserved-system invalidation for lease conditions; repository availability/health changes emit `repository_health`. A connected client still refreshes visible time-derived attention every 30 seconds because an expired lease can be observed before a replacement leader has persisted a condition.

## 9. Frontend architecture

### 9.1 Project structure

```text
src/draindeck_dashboard/
  app.py                    # route registration only
  api_queries.py            # bounded list/detail/aggregate SQL
  attention.py              # condition derivation/reconciliation
  migrations.py             # schema-version upgrades
  read_models.py            # persistent tolerant projection maintenance
  read_model_worker.py      # lease-owned off-thread backfill/rebuild queue
  search.py                 # bounded grouped search
  static/
    index.html              # semantic app shell and no-JS fallback
    styles/
      tokens.css            # DESIGN.md variables, light/dark/forced colors
      base.css              # reset, type, focus, utilities
      shell.css             # rail, utility bar, content layout
      components.css        # tables, chips, forms, dialog, pagination
      pages.css             # page-specific arrangements and charts
    js/
      app.js                # boot only
      api.js                # fetch/error/abort helpers
      router.js             # History API + route matching
      state.js              # small explicit UI/cache state
      stream.js             # EventSource invalidation and connection state
      dom.js                # safe node creation/keyed patch helpers
      format.js             # exact labels/dates/identifiers
      components/           # shell, table, filters, pagination, charts, topology
      pages/                # one module per route family
tests/dashboard/
  ...focused API, migration, projection, security, and route tests...
```

Modules may be consolidated when a boundary would otherwise contain trivial code, but no single replacement `app.js` should become a monolith. No bundler is introduced; browser modules load with `<script type="module">` and relative static URLs.

FastAPI registers `/api/*` first, mounts static assets only at `/assets`, and registers an explicit allowlist of approved UI route patterns that returns `index.html`. The current catch-all `app.mount("/", StaticFiles(...))` is removed only after compatibility routes for the legacy `/styles.css` and `/app.js` assets are tested. An allowlisted UI route can therefore reload directly without swallowing unknown `/api/*`; an unknown path retains FastAPI's normal 404.

### 9.2 State and navigation

- The URL is the source of truth for route and shareable list state.
- Fetches use `AbortController` on route/filter changes. Late responses may not overwrite a newer route.
- Native links work with open-in-new-tab and copy-link behavior; same-origin clicks enhance through History API.
- On route change, update document title, breadcrumbs, active rail state, and focus the main heading unless navigation came from a same-page filter.
- Theme preference is `system|light|dark` in local storage. System is default; absence/corruption falls back safely.
- Search uses a labelled combobox/listbox pattern with debounced requests, Escape close, arrow navigation, and Enter navigation. A full results page is not required.
- Offset-based UI pages use `page/pageSize` and the exact mapping in §7. Evidence writes keyset IDs into the URL and keeps only a bounded in-memory back-stack for Previous; it does not synthesize an unbounded page number.

### 9.3 Rendering and SSE

- Observed text is assigned through `textContent` or text nodes only. No untrusted string enters `innerHTML`, inline event handlers, style attributes, SVG markup, or URL schemes.
- Render skeletons immediately, then success/empty/error. Preserve the old successful view during background refresh and mark it stale rather than flashing blank.
- SSE invalidations are coalesced by repository/entity over a short bounded window. Refetch only visible data plus global badges/summaries affected by the change.
- Key rows and their child controls by stable entity ID. Patch changed text/status cells in place. Capture/restore focus only as a fallback; do not clear and recreate a focused row.
- After a reconnect or cursor reset, show “Refreshing snapshot,” refetch the active screen and global shell counts, then return to “Updates connected.”
- While `read_model_state` is preparing with no complete snapshot, show “Preparing indexed views” and retry with bounded backoff. During rebuild, retain the last complete data, mark it “Refreshing indexed views,” and replace it only after the atomic ready invalidation.

### 9.4 Charts and topology

Use native SVG/DOM and no chart dependency. Charts follow DESIGN.md's complete eight-position, contrast-alternating light/dark sequences and must have a heading, visible legend, exact value labels or accessible descriptions, keyboard-reachable linked data points, and a tabular/text equivalent. More than eight categories collapse into a labelled “Other” value linked to the full data table; colors are never recycled ambiguously. Mini topology uses deterministic layout—no physics simulation—and renders a text relationship list in the same DOM. Both degrade to the text equivalent under forced colors or narrow space. The current CSP blocks inline `<style>` and `style="..."`; dynamic geometry therefore uses validated numeric SVG presentation attributes or predeclared external classes, never an inline style sink.

## 10. Accessibility requirements

- WCAG 2.2 AA at light/dark themes; all normal-text color pairs ≥4.5:1 and interactive boundaries/focus indicators ≥3:1. `#CFC7B8`/`#42554B` remain divider tokens, while `#81796C`/`#82998D` are control boundaries. Focus is surface-aware: `#006E75` on light paper and `#6EDAE0` on Binding Forest/Night Canvas/Night Surface in either theme. The forest rail never uses `#006E75` as its focus ring.
- Full keyboard operation with logical order, skip link, landmarks, visible focus, no keyboard traps, Escape semantics for overlays, and WCAG 2.2 Focus Not Obscured. Sticky headers/toolbars establish `scroll-padding`; focus targets use `scroll-margin`, and browser tests tab through first/last rows under every sticky plane.
- 44×44 CSS pixel target size where feasible; dense table links may rely on row padding while remaining individually focusable.
- 200% text resize and reflow to 320 CSS pixels for shell, forms, detail content, About, navigation, and non-tabular controls without two-dimensional page scrolling. Genuine data tables/topology/diff content may scroll in their own labelled two-dimensional region under SC 1.4.10's exception. Product acceptance still emphasizes 768/1024/1440 layouts, with a separate 320px accessibility-reflow check.
- `prefers-reduced-motion: reduce` removes non-essential animation/scroll behavior; no information depends on animation.
- `forced-colors: active` retains borders, selected state, focus, links, and textual status.
- Live regions announce connection state, form errors, and loaded result counts without repeating every SSE row update.
- Dates use visible locale formatting plus machine-readable `<time datetime>`. Relative time never appears without an exact timestamp available.
- Truncated visible IDs/paths expose the full value through selectable text/detail/copy, not hover-only tooltips.
- The 72px rail retains short visible destination labels plus accessible names; tooltip-only navigation is prohibited. Any supplementary custom hover/focus content satisfies WCAG 1.4.13: dismissible without moving focus, hoverable, and persistent until hover/focus ends or the user dismisses it.

## 11. Security and privacy boundaries

- Preserve loopback bind, non-loopback client/Host rejection, Origin policy, no CORS, maximum body size, self-only CSP, no framing, and existing security headers.
- New stable UI fallback uses the explicit asset mount/UI-route allowlist in §9.1 and must never swallow `/api/*` 404/405 responses or weaken middleware coverage.
- All SQL values remain parameterized. Sort columns/directions are selected from server-side allowlists, never interpolated from arbitrary input.
- Clamp pagination, search length, group counts, topology size, and aggregate windows. Avoid unbounded `IN` lists and N+1 repository-health calls.
- Do not expose `payload_json`, raw event bytes, observer environment, lease owner token in cross-repository UI summaries, secrets, configuration contents, or arbitrary filesystem reads.
- Transcript path containment and diff subprocess protections remain unchanged. Browser code renders transcript/diff as text, not markup.
- Registration/unregistration are the only intended mutations. Unregistration remains CSRF-resistant through loopback/Origin enforcement and an explicit user confirmation.
- Theme preference is the only browser-persisted setting; do not persist observed evidence, search history, transcript, or diff contents in local storage.
- Keep all script and style resources self-hosted. Do not add inline `<script>`, inline `<style>`, `style` attributes, dynamic style strings, or remote origins; SVG presentation attributes accept only finite numbers or server-owned categorical values.

## 12. Code style and engineering conventions

Python remains typed, small-function, parameterized-SQL code consistent with the package. New Pydantic request models use `extra="forbid"`. JavaScript uses ES modules, explicit named exports, `const` by default, semicolons, safe DOM creation, and no framework conventions.

Representative JavaScript style:

```js
export function renderStatusChip({ label, tone, icon }) {
  const chip = document.createElement("span");
  chip.className = `status-chip status-chip--${tone}`;

  const glyph = document.createElement("span");
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = icon;

  const text = document.createElement("span");
  text.textContent = label;

  chip.append(glyph, text);
  return chip;
}
```

Representative Python query style:

```python
_SORT_COLUMNS = {"name": "r.project_path", "createdAt": "r.created_at"}

def repository_summaries(conn: sqlite3.Connection, *, sort: str, limit: int,
                         offset: int) -> dict:
    column = _SORT_COLUMNS.get(sort)
    if column is None:
        raise InvalidQueryError("unsupported repository sort")
    rows = conn.execute(
        f"SELECT r.id, r.project_path, r.log_path, r.created_at "
        f"FROM repositories AS r ORDER BY {column}, r.id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return paginate(rows, limit=limit, offset=offset)
```

The only interpolated SQL fragment is an allowlisted constant selected by server code; user values remain bound parameters.

## 13. Testing strategy

### 13.1 Test-driven sequence

Every behavior change starts with a focused failing test. Run that focused file until green, then the Dashboard suite, then the combined suite. Do not batch all tests after implementation.

### 13.2 Backend coverage

- v1→v2 migration, version read after `BEGIN IMMEDIATE`, simultaneous process start, busy-timeout failure, idempotent restart, newer-version refusal, rollback on failure, and evidence preservation.
- Lease-owned off-thread backfill/rebuild and acquire/renew writes, priority heartbeat scheduling under a full worker queue, lease loss before publish, readiness/error states, event-loop responsiveness, and atomic old-snapshot→new-snapshot visibility.
- Materialized view parity against the pure reducer over legal, illegal, duplicate, malformed, unknown, reordered, boundary-redelivered, TORN→OK, previously-OK replacement, containment-generation, and generation-rollover fixtures.
- Attention open/update/resolve/recur semantics, closed severity mapping including critical stale lease and TTL-delayed unclaimed lease, SSE invalidation, 30-second refresh, no pending/no-finish/TORN conditions, and exact detection-time language.
- Endpoint offset/keyset pagination, offset caps, total counts, filters, stable sorts/tie-breaks, current-generation cross-repository scoping, execution groupBy shapes, detail 404/422 compatibility, timeline metadata-only guarantees, and topology caps.
- Search group caps including evidence metadata, escaping, case behavior, minimum/maximum query length, and absence of payload/raw evidence leakage.
- Repository deletion removes every v2 projection/readiness/attention row without touching target paths.
- Security headers and middleware on every new API/UI route; hostile Host/Origin, oversized body, encoded path segments, transcript containment, and diff error paths.
- Query-count or trace assertions preventing per-row/per-repository N+1 access on home and explorer endpoints.

### 13.3 Frontend coverage

Use the current lightweight test approach where possible and add browser-executed tests without introducing a production dependency. Test route matching, page↔offset and evidence-keyset URL serialization, recent activity by evidence ID rather than mutable stored time, exact status formatting, safe DOM rendering, search keyboard behavior, theme/surface-aware focus selection, all eight chart colors/overflow, accessible collapsed navigation and supplementary tooltip behavior, stale response suppression, and keyed focus-preserving updates.

### 13.4 Real-browser acceptance

Real-browser testing is mandatory before completion. Unit 0 must prove that the Claude Code environment has a callable Chrome DevTools/browser automation capability before any source mutation. Merely having Chrome installed is insufficient. If unavailable, stop at the approval gate so the user can enable tooling or explicitly assign the final browser gate to a separate Codex session; do not discover this at Unit 15.

- exercise every route with populated, empty, loading, error, reconnecting, and relevant integrity/legacy states;
- verify console and network are clean, CSP blocks inline/remote content, and nested URL reload works;
- keyboard-only pass including search, rail, tables, filters, dialogs, transcript/diff, topology, and charts;
- Accessibility tree inspection and automated audit at WCAG 2.2 AA targets;
- light, dark, reduced motion, and forced-colors spot checks;
- screenshots at 768, 1024, and 1440 CSS pixels plus 200% text resize and 320px non-tabular reflow;
- performance trace using seeded scale data; no long blocking task above 100ms during ordinary filter/page navigation and no full-DOM replacement on a single SSE update.

### 13.5 Commands

From the repository root in PowerShell:

```powershell
python -m pip install -e ".[dashboard]"
python -m pytest tests/dashboard/test_target_file.py -q
python -m pytest tests/dashboard -q
python -m pytest tests/unit tests/dashboard -q
draindeck-dashboard --help
```

Use the actual CLI invocation documented by `src/draindeck_dashboard/cli.py` to launch a temporary loopback instance for browser tests. Do not guess flags; confirm with `--help`. Use a temporary Dashboard database and deterministic seeded repositories/evidence.

## 14. Performance acceptance

With the approved representative fixture (20 repositories, 1,000 issues, 10,000 executions, 100,000 evidence rows) on a normal local developer workstation:

- overview/repository-summary/search/list APIs: p95 ≤300ms after warm-up;
- detail/timeline/topology APIs: p95 ≤200ms for default page/caps;
- first meaningful shell render ≤1.5s and populated home ≤2.5s on loopback, excluding deliberate test throttling;
- list page changes update no more than the visible page plus shell summaries;
- no request rebuilds every repository projection or returns more than 200 list rows / 100 topology nodes / 200 edges;
- no ASGI event-loop task performs a full evidence scan/rebuild or page-persistence transaction; server heartbeat/API probes remain responsive during a 100,000-row backfill and a maximum 2,000-record tick, with no event-loop stall above 50ms attributable to Dashboard SQLite work;
- a normal TORN→OK tail repair does not enqueue a full-generation rebuild;
- evidence navigation uses indexed keysets; new offset endpoints reject offsets above 10,000 and the legacy scoped evidence endpoint rejects offsets above 100,000;
- SSE bursts coalesce without duplicate fetch storms, focus loss, or scroll reset.

These are local acceptance budgets, not production SLOs. Record fixture, hardware, command, and observed values in the implementation handoff.

## 15. Boundaries and non-goals

### In scope

- Multi-screen static UI, themes, accessibility, search, stable URLs, pagination, filters, links, charts, mini topology, comprehensive states.
- Additive Dashboard-only REST/query modules, SQLite v2 read models/indexes, attention detection history, and tests/docs.
- Refactoring existing Dashboard UI code to support modular vanilla JS/CSS.

### Out of scope

- Any change under `src/runtime`, event schema, state machines, observer contract, writer/recovery/Git behavior, or target repository contents.
- Authentication, TLS, remote/LAN serving, multi-user access, cloud sync, telemetry, notifications, or deployment changes.
- Mobile-specific feature/navigation design, native filesystem picker, warning dismissal, raw evidence/payload viewer, run heartbeat/liveness, cost usage, duration, or exact progress. WCAG-required 320px non-tabular reflow remains in scope.
- New frontend framework, build tool, package manager, chart dependency, icon dependency, remote font, or CDN asset.
- Whole-portfolio force topology and advanced search syntax.

## 16. Success criteria / definition of done

The redesign is complete only when:

1. Every route and state in §§4–6 is implemented with actual contract-backed data and no illustrative values.
2. Existing Dashboard API/SSE/artifact/security contracts remain green and backward compatible except for the explicitly approved pre-GA legacy evidence offset ceiling of 100,000; its response order and shape remain unchanged.
3. SQLite migration/read models pass concurrent-start, lease-loss, parity, tail-repair, retry, rollover, deletion, event-loop-responsiveness, and scale tests; no per-request full evidence replay remains on explorer/detail paths.
4. All new APIs are bounded, paginated where applicable, parameterized, metadata-only where specified, and covered by typed errors.
5. Keyboard, focus, zoom/reflow, reduced motion, light/dark, forced colors, charts, topology, dialogs, and connection announcements pass the acceptance checks.
6. Focus and scroll survive an SSE update to an unaffected row; focus inside an updated row is retained or restored to the equivalent control.
7. Focused tests, all Dashboard tests, and combined unit+Dashboard tests pass with no new warnings.
8. Real-browser review at 320/768/1024/1440 and 200% text resize shows no blocking layout, obscured focus, console, network, CSP, or accessibility defects.
9. Security review confirms no target mutation, raw payload exposure, arbitrary path read, unsafe DOM insertion, unbounded query, or Host/Origin/CSP regression.
10. Documentation records final endpoint shapes, schema migration, screenshots, performance evidence, test commands/results, and any approved deviations.
11. An independent pre-merge code-quality review reports no unresolved P0/P1/P2 finding.

## 17. Approval gate and open questions

No blocking product question remains from the approved brief. Implementation still requires explicit approval of this proposal, proposed ADR-27 in `docs/08`, and the version-controlled `tasks/plan.md`. Because `CLAUDE.md` requires runnable committed session checkpoints while also forbidding unauthorized commits, approval must separately state whether Claude Code may create local per-unit checkpoint commits on `dashboard-redesign`. Push and merge remain separately prohibited. Browser automation capability must be confirmed in Unit 0 before mutation.

Any implementation discovery requiring one of the following must stop and request a spec amendment: raw evidence/payload exposure, a new runtime event or state, target filesystem mutation, remote serving/authentication, a new dependency/framework, destructive migration, or a change to existing API/SSE semantics.
