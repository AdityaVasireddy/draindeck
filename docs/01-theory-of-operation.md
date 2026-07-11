# Theory of Operation
**System:** Autonomous Issue-Resolution Runtime (working name: "the runtime")
**Status:** FROZEN — v1.0, 2026-07-05
**Scope:** Single machine, single writer, sequential execution, one repository.

---

## 1. What this system is

A durable workflow runtime that drains a queue of development issues by repeatedly spawning **fresh, isolated coding-engine processes** against a git workspace, gating their output through **deterministic validation** and an **independent LLM reviewer**, and recording everything that happens in an **append-only event log**.

It is not an AI framework. It is a hybrid of ideas from git (immutable code history), event sourcing (append-only operational history), durable execution (crash recovery via reconciliation), and build systems (content-addressed artifacts, deterministic validation). The LLM is one kind of execution engine operating on a workspace — incidental to the runtime, decisive for the outcome.

## 2. Design philosophy

1. **The workspace is the contract.** Engines are black boxes that mutate a directory. The orchestrator never parses engine output for anything load-bearing; git tells it what changed. An engine can lie in its JSON summary; it cannot lie in the diff.
2. **Two sources of truth, joined by a hash.** Git is authoritative for *code states*. The append-only event log is authoritative for *workflow facts* (cost, duration, verdicts, engine identity, interventions). Every event that touches code carries commit hashes; the commit hash is the join key.
3. **LLMs are untrusted workers.** Validation is run by the orchestrator, deterministically. Behavioral guarantees ("engine leaves worktree clean," "engine respects budget") are never trusted — they are **enforced as orchestrator invariants** (reset the worktree yourself, meter cost yourself, strip push credentials yourself).
4. **Fresh context per execution.** LLM quality degrades as context fills. Every execution is a new process with a minimal context pack. The repository and the event log carry memory; the conversation does not. A failed execution is killed, not coached — feedback is written down and handed to a fresh process.
5. **Intent before action, fact after action.** Every external effect (spawning an engine, creating a commit) is preceded by an intent event and followed by a fact event. A crash can therefore only produce "world ahead of log," never "log ahead of world" — the direction that is safe to heal and never double-spends money.
6. **Schemas are cheap; behavioral abstractions are expensive.** Typed, versioned data contracts exist from day one (they are the persistence schema). Behavioral interfaces (a pluggable engine framework) are extracted from observed variation later, not invented from anticipated variation now.
7. **Abandonable, not universally idempotent.** Deterministic transitions (commit, validate, project) are idempotent via check-then-act. Non-deterministic, costly transitions (LLM executions) cannot be idempotent; they are made *safely abandonable*: crash residue is preserved as evidence, the workspace is reset, a fresh execution starts.

## 3. Core principles (normative)

- P1. Workspace is the contract.
- P2. Git is the source of truth for code; the event log is the source of truth for workflow. State files, queues, dashboards, and metrics are **projections** — deletable and rebuildable.
- P3. Orchestrator enforces invariants; it does not trust contracts.
- P4. LLMs are untrusted workers.
- P5. Intent before action; fact after action; the reconciler closes the gap.
- P6. Recovery never depends on knowing where the crash landed.
- P7. Every execution — including failed ones — ends in a commit (to a namespaced attempt ref) so that all diffs are derivable and no evidence is destroyed by resets.
- P8. Money is metered by the orchestrator: per-execution and per-run budget caps, enforced from normalized usage in the execution record.

## 4. Invariants (checked, not assumed)

| ID | Invariant | Enforced when |
|----|-----------|---------------|
| I1 | Every execution starts from a clean workspace at a known base commit (`git reset --hard` + `git clean -fd` before spawn). | Pre-spawn |
| I2 | Every execution's residue is committed to `refs/attempts/<issue>/<execution>` before any reset. | Post-execution, pre-reset |
| I3 | **Pinning:** an issue may enter COMMITTING only if `end_commit == validated_commit == reviewed_commit`. Three records, one hash. | Commit gate |
| I4 | Engine processes run with scoped permissions, no push credentials, and a wall-clock timeout. | Spawn config |
| I5 | An event is appended (fsync'd) before its projection is updated; projections are never written without a backing event. | Every transition |
| I6 | `ExecutionStarted` (intent) is appended before the engine process is spawned. | Pre-spawn |
| I7 | Per-execution token/dollar cap and per-run daily cap; breach terminates the execution and records `budget-exceeded`. | Continuous |
| I8 | Retry cap per issue (default 3 executions); breach transitions the issue to NEEDS_HUMAN, never silent grinding. | Issue policy |

## 5. Non-goals (v1)

- **No plugin framework.** Seams (function boundaries) exist for task source, engine, reviewer, validator; plugin registration/config-loading does not.
- **No engine abstraction layer.** One implementation engine (Claude Code headless) behind the workspace-in/diff-out boundary. A second engine justifies extracting the interface from two working implementations; anticipation does not.
- **No parallelism.** Sequential, one branch, one worktree. Worktree parallelism is a Phase 3 decision gated on measured sequential throughput.
- **No distributed workflow engine** (Temporal, n8n). Single node, single writer; the event log + reconciler provides durability at ~2% of the operational cost.
- **No external system as state store.** GitHub/Linear/Jira may later *feed* the local canonical queue via one-way sync; workflow state never lives in them.
- **No LLM-mediated git, testing, or state management.** Deterministic code only.
- **No unattended runs until 20 supervised issues have established baseline metrics.**

## 6. The falsification stance

The runtime is designed to instrument its own viability. The event log exists so that, after ~20 real issues, these questions have answers: attempt-1 success rate, cost per shipped issue, dominant failure category, reviewer disagreement rate. If cost-per-issue or success rate makes the loop uneconomical, the design's job is to reveal that quickly and cheaply — not to be elaborated further. Architecture beyond this document is procrastination dressed as rigor until the first 20 issues have run.
