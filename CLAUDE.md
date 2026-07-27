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
- Every session ends at a runnable, committed checkpoint; update NEXT.md.
- No commit without explicit authorization. Never commit or push until the user has explicitly authorized that specific commit.
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

## Environment
- Windows, Python 3.12+, deps: pyyaml, pydantic, pytest (no frameworks —
  no Temporal/LangGraph, no parallelism, no external state store in v1).
- Execution provider: `claude -p` on Claude Pro subscription (ADR-18).
  IMPORTANT: keep ANTHROPIC_API_KEY UNSET — if set, claude bills the API
  instead of the subscription. Applies to both this runtime and your own
  Claude Code sessions.

## Verify commands
- Unit: `python -m pytest tests\unit -q`  (expect 19 pass)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 46 pass,
  invariants I-a..I-h; the harness is mutation-tested — it can actually fail)

## Current task
Session 3: implement RepositoryAdapter (repo/adapter.py + repo/git_adapter.py
per docs/09 §7) and bind the three reconciler seams (preserve_residue,
check_unwitnessed_commit, check_dirty_workspace) in
src/runtime/recovery/reconciler.py. Extend the crash harness to use a real
temp git repo as the "world". See NEXT.md.