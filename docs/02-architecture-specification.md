# Architecture Specification
**Status:** FROZEN — v1.0, 2026-07-05

---

## 1. Component overview

```
┌────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR (single Python process, no LLM, single writer)    │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Task Ingest   │  │ Event Log    │  │ Reconciler          │  │
│  │ (seam:        │  │ (append-only │  │ (runs on startup,   │  │
│  │  provider.    │  │  JSONL,      │  │  3 boundary checks) │  │
│  │  sync)        │  │  fsync)      │  └─────────────────────┘  │
│  └──────────────┘  └──────────────┘                            │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐  │
│  │ Workspace    │  │ Validator    │  │ Projections         │  │
│  │ Manager      │  │ (determin-   │  │ (queue view, metrics│  │
│  │ (git ops,    │  │  istic:      │  │  dashboard, current │  │
│  │  attempt refs│  │  lint→type→  │  │  state — rebuild-   │  │
│  │  resets)     │  │  build→test→ │  │  able, deletable)   │  │
│  └──────────────┘  │  e2e)        │  └─────────────────────┘  │
│                    └──────────────┘                            │
│  ┌──────────────────────┐  ┌────────────────────────────────┐ │
│  │ Engine seam          │  │ Reviewer seam                  │ │
│  │ implement(prompt_file│  │ review(diff, issue, guidelines,│ │
│  │  , workspace) →      │  │  validation_output) →          │ │
│  │  ExecutionRecord     │  │  ReviewVerdict (structured)    │ │
│  └──────────┬───────────┘  └───────────────┬────────────────┘ │
└─────────────┼──────────────────────────────┼──────────────────┘
              │ subprocess                    │ single-shot call
     ┌────────▼─────────┐          ┌─────────▼──────────┐
     │ Claude Code      │          │ Qwen (Ollama)  or  │
     │ headless         │          │ Claude — config    │
     │ (claude -p,      │          │ flag; provider-    │
     │  JSON out =      │          │ independent; never │
     │  advisory only)  │          │ sees the repo      │
     └──────────────────┘          └────────────────────┘
```

### Responsibilities

| Component | Owns | Never does |
|---|---|---|
| **Orchestrator loop** | Issue selection, execution lifecycle, gate sequencing, budget metering, retry policy | Trust engine self-reports; parse engine stdout for control flow |
| **Workspace Manager** | Clean-base guarantee (I1), branch-per-issue, attempt-ref commits (I2, P7), resets, diff derivation (`git diff start..end`), pin checks (I3) | Let an engine touch git config or credentials |
| **Validator** | Deterministic gate chain, cheapest first: lint → typecheck → build → unit → E2E (E2E only when diff touches mapped UI paths); flake retry (retry test once before blaming code); per-test flake counters | Ask an LLM whether tests passed |
| **Engine seam** | Spawn headless subprocess with prompt file + workspace path + timeout + scoped permissions; normalize usage into `ExecutionRecord` | Interpret engine output as truth about the code |
| **Reviewer seam** | Single-shot structured call; parse-retry on malformed verdict; provider selected by config | See the repository; know who wrote the code |
| **Event Log** | Append-only workflow truth; fsync before ack; monotonic event IDs; schema_version per event | Get edited or compacted in place |
| **Reconciler** | Startup boundary healing (Section 4) | Contain issue-specific logic |
| **Projections** | Queue view, metrics, dashboard, current-state cache | Be treated as authoritative |
| **Task Ingest** | `provider.sync()`: import Issues.md (v1) into the local canonical queue; one-way, best-effort status projection back out (later) | Store workflow state externally |

## 2. Happy-path sequence (one issue)

```
Orchestrator          EventLog        Workspace           Engine        Validator      Reviewer
    │  select issue      │                │                  │              │              │
    │──IssueActivated───►│                │                  │              │              │
    │──ExecutionSpawned─►│  (intent, I6)  │                  │              │              │
    │  reset to clean base (I1); branch issue/<id>; record start_commit     │              │
    │────────────────────┼───────────────►│                  │              │              │
    │  spawn claude -p (prompt pack, timeout, scoped perms) ─►│             │              │
    │  ... engine mutates workspace ...   │◄─────────────────│              │              │
    │  engine exits; commit residue to refs/attempts/<i>/<e> (I2); end_commit             │
    │──ExecutionFinished►│  (fact: usage, duration, exit, start/end commits)│              │
    │  run gate chain against end_commit ────────────────────┼─────────────►│              │
    │──ValidationPassed─►│  (pins validated_commit = end_commit)            │              │
    │  derive diff = git diff start..end; send diff+issue+guidelines+val out──────────────►│
    │──ReviewApproved───►│  (pins reviewed_commit)            │             │              │
    │  GATE I3: end == validated == reviewed?  → yes          │             │              │
    │──CommitIntent─────►│                │                   │             │              │
    │  merge/commit to main branch ──────►│                   │             │              │
    │──CommitCreated────►│  (fact)        │                   │             │              │
    │──IssueCompleted───►│                │                   │             │              │
    │  update projections; next issue     │                   │             │              │
```

