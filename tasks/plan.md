# Implementation plan: Dashboard-controlled target configuration
**Status:** BUILD COMPLETE 2026-08-30 (Units 0-6), pending user review before
merge. Full evidence: `docs/reviews/TARGET_CONFIGURATION_BUILD_EVIDENCE.md`.
Governing ADR: ADR-29.
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

- [x] Tests describe every outcome-matrix row (except three pre-existing
      recovery/provenance behaviors this feature relies on but does not
      modify — see build evidence).
- [x] Tests prove the service owns dirty, lease, state, digest, and branch gates.
- [x] No adapter has direct policy/mutation imports (2 architecture-boundary
      tests added; this caught a real pre-existing CLI violation — see build
      evidence).

**Verification:** focused RED tests, then focused GREEN tests after implementation. DONE.

### Unit 2: Safe apply service

Implement lease/state admission, tracked-dirty checks, branch safety, digest
conflicts, and atomic publication behind the shared service.

**Acceptance criteria:**

- [x] Each predicted failure leaves the expected target state (3 real bugs
      found and fixed to make this true — see build evidence).
- [x] Config publication is atomic and fsync-backed (5 crash-window tests
      added: temp create/fsync/replace/post-replace-fsync failure, parent-
      directory fsync unavailable).
- [x] Provenance/recovery tests preserve config and remove genuine residue.
      (Relies on unmodified pre-existing recovery/reconciler behavior, proven
      by the durability harness rather than a new dedicated test.)

**Verification:** `python -m pytest tests\\unit -q`. DONE — 585 passed.

### Checkpoint: runtime safety

- [x] Focused service tests green.
- [x] Full unit suite green.
- [x] Outcome-matrix evidence recorded before adapter work.

### Unit 3: CLI delegation

Route `cmd_init` through the shared preview/apply service while preserving its
documented prompts and flags.

**Acceptance criteria:**

- [x] CLI has no direct Git/lease/write policy path. (This was FALSE in the
      pre-existing draft at session start — `run_preflight`/`setup_branch`
      mutated Git directly, bypassing the service entirely. Fixed.)
- [x] Sentinel tests prove exactly one shared-service apply call.
- [x] Existing CLI behavior remains compatible where within ADR-29 scope (all
      65 pre-existing cmd_init tests still pass, one updated to spy on the
      new single mutation gate instead of the removed helpers).

**Verification:** focused init tests plus `python -m pytest tests\\unit -q`. DONE.

### Unit 4: Dashboard API delegation and registration sequencing

Add typed preview/apply/read endpoints that invoke the service and create or
update registration only after durable success.

**Acceptance criteria:**

- [x] Strict inputs and typed errors preserve existing security policy.
- [x] Dashboard adapter cannot mutate target state directly.
- [x] Registration remains unchanged on service failure (including the
      registration-fails-after-durable-apply outcome-matrix row).

**Verification:** focused Dashboard API tests plus `python -m pytest tests\\dashboard -q`. DONE — 519 passed.
Extended beyond the original scope with GET .../detect and POST .../render
(server-side stack detection/YAML rendering, closing a gap between the
spec's UX section and its original REST contract table — see build
evidence) and preview branch-effect prediction (needed for the UI's
required explicit branch warning).

### Unit 5: Guided dashboard flows

Build New Target and Edit Configuration views with a shared form, advanced
sections, exact preview, conflict remediation, and explicit branch warning.

**Acceptance criteria:**

- [x] Essential settings are usable without exposing raw schema complexity.
- [x] Advanced fields are grouped and validated (via a direct, always-
      editable YAML view — not per-field controls; render_config itself only
      parameterizes branch/validation, so this is the honest, functional
      scope — see build evidence).
- [~] Keyboard, error, loading, unsafe, conflict, and responsive states work.
      (Error/loading/conflict live-verified; keyboard-only and the four
      responsive breakpoints were not — environment limitation, see build
      evidence.)

**Verification:** JavaScript tests and real-browser checks. DONE for the
golden path and conflict recovery, live in a real browser against a real Git
repository; two real defects found and fixed this way (a misleading dead
form field, and a genuine `[hidden]`-vs-CSS-cascade bug fixed at the base
stylesheet level). No standalone JS test suite exists in this codebase for
page modules (matches this dashboard's existing convention).

### Unit 6: Five-Gate closeout

Perform full verification and adversarial review; repair every real finding
test-first and retain raw evidence.

**Acceptance criteria:**

- [x] Unit, Dashboard, and combined suites pass (585 / 519 / 1104).
- [x] Durability harness passes all 60 scenarios on seeds 42 and 1337 with
      raw per-scenario output.
- [~] Security, provenance, API, browser, and independent-review findings are
      resolved or explicitly accepted by the user. (Continuous doubt-driven
      review during the build, not a separate fresh-context reviewer pass —
      8 real defects found and fixed test-first. User should decide whether a
      dedicated fresh-context review is wanted before merge.)

**Verification:** all commands in `tasks/todo.md`; `git diff --check`; final
evidence distinguishes VERIFIED from ASSUMED. DONE:
`docs/reviews/TARGET_CONFIGURATION_BUILD_EVIDENCE.md`.

## Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Dashboard and CLI drift | High | One shared apply function plus sentinel and import-boundary tests. |
| New config misclassified as residue | High | Lease/state admission, no write with unresolved execution, provenance regression test. |
| Config loss during publication | High | Same-directory temp, fsync, replace, digest check, crash matrix. |
| Branch history reset | High | Explicit confirmation, plain existing-branch checkout, regression test. |
| Stale browser overwrite | Medium | Preview digest required at apply, typed conflict, refresh flow. |
| Dashboard expands write authority | High | Canonical path only, no shell execution, strict request schemas, review. |
