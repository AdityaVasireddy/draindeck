# issue-runtime

Windows-first, durability-focused issue execution. `state/events.jsonl` is the
authoritative runtime record; projections are replayed from it. `Issues.md`
STATUS is human-facing only and never determines runtime state.

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
