# Implementation Guide — Solo Dev Checklist
**Cadence assumption:** ~3 hrs/week, one sitting. **Design rule for this cadence:** every session ends at a *runnable, committed checkpoint*. Never stop mid-component. If a session runs short, stop at the last green checkpoint and note the next step in `NEXT.md` — your future self has no memory of this sitting.

> This is the "how to build it" companion to the six frozen design docs. It does not re-derive decisions — it sequences them. When a step feels ambiguous, the frozen doc is the authority (referenced as → doc N).

---

## Session 0 — Prerequisites (before any code)
**Goal:** clear the two ⚠ unknowns and green the baseline. → doc 06

- [ ] Verify headless billing status on your account; write the answer + billing posture into `config.yaml`. (This can invalidate everything — do it first.)
- [ ] Pin Claude Code version; run the headless smoke test (`claude -p "..." --output-format json` → JSON parses, usage present).
- [ ] Ollama + Qwen pulled; single-shot JSON-verdict smoke test passes.
- [ ] Target repo baseline green (build/lint/typecheck/test on clean checkout). Run the test suite 3× — quarantine anything flaky.
- [ ] Pre-commit the Phase 4 kill criteria into `config.yaml` (e.g. "stop if attempt-1 success < 30% or cost/issue > $X after 20 issues").
- [ ] Create the dir layout: `log/`, `artifacts/`, `projections/`, `config.yaml`, `NEXT.md`.

**Checkpoint:** every box in doc 06 checked. Do not write orchestrator code until this is done — a red baseline makes the validator meaningless.

---

## PHASE 1 — Durable core, no LLM
*The hardest and most important phase. No AI runs here at all — you're building the thing that survives crashes. Get this right and the rest is plumbing.* → doc 02 §4, doc 03 §3

### Session 1 — Event log + schemas
- [ ] Event-log writer: append-only JSONL, monotonic `event_id`, **fsync before returning**, the common envelope (→ doc 03 §3).
- [ ] Reader/iterator over the log.
- [ ] Dataclasses for the 12 event types + artifact records, each with `schema_version` (→ doc 03 §3–4).
- [ ] Round-trip test: serialize → deserialize → identical.
- **Checkpoint:** write 10 fake events, kill -9 mid-write, confirm the log still parses.

### Session 2 — Workspace Manager
- [ ] Git plumbing functions: `clean_base()`, `branch()`, `commit_to_attempt_ref()`, `derive_diff(start,end)`, `pin_check()`, `ancestor_check()` (→ doc 02 §3, doc 05 ADR-15).
- [ ] Test: attempt refs survive a `reset --hard`; diff derivation matches expected output.
- **Checkpoint:** a scratch repo where you can create an attempt ref, reset the worktree, and still recover the diff.

### Session 3 — Projections + reconciler (the payoff session)
- [ ] Projection rebuild: delete projections → replay log → identical queue/current-state. Prove it's a pure function of the log.
- [ ] Reconciler: the three boundary checks (orphaned execution, unwitnessed commit, dirty workspace) against synthetic crash fixtures (→ doc 02 §4).
- [ ] Stub "engine" = a script that edits one file, so you can exercise the loop with zero AI.
- **PHASE 1 GATE (do not skip):** run the full loop with the stub engine and `kill -9` it at *every* transition. It must recover to a consistent world each time. This gate is cheap now and unpayable later.

---

## PHASE 2 — Real engine + deterministic gates
*Now the AI writes code, but nothing checks it except tests yet.* → doc 02 §1, §5

### Session 4 — Validator
- [ ] Gate-chain runner, cheapest-first: lint → typecheck → build → unit → E2E. Per-gate logs + exit codes.
- [ ] Path→E2E mapping (only run Playwright when the diff touches mapped paths).
- [ ] Single flake-retry + per-test flake counter.
- **Checkpoint:** point it at a known-good and a known-bad commit; correct pass/fail both times.

### Session 5 — Engine seam + context pack
- [ ] Engine seam: spawn `claude -p` with prompt file, scoped permissions, wall-clock timeout; normalize usage into the ExecutionRecord. Stdout → archived transcript, **never parsed for control flow** (→ doc 05 ADR-07).
- [ ] Context-pack assembler: lean CLAUDE.md + issue + feedback + file-path pointers (→ doc 02 §5).
- **Checkpoint:** one real issue gets implemented into an attempt ref (no validation wired yet — just confirm the engine runs and the diff lands).

### Session 6 — Inner loop, validation only + task ingest
- [ ] One-shot Issues.md → canonical queue preprocessing; review the output once by hand.
- [ ] Wire PENDING → EXECUTING → VALIDATING → COMMITTED, validation as the sole gate.
- **PHASE 2 GATE:** run **5 real issues, supervised — watch them, don't walk away.** Record cost + outcomes. Expect to revise the context pack here; first contact with reality always does.

---

## PHASE 3 — Reviewer gate
*The second AI checks the work. This is where quality jumps.* → doc 02 §1, doc 03 §4

### Session 7 — Reviewer seam
- [ ] Structured-verdict call + parse-retry; Qwen and Claude behind a config flag (→ doc 05 ADR-08).
- [ ] Cache verdicts by (issue, tree-hash).
- **Checkpoint:** feed it one good diff and one bad diff; correct APPROVE/REJECT with structured feedback.

### Session 8 — Retry policy + budgets
- [ ] Feedback accumulation into the next context pack; duplicate-category → immediate escalate; execution cap = 3.
- [ ] Per-execution + per-run dollar caps wired to normalized usage (→ doc 01 I7/I8).
- **PHASE 3 GATE:** 5 more supervised issues, full pipeline. v1 pairing = Claude implements, Qwen pre-reviews mechanicals, Claude reviews only if Qwen approves (cost-ordered).

---

## PHASE 4 — The falsification run (the actual point of all this)
### Sessions 9–11 — 20 real issues
- [ ] Run 20 real issues, increasingly unattended as trust builds.
- [ ] Query the event log for: attempt-1 success rate, cost/shipped issue, dominant failure category, reviewer disagreement rate, feedback recurrence.
- [ ] Weekly 15 min: promote recurring feedback into guidelines (`GuidelinePromoted`).
- **DECISION GATE:** compare against the kill/continue criteria you pre-committed in Session 0. Continue, stop, or rethink — **before** building anything in Phase 5. Do not tune indefinitely to avoid the verdict.

---

## PHASE 5 — Only if the metrics justify it
*Explicitly deferred. Building any of this earlier is a design violation (→ doc 05 ADR-17).* Pick up items here **one at a time**, each earning its place from a measured need:
- Second implementation engine → now extract the engine interface from two working impls.
- TaskProvider sync (GitHub/Linear, one-way import; local queue stays canonical).
- Dependency DAG + decomposition pass.
- Worktree parallelism — only after sequential throughput is measured and insufficient.

---

## The rule that matters most at 3 hrs/week
End every session green and committed, and write the next concrete step in `NEXT.md`. The cost of this cadence isn't the coding — it's re-loading context cold. A one-line "next: wire the validator's exit-code check" saves you 30 minutes of "where was I?" every single sitting.
