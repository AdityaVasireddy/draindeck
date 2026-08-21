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

**Corrected the same day (2026-08-21).** Verification against the
running code (not assumption) found the originally accepted text
overstated the no-downgrade refusal's scope and timing, and understated
what replaying these events actually requires. Both are corrected in
place below, each marked "— corrected 2026-08-21" with a note explaining
what changed and why; a new "Strict replay validation" section was also
added. Implement against the corrected text only.

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

### Replay and projection treatment — corrected 2026-08-21

**Correction note:** the version of this section accepted on 2026-08-21
claimed replaying `RunStarted`/`RunFinished` "requires no code change to
`projections.py`." That was wrong: it accounted for state-machine
bookkeeping only and omitted structural payload validation, which this
amendment does require (see "Strict replay validation" immediately
below). The corrected rule is stated here; do not implement against the
original claim.

Replaying `RunStarted` or `RunFinished` performs exactly two things:
generic bookkeeping (advancing the log's last-event-id and incrementing
its per-type event count — the same generic bookkeeping every event type
already receives on replay) and the structural validation defined in
"Strict replay validation" below. It does nothing else: no issue
transition (§1) and no execution transition (§2) ever fires for either
type, and no existing projection field (`issues`, `executions`,
`issue_executions`, `issue_base_commit`, `issue_depends_on`) is ever
touched by either type. A projection digest computed over a log that
contains these events naturally reflects their presence in the per-type
count, exactly as it already does for every event type; this needs no
special-casing for backward digest-byte compatibility, since old logs
simply never contained these types to begin with.

Dashboard-side rendering of `RunStarted`/`RunFinished` (provider/model/
budget/outcome, and the "run metadata unavailable (legacy/ambiguous)"
fallback for a run_id with no matching `RunStarted`) is specified in
`docs/19` and is Dashboard's own concern — this section states only what
the runtime's own replay/projection layer does.

### Strict replay validation (added 2026-08-21)

Structural validation of `RunStarted`/`RunFinished` happens at
**projection-building time** (`StateProjection.apply()`), the same layer
that already validates the containment-protocol payloads above — never at
raw byte-level replay (`EventLog.replay()`/`ReadOnlyEventLog.replay()`),
which only ever checks the envelope (`event_id` contiguity,
`schema_version`, a known `type` string, `payload` is a JSON object) and
has no concept of any specific type's payload shape. A **malformed but
recognized-type** payload therefore replays cleanly at the raw byte
level and only fails once a consumer builds a `StateProjection` from the
log — `show-state`, `recover()` (and therefore ordinary startup), the
orchestrator, and any future run-lifecycle projection all do this and
will all encounter the failure; a bare contiguity check (`verify-log`)
will not. This is the identical failure-mode split the containment
protocol amendment already established for its own payloads, not a new
asymmetry introduced here.

Validation is implemented as two new `_HANDLERS` entries
(`EventType.RUN_STARTED`, `EventType.RUN_FINISHED`) whose functions
**validate only — they perform no state mutation** (they never touch
`issues`, `executions`, or any other projection field). This is
independent of, and must not be confused with, `RESOLUTION_OF`: adding a
validation-only `_HANDLERS` entry does **not** add either type to
`RESOLUTION_OF`, and the reconciler continues to never attempt to
resolve, heal, or backfill a `RunFinished` for an orphaned `RunStarted`,
exactly as "Event vocabulary addition" above requires. `_HANDLERS` and
`RESOLUTION_OF` are separate mechanisms consulted by separate consumers
(`StateProjection.apply()` and the reconciler, respectively); nothing in
this section changes that.

