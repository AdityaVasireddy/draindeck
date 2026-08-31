# ADR-30 — Dashboard issue selection and run control

**Status:** ACCEPTED · **Proposed:** 2026-08-30 · **Accepted:** 2026-08-30.
Accepted together with `docs/31-dashboard-issue-run-control-outcome-matrix.md`,
`docs/plans/dashboard-issue-run-control-failing-tests.md`, and
`spec/dashboard-issue-run-control.md`, with explicit local checkpoint-commit
authority granted for this build's bounded per-unit commit series. Push and
merge remain separate, later decisions. It narrowly amends ADR-26 and ADR-27's
read-only Dashboard boundary; it does not accept, supersede, or depend on
ADR-29's separate target-configuration write authority — ADR-30 depends only
on the pre-existing `runtime.config.load_config`/`resolve_event_log_path` and
`runtime.queue.issues_md.parse`, all present on `master` independent of
ADR-29's merge status.

**Context.** ADR-26 and ADR-27 intentionally made the Dashboard an
observation-only local operator surface. It can register repositories and
display event-derived evidence, but it cannot start runtime work. Operators
must therefore leave the Dashboard, identify the configured issue file, and
invoke Draindeck from a terminal even when the Dashboard already presents the
repository's history and health.

The requested control flow lets an operator register the repository's
canonical `.draindeck/config.local.yaml`, view the issue file named by
`project.issues_file`, select one issue, several issues, or every current
non-terminal issue, and launch the resulting batch. The configured issue file
supplies issue identity, text, dependencies, and file order; it does not
supply workflow state. `events.jsonl` remains authoritative for per-issue
runtime state. A `Depends-On:` record is recognized only through the existing
`runtime.queue.issues_md.parse` behavior, including its known requirement that
the line be un-bulleted.

This feature crosses two existing safety boundaries. First, an unauthenticated
loopback Dashboard becomes capable of causing target-repository mutation
indirectly by launching the runtime. Second, the current runtime scheduler
chooses from the complete actionable projection and has no exact allowlist
interface. The design must preserve one sequential runtime process, workspace
ownership, recovery-before-work ordering, run-level budgets, and the event
log's sole authority without building a second workflow state machine in
SQLite.

**Decision.** Adopt the following five-part control contract.

1. **Dashboard control boundary.** The Dashboard changes from read-only to
   launch-capable for this single purpose. For a registered repository it may:
   validate the canonical config with the existing runtime config loader;
   resolve and parse the configured issue file with the existing issue
   parser; obtain event-derived state through the existing observer/indexed
   evidence boundary; plan an exact dependency-safe batch; persist that
   command in Dashboard-owned SQLite; and launch at most one Draindeck runtime
   process for that repository. It may run one process concurrently for each
   different repository.

   The Dashboard still must never open, parse, append, truncate, repair, or
   otherwise write `events.jsonl` directly. It must never mutate target Git
   state, source, artifacts, attempt refs, the runtime workspace lease, or
   recovery bindings. It must never synthesize `RunStarted`, `RunFinished`, or
   any other runtime event. It does not kill or cancel a running runtime under
   this ADR. The Dashboard supplies a command; the launched runtime remains the
   sole owner of workspace acquisition, Git mutation, event emission, engine
   work, reconciliation, validation, review, and shutdown restoration.

