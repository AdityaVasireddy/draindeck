# Implementation plan: Draindeck Intake v1

**Status:** PROPOSED — `/build auto` approval required before source mutation.
**Branch:** `codex/draindeck-intake`, clean baseline `4357b4a`.
**Governing spec:** `spec/draindeck-intake.md`.
**Mutation boundary:** new `src/draindeck_intake`, `tests/intake`, Intake docs,
packaging/test discovery, and bookkeeping. Never edit `src/runtime` or Doc 03.

## Architecture decisions

- Intake is an optional one-way preflight package. It compiles to the existing
  `Issues.md` contract and owns no workflow state.
- Provider JSON is mapped at the boundary into one immutable canonical model.
- All remote I/O uses an injected, bounded, no-redirect standard-library
  transport; there is no dependency installation.
- The generated file is managed, deterministic, parser-compatible, and
  atomically replaced only under explicit ownership rules.
- Runtime integration stops at the generated file. Existing event-log IDs are
  never updated or reinterpreted.

## Dependency graph

```text
ADR/spec acceptance
    -> canonical model + compiler
        -> source protocol + local adapter
            -> bounded HTTP transport
                -> GitHub adapter
                -> Jira adapter
                -> Linear adapter
                    -> CLI + atomic publication
                        -> docs, review, full verification
```

## Units

### Unit 0 — Record architecture acceptance and baseline

**Description:** Record ADR-28 as an Intake-only additive boundary and prove the
clean branch baseline before behavioral code.

**Acceptance criteria:**
- [ ] ADR-28 states the one-way compiler boundary, security limits, rejected
      alternatives, and explicit non-impact on `src/runtime`/Doc 03.
- [ ] Current unit + Dashboard suites pass before source mutation.
- [ ] Current tasks are archived and the approved spec/plan/todo are committed
      as one preparatory checkpoint.

