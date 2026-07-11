# Architecture Decision Records
**Status:** FROZEN — v1.0, 2026-07-05. Format: context → decision → alternatives rejected → consequences. All Accepted unless noted.

---

## ADR-01 — Two AI roles, not seven agents
**Context:** Initial spec proposed Planner, Orchestrator, Coder, Tester, Reviewer, Git, State-Manager agents.
**Decision:** Only two LLM roles: Implementer and Reviewer. Testing, git, and state are deterministic code; planning is a one-shot preprocessing pass.
**Rejected:** Multi-agent role mapping — maps a human org chart onto software; LLM testers/git agents add only failure modes.
**Consequences:** Orchestrator is plain code; validation is unforgeable; system cost and complexity drop by an order of magnitude.

## ADR-02 — Claude Code headless as the v1 implementation engine
**Context:** Build-vs-buy across Claude Code, OpenHands, SWE-agent, Aider, Codex CLI.
**Decision:** Reuse Claude Code as a headless subprocess (`claude -p`, JSON output advisory). OpenHands is the designated Plan B if Anthropic automation pricing becomes untenable.
**Rejected:** OpenHands as v1 (heavier ops for equivalent capability); SWE-agent (research harness); Aider (stalled release cadence, Aug 2025); building an agent loop from scratch (rebuilds Claude Code's internals).
**Consequences:** Fastest path to first run; pricing exposure mitigated by ADR-09 and the workspace boundary (ADR-07).

## ADR-03 — No LLM-call orchestration frameworks
**Decision:** No LangGraph/AutoGen/CrewAI. The unit of work is an *agent process* with its own inner loop, not an LLM call; the pipeline is a sequential gate chain expressible as a while-loop.
**Rejected:** Graph frameworks — a state machine wearable as a Python loop, plus a dependency to maintain.

## ADR-04 — No distributed workflow engine
**Decision:** No Temporal/n8n. Single node, single writer, sequential; event log + reconciler provides durability. Reconsider only for multi-machine parallel fleets.
**Rejected:** Temporal — solves distributed exactly-once for a problem that is neither distributed nor in need of it here.

## ADR-05 — Seams, not a plugin framework
**Context:** Proposal to model the system as a workflow engine with interchangeable Task/LLM/Validator plugins.
**Decision:** Function-boundary seams (`provider.sync`, `engine.implement`, `reviewer.review`, `validator.run`) in one module. No registration, config-driven loading, or capability negotiation. Abstractions are **extracted from observed variation, not invented from anticipated variation**.
**Rejected:** Day-one plugin architecture — encodes guesses; produces an interface shaped like Claude Code with the name scrubbed out.
**Consequences:** Second-implementation refactor is an afternoon and the interface will be evidence-derived (Phase 5).

## ADR-06 — Data contracts day one; behavioral contracts never trusted
**Context:** Pushback that an orchestrator needs typed boundaries early.
**Decision:** Typed, versioned records (`schema_version` on all) from day one — they are the persistence schema that crash-resumability forces anyway. Behavioral guarantees ("engine leaves worktree clean") are not interfaces; they are orchestrator-enforced invariants (reset yourself, meter yourself, strip credentials yourself).
**Principle recorded:** *Schemas are cheap; behavioral abstractions are expensive.*

## ADR-07 — The workspace is the contract; git is the integration API
**Decision:** Engine boundary = "spawn headless subprocess with prompt file + workspace path; subprocess mutates workspace; orchestrator derives the diff via git." Engine stdout is archived transcript, never load-bearing.
**Rejected:** JSON/stdout as the engine interface — engines can lie in summaries; they cannot lie in the diff.
**Consequences:** Any headless harness becomes pluggable later because all of them express work as file changes; the interface is unfakeable.

## ADR-08 — Asymmetric seam treatment: reviewer abstracted now, engine not
**Context:** "You already have two engines (Claude, Qwen)."
**Decision:** Reviewer seam gets full provider independence day one (two live providers exist; call shape is trivial: prompt→structured verdict). Engine seam stays concrete: Qwen-on-Ollama is a bare model, not an engine — it needs a harness, and *which harness* is exactly the unobserved variation ADR-05 defers.
**Consequences:** Qwen carries cheap review load immediately; engine abstraction waits for a real second harness.

## ADR-09 — Cost is a first-class, engine-invariant concern
**Context:** June 15, 2026 Anthropic change: headless/Agent-SDK usage moved to a separate credit pool billed at API rates (~$20/mo on Pro); reports conflict on whether the split shipped or was paused — verify (doc 06).
**Decision:** Budget caps (per-execution, per-run) live in the orchestrator core; `usage` is a mandatory normalized field of every ExecutionRecord; cost-ordered gating (local model before paid model) is default policy.
**Rejected:** Letting pricing drive structure (it drives *engine choice and caps*, not architecture) — and equally, dismissing it as ops trivia on a $20 plan.

## ADR-10 — Fresh process per execution; feedback over conversation
**Decision:** Retries are new processes with accumulated written feedback, not continued sessions. A session that produced a failure carries the reasoning that produced it; context quality degrades past ~100–150k tokens.
**Consequences:** Repository + event log are the memory; the Ralph-loop property (fresh context is the point, not a side effect) is preserved.

## ADR-11 — Dual truth stores: git for code, append-only event log for workflow
**Context:** "Git is the source of truth" was overclaimed — cost/verdicts/durations don't belong in a commit graph.
**Decision:** Event log (append-only JSONL, fsync, monotonic IDs, versioned events) is authoritative for workflow facts; git for code states; **commit hash is the join key**. Queue, metrics, dashboard, state file are projections — deletable, rebuildable, never authoritative.
**Rejected:** Git-as-workflow-database; mutable state file as truth (demoted to cache/index).

## ADR-12 — Replay + boundary reconciliation, not pure replay
**Context:** Event-sourcing claim: "delete projections, replay, done — no reconciliation code."
**Decision:** Pure replay is insufficient: critical effects (subprocess ran, billing advanced, commit object exists) are external and non-transactional — the dual-write problem means log and world can be split by a crash, and replay reconstructs what the log *knew*, not what *happened*. Recovery = replay projections, then a 3-check reconciler over the external boundary that **appends the events the crash prevented** (git and workspace as witnesses).
**Ordering law:** intent event before action, fact event after → only possible divergence is "world ahead of log," the safe-to-heal direction that never double-spends executions.

## ADR-13 — Idempotency split: deterministic transitions idempotent, costly ones abandonable
**Decision:** Commit/validate/project = check-then-act idempotent (git ancestry answers "did commit succeed?"). LLM executions cannot be idempotent (different output, real money) — they are abandonable: residue→attempt ref, `ExecutionCrashed`, reset, fresh execution. Governing property: **recovery never depends on knowing where the crash landed.**
**Rejected:** "Every transition is idempotent" as a universal — breaks on the expensive states.

## ADR-14 — Executions, not attempts; two-level state machine
**Decision:** Unit of work is an *execution* (may retry, decompose, escalate, or complete; `parent_execution_id` + `spawn_reason` make it a tree). Issues own a coarse lifecycle; executions own the fine one; failures are taxonomy-labeled terminal outcomes, not states; RETRY is policy, not a state.
**Rejected:** Single flat machine with FAILED_*→RETRY states — ambiguous ownership of counters/feedback during recovery.

## ADR-15 — Every execution ends in a commit; diffs are derived
**Context:** "Store facts, derive diffs" requires end_commit to exist — but resets destroy failed-attempt evidence.
**Decision:** Namespaced attempt refs (`refs/attempts/<issue>/<execution>`) for every execution including failures/crash residue, committed before any reset; diffs always `git diff start..end`; GC refs on completion. **Pinning invariant:** COMMITTING requires end_commit == validated_commit == reviewed_commit; verdicts approve *a tree hash*, not an issue, and are therefore cacheable.

## ADR-16 — Local canonical queue; external trackers are ingestion sources only
**Decision:** `TaskProvider.sync()` imports into the local queue (v1: Issues.md preprocessing); status flowing back out is one-way, best-effort projection. Workflow state never lives in GitHub/Linear/Jira.
**Rejected:** External tracker as state store — trades crash-durable local truth for network availability and someone else's API semantics; a distributed system by accident.

## ADR-17 — Design freeze pending falsification
**Decision:** No further architecture until 20 real issues have run (Phase 4). The event log is the instrument; pre-committed decision criteria live in doc 06. Six rounds of refinement against zero executed issues is the pattern this system's own methodology exists to catch.
