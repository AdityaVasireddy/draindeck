# Implementation Roadmap
**Status:** FROZEN — v1.0, 2026-07-05
**Rule:** each step produces something runnable/testable before the next begins. Order chosen so that durability primitives exist before anything expensive runs, and so a crash at any step of *building* the system loses nothing.

---

## Phase 0 — Prerequisites (see doc 06; nothing below starts until it's green)

## Phase 1 — Durable core, no LLM (est. half a day)

1. **Event log.** Append-only JSONL writer: monotonic IDs, fsync-before-ack, envelope schema, reader/iterator. *Test:* kill -9 mid-append leaves a parseable log.
2. **Schemas.** Dataclasses for the event vocabulary + artifact records (doc 03), all with `schema_version`. *Test:* round-trip serialize/deserialize.
3. **Workspace Manager.** clean_base(), branch(), commit_to_attempt_ref(), derive_diff(), pin_check(), ancestor_check(). Pure git plumbing. *Test:* attempt refs survive resets; diff derivation matches expectation.
4. **Projection rebuild.** Delete projections → replay log → identical queue/current-state. *Test:* property — projections are a pure function of the log.
5. **Reconciler.** The three boundary checks against synthetic crash fixtures (orphaned intent, unwitnessed commit, dirty worktree). *Test:* every fixture heals to a consistent world; healed events marked `backfilled`.

**Gate:** simulated full run using a stub "engine" (a script that edits a file) survives kill -9 at every transition. Do not proceed until this passes — this gate is cheap now and unpayable later.

## Phase 2 — Real engine, deterministic gates (est. half a day)

6. **Validator.** Gate chain runner with per-gate logs, cheapest-first ordering, path→E2E mapping, single flake-retry, flake counters.
7. **Engine seam.** Spawn `claude -p` with prompt file, scoped permissions, wall-clock timeout, usage normalization into the record. Engine stdout archived as transcript, never parsed for control flow.
8. **Context pack assembler.** Lean CLAUDE.md + issue + feedback + file-path pointers.
9. **Task ingest.** One-shot Issues.md → canonical queue preprocessing (LLM-assisted is fine here; output is reviewed by you once).
10. **Inner loop, no reviewer.** PENDING→…→CommitCreated with validation as the only gate.

**Gate:** run 5 real issues, *supervised — watch the first runs, do not walk away*. Record cost and outcomes. This is the first contact with reality; expect prompt-pack revisions.

## Phase 3 — Reviewer gate (est. a few hours)

11. **Reviewer seam.** Structured-verdict call + parse-retry; providers: Qwen (Ollama) and Claude behind a config flag; verdict cached by (issue, tree-hash).
12. **Retry policy.** Feedback accumulation into context packs; duplicate-category escalation; execution cap.
13. **Budget enforcement.** Per-execution + per-run caps wired to normalized usage (I7).

**Gate:** 5 more supervised issues with the full pipeline. Then run the pairing experiment: Claude-implements/Qwen-reviews vs. Qwen-harness-implements/Claude-reviews on ~10 issues each is *deferred* until baseline exists — v1 pairing is Claude implements, Qwen pre-reviews mechanicals, Claude reviews only if Qwen approves (cost-ordered gating).

## Phase 4 — The falsification run

14. **20 real issues**, increasingly unattended as trust builds. The event log answers: attempt-1 success rate, cost per shipped issue, dominant taxonomy category, reviewer disagreement rate, feedback recurrence.
15. **Learning loop (manual).** Weekly: query feedback recurrence → promote to guidelines (`GuidelinePromoted` event). Highest-leverage 15 minutes in the system.

**Decision gate (pre-committed, from doc 06):** evaluate against the kill/continue criteria *before* building anything from Phase 5.

## Phase 5 — Only if metrics justify (explicitly deferred; building these earlier is a design violation)

- Second implementation engine → *now* extract the engine interface from two working implementations.
- TaskProvider sync for GitHub/Linear (one-way import; local queue stays canonical).
- Dependency DAG ordering; decomposition pass.
- Worktree parallelism for independent subsystems — only after sequential throughput is measured and insufficient.
- Dashboard beyond a CLI metrics query.

**Anti-roadmap** (recorded so future-you doesn't relitigate): no plugin framework, no Temporal, no LangGraph, no LLM git/test/state agents, no external state store. See ADR-03/04/05.
