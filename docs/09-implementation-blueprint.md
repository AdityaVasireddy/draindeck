# 09 — Implementation Blueprint (Session 1)

**Status:** DRAFT until reconciled against doc 03 · **Date:** 2026-07-10
**Purpose:** the complete structural blueprint so that Session 2 begins writing code with zero remaining design questions. This document contains **no implementation code** — only structure, schemas, interface contracts, and lifecycle definitions.

**Reconciliation rule:** doc 03 (state machine & event schema) is the implementation contract. This blueprint was drafted from the frozen handoff summary; before Session 2, diff §4 and §5 below against doc 03 and correct this document to match. Items requiring that diff are marked ⟦reconcile⟧.

**Language assumption:** Python 3.12+, standard library plus `pyyaml` and `pydantic` only (no framework, per non-goals doc 01 §5). ⟦reconcile⟧ against doc 07 if it fixed a different language; the blueprint's structure translates directly.

---

## 1. Project folder structure

```
issue-runtime/
├── config.yaml                    # the ONLY repo-specific knowledge (ADR-20)
├── NEXT.md                        # solo-builder resume pointer (user constraint)
├── README.md
├── pyproject.toml
├── state/                         # runtime-owned, gitignored in target repo terms
│   ├── events.jsonl               # append-only truth store (ADR-11)
│   └── projections/               # rebuildable — safe to delete (ADR-11)
│       ├── queue.json
│       ├── metrics.json
│       └── state.json
├── src/runtime/
│   ├── __init__.py
│   ├── main.py                    # entrypoint: startup → recover → loop → shutdown
│   ├── config.py                  # config schema + load/validate (§3)
│   ├── events/
│   │   ├── schema.py              # event envelope + 12 event types (§4)
│   │   ├── log.py                 # EventLog: append / replay (§6.1)
│   │   └── projections.py         # queue, metrics, state projections
│   ├── state/
│   │   ├── model.py               # issue + execution lifecycles (§5)
│   │   └── transitions.py         # exhaustive transition table (from doc 03)
│   ├── engine/
│   │   └── claude_headless.py     # sole concrete engine, NOT a seam (ADR-08, §6.2)
│   ├── reviewer/
│   │   ├── base.py                # ReviewerProvider ABC (ADR-05, §6.3)
│   │   ├── qwen_ollama.py
│   │   └── claude_reviewer.py
│   ├── repo/
│   │   ├── adapter.py             # RepositoryAdapter interface (§7)
│   │   └── git_adapter.py         # git CLI implementation
│   ├── validation/
│   │   └── runner.py              # deterministic validator (config-supplied commands)
│   ├── budget/
│   │   └── manager.py             # ADR-09 caps + proxy-cost accounting
│   ├── recovery/
│   │   └── reconciler.py          # 3-check boundary reconciler (ADR-12, §8.4)
│   ├── queue/
│   │   └── issues_md.py           # Issues.md parser → queue projection input
│   └── context/
│       └── pack.py                # context-pack builder (doc 02 spec)
├── tests/
│   ├── unit/
│   ├── crash/                     # kill -9 harness — Phase 1 gate lives here
│   └── stub_engine/               # deterministic fake engine for Phase 1
└── docs/                          # docs 01–09 committed here
```

Structural rules: `state/` is machine-owned and never hand-edited; `projections/` must be deletable at any time without loss (rebuild = replay); nothing under `src/` may import a path, branch, or command literal — those exist only in `config.yaml`.

---

## 2. Module dependency direction

```
main → recovery → events, repo
main → loop → queue, context, engine, validation, reviewer, repo, budget → events
events → (nothing internal)          # the log is the bottom of the graph
state ← events (projections)         # state is derived, never authored directly
```

The event log has no internal dependencies; everything else depends on it. The engine and reviewer never touch git or the log directly — the orchestrator loop mediates all writes (LLM self-reports are never trusted, ADR-01/06).

---

## 3. Configuration schema

Canonical example in doc 08 §6. Schema constraints the loader must enforce:

| Section | Required keys | Validation |
|---|---|---|
| `project` | `repository`, `branch`, `issues_file`, `validation.commands` | path exists, is a git repo, branch exists, ≥1 validation command |
| `engine` | `provider`, `auth_mode`, `max_turns`, `timeout_seconds` | `provider == claude-headless` (v1); `auth_mode ∈ {subscription, api_key}`; if `api_key`, `ANTHROPIC_API_KEY` must be present in env; if `subscription`, loader records that the engine wrapper must strip it |
| `reviewer` | `provider` + matching subsection | `provider ∈ {qwen, claude}`; qwen endpoint reachable check deferred to startup, not load |
| `budget` | all caps > 0 | `hard_stop` ≥ expected per-execution proxy cost |
| `experiment` | all three values | loader refuses to start a Phase-4 run if these differ from the values recorded in the first `run_started` event of that experiment (tamper guard for ADR-19 honesty clause) |
| `event_log` | `path` | parent dir writable; file append-only open mode |

