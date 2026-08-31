# Spec: Dashboard issue selection and run control

**Status:** Accepted 2026-08-30. The governing architectural decision is
ADR-30 in `docs/adr/ADR-30-dashboard-issue-selection-and-run-control.md` (also
recorded as §5l of `docs/08-session-0-closure-and-adr-amendments.md`). The
pre-committed verification contract is
`docs/31-dashboard-issue-run-control-outcome-matrix.md` together with
`docs/plans/dashboard-issue-run-control-failing-tests.md`. This spec restates
that contract for implementation; it invents no behavior beyond it.

## Objective

Let a registered repository's operator view the issue file named by its
canonical `.draindeck/config.local.yaml`'s `project.issues_file`, select one
issue, several issues, or every current non-terminal issue, and launch exactly
one sequential Draindeck runtime process for that batch — without leaving the
Dashboard for a terminal.

## Non-goals and hard boundaries

- The Dashboard never opens, parses, appends, truncates, or repairs
  `events.jsonl` directly. Per-issue state comes only from the existing
  observer/indexed event projection.
- The Dashboard never mutates target Git state, source, artifacts, attempt
  refs, the runtime workspace lease, or recovery bindings, and never
  synthesizes `RunStarted`, `RunFinished`, or any other runtime event.
- The Dashboard does not kill or cancel a running runtime under this feature.
- No event type, schema version, payload key, selection field, queue ID, or
  idempotency key is added to `events.jsonl`. Doc 03's `RunStarted`/
  `RunFinished` schemas are unchanged.
- `runtime.queue.issues_md.parse` is the only issue-file parser; this feature
  implements no second parser and must surface, not silently fix, the known
  un-bulleted `Depends-On:` requirement.
- Stop/cancel-running controls, parallel issues within one repository, editing
  the issue file, and automatically repairing configuration or runtime state
  are out of scope.
- This feature does not accept, supersede, or depend on ADR-29's separate
  target-configuration write authority; it depends only on the pre-existing
  `runtime.config.load_config`, `runtime.config.resolve_event_log_path`, and
  `runtime.queue.issues_md.parse`.

## Registration and configured issue source

Registration accepts the absolute canonical path to a repository's
`.draindeck/config.local.yaml`. Before the row commits, the service validates
that the path is absolute, exists, is a regular file, parses through the
existing `runtime.config.load_config`, and that the parsed
`project.repository` resolves to the registered Git worktree. Any failure is a
typed `CONFIG_PATH_*`/`CONFIG_INVALID`/`CONFIG_REPOSITORY_MISMATCH` error with
no registration row — registration is atomic. A pre-existing (legacy)
registration without a config path remains observation-only until a valid
config is supplied.

The canonical config path is persisted through an additive SQLite migration.
`project.issues_file` and `event_log.path` are resolved against
`project.repository`, never the Dashboard process's CWD; `event_log.path` is
resolved only through `runtime.config.resolve_event_log_path` — no
reimplementation. The config and issue file are re-read (not cached) every
time configured issues are served and before every planning or launch
decision.

The configured file supplies issue identity, title, body, acceptance
criteria, dependencies, and file order. It never supplies workflow state.
State comes only from `events.jsonl` through the existing observer/indexed
projection: a configured issue with no `IssueCreated` evidence is
`NOT_INGESTED`, not `PENDING`. Source `STATUS` text is decorative and never
authoritative (see doc 31's state-interpretation table for the full mapping,
including `NEEDS_HUMAN`/`NEEDS_DECOMPOSITION` as terminal-for-automation and
unavailable/corrupt/rebuilding projections failing every start closed).

## Pure selection and dependency planner

A single pure function — no filesystem, subprocess, SQLite, or browser access
— is shared by API admission and runtime re-validation. Its inputs are the
parsed `IssueSpec` list (file order) and an authoritative map of per-issue
`IssueState`.

**Run selected** is an exact allowlist:

- Empty, duplicate, unknown, terminal, non-actionable, cyclic, or otherwise
  invalid selections refuse the *entire* batch, naming every offending ID.
- Dependencies are never auto-added and a blocked/terminal issue is never
  silently dropped. Every blocker is reported as
  `{issueId, missingDependencyId, dependencyState}`.
- A dependency is satisfied only by `DONE` event evidence; `NEEDS_HUMAN` and
  `NEEDS_DECOMPOSITION` never satisfy it, whether or not the dependency ID
  appears in the current file.