2. **Runtime exact-selection interface.** Extend `runtime.main run` with two
   explicit, mutually exclusive selection forms. A selected batch uses one
   repeated option per ID:

   ```text
   draindeck run --config <absolute-config-path> \
     --issues-digest <64-lowercase-hex> \
     --issue <issue-id> [--issue <issue-id> ...]
   ```

   A run-all batch uses:

   ```text
   draindeck run --config <absolute-config-path> \
     --issues-digest <64-lowercase-hex> \
     --all-issues
   ```

   `--issue` is repeatable, preserves the validated topological order, and is
   never comma-packed or shell-expanded. `--all-issues` and any `--issue` are
   mutually exclusive. The Dashboard always passes one explicit form and
   launches with an argv vector and `shell=False`; no browser value can choose
   the executable, config path, option name, or shell syntax. To retain direct
   CLI compatibility, an operator invocation that supplies neither form keeps
   the existing drain-all behavior, but it is not used by the Dashboard.

   The digest is SHA-256 over the exact configured issue-file bytes presented
   during planning. After the runtime has loaded config, acquired workspace
   ownership, and completed the existing recovery path, it re-reads the
   configured issue file through `runtime.queue.issues_md.parse`, verifies the
   digest, replays authoritative state, and re-validates the complete batch.
   Selected mode is an exact allowlist: the runtime refuses the whole batch if
   any ID is missing, duplicated, terminal, non-actionable, blocked by an
   unfinished dependency outside the allowlist, or if an authoritative active
   issue was omitted. Run-all mode recomputes every current non-terminal
   configured issue, excludes terminal issues with counts, and validates the
   complete dependency graph. Both modes use dependency order with configured
   file order as the stable tie-breaker.

   Runtime rejection occurs after ownership/recovery but before `RunStarted`
   and before any `IssueActivated` or new execution event for the proposed
   batch. It names every refusal reason and exits without silently adding,
   dropping, or activating an issue. A valid zero-item run-all is a successful
   no-op and emits no empty run lifecycle. Dashboard planning is advisory; the
   runtime check is the authority that prevents a stale or forged request from
   expanding execution scope.

3. **Persisted queue ownership.** Run commands are Dashboard-owned control
   records in its SQLite database. Each record stores the repository, mode,
   ordered selected IDs when applicable, exact issue-file digest, submission
   sequence, required idempotency key, and launcher correlation fields. Queue
   order is FIFO by the database-assigned monotonic sequence within a
   repository. An atomic SQLite claim permits at most one active launcher
   process per repository; repositories have independent claims and may launch
   in parallel.

   The run-request API requires an `Idempotency-Key` header. Its value is
   scoped to the repository and uniquely constrained with that repository ID.
   Repeating the same key with the same normalized mode, digest, and issue IDs
   returns the existing command and never creates a second launch. Reusing the
   key with different normalized content returns
   `IDEMPOTENCY_KEY_REUSED` and changes nothing. Queue rows and their
   idempotency/launcher data are never copied into `events.jsonl` and never
   presented as runtime workflow facts.

   `QUEUED`, a launch claim, and `LAUNCH_FAILED` are control-plane conditions
   that exist before a runtime run is evidenced. After a matching
   `RunStarted` is observed through the normal observer path, per-issue
   progress and run outcome are derived only from `events.jsonl`. SQLite may
   retain the submitted command and its correlation for audit and
   idempotency, but it does not independently decide that an issue or run is
   running, completed, failed, or recovered.

4. **Launcher crash behavior.** The queue claim and spawn intent are durable
   before process creation. The OS process spawn and the SQLite receipt cannot
   be one atomic transaction, so ambiguity is handled fail-closed:

   - If the Dashboard crashes while a command is still durably queued and no
     spawn intent was claimed, restart leaves it FIFO-queued and it may be
     claimed normally after full re-validation.
   - If the Dashboard crashes after recording spawn intent, the command is
     never automatically spawned again unless the stored process identity and
     observer evidence prove that no prior spawn occurred. The ambiguous
     window—including a process spawned before its PID/creation identity was
     durably recorded—is `LAUNCH_OWNERSHIP_UNKNOWN`. That repository remains
     closed to another launch and requires explicit operator resolution. The
     Dashboard may observe a recorded PID/creation identity to avoid a
     duplicate launch, but that process evidence is control-plane information,
     not workflow state, and it grants no authority to acquire or repair the
     runtime lease.
   - If a spawned runtime exits before `RunStarted`, the Dashboard reports a
     pre-run/launch failure from bounded, redacted process diagnostics and does
     not fabricate a run or automatically retry it. If `RunStarted` appears,
     subsequent status comes from event evidence. If the runtime crashes after
     `RunStarted`, the missing `RunFinished` remains the permanent honest
     record; the Dashboard displays the existing phrase `no controlled finish
     observed`, never `Running`, and never creates a terminal event.

   A live PID may be displayed separately as `launcher process present`, but
   it cannot upgrade an unresolved `RunStarted` to a liveness claim. An
   abnormal or ambiguous exit pauses later FIFO commands for that repository
   rather than cascading mutations. A later operator-approved retry launches
   the ordinary `runtime.main run` entrypoint; that process acquires the
   existing workspace lease and executes the existing recovery path before
   re-validating selection. The Dashboard never calls recovery bindings,
   repairs the log, breaks or substitutes for the lease, resets Git, or marks
   recovery complete itself.

