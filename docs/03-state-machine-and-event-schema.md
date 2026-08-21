# State Machine & Event Schema
**Status:** FROZEN — v1.0, 2026-07-05

Two-level model: **issues** own a coarse lifecycle; **executions** (units of work — a retry, a decomposition pass, a human intervention are all executions) own the fine one. Failure "states" are terminal execution outcomes carrying a taxonomy label, not states. RETRY does not exist as a state; it is issue-level policy: "spawn execution N+1 with accumulated feedback, unless N ≥ cap."

## 1. Issue lifecycle (coarse — projection over events)

```
                 ┌───────────────────────────────┐
                 ▼                               │
PENDING ──► ACTIVE ──► DONE                      │ (child issues from
                │                                │  decomposition enter
                ├────► NEEDS_HUMAN               │  as PENDING)
                └────► NEEDS_DECOMPOSITION ──────┘
```

| Transition | Trigger event | Pre-invariant | Artifact produced | Crash-resumable? |
|---|---|---|---|---|
| PENDING→ACTIVE | IssueActivated | Queue selected it; deps (if any) DONE | — | Yes (replay) |
| ACTIVE→DONE | IssueCompleted | I3 pin passed; CommitCreated present | Merge commit on main | Yes (check 2 heals the gap) |
| ACTIVE→NEEDS_HUMAN | IssueEscalated | Execution cap hit, or duplicate feedback category | Escalation record + full evidence chain | Yes |
| ACTIVE→NEEDS_DECOMPOSITION | IssueEscalated(reason=decompose) | Context/turn budget breached mid-work | Child issue specs (optional) | Yes |

## 2. Execution lifecycle (fine — owned by one ExecutionRecord)

```
SPAWNED ──► EXECUTING ──► VALIDATING ──► REVIEWING ──► ACCEPTED
               │               │             │
               │               │             └──► REJECTED(review-*)
               │               └──► REJECTED(validation-*)
               ├──► REJECTED(timeout | budget-exceeded)
               └──► CRASHED   (reconciler-assigned)
```

Per-transition answers to the three design questions:

| State | Artifact produced on exit | Invariant to enter | Resumable after crash? |
|---|---|---|---|
| SPAWNED | intent event on disk | ExecutionSpawned appended & fsync'd (I6) | Yes — no side effects yet |
| EXECUTING | attempt-ref commit (`end_commit`), transcript, usage | I1 clean base; I4 sandbox; start_commit recorded | **No — abandonable.** Reconciler check 1: residue→ref, ExecutionCrashed, reset |
| VALIDATING | ValidationReport pinned to end_commit | end_commit exists on attempt ref | Yes — deterministic; re-run against pinned tree |
| REVIEWING | ReviewVerdict pinned to end_commit | ValidationReport(passed) for same hash | Yes — re-callable; verdicts cacheable by (issue, tree hash) |
| ACCEPTED | — (hands off to issue-level commit) | I3: end==validated==reviewed | Yes — check-then-act commit; reconciler check 2 |
| REJECTED / CRASHED | taxonomy-labeled terminal event, feedback list | — | Terminal |

## 3. Event vocabulary (append-only, versioned)

Envelope, common to all events:

```json
{
  "event_id": 1042,                     // monotonic, single writer
  "schema_version": 1,
  "ts": "2026-07-05T21:14:03Z",
  "run_id": "run-2026-07-05-a",
  "type": "ExecutionFinished",
  "issue_id": "042",
  "execution_id": "042-e3",             // null for issue-only events
  "payload": { }
}
```

