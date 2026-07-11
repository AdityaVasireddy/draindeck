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
| EXECUTING (context blowout) | budget=context/turns | escalate for splitting | IssueEscalated(NEEDS_DECOMPOSITION) |
