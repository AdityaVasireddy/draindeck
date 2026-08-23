# Autonomous Issue-Resolution Runtime

## What this is
An orchestrator that drains an issue backlog by spawning fresh `claude -p`
sessions per issue, gating output through deterministic validation + an
independent LLM reviewer, committing on approval, and surviving crashes
without repeating or double-committing work. Durability is the first
production feature; everything builds on the event-log layer.

## Read before working
- `NEXT.md` — current resume point and the immediate next task. Read FIRST.
- `docs/03-state-machine-and-event-schema.md` — THE FROZEN CONTRACT.
  Code must match it. On any conflict between code and doc 03, doc 03 wins.
- `docs/10-reconciliation-report.md` — how the code was aligned to doc 03;
  the divergence table explains why things are named as they are.
- `docs/handoffs/` — latest handoff has full state; read the newest one.
- Other docs (01, 02, 04–09) are referenced on demand, not read wholesale.

## Hard rules (do not violate)
- Architecture is FROZEN. Changes go through an ADR (docs/08...), never ad hoc.
- The target repo path is CONFIG ONLY (config.yaml → project.*). Never
  hardcode a repo path, branch, language, or test command anywhere in src/.
- Honesty discipline: in every summary, separate what was VERIFIED this
  session (ran it, saw it pass) from what is ASSUMED. Never report a test
  as passing without running it.
- Every implementation session ends at a runnable checkpoint and updates NEXT.md.
  A commit is part of that checkpoint only when explicitly authorized. A planned
  uninterrupted multi-unit build must obtain explicit authority for its bounded
  local checkpoint-commit series before source mutation; otherwise stop at the
  first approval gate rather than accumulating an unreviewable uncommitted diff.
- No commit without explicit authorization. Never push or merge until the user
  has explicitly authorized that separate action.
- Kill criteria (ADR-19) are frozen: 20 issues, attempt-1 ≥30%, cost/shipped
  ≤ $3. Never tune them to dodge a verdict.
- Process depth scales to blast radius, not session length. (Correction after ~17 sessions:
  the five-gate method and heavy review apparatus were applied uniformly, including
  reversible documentation work. This rule makes effort sizing explicit.)
- Five gates are the default engineering discipline, but the heavy review apparatus
  (pre-committed outcome matrices, detailed evidence accounting, multi-phase approvals)
  is reserved for high-blast-radius changes.
- High-blast-radius changes include:
  real repository mutation, src/runtime behavior, event schemas, state transitions,
  external contracts, Git/recovery behavior, and safety or durability claims about
  committed behavior.
- Low-blast-radius changes include:
  documentation, NEXT.md, handoffs, scratch work, and reversible cleanup.
  These use a lightweight scope check and verification of the result.
- When uncertain, default to the lighter process unless the change touches the
  high-blast-radius list above.
- Entrypoint scope (recover vs run): For any gated recovery-only phase, use
  `python -m runtime.main recover` — it hard-stops after recovery by construction.
  `python -m runtime.main run` is the full loop and will continue past recovery into fresh
  spawns and real target merges; never use `run` for a phase contracted to stop after
  crash-preserve. Verify the entrypoint's scope against main.py's usage banner BEFORE any
  gated run against StockPhotoAgent.

## Environment
- Windows, Python 3.12+, core deps: pyyaml, pydantic, pytest. Core `src/runtime`
  remains framework-free (no Temporal/LangGraph, no external state store in
  v1). ADR-26 separately permits FastAPI/Uvicorn only in the optional
  `draindeck_dashboard` package/`dashboard` extra.
- Execution provider: `claude -p` on Claude Pro subscription (ADR-18).
  IMPORTANT: keep ANTHROPIC_API_KEY UNSET — if set, claude bills the API
  instead of the subscription. Applies to both this runtime and your own
  Claude Code sessions.

## Verify commands
- Unit: `python -m pytest tests\unit -q`  (expect 560 pass at baseline `4052fef`)
- Dashboard: `python -m pytest tests\dashboard -q`  (expect 197 pass at baseline)
- Combined: `python -m pytest tests\unit tests\dashboard -q`  (expect 757 pass at baseline)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 60 pass on
  BOTH seed 42 and seed 1337, invariants I-a..I-h; the harness is mutation-tested —
  it can actually fail; see docs/14 for current harness state)

## Current task

Dashboard redesign planning on branch `dashboard-redesign`, baseline
`4052fef97dbb90b52ae91fc01832557bc348cab8`. Proposed ADR-27 is in docs/08
§5i; the full proposed contract is docs/27; PRODUCT.md/DESIGN.md define the
approved visual/product direction; tasks/plan.md is the version-controlled
build-auto plan. Do not mutate `src/` until the user explicitly accepts all
three planning gates, resolves local checkpoint-commit authority, and Unit 0
proves real-browser automation is callable. `src/runtime` remains out of scope.