| # | Type | Kind | Key payload fields |
|---|---|---|---|
| 1 | IssueCreated | fact | source, title, body, acceptance_criteria, depends_on[] |
| 2 | IssueActivated | fact | base_commit |
| 3 | ExecutionSpawned | **intent** | parent_execution_id, spawn_reason (`initial\|retry\|decompose\|human`), engine, prompt_hash, budget {tokens, dollars, wall_seconds} |
| 4 | ExecutionFinished | fact | start_commit, end_commit (attempt ref), exit_status, usage {input_tokens, output_tokens, dollars}, duration_s, transcript_path |
| 5 | ExecutionCrashed | fact (reconciler) | residue_ref, last_known_state |
| 6 | ValidationPassed / ValidationFailed | fact | validated_commit, gate_results[{gate, passed, duration_s, log_path}], taxonomy_category, flake_retries |
| 7 | ReviewApproved / ReviewRejected | fact | reviewed_commit, reviewer_provider, verdict, severity, feedback[{category, message}] |
| 8 | CommitIntent | **intent** | end_commit, target_branch |
| 9 | CommitCreated | fact | merge_commit, target_branch, backfilled: bool |
| 10 | IssueCompleted / IssueEscalated | fact | reason, taxonomy_category, evidence_refs[] |
| 11 | HumanIntervention | fact | action, note |
| 12 | GuidelinePromoted | fact | feedback_category, guideline_diff — closes the learning loop |

Rules: events are never edited or deleted; new needs → new event type or bumped `schema_version`; projections may change forever, history doesn't. Ordering law (I5/I6): intent events before the effect, fact events after; a crash may therefore only leave a missing *fact*, which the reconciler backfills.

## 4. Artifact schemas

**ExecutionRecord** (projection assembled from events 3–5; the log rows are authoritative):

```json
{
  "schema_version": 1,
  "execution_id": "042-e3",
  "issue_id": "042",
  "parent_execution_id": "042-e2",
  "engine": "claude-code@2.1.x",
  "workspace_path": "/work/repo",
  "start_commit": "a1b2c3…",
  "end_commit": "d4e5f6…",
  "exit_status": 0,
  "usage": {"input_tokens": 41200, "output_tokens": 9800, "dollars": 1.84},
  "duration_s": 1080,
  "transcript_path": "artifacts/042-e3/transcript.jsonl",
  "outcome": "REJECTED",
  "taxonomy_category": "review-correctness"
}
```
Note: **no diff field.** Diffs are derived: `git diff start_commit end_commit`. The record stores facts; git stores code.

**ValidationReport:** `{schema_version, execution_id, validated_commit, gates:[{name, passed, duration_s, log_path}], flake_retries, passed}`

**ReviewVerdict** (the structured contract; parse-retry enforced by orchestrator): `{schema_version, execution_id, reviewed_commit, provider, verdict: "APPROVE"|"REJECT", severity: "blocking"|"minor", feedback: [{category, message, location?}]}` — a verdict approves *tree `reviewed_commit` for issue X*, not "the issue," making verdicts cacheable and replay-safe.

**Issue (queue record, projection):** `{schema_version, issue_id, source_ref, status, depends_on[], executions[], execution_count, cap, accumulated_feedback[], total_dollars}`

## Amendment — execution containment protocol (accepted 2026-08-15)

This amendment adds a durable execution/workspace containment projection. It
does not add an issue transition or alter the execution lifecycle. The Windows
runtime now enforces this protocol with a contained Job root, controlled stdio
inheritance, and a per-workspace ownership lease; the 2026-08-15 T7 witness
validated the configured batch launcher as `cmd.exe` → `claude.exe` inside the
Job. Historical logs with no containment facts remain valid and acquire no
containment guarantee.
The new event types are additive under schema version 1; historical logs with
none of these events remain valid and acquire no containment guarantee.

| Type | Kind | Required relation |
|---|---|---|
| ExecutionContainmentPrepared | intent | Before any contained-root launch attempt; opens a workspace blocker. |
| ExecutionContainmentEstablished | fact | Matching Prepared; suspended root membership/configuration witnessed before resume. |
| ExecutionTerminationUnconfirmed | fact | Matching unreleased Established; latches fail-closed cleanup uncertainty. |
| ExecutionContainmentReleased | fact | Matching unreleased generation; requires a release proof witness. |

Each carries `workspace_key` and `containment_generation`; the append-once
identity is `(execution_id, containment_generation, event_type)`. Replay
blocks a workspace whenever a generation is PREPARED, ESTABLISHED, or
UNCONFIRMED without a matching RELEASED event. Startup/recovery enforce that
blocker before any conflicting workspace operation. T5 worker identity and
human authorization are never release proof.

## 5. Transition table (orchestrator's inner loop, exhaustive)

