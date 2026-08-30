# Todo: Dashboard-controlled target configuration
**Status:** Planning gate cleared 2026-08-30. ADR-29, the spec, outcome
matrix, and this task list are accepted; implementation in progress under
explicit local checkpoint-commit authority.

Legend: `[ ]` pending · `[~]` in progress · `[x]` verified complete

## Planning gate

- [x] ADR-29 accepted with the controlled-write and branch-confirmation
      boundary.
- [x] `spec/dashboard-target-configuration.md` accepted.
- [x] Outcome matrix committed before any `src/` edit.
- [x] Explicit local checkpoint-commit authority recorded before implementation.

## Full test list

- [ ] CLI and Dashboard both delegate to the same apply function.
- [ ] Sentinel delegation tests prove exactly one call from each adapter and no
      target mutation when the service refuses.
- [ ] Architecture tests forbid CLI/Dashboard adapters from directly importing
      or calling `GitCliAdapter`, `WorkspaceLease`, config write helpers,
      `os.replace`, or write-mode filesystem APIs.
- [ ] Preview is side-effect free for file, branch, registration, log, and
      artifact state.
- [ ] Dirty tracked, staged, deleted, renamed, and conflicted repositories
      reject identically through CLI and Dashboard.
- [ ] Untracked-only repositories succeed without staging, deleting, or
      altering existing untracked files.
- [ ] Lease unavailable, lease error, and abandoned lease fail closed.
- [ ] Torn/corrupt logs, unresolved execution, active run, and unresolved
      containment state fail closed without repair.
- [ ] Invalid schema and environment failures occur before branch or file
      mutation.
- [ ] Missing branch confirmation causes zero mutation.
- [ ] Existing branches are never force-reset; a confirmed missing branch is
      created at the previewed commit.
- [ ] Create and edit output round-trips through `load_config` and rejects
      unknown fields.
- [ ] Stale config digest returns a typed conflict without overwrite.
- [ ] Same-directory temporary write, temp fsync, replace, final fsync, and
      cleanup failures satisfy every outcome-matrix prediction.
- [ ] Published config is always complete old bytes, complete new bytes, or
      absent when it was absent; it is never intentionally truncated in place.
- [ ] Parent-directory fsync unavailability does not weaken final-file fsync or
      silently choose in-place writing.
- [ ] A config created before future spawn appears in
      `pre_execution_untracked` when unignored.
- [ ] Recovery preserves the config baseline while archiving/removing genuine
      post-spawn residue.
- [ ] Ignored config survives recovery because `git clean -fd` excludes ignored
      paths.
- [ ] Dashboard registration is created/updated only after durable apply and
      remains unchanged if service publication fails.
- [ ] Duplicate resolved log paths remain rejected.
- [ ] API bodies use strict schemas, body bounds, typed errors, loopback/Origin
      protections, and unchanged CSP/Host behavior.
- [ ] New and edit forms support keyboard operation, visible focus, field and
      form errors, loading, unsafe state, conflict recovery, 200% zoom, and
      320/768/1024/1440 CSS-pixel layouts.
- [ ] Focused unit tests pass.
- [ ] `python -m pytest tests\\unit -q` passes.
- [ ] `python -m pytest tests\\dashboard -q` passes.
- [ ] `python -m pytest tests\\unit tests\\dashboard -q` passes.
- [ ] `python tests\\crash\\harness.py "$env:TEMP\\draindeck-config-42" 42`
      reports all 60 scenarios passing; retain raw stdout/stderr and exit code.
- [ ] `python tests\\crash\\harness.py "$env:TEMP\\draindeck-config-1337" 1337`
      reports all 60 scenarios passing; retain raw stdout/stderr and exit code.
- [ ] Fresh-context adversarial API/security/Git/provenance review completed;
      each real finding has a regression test or explicit user decision.
- [ ] `git diff --check` passes and final evidence separates VERIFIED from
      ASSUMED claims.
