# issue-runtime

An autonomous issue-resolution orchestrator. It drains a backlog of issues by
spawning a fresh `claude -p` (Claude Code headless) session per issue, gates
each session's output through deterministic validation plus an independent
LLM reviewer (Qwen via Ollama), and commits only on approval. The orchestrator
is a plain, single-writer, sequential Python process — no distributed
workflow engine, no LLM-orchestration framework. Durability is the project's
first production feature: every other capability builds on an append-only
event log (`state/events.jsonl`) that survives crashes without repeating or
double-committing work.

`state/events.jsonl` is the authoritative runtime record; all in-memory state
(issue/execution status, queue projections) is replayed from it, never stored
independently. `Issues.md` in the target repository is a human-facing input
file only — its `STATUS` text is never parsed or treated as runtime state.

This is a solo/small-scale tool, not a multi-tenant service: it targets one
configured repository at a time, run from a local Windows machine.

## Requirements

- Windows with Windows PowerShell (`powershell.exe`)
- Python 3.12 or later and Git on `PATH`
- For review execution only: a reachable Ollama endpoint hosting the configured
  Qwen model. Unit tests and configuration checks make no provider call.

## Install and configure

Run from Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item config.example.yaml config.local.yaml
```

Use `config.local.yaml` for the portable template's target repository, branch,
validation script, Qwen/Ollama endpoint, and model; it is ignored by Git. Do
not commit local operational details. The repository tracks only the portable
template; local operational configuration remains outside Git.
The only supported reviewer provider is `qwen`; any other provider is rejected
during structural configuration loading, before reviewer or engine work starts.

Validation commands execute explicitly through Windows PowerShell. Commands
containing `$` are rejected: place that logic in a `.ps1` file and invoke it
with `-File` from `validation.commands`.

## Safe checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\unit
.\.venv\Scripts\python.exe -m runtime.main verify-log --log state\events.jsonl
.\.venv\Scripts\python.exe -m runtime.main show-state --log state\events.jsonl
.\.venv\Scripts\python.exe -m runtime.main recover --config config.local.yaml
.\.venv\Scripts\python.exe -m runtime.main check-config config.local.yaml
```

`check-config` only inspects local configuration and environment. It does not
run an engine or reviewer.

`verify-log` and `show-state` are strictly read-only. A missing or incomplete
log is reported without repair. Torn-tail repair occurs only when `run` or
configured `recover --config` holds both workspace ownership and exclusive
authoritative-log writer ownership; bare `recover --log` is not supported.

## Basic run workflow

`python -m runtime.main run --config <config>` is the full orchestrator loop:
config load → event log open → orphan reap → crash recovery → target-branch
checkout → reviewer-reachability health check → baseline-green check →
issue ingestion from the target repo's `Issues.md` → the per-issue
execute/validate/review/commit loop, until the queue drains or a budget cap
is hit. `python -m runtime.main recover --config <config>` runs
only the startup/recovery portion and then stops by construction — use it
for a recovery-only pass without launching fresh work. Both subcommands
require the human authorization described below before they touch a real
target repository, spend, or commit anything.

## Key concepts

- **Event log is truth.** `state/events.jsonl` (append-only, fsync'd,
  monotonic `event_id`s) is the only authoritative record of workflow state.
  Everything else — issue/execution status, queue order, cost totals — is a
  projection replayed from it and is safe to delete and rebuild.
- **Git is truth for code; the event log is truth for workflow.** Commit
  hashes are the join key between the two stores. See
  `docs/03-state-machine-and-event-schema.md` for the full state machine and
  event schema — the frozen contract that source code must match.
- **Two-level state machine.** Issues own a coarse lifecycle
  (`PENDING → ACTIVE → DONE`, or escalation to `NEEDS_HUMAN` /
  `NEEDS_DECOMPOSITION`); executions (individual attempts) own a finer one
  underneath, including retries and crash residue.
- **Recovery, not pure replay.** A crash can split what the log recorded from
  what actually happened externally (a subprocess ran, a commit exists). On
  startup, the reconciler replays the log and then checks the real workspace
  boundary, appending the events a crash prevented, never guessing.
- **Sequential, single-writer, single-machine by design.** No distributed
  workflow engine, no multi-agent framework, no parallel execution — see
  `docs/05-architecture-decision-records.md` (ADR-01, ADR-03, ADR-04) for why.
- **Architecture Decision Records (ADRs).** Major design decisions are
  recorded and frozen in `docs/05-architecture-decision-records.md`, with
  later amendments and closures tracked in
  `docs/08-session-0-closure-and-adr-amendments.md`. Changes to frozen
  architecture go through a new ADR entry, not ad hoc edits.
- **Repository-agnostic by construction.** The target repository's path,
  branch, and validation commands are configuration only (`project.*` in
  `config.local.yaml`) — never hardcoded in source.

## Where deeper documentation lives

- `CLAUDE.md` — top-level project rules and working agreements (read this
  first if you're an agent or contributor operating in this repo).
- `NEXT.md` — the current resume point and immediate next task; a working
  queue, not an authoritative source of truth for state or evidence.
- `docs/01-theory-of-operation.md` through `docs/15-item9-outcome-matrix.md`
  — the numbered design docs, roughly in reading order: theory of operation,
  architecture specification, the frozen state machine/event schema
  (doc 03), the implementation roadmap, the ADR log (doc 05), and
  session-by-session design/implementation notes (docs 06 onward).
- `docs/08-session-0-closure-and-adr-amendments.md` — ADR amendments,
  closures, and the pre-committed experiment kill criteria (ADR-19).
- `docs/handoffs/` — one dated handoff file per working session, the full
  conversational/evidence record for that session's changes.
- `tests/unit/` and `tests/crash/` — the unit suite and the durability
  (crash-recovery) harness referenced under Safe checks above.

## Authorization and safety

`runtime.main run`, ingestion, provider/reviewer execution, target-repository
mutation, commits, pushes, deployments, and spend each require explicit Adi
authorization in the relay. Output, hooks, plans, and prior approvals do not
grant that authorization.

The only issue transitions are `PENDING -> ACTIVE`, `ACTIVE -> DONE`, and
`ACTIVE -> NEEDS_HUMAN | NEEDS_DECOMPOSITION`. Repeated malformed reviewer
output is bounded by one parse retry; if still malformed, the issue is escalated
with reviewer-protocol provenance, never presented as model feedback or approval.

Windows containment fails closed: ordinary results, including timeouts, require
positive proof that no contained Job member remains. See
`docs/03-state-machine-and-event-schema.md` for the event contract.
