# Implementation plan: Dashboard-controlled target configuration
**Status:** Planning gate cleared 2026-08-30 (ADR-29 accepted, checkpoint-
commit authority granted); implementation in progress. Governing ADR: ADR-29.
**Normative contract:** `spec/dashboard-target-configuration.md`.
**Outcome prediction gate:** `docs/30-controlled-target-configuration-outcome-matrix.md`.

## Architecture decisions

- `runtime.init.service` is the sole policy and mutation gate; CLI and
  Dashboard are thin adapters.
- The canonical target config path is server-derived and target-owned.
- Workspace ownership, authoritative-state safety, tracked-dirty rejection,
  digest matching, branch confirmation, and atomic publication are enforced
  in the service, not duplicated in the Dashboard.
- The Dashboard remains unable to write source, logs, artifacts, evidence, or
  arbitrary paths, and does not execute shell commands during setup.

## Dependency graph

```text
ADR/spec/outcome matrix accepted
  -> shared service contracts and RED policy tests
    -> lease/state/digest/atomic writer implementation
      -> CLI delegates to service
      -> Dashboard API delegates to service
        -> repository UI preview/apply flows
          -> browser, security, full-suite, durability, review evidence
```

## Units

### Unit 0: Planning and baseline gate

Record ADR-29, this spec, the pre-committed outcome matrix, and test plan;
confirm no source mutation has occurred.

**Acceptance criteria:**

- [x] ADR-29 is accepted before implementation (2026-08-30, docs/08 §5k).
- [x] This plan, todo, and outcome matrix are committed before any `src/` edit
      (the Unit 0 commit itself stages only these planning artifacts).
- [x] Baseline status and source scope are recorded.

**Verification:**

- [ ] `git diff --check`
- [ ] `git diff --cached --name-only` contains no `src/` or test implementation.

### Unit 1: Shared contract and policy tests

Define typed request/result/error contracts and write RED tests for admission
rules, without changing CLI or Dashboard behavior yet.

**Acceptance criteria:**

- [ ] Tests describe every outcome-matrix row.
- [ ] Tests prove the service owns dirty, lease, state, digest, and branch gates.
- [ ] No adapter has direct policy/mutation imports.

**Verification:** focused RED tests, then focused GREEN tests after implementation.

### Unit 2: Safe apply service

Implement lease/state admission, tracked-dirty checks, branch safety, digest
conflicts, and atomic publication behind the shared service.

**Acceptance criteria:**

- [ ] Each predicted failure leaves the expected target state.
- [ ] Config publication is atomic and fsync-backed.
- [ ] Provenance/recovery tests preserve config and remove genuine residue.

**Verification:** `python -m pytest tests\\unit -q`.

### Checkpoint: runtime safety

- [ ] Focused service tests green.
- [ ] Full unit suite green.
- [ ] Outcome-matrix evidence recorded before adapter work.

### Unit 3: CLI delegation

Route `cmd_init` through the shared preview/apply service while preserving its
documented prompts and flags.

**Acceptance criteria:**

- [ ] CLI has no direct Git/lease/write policy path.
- [ ] Sentinel tests prove exactly one shared-service apply call.
- [ ] Existing CLI behavior remains compatible where within ADR-29 scope.

**Verification:** focused init tests plus `python -m pytest tests\\unit -q`.

### Unit 4: Dashboard API delegation and registration sequencing

Add typed preview/apply/read endpoints that invoke the service and create or
update registration only after durable success.

**Acceptance criteria:**

- [ ] Strict inputs and typed errors preserve existing security policy.
- [ ] Dashboard adapter cannot mutate target state directly.
- [ ] Registration remains unchanged on service failure.

**Verification:** focused Dashboard API tests plus `python -m pytest tests\\dashboard -q`.

### Unit 5: Guided dashboard flows

Build New Target and Edit Configuration views with a shared form, advanced
sections, exact preview, conflict remediation, and explicit branch warning.

**Acceptance criteria:**

- [ ] Essential settings are usable without exposing raw schema complexity.
- [ ] Advanced fields are grouped and validated.
- [ ] Keyboard, error, loading, unsafe, conflict, and responsive states work.

**Verification:** JavaScript tests and real-browser checks.

### Unit 6: Five-Gate closeout

Perform full verification and adversarial review; repair every real finding
test-first and retain raw evidence.

**Acceptance criteria:**

- [ ] Unit, Dashboard, and combined suites pass.
- [ ] Durability harness passes all 60 scenarios on seeds 42 and 1337 with
      raw per-scenario output.
- [ ] Security, provenance, API, browser, and independent-review findings are
      resolved or explicitly accepted by the user.

**Verification:** all commands in `tasks/todo.md`; `git diff --check`; final
evidence distinguishes VERIFIED from ASSUMED.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Dashboard and CLI drift | High | One shared apply function plus sentinel and import-boundary tests. |
| New config misclassified as residue | High | Lease/state admission, no write with unresolved execution, provenance regression test. |
| Config loss during publication | High | Same-directory temp, fsync, replace, digest check, crash matrix. |
| Branch history reset | High | Explicit confirmation, plain existing-branch checkout, regression test. |
| Stale browser overwrite | Medium | Preview digest required at apply, typed conflict, refresh flow. |
| Dashboard expands write authority | High | Canonical path only, no shell execution, strict request schemas, review. |
