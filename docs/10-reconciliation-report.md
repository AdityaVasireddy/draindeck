# 10 — Doc 03 Reconciliation Report

**Status:** COMPLETE · **Date:** 2026-07-11
**Inputs:** doc 03 (frozen v1.0, 2026-07-05) vs. doc 09 §§4–5 draft and the Session 2 codebase built from it.
**Verdict:** doc 09's provisional event schema and state model diverged from the contract in both names and semantics. All divergences are resolved in code; doc 03 won every conflict. Doc 09 §4 and §5 are **superseded** by doc 03 plus this report.

## 1. Divergences found and resolved

| # | Area | Doc 09 draft (wrong) | Doc 03 contract (now implemented) |
|---|---|---|---|
| 1 | Envelope id | uuid `event_id` + separate integer `seq` | `event_id` IS the monotonic integer (single writer); no uuid |
| 2 | Envelope fields | `kind` serialized; no `schema_version` | `schema_version` serialized; `kind` is code-side schema knowledge only |
| 3 | Type naming | snake_case | CamelCase, verbatim from §3 |
| 4 | Validation events | one `validation_recorded` with `passed` flag | two types: `ValidationPassed` / `ValidationFailed` |
| 5 | Review events | intent `review_requested` + `review_recorded` | **no review intent** (REVIEWING is re-callable, verdicts cacheable); two facts: `ReviewApproved` / `ReviewRejected` |
| 6 | Commit events | single fact `commit_recorded` | **`CommitIntent` (intent) + `CommitCreated` (fact)** with `backfilled` flag — a whole intent event was missing |
| 7 | Attempt archival | dedicated `attempt_archived` event | no such event: the attempt ref is carried by `ExecutionFinished.end_commit` / `ExecutionCrashed.residue_ref` |
| 8 | Issue vocabulary | `issue_selected` / `issue_closed(disposition)` | `IssueCreated`, `IssueActivated`, `IssueCompleted`, `IssueEscalated(reason)` |
| 9 | Missing types | — | `HumanIntervention`, `GuidelinePromoted` (counted; orchestration later) |
| 10 | Run events | `run_started` / `run_stopped` types | not in the vocabulary; `run_id` is an envelope field only |
| 11 | Issue states | QUEUED / IN_PROGRESS / SHIPPED / FAILED / BLOCKED | PENDING / ACTIVE / DONE / NEEDS_HUMAN / NEEDS_DECOMPOSITION |
| 12 | Execution states | ENGINE_DONE / VALIDATED / REVIEWED / COMMITTED / ABANDONED | EXECUTING / VALIDATING / REVIEWING / ACCEPTED / REJECTED(taxonomy) / CRASHED |
| 13 | **Recovery semantics** | orphan with completion evidence → *witness* `execution_finished` | **never witnessed**: residue → attempt ref → `ExecutionCrashed` → reset; an unwitnessed exit is indistinguishable from a partial run. Backfill applies to check 2 (`CommitCreated(backfilled=true)`) only |
| 14 | Timeout/budget | separate rejection path | `ExecutionFinished(outcome=REJECTED, taxonomy budget/timeout)` |

Two notes on faithful-but-explicit interpretation, flagged rather than silently decided:
- **SPAWNED vs EXECUTING:** no event marks the subprocess spawn, so replay cannot distinguish them. The projection maps `ExecutionSpawned` → EXECUTING; SPAWNED remains in the enum for the orchestrator's in-process bookkeeping (documented in `state/model.py`).
- **"12 event types":** doc 03's table has 12 rows but 15 distinct type strings (three rows are pass/fail pairs). The code implements all 15.

## 2. What changed in code

`events/schema.py` and `state/transitions.py` (the two declared reconciliation surfaces) were rewritten verbatim to the contract. The semantic deltas rippled further than names, exactly at the two places doc 03 disagreed with the draft's *behavior*: `recovery/reconciler.py` (crashed-not-witnessed, `preserve_residue` seam running before the fact), and `events/projections.py` (CommitIntent/CommitCreated ordering enforced — `CommitCreated` without a prior `CommitIntent` is a replay error, I5/I6 made structural). The worker and harness were rewritten to the doc 03 happy path (15 injection points, up from 14) and the invariant set gained **I-h**: each execution's `ExecutionFinished` pid must equal its `ExecutionSpawned` pid — the "abandonable, never replayed" rule made observable in the log.

## 3. Re-verification evidence (all observed this session)

19/19 unit tests pass, including two new contract tests: `CommitCreated`-without-intent raises, and recovery emits `ExecutionCrashed` (never `ExecutionFinished`) even when world evidence of completion exists. The kill-9 harness passes **46/46 scenarios on two seeds** (15 points × 2 occurrences + 15 random-timing rounds + control). Mutation test: disabling recovery in the worker was caught by I-h ("finished by a different process than spawned it"). The event log durability layer itself needed only the `seq`→`event_id` rename — no durability semantics changed, which is the payoff of keeping the machinery envelope-generic.

## 4. Standing caveats

Windows execution of both suites remains untested (Linux only; `NEXT.md` step 1). `kill -9` proves process-crash durability, not power-loss durability — the fsync calls cover the latter by construction but are unverifiable in this harness. Reconciler checks 2 and 3 remain injectable seams reported as SKIPPED until the RepositoryAdapter (Session 3) binds them; the stub heals check-2 situations check-then-act with the `backfilled` flag, matching the contract's intent.