| From | Guard | Action | Events |
|---|---|---|---|
| idle | queue has PENDING with deps met & budget remaining | activate; clean base; branch | IssueActivated, ExecutionSpawned |
| SPAWNED | intent fsync'd | spawn engine subprocess | — |
| EXECUTING | engine exit (any) | commit residue to attempt ref | ExecutionFinished |
| EXECUTING | timeout/budget breach | kill process; residue to ref | ExecutionFinished(outcome=REJECTED, budget/timeout) |
| post-exec | exit ok | run gate chain vs end_commit | ValidationPassed \| ValidationFailed |
| validated | report.passed | call reviewer (diff, issue, guidelines, val-output) | ReviewApproved \| ReviewRejected |
| reviewed | I3 pin holds | commit intent → merge → fact | CommitIntent, CommitCreated, IssueCompleted |
| any REJECTED | executions < cap ∧ no duplicate feedback category | reset workspace; fresh execution with feedback | ExecutionSpawned(retry) |
| any REJECTED | cap hit ∨ duplicate feedback | escalate | IssueEscalated(NEEDS_HUMAN) |

## Consumer note — read-only external observer (added 2026-08-19)

`src/runtime/observe.py` (ADR-25, `docs/08` §5g, amended §5g Amendment 1)
reads this file's on-disk bytes directly, framing records on `\n` without
instantiating `EventLog`/`ReadOnlyEventLog` or touching any lock, and
streams them in bounded chunks rather than loading the file whole. It also
fingerprints the file's identity (first-record content hash + device/file
index) purely by reading/stat-ing bytes already in view, so a resumed
paginated read can detect the log going missing, that identity changing,
or its own cursor position landing past the current file's end — a
bounded check, not a guarantee against every possible replacement (see
`docs/08` §5g Amendment 1's "Honest scope" note for the specific gap this
does not close). This is observation of the existing physical file, not a
new piece of state this file's schema owns. It is a consumer of the
physical log format above, not
a participant in the state machine: it introduces no event type, no schema
version, and no transition, and this note does not amend anything above
it. Any future change to record framing (event
vocabulary in §3, artifact schemas in §4) must be evaluated against this
second reader, not just the writer/replay path.
| EXECUTING (context blowout) | budget=context/turns | escalate for splitting | IssueEscalated(NEEDS_DECOMPOSITION) |

## Amendment — run lifecycle events: RunStarted/RunFinished (accepted 2026-08-21)

**Status:** ACCEPTED (2026-08-21). This amendment defines the event
schema only. It is **not** authorization to implement, test, or commit
any of it — per the project's own Phase-7 gate, every source-code,
schema-implementation, test, migration, and Dashboard change still
requires its own separate, explicit per-commit authorization before it
lands, exactly as ADR-26 (`docs/08` §5h) required this amendment itself
to exist before implementation could begin.

This amendment adds two new **schema-version-1** event types, `RunStarted`
and `RunFinished`, giving Dashboard Part 2 (`docs/19`) run-level
provenance — engine/reviewer identity, a config fingerprint, and a
controlled-exit outcome — that ADR-25's read-only observer boundary
cannot otherwise see. `schema_version` is not bumped; this is purely
additive to the existing vocabulary, exactly like the containment-protocol
amendment above. It adds **no** issue transition, **no** execution
transition, and changes **no** existing event's envelope or payload.
Historical logs containing neither event type remain fully valid and
receive no fabricated lifecycle metadata.

### Event vocabulary addition

| Type | Kind | Key payload fields |
|---|---|---|
| RunStarted | **intent** | engine {provider, model}, reviewer {provider, model}, budget {max_attempts_per_issue, max_executions_per_run, hard_stop_proxy_cost_per_run_usd, proxy_pricing}, config_digest |
| RunFinished | fact | outcome, detail |

Both are run-scoped: `issue_id` and `execution_id` are always `null` on
both; `run_id` carries the run identifier (see "Run ID format" below);
`ts` uses the existing UTC-seconds-with-`Z` convention (`_utcnow()`),
unchanged.

