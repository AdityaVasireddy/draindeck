# Controlled target configuration outcome matrix

**Status:** Pre-committed prediction gate. Written before any `src/` edit or
test implementation. Each row is a prediction, not observed evidence. A
future test or raw harness run must report its own result rather than inherit
this document's confidence.

**Scope:** ADR-29 and `spec/dashboard-target-configuration.md`. The policy
gate owner is the planned `runtime.init.service`; `workspace_lease.py`,
`GitCliAdapter`, and the reconciler retain their existing mechanism roles.

| Scenario / failure window | Predicted outcome | Falsifier |
|---|---|---|
| Preview request | No target file, branch, registration, log, or artifact changes. | Any filesystem/Git/SQLite mutation occurs. |
| Digest mismatch before apply | `CONFIG_REVISION_CONFLICT`; old config and branch remain unchanged. | Replacement, branch switch, or registration update occurs. |
| Lease unavailable | `WORKSPACE_LEASE_UNAVAILABLE`; no read-repair, Git, or config write occurs. | Service writes or switches branch without lease ownership. |
| Lease error | Typed lease error; no mutation. | A lease API error is downgraded to an apply attempt. |
| Abandoned lease | `RECOVERY_REQUIRED`; service releases it and performs no recovery or write. | Config is published or branch changed after abandoned acquisition. |
| Torn or corrupt authoritative log | `RUNTIME_STATE_UNSAFE`; log bytes remain untouched. | Service repairs, truncates, or writes config despite unreadable evidence. |
| Unresolved execution / containment / active run | `RUNTIME_STATE_UNSAFE`; no config file is created or replaced. | A file created after an already-frozen baseline is accepted. |
| Dirty tracked/staged/deleted/renamed/conflicted tree | `DIRTY_WORKTREE`; no branch or config mutation. | CLI and Dashboard differ, or either mutates. |
| Untracked-only tree | Apply may proceed; existing untracked files remain untouched. | Existing untracked file is staged, removed, or altered. |
| Branch confirmation absent | `BRANCH_CONFIRMATION_REQUIRED`; no branch/config mutation. | New or existing branch is changed without explicit confirmation. |
| Existing branch selected | Plain checkout preserves its tip; no `-B`/force reset. | Existing tip is reset to current HEAD. |
| Missing branch selected and confirmed | Branch is created from the previewed current commit, then config publication proceeds. | Branch points elsewhere or is created without confirmation. |
| Temp file creation/write fails | Destination bytes and branch state remain as before; temporary artifact is cleaned where possible. | Existing config is truncated, partially changed, or branch switched before this failure point. |
| Temp-file fsync fails | Destination remains old or absent; no replace occurs; temporary artifact is cleaned where possible. | Destination contains partial/new bytes. |
| Crash/failure after temp fsync before replace | Destination is old or absent; a later preview reports that actual state. | Destination is torn or falsely reported as published. |
| Replace fails | Destination remains a complete old version or absent; typed publication failure. | Destination is partial or registration advances. |
| Crash/failure after replace before final fsync | Destination is never intentionally truncated; next preview must read actual complete old/new bytes and cannot claim durable success. | A torn destination is accepted as valid or the UI fabricates completion. |
| Post-replace final-file fsync fails | Return `CONFIG_PUBLICATION_FAILED`; do not update registration; next preview reports actual bytes/digest. | Registration is updated or success returned despite failed final fsync. |
| Parent directory fsync unsupported | Final-file fsync remains required; platform limitation is recorded, not silently replaced with weaker in-place writing. | Service skips final-file fsync or truncates in place. |
| Apply succeeds before any execution exists | Future `ExecutionSpawned` baseline records unignored config file; ignored config survives `clean -fd`. | Recovery later classifies the config as post-spawn residue. |
| Config exists in a captured baseline; post-spawn scratch is added | Recovery preserves config and archives/removes scratch residue. | Config is removed or scratch residue remains. |
| Dashboard registration update fails after durable config apply | Config/branch result remains truthful; API returns registration failure and does not roll back the published config. | API claims full success or corrupts config attempting rollback. |
| CLI vs Dashboard apply | Both invoke the shared service and return equivalent typed policy outcomes. | Either adapter directly performs Git/lease/write work or produces a different policy result. |

## Required crash and regression evidence

The existing durability harness must run unchanged against both seed 42 and
1337. Capture unfiltered per-scenario stdout/stderr and exit status in the
final evidence record. Its 60 scenarios establish no regression of the frozen
runtime; targeted service tests settle the rows above.

The outcome matrix itself must be committed before the first `src/` edit. Any
new failure window discovered during implementation requires a matrix amendment
and user review before the corresponding mutation logic proceeds.
