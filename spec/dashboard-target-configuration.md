# Spec: Dashboard-controlled target configuration

**Status:** Accepted 2026-08-30. The governing architectural decision is
ADR-29 in `docs/08-session-0-closure-and-adr-amendments.md`.

## Objective

Let a local Draindeck operator configure a new target or edit an existing
target through the Dashboard without hand-editing YAML. The Dashboard provides
an honest preview, but the target's canonical
`<repository>/.draindeck/config.local.yaml` remains the source of truth.

Success means an operator can choose a target path, review detected defaults,
edit essential or advanced settings, see the exact resulting YAML and branch
effect, and apply the change safely. Existing Dashboard observation and target
runtime behavior must remain intact.

## Non-goals and hard boundaries

- The Dashboard never writes target source, event logs, artifacts, evidence,
  attempt refs, or arbitrary target paths.
- The Dashboard never runs validation, dependency-install, engine, reviewer,
  `run`, or `recover` commands while configuring a target.
- The Dashboard cannot edit an arbitrary `--config-out` location. Its only
  target destination is the canonical `.draindeck/config.local.yaml` path.
- This feature adds no `Config` schema keys. Unknown fields remain rejected.
- A target with runtime history cannot change its configured branch through
  this feature. That is a later migration decision, not an editor shortcut.
- The core runtime remains framework-free. FastAPI imports remain confined to
  `draindeck_dashboard`.

## Shared service contract

`runtime.init.service` is the only mutation-policy owner.

```python
prepare_target_configuration(request: TargetConfigurationRequest) -> TargetConfigurationPreview
apply_target_configuration(request: ApplyTargetConfigurationRequest) -> TargetConfigurationResult
```

`prepare_target_configuration` has no filesystem or Git mutation. It resolves
the canonical config path, reads any existing config, detects candidate
validation defaults for a new target, renders the exact proposed YAML, and
reports a SHA-256 revision of the current file (or `None` if absent).

`apply_target_configuration` is the sole writer. It validates the request,
acquires `WorkspaceLease`, confirms the repository and authoritative state are
safe, validates the expected revision, performs the explicitly confirmed
initial branch operation when applicable, and atomically publishes the exact
previewed bytes. It returns the canonical config path, published digest,
resolved log path, branch outcome, and whether a Dashboard registration should
be created or updated.

CLI `cmd_init` and Dashboard adapters may translate their own input into these
request objects, but they may not independently call `GitCliAdapter`,
`WorkspaceLease`, `write_config`, `os.replace`, or direct config write APIs.

## Apply admission rules

Before any mutation, the service must:

1. Validate the absolute repository path and canonical config destination.
2. Acquire the target's `WorkspaceLease`. `UNAVAILABLE`, `ERROR`, and
   `ABANDONED_ACQUIRED` refuse with a typed error. The service never repairs
   an abandoned workspace itself.
3. Read existing authoritative state without repair. A torn, corrupt, or
   unavailable log refuses the write. An unresolved execution, containment
   condition, active run, or other state without a safe provenance proof also
   refuses the write.
4. Reject tracked, staged, deleted, renamed, or conflicted worktree changes
   using `GitCliAdapter.worktree_status().blocking`. Untracked-only files are
   allowed and left untouched.
5. Parse the proposed YAML through `load_config` and run
   `validate_environment` before Git or file mutation.
6. Require the preview's current digest for an update. A changed or missing
   expected digest returns `CONFIG_REVISION_CONFLICT` with no mutation.
7. Require `branchChangeConfirmed=true` for an initial create/checkout. A
   pre-existing branch is checked out without force-reset; a missing branch is
   created from the previewed current commit.
8. Recheck the worktree status and config digest immediately before the first
   irreversible operation.

The branch operation and config replacement cannot be one cross-resource
transaction. Their crash windows are intentionally predicted in the outcome
matrix; a later preview must disclose the actual branch/config state instead
of claiming the request completed.

## Atomic publication

The service writes only a same-directory temporary file. It writes complete
UTF-8 bytes, flushes and fsyncs that file, uses `os.replace` onto the canonical
destination, reopens and fsyncs the final file, attempts a parent-directory
fsync where the platform supports it, and removes a leftover temporary file on
failure. It never truncates the destination in place.

If the config is unignored, the next `ExecutionSpawned` captures
`.draindeck/config.local.yaml` in `pre_execution_untracked`; recovery then
preserves it. If ignored, `git clean -fd` does not remove it because it does
not use `-x`. The service refuses a write whenever it cannot establish that a
future baseline, rather than a past baseline, will govern the file.

## Dashboard REST contract

All responses use the existing typed error envelope. Request validation is
strict (`extra=forbid`) and occurs at the API boundary.

| Route | Purpose | Mutation |
|---|---|---|
| `POST /api/target-configurations/preview` | Render defaults or an edit preview, validation result, digests, YAML diff, and branch effect. | None |
| `POST /api/target-configurations` | Apply a new canonical config and create Dashboard registration after durable success. | Controlled write and optional confirmed initial branch setup |
| `GET /api/repositories/{repoId}/configuration` | Read the registered target's canonical configuration and current digest. | None |
| `PATCH /api/repositories/{repoId}/configuration` | Apply an edit through the shared service and update registration only after success. | Controlled config write only |

Preview and apply inputs contain a typed draft, `projectPath`, optional
`repositoryId`, `expectedConfigDigest`, and `branchChangeConfirmed`. The
canonical config path is server-derived, never accepted from the browser.

The preview output includes `currentConfigDigest`, `proposedConfigDigest`,
`renderedYaml`, a line-oriented diff, detected stack/defaults, warnings,
`branchOperation` (`NONE`, `CREATE`, or `CHECKOUT`), and whether confirmation
is required. Apply output includes the durable result plus the registration
record. Typed failures include `WORKSPACE_LEASE_UNAVAILABLE`,
`RECOVERY_REQUIRED`, `DIRTY_WORKTREE`, `CONFIG_REVISION_CONFLICT`,
`CONFIG_INVALID`, `ENVIRONMENT_INVALID`, `BRANCH_CONFIRMATION_REQUIRED`,
`RUNTIME_STATE_UNSAFE`, and `CONFIG_PUBLICATION_FAILED`.

## User experience

The new-target screen begins with repository path, work branch, and validation
command. It shows detected defaults and a clear review step. Engine, reviewer,
budget, event-log, attempts, billing, and experiment fields are grouped under
advanced settings. The edit screen uses the same form and displays the current
canonical config. The final action presents the exact config diff and explicit
branch warning when relevant.

The form must keep labels visible, expose field and form-level errors, support
keyboard use and visible focus, and reflow without loss at 320, 768, 1024, and
1440 CSS pixels. Saving, conflict, unavailable, and unsafe-state outcomes are
explicit; no state is inferred from an absence of runtime evidence.

## Verification commands

Focused tests, then the full suites, are required during implementation:

```powershell
python -m pytest tests\unit -q
python -m pytest tests\dashboard -q
python -m pytest tests\unit tests\dashboard -q
python tests\crash\harness.py "$env:TEMP\draindeck-config-42" 42
python tests\crash\harness.py "$env:TEMP\draindeck-config-1337" 1337
```

The final two commands require retained raw per-scenario stdout/stderr and
exit codes. A green harness is regression evidence for the frozen runtime;
the feature-specific safety claims require the focused tests named in
`tasks/todo.md` and the outcome matrix.