`RunStarted` is classified **`Kind.INTENT` for write-ordering purposes
only** — it must be fsync'd before the action it announces (normal run
work), exactly matching §3's existing definition of `Kind.INTENT`
("fsync'd BEFORE the action it announces"). It is **deliberately not
added to `RESOLUTION_OF`** (§3's intent/fact pairing table), and the
reconciler/recovery layer must never attempt to resolve, heal, or
backfill a matching `RunFinished` for an orphaned `RunStarted`. This is a
narrow, explicit exception to §3's ordering law ("a crash may therefore
only leave a missing fact, which the reconciler backfills") — `RunStarted`
does not participate in that healing mechanism. An unresolved
`RunStarted` (no matching `RunFinished` anywhere later in the log) is a
**permanent, honest record** that a run started and no controlled exit is
known for it — never a defect the reconciler is expected to fix, and
never a condition any reconciler check trips on. This directly implements
ADR-26 decision 7's "RunFinished is never synthesized after abrupt
process death; recovery may describe crash facts only through existing
recovery mechanisms."

### Run ID format

New run IDs are `run-<UTC-second>-<uuid4>`, e.g.
`run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6` — the existing
legacy timestamp format (`run-YYYYMMDDTHHMMSSZ`) with a UUID4 suffix
appended. Timestamp readability is retained; the UUID4 suffix exists
solely to prevent two runs starting within the same UTC second from
colliding, which the legacy format cannot.

Existing timestamp-only run IDs (no UUID4 suffix) remain valid and are
never rejected, rewritten, or migrated. They are also never claimed to be
collision-free — two historical runs starting in the same second may
share an identical legacy run_id, a known, accepted, unfixed limitation
of runs that predate this amendment. **The authoritative signal for "is
run-level metadata available for this run_id" is the presence of a
matching `RunStarted` event in the log — never the run_id's string shape
or format.** A projection or Dashboard view must never infer
availability, ambiguity, or format by pattern-matching the run_id string
itself.

### RunStarted payload (exact schema)

```json
{
  "event_id": 1042,
  "schema_version": 1,
  "ts": "2026-08-21T06:05:12Z",
  "run_id": "run-20260821T060512Z-3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "type": "RunStarted",
  "issue_id": null,
  "execution_id": null,
  "payload": {
    "engine": {"provider": "claude-headless", "model": "default"},
    "reviewer": {"provider": "qwen", "model": "qwen2.5-coder"},
    "budget": {
      "max_attempts_per_issue": 3,
      "max_executions_per_run": 10,
      "hard_stop_proxy_cost_per_run_usd": 15.0,
      "proxy_pricing": "api_list_rates"
    },
    "config_digest": "…64 lowercase hex chars…"
  }
}
```

- `payload.engine.provider` — the configured engine provider verbatim
  (`"claude-headless"` in v1; ADR-08 governs).
- `payload.engine.model` — the configured engine model verbatim. **Never
  null** (defaults to the literal string `"default"` when unset in
  config).
- `payload.reviewer.provider` — the configured reviewer provider verbatim.
- `payload.reviewer.model` — resolved from the reviewer's own
  provider-specific config subsection (e.g. the `qwen` subsection's
  `model` field when `provider == "qwen"`, the only registered provider
  as of this amendment). **Null only when the selected provider's own
  config subsection has no `model` field at all** — a structural property
  of that provider's config shape, never an omission or a masking of a
  real configured value. No provider registered as of this amendment
  lacks a `model` field; the null case exists for forward compatibility
  with a future provider registration.
- `payload.budget.*` — exactly the four fields named in the table above,
  verbatim from configuration. These are the same four fields as the
  `config_digest` allowlist below, and the only four fields the budget
  configuration has to offer.
- `payload.config_digest` — see below.

### `config_digest` (exact computation)

SHA-256, lowercase hex, over the UTF-8 bytes of a canonical JSON
serialization (`sort_keys=True`, separators `(",", ":")`, no whitespace)
of exactly this object, constructed **by allowlist** — never by taking
the full configuration object and stripping fields:

```json
{
  "budget": {
    "hard_stop_proxy_cost_per_run_usd": <configured value>,
    "max_attempts_per_issue": <configured value>,
    "max_executions_per_run": <configured value>,
    "proxy_pricing": <configured value>
  },
  "engine": {
    "max_turns": <configured value>,
    "model": <configured value>,
    "provider": <configured value>,
    "timeout_seconds": <configured value>
  },
  "reviewer": {
    "model": <resolved reviewer model, or null>,
    "provider": <configured value>
  }
}
```

Ten fields total, matching ADR-26 decision 6 exactly: engine
provider/model/max_turns/timeout_seconds; reviewer provider/model
(resolved, nullable); budget
max_attempts_per_issue/max_executions_per_run/hard_stop_proxy_cost_per_run_usd/proxy_pricing.
Sorting is applied at every nesting level by the serializer, so this
nested shape is fully canonical without manual key-flattening.

**Explicitly excluded — never present anywhere in the digest input, by
construction (the object above is built field-by-field from an
allowlist; nothing else is ever read into it):** every credential,
secret, or token (including but not limited to an Anthropic API key);
engine auth mode and engine child-environment overlay; the reviewer's
endpoint/URL and any other endpoint; validation commands and the
validation child-environment overlay; the repository path and every
other filesystem path; experiment, billing, event-log, and attempts
configuration; and the raw configuration object or any full serialization
of it. This is the same allowlist-not-denylist principle ADR-26 states
explicitly ("Blacklisting secrets in a digest: new secret-shaped fields
could leak; allowlisting safe fields is the safer boundary") — a field
is in the digest only because this section names it, never because it
merely wasn't thought to be dangerous.

### RunFinished payload (exact schema) and the seven controlled outcomes

```json
{"outcome": "COMPLETED", "detail": null}
```

The `detail` key is always present; its value is `null` unless a future
amendment defines a safe, bounded, non-exception-derived classification
for it (see below).

`outcome` is exactly one of: `CHECKOUT_FAILED`, `REVIEWER_UNREACHABLE`,
`BASELINE_FAILED`, `INGEST_FAILED`, `COMPLETED`, `HALTED`, `INTERRUPTED`.
Exactly one `RunFinished` is appended for every controlled terminal exit
that occurs after a `RunStarted` was appended for the same run — never
zero, never more than one.

**Binding safety rule for `detail`:** it must never be constructed from
`str(exception)`, an f-string interpolating exception content, or any
other dynamically-derived value that could carry a filesystem path, a
shell command, a URL/endpoint, or a credential — only a static string
literal chosen by the emitting code, never data extracted at runtime from
an error. Verified against the runtime's current exception types at each
of the seven exit points: `RepoError` ("carries the command and stderr"
per its own docstring); `IssuesParseError`/`FileNotFoundError` (the
latter can embed the issues-file path); the reviewer-reachability health
check's own diagnostic string (embeds the reviewer endpoint);
`OrchestratorHalt`/`ReviewerError` (free-form messages, unaudited against
this contract). None of these is safe to persist verbatim under this
rule. Consequently, **`detail` is defined as always `null` under this
amendment.** Populating it with real information for any outcome requires
a later, separate amendment introducing a genuinely bounded,
non-exception-derived classification (comparable to `taxonomy_category`
elsewhere in this document) — not a retroactive loosening of this rule.

Exact meaning of each outcome, verified against the runtime's current
control flow as of this amendment:

| Outcome | Meaning |
|---|---|
| `CHECKOUT_FAILED` | The target-branch checkout that follows `RunStarted` failed. |
| `REVIEWER_UNREACHABLE` | The pre-flight reviewer-reachability health check (run before baseline validation and issue ingestion) failed. |
| `BASELINE_FAILED` | The baseline validation gate (run only on a fresh log with no replayed events, when not explicitly skipped) failed. |
| `INGEST_FAILED` | Reading or parsing the issues source failed. |
| `COMPLETED` | The run loop returned normally to quiescence — for any of its internal stop reasons (queue drained, or a run-level budget hard stop reached). The internal stop reason is never itself persisted as `detail`, per the rule above. |
| `HALTED` | The run loop raised a controlled halt (a tamper/illegal-state halt, or a reviewer-side error) **during** the run loop. This is distinct from `REVIEWER_UNREACHABLE`: a reviewer error raised during the loop is `HALTED`, not `REVIEWER_UNREACHABLE`, which is reserved for the earlier pre-flight check only. |
| `INTERRUPTED` | The run loop was interrupted (e.g. an operator-initiated interrupt) before reaching quiescence. **The process's own exit code does not distinguish this from `COMPLETED`** in the runtime's current implementation; only the code path actually taken may be used to decide `outcome` — never the exit code. |

### Ordering and pre-normal-run failures

`RunStarted` is appended and fsync'd as the run's **first action after
entering normal run work** — before the target-branch checkout, before
the reviewer-reachability health check, before baseline validation, and
before issue ingestion. This matches ADR-26 decision 6 and `docs/19`'s
"Run lifecycle compatibility" section verbatim.

Any failure that occurs **before** normal run work is entered — a
structurally-invalid or environment-rejected configuration, or any
startup/recovery-boundary failure (workspace ownership unavailable, the
authoritative log writer unavailable, workspace containment blocked, or
engine initialization failure) — is a **pre-normal-run failure** and
emits **neither** `RunStarted` nor `RunFinished`. Recovery and
reconciliation, which run strictly before normal run work is entered, are
entirely unaffected by and unaware of this amendment.

### Never-fabricated abrupt death

If the process dies (crash, kill, power loss, or any failure not among
the seven controlled outcomes above) after `RunStarted` was appended but
before any controlled exit is reached, **no `RunFinished` is ever
written** — not by the dying process, and not retroactively by a later
process's startup or recovery pass. The reconciler's existing
per-execution healing (`ExecutionCrashed` backfill, containment
`ExecutionTerminationUnconfirmed`) is unaffected and unrelated to this
amendment; it must never be extended to also backfill a `RunFinished`.
An unresolved `RunStarted` is the permanent, correct record of this case
(see "Event vocabulary addition" above).

### Replay and projection treatment

Replaying `RunStarted` or `RunFinished` advances the log's last-event-id
and increments its per-type event count — the same generic bookkeeping
every event type already receives on replay — and does nothing else: no
issue transition (§1) and no execution transition (§2) ever fires for
either type, and no existing projection field is touched. A projection
digest computed over a log that contains these events naturally reflects
their presence in that per-type count, exactly as it already does for
every event type; this is expected and requires no special-casing for
backward digest-byte compatibility, since old logs simply never contained
these types to begin with.

Dashboard-side rendering of `RunStarted`/`RunFinished` (provider/model/
budget/outcome, and the "run metadata unavailable (legacy/ambiguous)"
fallback for a run_id with no matching `RunStarted`) is specified in
`docs/19` and is Dashboard's own concern — this section states only what
the runtime's own replay/projection layer does, which is nothing beyond
the bookkeeping above.

### No-downgrade policy

Once a log contains a `RunStarted` or `RunFinished` event, every
subsequent attempt to open it — for writing or for read-only replay — by
a binary that does not recognize both new event types must refuse. This
is a **binding operational policy**: operators must not attempt to
replay or write such a log with a Draindeck binary older than the one
that introduced this amendment. Release documentation must state this as
a refusal, not an implied compatibility promise — matching ADR-26
decision 8 exactly.

This refusal is already structural in the existing schema/log
implementation, verified by inspection as of this amendment, not merely
asserted as a hoped-for property: an event's `type` string is resolved
through the closed `EventType` enum, an unrecognized string raises a
schema error, and every entry point that reads or opens a log for
writing — a fresh open, a full replay, or a read-only inspection —
already converts that schema error into a refusal to proceed. Adding
`RunStarted`/`RunFinished` to the enum on the introducing binary and
leaving them absent on an older one is therefore sufficient by itself to
make an older binary refuse such a log; this amendment requires no new
enforcement code beyond registering the two new type strings.

Existing logs containing neither `RunStarted` nor `RunFinished` remain
fully valid under every existing rule in this document — this amendment
adds two new rows to the vocabulary above and one narrow exception to the
reconciler-resolution rule; it changes no envelope field, no existing
event's payload, no issue transition (§1), no execution transition (§2),
and no transition-table row (§5).