**Verification:**
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\dashboard -q`
- [ ] `git diff --check`
- [ ] `git diff --name-only master -- src/runtime docs/03-state-machine-and-event-schema.md` is empty

**Dependencies:** None

**Files likely touched:** `docs/08-session-0-closure-and-adr-amendments.md`,
`spec/draindeck-intake.md`, `tasks/plan.md`, `tasks/todo.md`, `docs/plans/*`

**Estimated scope:** Medium

### Unit 1 — Canonical model and deterministic compiler

**Description:** Establish the immutable public model, ID normalization, and
safe deterministic Issues.md compiler as a parser-compatible vertical slice.

**Acceptance criteria:**
- [ ] Model rejects invalid IDs, strings, URLs, self/duplicate dependencies,
      duplicate labels, and all documented bounds.
- [ ] Compiler orders stably, quotes reserved remote lines, rejects duplicate
      IDs, and emits exact LF/trailing-newline bytes.
- [ ] Runtime parser round-trip proves no unintended control records.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_model_compiler.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`
- [ ] `.venv\Scripts\python.exe -m compileall -q src\draindeck_intake`

**Dependencies:** Unit 0

**Files likely touched:** `src/draindeck_intake/__init__.py`,
`src/draindeck_intake/model.py`, `src/draindeck_intake/compiler.py`,
`tests/intake/test_model_compiler.py`

**Estimated scope:** Medium

### Unit 2 — Source protocol, bounded collector, and local adapter

**Description:** Add the page protocol and a complete local Issues.md import
path without network I/O.

**Acceptance criteria:**
- [ ] Collector rejects cursor cycles, empty continuation pages, oversized
      pages, duplicates, and totals above `max_issues`.
- [ ] Local adapter performs a bounded UTF-8 read and maps current Issues.md
      fields without changing IDs.
- [ ] Local input -> canonical collection -> compiled output works end-to-end.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_sources.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`

**Dependencies:** Unit 1

**Files likely touched:** `src/draindeck_intake/sources.py`,
`src/draindeck_intake/issues_md.py`, `src/draindeck_intake/__init__.py`,
`tests/intake/test_sources.py`

**Estimated scope:** Medium

### Unit 3 — Bounded HTTP transport and GitHub adapter

**Description:** Prove the external boundary with a reusable HTTPS JSON
transport and the first live provider mapping.

**Acceptance criteria:**
- [ ] Transport enforces HTTPS/host allowlists, timeouts, response-size bounds,
      redirect refusal, JSON object/list expectations, and sanitized errors.
- [ ] GitHub request uses documented headers/query bounds and optional env-token
      authorization.
- [ ] Pull requests are excluded and malformed issue records fail closed.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_http_github.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`

**Dependencies:** Unit 2

**Files likely touched:** `src/draindeck_intake/http.py`,
`src/draindeck_intake/github.py`, `tests/intake/test_http_github.py`

**Estimated scope:** Medium

### Unit 4 — Jira Cloud adapter and ADF extraction

**Description:** Add current enhanced-JQL pagination, API-token authentication,
and safe plain-text extraction from Jira Cloud ADF descriptions.

**Acceptance criteria:**
- [ ] Only HTTPS `*.atlassian.net` sites are accepted and credentials come from
      environment values supplied to the adapter.
- [ ] Requests use POST `/rest/api/3/search/jql`, field allowlisting,
      `maxResults`, and opaque `nextPageToken`.
- [ ] ADF and malformed response tests cover nested text, hard breaks, null
      descriptions, invalid fields, and secret-free errors.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_jira.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`

**Dependencies:** Unit 3

**Files likely touched:** `src/draindeck_intake/jira.py`,
`tests/intake/test_jira.py`

**Estimated scope:** Small

### Unit 5 — Linear adapter

**Description:** Add Relay-pagination and team-filtered issue mapping over
Linear's GraphQL endpoint.

**Acceptance criteria:**
- [ ] Request uses the fixed Linear endpoint, env API key, explicit variables,
      team-key filter, and `first`/`after` pagination.
- [ ] A non-empty GraphQL errors array fails even on HTTP 200.
- [ ] Missing/null required fields, bad pageInfo, labels, state, priority, and
      URL mapping are covered.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_linear.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`

**Dependencies:** Unit 3

**Files likely touched:** `src/draindeck_intake/linear.py`,
`tests/intake/test_linear.py`

**Estimated scope:** Small

### Unit 6 — Atomic output and CLI composition

**Description:** Deliver the operator-facing command for all four sources with
safe managed-file publication and machine-readable results.

**Acceptance criteria:**
- [ ] Unmanaged existing files are refused without `--force`; managed files are
      replaced atomically; byte-identical output is a no-op.
- [ ] CLI validates bounds/env names/provider arguments before I/O and returns
      documented JSON envelopes/exit codes without secrets or stack traces.
- [ ] Local Issues.md CLI path passes end-to-end and provider construction is
      covered without live network access.

**Verification:**
- [ ] RED then GREEN: `.venv\Scripts\python.exe -m pytest tests\intake\test_cli_output.py -q`
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake -q`
- [ ] `.venv\Scripts\python.exe -m draindeck_intake.cli --help`

**Dependencies:** Units 4 and 5

**Files likely touched:** `src/draindeck_intake/output.py`,
`src/draindeck_intake/cli.py`, `tests/intake/test_cli_output.py`,
`pyproject.toml`

**Estimated scope:** Medium

### Unit 7 — Documentation, adversarial review, and final evidence

**Description:** Document the public contract and operational limits, perform a
fresh-context multi-axis review, fix every real finding test-first, and close
the build with full evidence.

**Acceptance criteria:**
- [ ] README/docs cover commands, auth environment variables, generated-file
      ownership, source limitations, immutable-after-ingestion behavior, and
      official API references.
- [ ] Security/review/simplification passes find no unresolved Critical or
      Required issue; each real finding has a regression test.
- [ ] Full test, Dashboard, durability, compile, diff, secret, and core-carveout
      gates pass; final handoff separates VERIFIED from ASSUMED live-provider
      behavior.

**Verification:**
- [ ] `.venv\Scripts\python.exe -m pytest tests\unit tests\intake tests\dashboard -q`
- [ ] `.venv\Scripts\python.exe tests\crash\harness.py <temp> 42`
- [ ] `.venv\Scripts\python.exe tests\crash\harness.py <temp> 1337`
- [ ] `.venv\Scripts\python.exe -m compileall -q src\draindeck_intake`
- [ ] `git diff --check`
- [ ] `git diff --name-only master -- src/runtime docs/03-state-machine-and-event-schema.md` is empty
- [ ] staged-diff secret scan before each commit

**Dependencies:** Unit 6

**Files likely touched:** `README.md`, `docs/29-draindeck-intake.md`,
`docs/reviews/DRAINDECK_INTAKE_BUILD_EVIDENCE.md`, `NEXT.md`,
`docs/handoffs/HANDOFF_2026-08-29_draindeck-intake-complete.md`

**Estimated scope:** Medium

## Checkpoints

- After Unit 0: architecture accepted, baseline green, planning committed.
- After Units 1-2: local end-to-end canonical/compiler path green.
- After Units 3-5: all provider contracts green under adversarial fixtures.
- After Unit 6: installable CLI path green.
- After Unit 7: Definition of Done met; ready for user review, not merged/pushed.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider response drift | High | Strict boundary mapping, sanitized failure, official-doc citations, fixtures |
| Credential disclosure | High | env-only secrets, no redirects, allowlisted errors, staged secret scan |
| Prompt/control injection through issue text | High | quote reserved parser-control lines; parser round-trip tests |
| Unbounded source backlog/response | High | page/total/body/response/time bounds and cursor-cycle rejection |
| Overwriting human Issues.md | High | managed marker, atomic replacement, unmanaged refusal by default |
| Canonical ID collision | Medium | deterministic visible prefixes and collision refusal |
| False update expectations | Medium | one-way docs and immutable-after-event-ingestion warning |

## Authorization requested

Approval of this plan authorizes one uninterrupted `/build auto` pass and a
bounded series of **nine local commits** on `codex/draindeck-intake`: one
preparatory spec/plan/archive commit followed by Units 0-7. It does not authorize
push, merge, live credentialed calls, dependency installation, runtime/event
changes, or mutation of the main checkout's untracked Dashboard files.