Config is loaded once at startup, validated fully before any side effect, and passed as an immutable object. No component re-reads the file mid-run.

---

## 4. Event log schema

### 4.1 Envelope (every event)

```json
{
  "event_id":   "uuid4",
  "seq":        1234,               // monotonic per log file
  "ts":         "2026-07-10T14:03:22.123Z",
  "type":       "execution_started",
  "kind":       "intent",           // intent | fact  (ADR-12 ordering)
  "issue_id":   "ISS-042",          // null for run-level events
  "execution_id": "uuid4-or-null",
  "run_id":     "uuid4",
  "payload":    { }                  // type-specific, schemas in doc 03
}
```

Envelope rules: one JSON object per line, UTF-8, `\n` terminated; append with flush+fsync before the action an intent event announces (I-ordering); `seq` gaps are a corruption signal detected at replay; the log is never rewritten — corrections are new events.

### 4.2 The 12 event types ⟦reconcile — names must match doc 03 exactly⟧

| # | Type | Kind | Emitted when | Key payload |
|---|---|---|---|---|
| 1 | `run_started` | fact | orchestrator boot complete | config snapshot, experiment params |
| 2 | `run_stopped` | fact | clean shutdown | reason |
| 3 | `issue_selected` | intent | issue claimed from queue | issue text hash |
| 4 | `execution_started` | intent | **before** spawning `claude -p` | context-pack hash, start_commit |
| 5 | `execution_finished` | fact | engine process exited | exit code, usage/proxy-cost, end_commit |
| 6 | `execution_abandoned` | fact | reconciler/timeout kills orphan | cause (ADR-13: never replayed) |
| 7 | `validation_recorded` | fact | deterministic checks done | pass/fail per command, validated_commit |
| 8 | `review_requested` | intent | before reviewer call | reviewer provider, input hash |
| 9 | `review_recorded` | fact | verdict received | approve/reject, reviewed_commit |
| 10 | `attempt_archived` | fact | refs/attempts push done (ADR-15) | ref name, commit |
| 11 | `commit_recorded` | fact | commit on work branch witnessed | **commit hash (join key, ADR-11)**, pinning check result |
| 12 | `issue_closed` | fact | terminal state reached | SHIPPED / FAILED / BLOCKED, attempts count |

Intent/fact discipline (ADR-12): every action with an external side effect is bracketed — intent event flushed **before** the action, fact event **after**. The only reachable divergence after a crash is "world ahead of log," which is exactly what the reconciler's three checks detect.

---

## 5. State model

### 5.1 Issue lifecycle (level 1)

```
QUEUED ──select──▶ IN_PROGRESS ──ship──▶ SHIPPED        (terminal)
                        │────fail (attempts exhausted)──▶ FAILED   (terminal)
                        │────block (needs human)────────▶ BLOCKED  (terminal for the run)
```

### 5.2 Execution lifecycle (level 2, ≥0 per issue, ≤ max_attempts)

```
SPAWNED ──engine exit──▶ ENGINE_DONE ──checks pass──▶ VALIDATED ──approve──▶ REVIEWED ──pin holds──▶ COMMITTED
   │                          │                          │                       │
   └──▶ ABANDONED             └──▶ REJECTED(validation)  └──▶ REJECTED(review)   └──▶ REJECTED(pin)
```

Rules: states are **projections of the event log**, never stored authoritatively (ADR-11); an ABANDONED or REJECTED execution is archived to `refs/attempts/<issue>/<execution>` **before** workspace reset (ADR-15) and is never resumed — a retry is a fresh execution (ADR-13); COMMITTED requires the pinning gate `end_commit == validated_commit == reviewed_commit`; deterministic transitions are check-then-act idempotent (safe to re-run after crash); the exhaustive legal-transition table comes verbatim from doc 03 ⟦reconcile⟧ and `transitions.py` must reject anything not in it.

Mapping: `issue_closed(SHIPPED)` requires exactly one COMMITTED execution; `FAILED` requires attempts exhausted with zero COMMITTED.

---

## 6. Interfaces

Contracts only; signatures are normative, bodies are Session ≥2 work.

### 6.1 EventLog

```
append(event: Event) -> int            # returns seq; flush+fsync before return
replay() -> Iterator[Event]            # full ordered scan; detects seq gaps
last_event(filter) -> Event | None
```

### 6.2 Engine — concrete class, not a seam (ADR-08)

`ClaudeHeadlessEngine` (the only engine in v1):

```
run(context_pack: ContextPack, workspace: Path) -> EngineResult
# EngineResult: exit_code, usage (tokens in/out), transcript_path, duration
```

Contract: spawns `claude -p` as a subprocess in the workspace; enforces `max_turns`/`timeout`; owns env hygiene per ADR-18 (strip `ANTHROPIC_API_KEY` in subscription mode, require it in api_key mode); **its return value is advisory only** — workspace mutation observed via the RepositoryAdapter is the real output (ADR-07); transcript stored for debugging, never parsed for facts.

