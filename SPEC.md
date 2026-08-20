# Spec: Read-only observer contract

## Objective

Provide a stable local read boundary for the Draindeck Dashboard. It exposes event evidence and observational status without changing workflow behavior, event schema, filesystem state, locks, or Git state.

## Commands

```text
draindeck observe events --log <absolute-path> [--after <opaque-cursor>] [--limit <1..500>] --format json
draindeck observe status --log <absolute-path> --format json
.venv\Scripts\python.exe -m pytest tests\unit -q
.venv\Scripts\python.exe tests\crash\harness.py <temporary-directory> 42
.venv\Scripts\python.exe tests\crash\harness.py <temporary-directory> 1337
```

## Public contract

Add an installable `draindeck` entry point. Every successful observer response is one JSON object with an explicit contract version.

`events` returns `metadata` (`availability`, `logSizeBytes`, `contentLineage`, `fileGeneration`), ordered `records`, `nextCursor`, and `hasMore`. Each record includes its observable event ID/type/schema when parseable, `recordBytesBase64`, and `recordHash`: SHA-256 over exactly the bytes encoded by `recordBytesBase64`. `records.length` never exceeds the requested `limit`, including when the next unread item is a torn or oversized record — that item is reported as `hasMore=true` with a cursor pointing at it instead of being force-included past the limit. No raw byte offset ever appears in public output (no `offsetBytes` field, on a record or elsewhere); a cursor is an opaque, adapter-owned token, self-describing only to the observer itself.

`status` reports availability and `writerState` (`ACTIVE`, `IDLE`, or `UNKNOWN`). MVP returns `UNKNOWN` whenever observing state would acquire a mutex.

### Identity: `contentLineage` and `fileGeneration`

Every `events` response's `metadata` includes:
- `contentLineage`: SHA-256 hex of the exact raw bytes (including the trailing `\n`) of the log's first complete record, or `null` when no complete record exists yet (an empty log, or a first record that is itself torn/oversized).
- `fileGeneration`: `{"device", "fileIndex", "available"}` — the POSIX device/inode pair, which is the same pair Python's `os.stat` surfaces on Windows as the NTFS volume serial number and file index. `available` is `false` (with `device`/`fileIndex` both `null`) on a filesystem that cannot expose a stable file index, or when the log doesn't exist / can't be opened — never a guessed or fabricated identity.

A cursor embeds the `(contentLineage, fileGeneration)` pair it was issued against alongside its resume position. `read_events_page` recomputes the log's *current* identity on every call and compares it against what the presented cursor embeds — a mismatch, or an embedded position past the current file's end, is rejected as `CURSOR_LOG_REPLACED` rather than silently continued.