- An authoritative `ACTIVE` issue must be included in any new selection that
  touches it; omitting it refuses the whole batch.

**Run all**:

- Includes every currently non-terminal configured issue plus its complete
  non-terminal dependency chain.
- Displays but excludes terminal issues, with explicit per-state and total
  counts.
- Refuses if an unfinished dependency would remain outside the resulting run
  set.
- An all-terminal or empty issue file is a successful no-op: zero `toRun`, no
  queue row, no process, no run lifecycle event.

**Ordering** is topological by dependency, with configured file order as the
deterministic tie-breaker. A self-dependency or cycle refuses with every
involved ID named — never a silent no-op or a hang.

## Runtime exact-selection CLI

`runtime.main run` gains two explicit, mutually exclusive selection forms:

```text
draindeck run --config <absolute-config-path> \
  --issues-digest <64-lowercase-hex> \
  --issue <issue-id> [--issue <issue-id> ...]

draindeck run --config <absolute-config-path> \
  --issues-digest <64-lowercase-hex> \
  --all-issues
```

`--issue` is repeatable (each ID a separate argv value, never comma-packed or
shell-expanded); `--issue` and `--all-issues` are mutually exclusive. An
invocation supplying neither form keeps the existing direct-CLI drain-all
behavior — the Dashboard never uses that form.

After config load, workspace ownership, and the existing recovery path — but
strictly before `RunStarted` and before any issue activation — the runtime
re-reads and re-parses the issue file, validates the SHA-256 digest (over the
exact bytes presented during Dashboard planning) against the freshly-read
file, replays authoritative state, and re-validates the complete selection
through the same pure planner used by the API. Refusal emits no new
`RunStarted`, `RunFinished`, `IssueActivated`, or execution event for the
proposed batch and names every reason. Runtime scheduling never activates an
issue outside the validated allowlist. A valid zero-item run-all is a clean
no-op with no empty run lifecycle. Sequential execution, dependency order, one
run-level budget shared across the whole batch, workspace ownership, and
recovery behavior are all preserved unchanged.

## Frozen event schema

Doc 03 is unchanged. No event type, schema version, `RunStarted` payload
field, selection field, queue ID, idempotency key, or Dashboard command ID is
added to any event. `RunFinished` is never synthesized. If a bounded
machine-readable stdout correlation line is added immediately after the
existing fsynced `RunStarted` (to let the launcher correlate a spawned process
with its run), it is only a correlation hint — the Dashboard must confirm the
same run ID through the normal observer/indexed evidence before displaying
any event-derived status. Any requirement that would need selection metadata
inside the event log itself is out of scope and requires a separate Doc 03
amendment.

## Persisted Dashboard queue

A Dashboard-owned SQLite queue is FIFO per repository, using a
database-assigned monotonic sequence. At most one active runtime process is
allowed per repository; different repositories may run concurrently. Each
queued command persists: repository, mode, ordered selected IDs (when
applicable), the exact issue-file digest, submission sequence, control state,
spawn intent, process identity, and run correlation. An atomic SQLite claim
prevents two Dashboard workers from launching the same command.

The run-request API requires an `Idempotency-Key` header scoped to the
repository. The same key with an identical normalized request returns the
existing command; the same key with different normalized content returns
`IDEMPOTENCY_KEY_REUSED` and changes nothing.

`QUEUED`, the launch claim, `LAUNCH_FAILED`, and `LAUNCH_OWNERSHIP_UNKNOWN` are
control-plane conditions, never runtime workflow states, and are never written
to `events.jsonl`. Dequeuing revalidates config, issue digest, selection, and
dependencies against current event state: a selected command refuses if a
selected issue became terminal while queued; a run-all command recomputes
terminal exclusions at dequeue, and zero remaining is a no-op. Queued commands
survive a Dashboard restart. Deleting a repository registration must not
orphan an active process, and must clean only Dashboard-owned queue data —
never target files or `events.jsonl`.

## Safe launcher

The launcher uses the already-configured, already-validated Dashboard
Draindeck executable — never one supplied by the browser — and builds an argv
vector with `shell=False`; there is no string concatenation anywhere on this
path. Exactly one child process is spawned per claimed batch. Diagnostics are
bounded and redacted; environment variables, credentials, and API keys are
never persisted or rendered. A missing or invalid executable produces a typed
`LAUNCH_FAILED` with no fabricated run.

