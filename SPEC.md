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

`events` returns metadata, ordered records, an opaque per-record cursor, `nextCursor`, and `hasMore`. Each record includes its observable event ID/type/schema when parseable, `recordBytesBase64`, and `recordHash`: SHA-256 over exactly the bytes encoded by `recordBytesBase64`. Cursors are adapter-owned and opaque to consumers.

`status` reports availability and `writerState` (`ACTIVE`, `IDLE`, or `UNKNOWN`). MVP returns `UNKNOWN` whenever observing state would acquire a mutex.

## Read-only and forward-compatible behavior

The observer reads the existing absolute regular file as bytes and frames on `\n` itself. It must not instantiate `EventLog` or `ReadOnlyEventLog`, acquire writer/workspace mutexes, repair or truncate a log, create paths or sidecars, or invoke Git.

Unknown types and schema versions are retained as exact raw evidence. A malformed complete record remains evidence with an integrity observation. An unterminated final record is reported as torn and does not prevent delivery of earlier complete records. Existing strict writer/replay behavior is unchanged.

## Inputs and errors

`--log` must name an existing absolute regular file. Relative paths, directories, and invalid limits return structured JSON errors on stderr and a nonzero exit code. The observer does not resolve configuration-relative paths and never exposes credentials.

## Documentation boundary

Add a lightweight ADR documenting the additive external read contract, its separate byte reader, and no-downgrade consumer expectation. Add a Doc 03 consumer note only; do not amend the frozen schema, state machine, or event types.

Filed as `docs/08-session-0-closure-and-adr-amendments.md` §5g, ADR-25 — Read-only external observer contract. Doc 03 consumer note: `docs/03-state-machine-and-event-schema.md`, "Consumer note — read-only external observer".

## Project structure

- `src/runtime/observe.py`: bytes-direct observer implementation.
- `src/runtime/main.py`: CLI registration only.
- `tests/unit/test_observe.py`: contract and non-mutation tests.
- `docs/`: ADR and Doc 03 consumer note.

## Testing strategy

Test missing, empty, healthy, malformed, unknown-type/schema, torn-tail, cursor pagination, stable exact-byte hashing, structured errors, and a snapshot proving no log, `.draindeck`, or Git mutation. Run the full unit suite and both harness seeds after implementation.

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