A validation failure raises `TransitionError` — the same exception type
containment-payload validation already raises — and propagates out of
`StateProjection.apply()`/`rebuild()` exactly as any other
`TransitionError` does today, including out of `recover()`
(`src/runtime/recovery/reconciler.py`, which constructs a fresh
`StateProjection` and calls `apply()` for every replayed event as part of
ordinary startup, verified by reading that module). A log containing a
structurally malformed `RunStarted`/`RunFinished` therefore refuses to
complete startup recovery — the same fail-loud posture already applied
to every other event this document governs ("a log that does not replay
cleanly is corrupted history").

Exact rules, applied at `apply()` time:

**Envelope, both types:**
- `run_id` must be non-null (§3's envelope otherwise allows `run_id` to
  be null for other event types; for `RunStarted`/`RunFinished` it must
  not be).
- `run_id` must match the new-format pattern
  `run-\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`
  — the legacy timestamp-only format is never valid for either type,
  because a legacy-format run never has a `RunStarted`/`RunFinished` in
  the first place.
- `issue_id` must be null.
- `execution_id` must be null.

**`RunStarted` payload — closed schema, exactly these keys, no others:**
- `engine`: a JSON object with exactly the keys `provider` (non-empty
  string) and `model` (non-empty string — never null for `RunStarted`,
  per "RunStarted payload (exact schema)" above).
- `reviewer`: a JSON object with exactly the keys `provider` (non-empty
  string) and `model` (string or `null` — the documented nullable rule
  above; when present as a string it must be non-empty).
- `budget`: a JSON object with exactly the keys
  `max_attempts_per_issue` (integer ≥ 1), `max_executions_per_run`
  (integer ≥ 1), `hard_stop_proxy_cost_per_run_usd` (number > 0), and
  `proxy_pricing` (non-empty string).
- `config_digest`: a string matching `^[0-9a-f]{64}$` (exactly 64
  lowercase hexadecimal characters).
- No key other than `engine`, `reviewer`, `budget`, `config_digest` may
  be present at the top level of the payload, and no key other than the
  ones named above may be present inside `engine`, `reviewer`, or
  `budget`. This makes the schema **closed**, not merely a
  minimum-required-fields check — see "Why the schema is closed" below.

**`RunFinished` payload — closed schema, exactly these keys, no others:**
- `outcome`: a string, exactly one of `CHECKOUT_FAILED`,
  `REVIEWER_UNREACHABLE`, `BASELINE_FAILED`, `INGEST_FAILED`,
  `COMPLETED`, `HALTED`, `INTERRUPTED`. Any other value — including a
  plausible-looking string — is rejected.
- `detail`: the key must be present, and its value must be `null`. Under
  this amendment any non-null `detail` is rejected, which makes "`detail`
  is always null" (a design decision stated above) an enforced invariant
  rather than documentation prose alone: no implementation can begin
  quietly populating it without this document being amended first.
- No key other than `outcome` and `detail` may be present.

**Why the schema is closed.** §3's general rule ("new needs → new event
type or bumped `schema_version`") already implies payload evolution
within one `schema_version` should never be silent; closing the schema
for these two types makes that implication an enforced invariant instead
of a convention. It also extends the same allowlist discipline
`config_digest`'s own computation already applies to *configuration*
fields to the *entire payload shape* — an unexpected extra field (for
example, a future code change accidentally attaching a raw configuration
fragment alongside the allowlisted ones) fails loudly at replay instead
of silently persisting unnoticed. A field genuinely needed in the future
is added via a new amendment to this document, exactly like this one.

### No-downgrade policy — corrected 2026-08-21

**Correction note:** the version of this section accepted on 2026-08-21
overstated the refusal's scope ("every subsequent attempt to open it —
for writing or for read-only replay") and implied no mutation could occur
before it fires. Both are corrected below: the refusal applies to the
strict writer/replay path only (`EventLog`, `ReadOnlyEventLog`) — not to
ADR-25's bytes-direct observer — and `EventLog`'s own pre-existing
torn-tail repair can mutate the physical file before the refusal is
reached, in a narrow, unrelated case described below. Do not implement
against the original claims.

**Scope: the strict writer/replay path only.** `EventLog` (the
authoritative writer) and `ReadOnlyEventLog` (`verify-log`, `show-state`,
and any other strict inspection) both resolve every event's `type`
through the closed `EventType` enum; an unrecognized string raises a
schema error that every entry point on this path — `EventLog.__init__`'s
own startup scan, `EventLog.replay()`, and `ReadOnlyEventLog`'s replay —
already converts into a refusal to proceed, with no new code required
beyond registering the two new type strings on the introducing binary.
The scan that performs this check reads the whole file in `event_id`
order and refuses on the **first** unrecognized type it reaches, so a
`RunStarted`/`RunFinished` anywhere in the log — not only at the very
end — is caught.

**ADR-25's `draindeck observe` is intentionally exempt from this
refusal** — this restates this document's own existing "Consumer note"
above, applied to this amendment as that note itself requires ("Any
future change to record framing... must be evaluated against this
second reader, not just the writer/replay path"). The bytes-direct
observer never instantiates `EventLog` or `ReadOnlyEventLog` and never
validates a record's `type` against `EventType` at all (per its own
module docstring: "Unknown event types and schema versions are retained
as exact raw evidence"). It can therefore continue to expose a
`RunStarted`/`RunFinished` record as ordinary `integrity: "OK"` evidence
— with `eventType` carrying the literal string, unvalidated — even from
an observer binary **older** than the one that introduced this
amendment, with no code change to `observe.py` required for that forward
compatibility. What the observer categorically cannot do, regardless of
its own version, is replay in the strict §3 sense (it enforces no
`event_id` contiguity and no payload structure) or write to the log at
all — it is read-only by construction (ADR-25). "No-downgrade" as a
refusal-to-proceed guarantee is therefore a property of the strict
writer/replay path only; it was never intended to be a property of the
bounded observer, which trades that strictness for the forward-compatible,
torn-tail-tolerant reading ADR-25 requires of it.

**Refusal is not necessarily the first thing that happens to the
physical file.** `EventLog.__init__` runs its existing, pre-existing
torn-tail repair (`_repair_torn_tail`) *before* the strict type-scan
(`_scan_last_event_id`) that would raise on an unrecognized type.
Torn-tail repair reads the whole file and, only if the file's physical
last line is not newline-terminated, truncates that incomplete tail to a
sidecar file — a mechanism that predates this amendment, exists for an
unrelated reason (recovering from a crash mid-append), and engages
identically whether or not the log contains any lifecycle event. For the
common case — a cleanly closed log, or a `RunStarted`/`RunFinished` that
is not the physical last, torn line — this performs a read with no
write, and the type-scan's refusal is reached with the file completely
unmodified. In the narrow case where the log's torn tail happens to *be*
an incomplete `RunStarted`/`RunFinished` write (the process crashed
during that specific append, before its `fsync` completed) and no other
lifecycle event exists earlier in the log, torn-tail repair quarantines
that incomplete line before the type-scan ever sees it; the now-truncated
file may then contain no lifecycle event at all, and an older binary
could open and append to it successfully. This is the same class of
narrow, accepted gap the "Consumer note" above and ADR-25 already accept
for the observer's own bounded reading (an in-place rewrite the
fingerprint cannot see) — not something this amendment closes, and worth
stating honestly rather than implying away.

Once the type-scan reaches an unrecognized `RunStarted`/`RunFinished`
line without having quarantined it away, the refusal fires **before**
the file is ever reopened for appending (`EventLog.__init__` raises
before reaching the `open(self.path, "ab")` call) — an older binary
therefore never appends a new event past that point. **Operators must
still not open a log that has any `RunStarted`/`RunFinished` event with a
Draindeck binary older than the one that introduced this amendment,
regardless of this mechanism's exact boundary** — the guarantee that
matters operationally (no silent data loss, no split-brain log) holds for
every realistic case, and the one narrow gap above requires a crash
timed to the single specific write this amendment adds, not an everyday
occurrence. Release documentation must state this as an operator rule, a
refusal, not an implied compatibility promise — matching ADR-26 decision
8.

Existing logs containing neither `RunStarted` nor `RunFinished` remain
fully valid under every existing rule in this document — this amendment
adds two new rows to the vocabulary above and one narrow exception to the
reconciler-resolution rule; it changes no envelope field, no existing
event's payload, no issue transition (§1), no execution transition (§2),
and no transition-table row (§5).