**Honest limit of this check:** it detects the log going missing, the file's on-disk identity (`fileGeneration`) changing, the first record's bytes (`contentLineage`) changing, or the cursor's position landing past the current file's end — the realistic shapes of "this log is not the one the cursor came from" (deletion, restore-from-backup, rotation, most truncation). It does **not** detect an in-place truncate-and-rewrite that happens to preserve both the file's identity and the exact first-record bytes while changing only the bytes between the first record and the cursor's position — that specific combination is indistinguishable from ordinary append-only growth by a bounded reader that hashes only the first record. Closing that gap would require hashing the full prefix up to the cursor's offset on every call (unbounded per Part 3's own contract), persistent server-side state (this CLI has none between invocations), or writer/schema cooperation (out of scope — see doc 03's consumer note). This is a deliberate, documented boundary, not an oversight.

## Read-only, bounded, and forward-compatible behavior

The observer opens the existing absolute regular file and frames records on `\n` itself, streaming in bounded chunks (`CHUNK_SIZE`) — it never calls `Path.read_bytes()` or otherwise loads the whole file into memory, so a small `--limit` costs roughly one chunk regardless of file size. It must not instantiate `EventLog` or `ReadOnlyEventLog`, acquire writer/workspace mutexes, repair or truncate a log, create paths or sidecars, or invoke Git.

Unknown types and schema versions are retained as exact raw evidence. A malformed complete record remains evidence with an integrity observation. An unterminated final record is reported as torn (`integrity: "TORN"`) and does not prevent delivery of earlier complete records. Existing strict writer/replay behavior is unchanged.

A single record's scan for its terminating `\n` is capped at `MAX_RECORD_BYTES` (8 MiB — generous for any real Draindeck record, engaged only by corruption or pathological input). A record that never terminates within that cap is reported as `integrity: "OVERSIZED"`: `recordBytesBase64` and `recordHash` are withheld (they would misrepresent an unknown, possibly much larger true record as if it were complete), and `truncatedPrefixHash`/`truncatedPrefixBytes` report an exact hash and length of only the scanned prefix instead — evidence is never silently truncated and re-presented as if it were the whole record. Scanning stops at the cap rather than reading an unbounded distance looking for a `\n` that may not exist; `hasMore` still reports honestly whether the file has bytes beyond the capped prefix.

## Inputs and errors

`--log` must name an existing absolute regular file. Relative paths, directories, and invalid limits return structured JSON errors on stderr and a nonzero exit code. A cursor that is malformed returns `CURSOR_INVALID`; a cursor whose embedded log identity no longer matches the current log returns `CURSOR_LOG_REPLACED` (see the Identity section above for exactly which cases this catches) — both structured, both nonzero exit. The observer does not resolve configuration-relative paths and never exposes credentials.

## Documentation boundary

Add a lightweight ADR documenting the additive external read contract, its separate byte reader, and no-downgrade consumer expectation. Add a Doc 03 consumer note only; do not amend the frozen schema, state machine, or event types.

Filed as `docs/08-session-0-closure-and-adr-amendments.md` §5g, ADR-25 — Read-only external observer contract. Doc 03 consumer note: `docs/03-state-machine-and-event-schema.md`, "Consumer note — read-only external observer".

**Remediation amendment (2026-08-20):** identity (`contentLineage`/`fileGeneration`), cursor lineage/generation rejection, strict per-page `limit` enforcement, bounded streaming reads, and oversized-record handling were added after initial shipment found gaps against this contract. Recorded as an amendment to ADR-25 in the same doc 08 section — not a new ADR — per this remediation's own authorization. `offsetBytes` was removed from public record output as part of the same amendment; there were no external consumers of the initial shape yet, so this is documented as a pre-GA correction rather than a silent break. A same-day follow-up pass (still before this diff's first commit) fixed a boundary bug where a `\n` past `MAX_RECORD_BYTES` could still validate a record in one large single-`read()` gulp, and narrowed the cursor-rejection guarantee's wording to the honest, bounded claim above rather than an unconditional "detects every replacement/truncation."

## Project structure

- `src/runtime/observe.py`: bytes-direct observer implementation.
- `src/runtime/main.py`: CLI registration only.
- `tests/unit/test_observe.py`: contract and non-mutation tests.
- `docs/`: ADR and Doc 03 consumer note.

## Testing strategy

Test missing, empty, healthy, malformed, unknown-type/schema, torn-tail, cursor pagination (including strict `limit` enforcement into a torn tail), stable exact-byte hashing, `contentLineage`/`fileGeneration` reporting (present, absent/unavailable, and stable across repeated reads), cursor rejection on the detectable cases (log missing, `fileGeneration` change, `contentLineage` change, cursor offset past current file length), the boundary at exactly `MAX_RECORD_BYTES` for both record streaming and `contentLineage` discovery (a terminator past the cap must never validate the record, in either code path), the documented in-place-rewrite limitation (proves it is accepted behavior, not silently different from what the docs claim), oversized-record capping, bounded reads (no `Path.read_bytes()`; a small `limit` against a large fixture reads only a small bounded slice), structured errors, and a snapshot proving no log, `.draindeck`, or Git mutation. Run the full unit suite and both harness seeds after implementation.

## Boundaries

Always: preserve exact raw evidence, test non-mutation, and run regressions.
Ask first: dependencies, event-schema changes, run events, run-ID changes, model/cost/config metadata, or locking/recovery changes.
Never: repair logs, acquire locks, route unknown data through `Event.from_line`, expose secrets, or modify runtime/Git state.

## Success criteria

- Console and observer contract tests pass.
- Complete records retain byte identity and stable hashes.
- Unknown/malformed/torn records are observable without mutation.
- Existing strict replay behavior and baseline gates remain green.

## Deferred

`RunStarted`/`RunFinished`, model/provider/cost/config metadata, schema changes, and run-ID changes require a separate ADR-governed feature.