5. **Frozen event schema.** Doc 03 and the existing closed schemas for
   `RunStarted` and `RunFinished` remain unchanged. This ADR adds no event type,
   schema version, payload key, selection field, queue identifier, or
   idempotency key to the event log. Selection intent and launcher correlation
   remain Dashboard-owned control metadata; runtime workflow truth remains the
   existing event stream.

   Event-log selection metadata is explicitly deferred. If future audit or
   recovery requirements need the selected IDs, mode, issue-file digest, or
   Dashboard command ID inside `RunStarted` or another runtime event, that
   change requires a separate Doc 03 amendment with wire-format validation,
   no-downgrade behavior, observer compatibility, crash semantics, and an
   explicit acceptance gate. Implementers must not silently add such a field
   under this ADR.

**Alternatives rejected.** Launching one process per issue breaks the existing
sequential workspace and budget model and creates lease contention. Passing a
comma-delimited list or shell command weakens exact identity and injection
boundaries; repeated argv options keep each validated ID as data. Trusting only
the Dashboard plan leaves a stale/forged-request race, so runtime re-validation
is mandatory. An in-memory queue loses operator intent on restart; a global
queue prevents safe cross-repository parallelism; writing queue rows to the
event log creates a second writer and pollutes workflow truth with
pre-execution UI state. Automatically retrying an ambiguous spawn can create
two runtimes, while treating PID presence or unresolved `RunStarted` as
`Running` makes a liveness claim the evidence contract cannot support. Adding
selection fields to `RunStarted` is rejected for this feature because it would
silently change the frozen closed schema and no-downgrade boundary.

**Consequences and gate.** The Dashboard becomes capable of initiating real
target mutation indirectly and its local web mutation routes therefore inherit
the existing loopback Host/Origin, strict-body, body-size, CSP, and secret
handling requirements. The runtime gains a public exact-selection contract,
but its state transitions, event schemas, recovery ownership, Git authority,
sequential execution, and run-level budget semantics remain unchanged. SQLite
gains durable command/idempotency/launcher state, explicitly separated from
event-derived workflow state. Conservative crash handling may require operator
attention rather than automatic throughput; this is the cost of preventing an
ambiguous spawn from becoming a duplicate mutation.

If this ADR is accepted, the verification contract is
`docs/31-dashboard-issue-run-control-outcome-matrix.md` together with
`docs/plans/dashboard-issue-run-control-failing-tests.md`. Acceptance
authorizes those documents to govern a later test-first implementation plan;
it does not by itself authorize implementation or commits. Before any
`src/` change, each planned RED group must fail for its intended missing
behavior, not for collection or fixture errors. Completion requires focused
unit and Dashboard tests, the combined suite, unchanged durability-harness
runs for seeds 42 and 1337 with retained raw output, real-browser security and
accessibility verification, and fresh-context adversarial review. Any new
failure window or desired event metadata must return to the applicable
architecture/document gate before source mutation.