### 6.3 ReviewerProvider — abstract, day one (ADR-05)

```
review(review_pack: ReviewPack) -> ReviewVerdict
# ReviewVerdict: decision ∈ {approve, reject}, reasons: list[str], reviewed_commit: str
```

Implementations `QwenOllamaReviewer`, `ClaudeReviewer` selected by `config.reviewer.provider`. Contract: input is a diff (derived via git, ADR-15) plus issue text; the reviewer never sees or influences git state; a malformed/unparseable verdict is a **reject**, never a retry-until-approve.

### 6.4 BudgetManager (ADR-09)

```
check(scope) -> Allow | Deny(reason)   # called before every execution and reviewer call
record_usage(execution_id, usage)      # feeds proxy-cost accounting (ADR-19)
metrics() -> ExperimentMetrics         # attempt-1 rate, cost/shipped-issue
```

### 6.5 Validator

```
validate(workspace: Path) -> ValidationResult   # runs config-supplied commands
# ValidationResult: passed: bool, per_command: list, validated_commit: str
```

Pure deterministic code; captures the commit it validated so the pinning gate can compare.

---

## 7. Repository adapter interface

All git/filesystem contact with the target repo goes through this — the enforcement point for ADR-20's repository-agnosticism.

```
RepositoryAdapter (ABC), v1 impl: GitCliAdapter

current_commit() -> str
is_dirty() -> bool
checkout_branch(branch: str)
snapshot_commit(message) -> str          # commits ALL workspace changes; returns hash
push_attempt_ref(issue, execution, commit)   # refs/attempts/<issue>/<execution> (ADR-15)
reset_hard(commit: str)                  # workspace cleanup after reject/abandon
diff(base: str, head: str) -> str        # diffs derived, never stored (ADR-15)
verify_commit_exists(hash) -> bool       # reconciler support
```

Contracts: `snapshot_commit` and `push_attempt_ref` are idempotent (check-then-act: if the ref/commit already exists with identical content, succeed silently) — required for crash-safe re-entry (ADR-13); `reset_hard` must be preceded, in orchestrator order, by a successful `push_attempt_ref` — the adapter cannot enforce ordering, so the transition table (§5) does, and a crash between the two is caught by reconciler check 3; no method takes a repo path — the adapter is constructed once from `config.project.repository` and everything else is relative to it. Windows note: the v1 target path is a Windows path; `GitCliAdapter` must treat paths via `pathlib` and never assume `/` separators or POSIX permissions.

---

## 8. Runtime lifecycle

### 8.1 Startup
Load + validate config (§3) → open event log append-only → replay to rebuild projections → **recovery (8.4) before anything else** → emit `run_started` (with experiment-params tamper check, §3) → health checks (repo reachable, branch correct, baseline green if first run, reviewer endpoint up).

### 8.2 Main loop (per issue)

```
select issue          → emit issue_selected (intent)
build context pack    (doc 02 spec)
budget check          → deny ⇒ BLOCKED, next issue
emit execution_started (intent, flushed)      ── crash after this = orphan, check 1
spawn engine          → wait → emit execution_finished (fact)
snapshot_commit       → validate → emit validation_recorded
  fail ⇒ push_attempt_ref → emit attempt_archived → reset → retry or FAILED
review_requested (intent) → reviewer → review_recorded (fact)
  reject ⇒ same archive-reset path
pinning gate: end == validated == reviewed
  hold ⇒ emit commit_recorded (fact, join key) → emit issue_closed(SHIPPED)
  break ⇒ treat as reject
loop until queue empty, budget hard-stop, or stop signal → run_stopped
```

### 8.3 Shutdown
Clean: finish current deterministic step, never interrupt mid-transition; emit `run_stopped`. Crash: no cleanup by definition — recovery owns it.

### 8.4 Recovery (every startup, unconditional — ADR-12)
Replay projections, then run the three boundary checks:
1. **Orphaned execution** — `execution_started` without `execution_finished` → verify no engine process, emit `execution_abandoned`, archive+reset.
2. **Unwitnessed commit** — repo HEAD ahead of last `commit_recorded` → reconcile via `verify_commit_exists` and attempt refs; emit the missing fact or archive+reset.
3. **Dirty workspace** — `is_dirty()` with no execution in flight → archive to a recovery attempt ref, reset to last known-good commit.
Only after all three pass does the main loop start. Phase 1 gate (doc 04): the stub-engine loop must survive `kill -9` at **every** transition in §8.2 and recover to a consistent state through this path.

---

## 9. Session 1 exit criteria

This blueprint is complete when: (a) §4 and §5 are diffed against doc 03 and every ⟦reconcile⟧ marker is resolved; (b) the folder skeleton, empty modules, `config.yaml`, and this doc are committed; (c) `NEXT.md` points at Session 2: "implement `events/schema.py` + `events/log.py` + replay, with the crash-test harness first." No other code exists — that is by design.