**Rejection path (validation or review):** append `ValidationFailed`/`ReviewRejected` with taxonomy category and feedback → workspace reset to clean base (residue already preserved on attempt ref) → if executions-for-issue < cap: append `ExecutionSpawned(parent_execution_id, spawn_reason)` and start a **fresh process** whose context pack includes accumulated feedback → else `IssueEscalated(NEEDS_HUMAN)`. Feedback dedupe rule: if the same reviewer critique category appears twice for one issue, escalate immediately — the loop will not converge.

## 3. Workspace model

- One repo clone; work happens on `issue/<id>` branches cut from a pinned clean base (`main` at run start).
- **Attempt refs:** `refs/attempts/<issue-id>/<execution-id>` — every execution's end state, including failures and crash residue. This is what makes P7 real: diffs are always derivable (`git diff start_commit end_commit`), no evidence is destroyed by resets, and the log stores facts (hashes) rather than duplicated diff blobs. GC attempt refs on issue completion.
- **Pinning:** `ValidationReport` and `ReviewVerdict` record the tree hash they evaluated. Anything that mutates the workspace after validation invalidates the pin; the I3 gate check makes committing an unvalidated/unreviewed tree structurally impossible.
- Engine processes get: the workspace path, a prompt file, read/write on the worktree only, no network push, no credential access, hard wall-clock timeout.

## 4. Recovery model & boundary reconciliation

**Model:** replay, then reconcile the boundary. Recovery = (a) rebuild all projections from the event log — correct for everything the log fully owns; then (b) run the reconciler over the *external boundary*: the only places an effect and its event can be split by a crash. The reconciler does not decide what to do; it **appends the events the crash prevented from being written**, treating git and the workspace as witnesses whose testimony backfills the log.

**The three checks:**

1. **Orphaned execution.** `ExecutionStarted` with no terminal event → the in-flight execution died. Commit workspace residue to its attempt ref (evidence), append `ExecutionCrashed`, reset workspace. Cost of the dead execution is lost; correctness is not.
2. **Unwitnessed commit.** `CommitIntent` with no `CommitCreated` → ask git: `git merge-base --is-ancestor <end_commit> main`. Ancestor → the commit happened; append `CommitCreated` (backfill). Not ancestor → redo the commit (check-then-act; idempotent).
3. **Dirty workspace.** Worktree state inconsistent with the log's last pinned expectation → preserve residue to a `refs/attempts/.../reconciler` ref, reset to last known-good base.

**Why not pure replay:** the system's critical effects (subprocess ran, billing meter advanced, commit object exists) are external and non-transactional — appending the event is not the state change, so log and world can always be split by a crash (the dual-write problem). Pure replay reconstructs what the log *knew*, not what *happened*, and answers "did the commit succeed?" wrong with confidence. Intent-before-action ordering (I5/I6) guarantees the only possible divergence is "world ahead of log," which the three checks heal safely. This preserves P6: recovery inspects invariants, never crash locations.

**Idempotency classes:**

| Class | Transitions | Recovery semantics |
|---|---|---|
| Deterministic | commit, validate, projection updates | Genuinely idempotent: check-then-act against git/filesystem |
| Non-deterministic & costly | engine executions, LLM reviews | **Abandonable**: preserve residue → mark crashed → reset → fresh execution. Never replayed. |

## 5. Context pack (what a fresh engine session receives)

1. **Static:** lean CLAUDE.md — conventions, build/test commands, architecture pointers; target < ~2k tokens.
2. **Per-issue:** issue text + acceptance criteria; accumulated structured feedback from prior executions; *pointers* to likely-relevant file paths (optionally produced by a cheap local-model retrieval pass) — paths, not contents.
3. **Agent-discovered:** the engine's own search tools pull what it needs. Under-stuff rather than over-stuff.

Reviewer receives strictly: diff, issue, guidelines, validation output. Not the repo, not the transcript, not authorship.

## 6. Observability

Every event carries: `run_id, issue_id, execution_id, phase, outcome, taxonomy_category, usage, duration, schema_version`. Failure taxonomy (closed set, extend by ADR): `validation-lint | validation-type | validation-build | validation-test | validation-e2e | review-correctness | review-style | budget-exceeded | timeout | flaky-suite | crashed | needs-decomposition | needs-human`. All metrics (success rate, retries, time/tokens/cost per issue, review failure rate, human interventions, **feedback recurrence** — the promote-to-guidelines signal) are projections: a groupby over the log. Raw transcripts archived per execution at `transcript_path`.