**Crash behavior** (fail-closed on ambiguity, since OS process creation and
the SQLite receipt cannot be one atomic transaction):

- Crash while still queued, before spawn intent is claimed: the command
  remains FIFO-queued and may be claimed normally after full re-validation.
- Crash after spawn intent is durably recorded, with any ambiguity about
  whether the spawn happened: no automatic re-spawn. The command becomes
  `LAUNCH_OWNERSHIP_UNKNOWN` and that repository is closed to further
  automatic launch until explicit operator resolution. A known live process
  identity is control-plane evidence only, never workflow state, and grants
  no authority to touch the runtime lease.
- Exit before `RunStarted`: a bounded pre-run/launch failure; no fabricated
  run, no automatic retry.
- Crash after `RunStarted`: the missing `RunFinished` is the permanent,
  honest record — displayed as `"no controlled finish observed"`, never
  `"Running"`, and no terminal event is ever synthesized.
- An abnormal or ambiguous exit pauses later same-repository commands rather
  than cascading further launches. A later operator-approved retry is an
  ordinary `runtime.main run` invocation, which acquires the existing lease
  and performs the existing recovery — the Dashboard itself never parses or
  repairs the log, acquires/breaks/repairs the workspace lease, invokes
  recovery bindings, resets Git, or declares recovery complete.

## Dashboard REST contract

Request bodies are strict (`extra=forbid`), with bounded issue count and
issue-ID byte lengths. A run-request body never accepts an executable, config
path, issue path, shell arguments, or environment — those are always
server-derived from the existing repository registration. Every route
preserves the existing loopback Host/Origin enforcement, no-CORS posture, CSP,
security headers, and body-size limits.

| Route | Purpose | Mutation |
|---|---|---|
| `GET /api/repositories/{repoId}/configured-issues` | Configured issue list with event-derived state, parser warning, and file SHA-256 revision. | None |
| `POST /api/repositories/{repoId}/run-plans` | Validate a proposed selected/all-issues batch and return the plan or every blocker. | None |
| `POST /api/repositories/{repoId}/runs` | Enqueue an idempotent run command (`Idempotency-Key` required). | Persisted queue row; may claim a launch |
| `GET /api/repositories/{repoId}/runs/{commandId}` | Queue position/control condition plus correlated event-derived run status. | None |

All values remain data across SQL, argv, paths, and HTML — an
injection-shaped issue ID or path never changes command, query, or DOM
structure. Every typed error names every issue-specific blocker; nothing is
communicated by toast/color/first-error-only.

## User experience

The configured-issues screen shows the config path, issue-file path and
revision, the parser's un-bulleted-`Depends-On:` warning, and per issue: ID,
title, dependencies, acceptance criteria, and event-derived state —
`NOT_INGESTED` shown honestly, never as `PENDING`, and never derived from
source `STATUS` text. Rows have accessible one/many/select-all checkboxes.
Run Selected and Run All controls open a confirmation that names the
repository, mode, exact ordered scope/count, terminal exclusions, and run-level
budget context before mutating anything. A refusal moves focus to a
focusable error summary listing every blocker. Explicit selection survives an
SSE refresh without auto-selecting newly appeared rows. Queue position is
shown as control-plane state, distinct from runtime progress, which is shown
only from observed events — an unresolved `RunStarted` always reads exactly
`"no controlled finish observed"`. Controls disable whenever config, issue
parsing, event projection, or runtime state is unavailable or inconsistent.
The page meets keyboard, focus, screen-reader, reduced-motion, forced-colors,
200%-text, and 320/768/1024/1440 requirements, with zero browser console
errors.

## Verification commands

```powershell
python -m pytest tests\unit -q
python -m pytest tests\dashboard -q
python -m pytest tests\unit tests\dashboard -q
python tests\crash\harness.py "$env:TEMP\draindeck-run-control-42" 42
python tests\crash\harness.py "$env:TEMP\draindeck-run-control-1337" 1337
```

The two harness runs must retain unfiltered raw stdout/stderr and exit codes;
they are regression evidence for the unchanged runtime, not the feature's own
safety proof — the RED tests named in
`docs/plans/dashboard-issue-run-control-failing-tests.md` and the outcome
matrix in `docs/31-dashboard-issue-run-control-outcome-matrix.md` settle the
new control claims.
