# Todo: Dashboard-controlled target configuration
**Status:** BUILD COMPLETE 2026-08-30 (Units 0-6), pending user review before
merge. Full evidence: `docs/reviews/TARGET_CONFIGURATION_BUILD_EVIDENCE.md`.
No merge or push has occurred.

Legend: `[ ]` pending · `[~]` in progress · `[x]` verified complete

## Planning gate

- [x] ADR-29 accepted with the controlled-write and branch-confirmation
      boundary.
- [x] `spec/dashboard-target-configuration.md` accepted.
- [x] Outcome matrix committed before any `src/` edit.
- [x] Explicit local checkpoint-commit authority recorded before implementation.

## Full test list

- [x] CLI and Dashboard both delegate to the same apply function.
- [x] Sentinel delegation tests prove exactly one call from each adapter and no
      target mutation when the service refuses.
- [x] Architecture tests forbid CLI/Dashboard adapters from directly importing
      or calling `GitCliAdapter`, `WorkspaceLease`, config write helpers,
      `os.replace`, or write-mode filesystem APIs.
- [x] Preview is side-effect free for file, branch, registration, log, and
      artifact state.
- [x] Dirty tracked, staged, deleted, renamed, and conflicted repositories
      reject identically through CLI and Dashboard.
- [x] Untracked-only repositories succeed without staging, deleting, or
      altering existing untracked files.
- [x] Lease unavailable, lease error, and abandoned lease fail closed.
- [x] Torn/corrupt logs, unresolved execution, active run, and unresolved
      containment state fail closed without repair.
- [x] Invalid schema and environment failures occur before branch or file
      mutation.
- [x] Missing branch confirmation causes zero mutation.
- [x] Existing branches are never force-reset; a confirmed missing branch is
      created at the previewed commit.
- [x] Create and edit output round-trips through `load_config` and rejects
      unknown fields.
- [x] Stale config digest returns a typed conflict without overwrite.
- [x] Same-directory temporary write, temp fsync, replace, final fsync, and
      cleanup failures satisfy every outcome-matrix prediction.
- [x] Published config is always complete old bytes, complete new bytes, or
      absent when it was absent; it is never intentionally truncated in place.
- [x] Parent-directory fsync unavailability does not weaken final-file fsync or
      silently choose in-place writing.
- [~] A config created before future spawn appears in
      `pre_execution_untracked` when unignored. (Pre-existing runtime
      behavior, unmodified by this feature; not independently re-tested —
      see build evidence "Outcome-matrix coverage".)
- [~] Recovery preserves the config baseline while archiving/removing genuine
      post-spawn residue. (Same as above.)
- [~] Ignored config survives recovery because `git clean -fd` excludes ignored
      paths. (Same as above.)
- [x] Dashboard registration is created/updated only after durable apply and
      remains unchanged if service publication fails.
- [x] Duplicate resolved log paths remain rejected.
- [x] API bodies use strict schemas, body bounds, typed errors, loopback/Origin
      protections, and unchanged CSP/Host behavior.
- [~] New and edit forms support keyboard operation, visible focus, field and
      form errors, loading, unsafe state, conflict recovery, 200% zoom, and
      320/768/1024/1440 CSS-pixel layouts. (Golden path, error states, and
      conflict recovery are live-browser verified. Keyboard-only operation,
      200% zoom, and the four CSS-pixel breakpoints were NOT independently
      live-verified — see build evidence "Known limitation, not resolved.")
- [x] Focused unit tests pass.
- [x] `python -m pytest tests\\unit -q` passes. **585 passed.**
- [x] `python -m pytest tests\\dashboard -q` passes. **519 passed.**
- [x] `python -m pytest tests\\unit tests\\dashboard -q` passes. **1104 passed.**
- [x] `python tests\\crash\\harness.py <dir> 42` — **ALL 60 SCENARIOS PASSED.**
- [x] `python tests\\crash\\harness.py <dir> 1337` — **ALL 60 SCENARIOS PASSED.**
- [~] Fresh-context adversarial API/security/Git/provenance review completed;
      each real finding has a regression test or explicit user decision.
      (Continuous doubt-driven review during the build found and fixed 8 real
      defects, test-first — see build evidence. No SEPARATE fresh-context
      reviewer agent was run; user should decide whether one is wanted before
      merge.)
- [x] `git diff --check` passes and final evidence separates VERIFIED from
      ASSUMED claims. Full evidence:
      `docs/reviews/TARGET_CONFIGURATION_BUILD_EVIDENCE.md`.
