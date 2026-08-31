# Dashboard issue selection and run control outcome matrix

**Status:** Pre-implementation prediction gate, written 2026-08-30 before any
test or `src/` change for this feature. Every row is a required outcome, not
observed evidence. Implementation is not authorized by this document.

**Scope:** View the issue file named by a registered repository's canonical
`.draindeck/config.local.yaml`, select one/many/all eligible issues, and start
exactly one sequential Draindeck runtime process per batch. This changes the
Dashboard's existing read-only product boundary and the runtime's current
unfiltered queue selection, so an accepted ADR/spec must precede source work.

## Locked decisions

- Repository registration accepts the absolute path to that repository's
  `.draindeck/config.local.yaml`. The file must exist and pass the existing
  `runtime.config.load_config` structural parser before registration commits.
- `project.repository` in the parsed config must resolve to the registered Git
  worktree. Relative `project.issues_file` and `event_log.path` values resolve
  against `project.repository`, never the Dashboard process CWD.
- The existing `runtime.queue.issues_md.parse` function is the only issue-file
  parser. A `Depends-On:` line must be un-bulleted; the UI must disclose that
  known parser behavior instead of pretending a bulleted line created a
  dependency.
- The configured file supplies issue identity, text, acceptance criteria,
  dependencies, and file order. It does **not** supply workflow state.
  `events.jsonl` is authoritative for `PENDING`, `ACTIVE`, `DONE`,
  `NEEDS_HUMAN`, and `NEEDS_DECOMPOSITION`.
- `Run selected` is an exact allowlist. It refuses the entire request if an
  issue is unknown, terminal, otherwise non-actionable, or needs an unfinished
  dependency outside the allowlist. It never adds or drops an issue silently.
- `Run all` means every currently non-terminal configured issue. Terminal
  issues remain visible but are excluded with an explicit count. A zero-item
  result is a successful no-op. The request refuses if any included issue has
  an unfinished dependency outside the resulting set.
- A valid batch is ordered topologically; configured file order is the stable
  tie-breaker. One batch launches exactly one runtime process and the runtime
  remains sequential.
- One process may be active per repository. Later requests for the same
  repository enter a FIFO Dashboard-owned command queue; different
  repositories may run concurrently.
- Before a process exists, `QUEUED`, `CANCELLED_BEFORE_START`, or
  `LAUNCH_FAILED` describes the Dashboard command, not runtime workflow state.
  Once `RunStarted` exists, progress and outcome come from that run's
  `events.jsonl` evidence; no parallel Dashboard workflow state machine is
  allowed.
- No new lifecycle event or `RunStarted` payload field is assumed here. Adding
  selection metadata to the frozen event schema would require a separate Doc
  03 amendment and compatibility decision.
- Stop/cancel-running controls, parallel issues within a repository, editing
  the issue file, and automatically repairing configuration or runtime state
  are out of scope.

## State interpretation

| Configured issue evidence | Presentation and admission meaning |
|---|---|
| No `IssueCreated` event | `NOT_INGESTED` presentation state; non-terminal and eligible for a valid new batch. It must not be mislabeled `PENDING`. |
| `PENDING` | Non-terminal; eligible when dependencies are satisfied by `DONE` evidence or are in the same batch. |
| `ACTIVE` | Non-terminal resumable work. It must be included in the batch; a new selection that omits any authoritative `ACTIVE` issue is refused rather than bypassing recovery/order. |
| `DONE` | Terminal/completed. Refused in `Run selected`; displayed but excluded from `Run all`. |
| `NEEDS_HUMAN` | Terminal for automated running. Refused in `Run selected`; displayed but excluded from `Run all`, with the state as the reason. |
| `NEEDS_DECOMPOSITION` | Terminal for that configured parent. Refused in `Run selected`; displayed but excluded from `Run all`, with the state as the reason. |
| Inconsistent, corrupt, unavailable, or not-ready event projection | No runnable conclusion is permitted; listing remains honest about unavailable state and every start request fails closed. |

## Outcome matrix

### Registration and source resolution

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Valid canonical config | Registration stores canonical project, config, and resolved log paths only after the config passes the existing loader and project identity check. | Registration commits before validation or stores a Dashboard-CWD-relative path. |
| Relative config path submitted | `CONFIG_PATH_NOT_ABSOLUTE`; no registration row. | Relative input is resolved against Dashboard CWD and accepted. |
| Config path missing, directory, unreadable, or non-regular | Typed `CONFIG_PATH_*` error naming the path; no registration row or target mutation. | A broken registration is created or an unhandled traceback is returned. |
| Invalid YAML, non-mapping YAML, unknown field, or schema-invalid value | `CONFIG_INVALID` with the existing loader's useful detail; no registration row. | Dashboard applies a weaker schema or accepts a config the runtime rejects. |
| Config path is not the registered repo's `.draindeck/config.local.yaml` | `CONFIG_PATH_MISMATCH`; no registration. | An arbitrary YAML path is accepted as the repository's control config. |
| Parsed `project.repository` differs from registered project | `CONFIG_REPOSITORY_MISMATCH`; response names both resolved paths. | Cross-repository config is accepted. |
| Duplicate canonical config/log registration | Existing uniqueness rule returns a typed conflict; original row remains. | Duplicate polling/control authority is created. |
| Config changes or disappears after registration | Registration remains historical, but configured-issue reads and new starts re-read the source and fail with current typed config error. | Cached config silently remains authoritative. |
| Relative `issues_file` | Resolve from `project.repository`; Dashboard CWD has no effect. | Changing Dashboard CWD changes the file read. |
| Absolute `issues_file` already supported by runtime config | Resolution matches runtime `Path(repository) / issues_file` behavior exactly; it is never re-anchored to Dashboard CWD. | Dashboard and runtime open different issue files. |
| Relative/absolute `event_log.path` | Resolve only through `runtime.config.resolve_event_log_path`. | Dashboard reproduces divergent path logic. |

### Issue-file reading and display

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Healthy configured file | Existing parser output is returned in file order with ID, title, body, acceptance criteria, and dependencies; response includes a SHA-256 file revision. | A second parser or positional/content-derived ID is used. |
| Missing, directory, unreadable, invalid UTF-8, malformed heading, or duplicate ID | Typed `ISSUES_FILE_*`/`ISSUES_PARSE_ERROR`; no partial list and no process start. | Some issues are silently dropped or partial data is runnable. |
| Bulleted `- Depends-On: X` | Existing parser result is preserved (no dependency); UI/API exposes the standing warning that dependencies must be un-bulleted. | Dashboard invents a dependency that the runtime parser does not produce or hides the gotcha. |
| `STATUS` text/column conflicts with events | Displayed runtime state follows events only; source status may be shown only as non-authoritative text, never as state. | `STATUS=DONE` marks an event-`PENDING` issue completed, or the reverse. |
| File issue has no event | Display `NOT_INGESTED`, not `PENDING`; it may be selected. | Absence of evidence is presented as an observed event state. |
| Event issue no longer appears in configured file | It remains available in historical event views but not as a selectable configured issue. An `ACTIVE` missing-file issue blocks new starts with a named safety error. | Historical evidence disappears or new work bypasses an active orphan. |
| Event projection unavailable/corrupt/inconsistent/rebuilding | Issue text may be shown, but state is `UNAVAILABLE` and run controls fail closed. | Dashboard guesses state from the file or enables start. |
| Issue file changes after list render | Submitted `expectedIssuesDigest` mismatch returns `ISSUES_REVISION_CONFLICT`; selection is not reinterpreted. | Renamed/removed/new issues are silently substituted into the batch. |

### Selection, terminal handling, and dependency admission

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Selected request is empty | `EMPTY_SELECTION`; no queue row, process, or lifecycle event. | Empty selection drains the backlog. |
| Unknown or duplicate selected ID | Whole request refuses and names every invalid ID; no silent dedupe/drop. | A partial batch is queued. |
| One or more selected issues are terminal/non-actionable | Whole request refuses and reports each issue/state/reason. | Terminal items are skipped while others launch. |
| Selected dependency is already `DONE` | Dependency need not be selected; request may proceed. | Completed dependency is treated as missing. |
| Selected dependency is unfinished and also selected | Request may proceed; dependency is ordered before its dependent. | Dependent runs first or request falsely refuses. |
| Selected dependency is unfinished and not selected | Whole request refuses and returns every `{issueId, missingDependencyId, dependencyState}` blocker. | Dependency is auto-added, blocked issue is dropped, or only the first blocker is reported. |
| Dependency ID is absent from file and events | It is unfinished/unknown and blocks with a named reason. | Unknown dependency is treated as complete. |
| Dependency absent from file but `DONE` in events | It is complete and does not need selection. | File absence overrides authoritative completion evidence. |
| Dependency is `NEEDS_HUMAN`/`NEEDS_DECOMPOSITION` | It is not `DONE`; dependent batch refuses with the terminal dependency state. | Any terminal state is treated as successful completion. |
| Self-dependency or dependency cycle | Whole request refuses and returns the complete cycle/member set; no process starts. | Queue reports a successful no-op or hangs. |
| Existing `ACTIVE` issue is selected | It is first subject to dependency order/recovery and may resume within the exact batch. | It is duplicated as a new issue or silently ignored. |
| Existing `ACTIVE` issue is omitted | Whole new batch refuses and names the omitted active issue. | Runtime processes work outside the explicit allowlist or bypasses active recovery. |
| Independent selected issues | Stable order follows configured file order. | Hash/set/DB order changes execution order. |

### Run-all admission

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Mix of non-terminal and terminal issues | Include every non-terminal issue; exclude terminal issues and return explicit `toRun` and per-terminal-state counts. | Terminal issues launch or disappear without counts. |
| All configured issues terminal | Success/no-op message with zero `toRun`; no queue row, process, or new run events. | Request returns an error or creates an empty runtime run. |
| No configured issues | Same successful no-op with zero counts. | Empty file is treated as a launch failure. |
| Full dependency chain is non-terminal and in file | Include the full chain and topologically order it, file order breaking ties. | Run-all refuses merely because the operator did not select dependencies individually. |
| Non-terminal issue depends on unfinished issue outside run-all set | Whole request refuses and names every blocker. | Blocked issue is skipped or the external dependency is silently added. |
| A terminal `DONE` dependency is outside run-all set | Request may proceed because authoritative completion is satisfied. | Completed dependency is demanded in the run set. |

### Queue, concurrency, and revalidation

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Repository has no active process | Valid non-empty command becomes next launch candidate. | More than one process is started for the repository. |
| Repository already has an active process | Second valid command is persisted FIFO as `QUEUED`; it does not invoke a process yet. | It races the active process or returns false evidence of a `RunStarted`. |
| Different repositories | Each may own one process concurrently; queues and process handles remain repository-scoped. | Global serialization or cross-repo command leakage occurs. |
| Dashboard restarts with queued commands | Queue survives in Dashboard-owned SQLite; each command is revalidated before launch. | Commands vanish or launch without revalidation. |
| Double-click/retry of same request identity | Idempotent response returns the existing queued command; exactly one launch occurs. | Duplicate processes/runs result from one operator action. |
| Issue file changes while queued | Digest conflict pauses/refuses that command; it is never reinterpreted against new file content. | Changed file silently expands/shrinks the batch. |
| Selected issue becomes terminal while queued | Exact selected command refuses at dequeue and names the new terminal state. | It silently drops the item or reruns it. |
| Run-all issue becomes terminal while queued | Revalidation recomputes terminal exclusions and summary from current event state; zero remaining is a clean no-op. | It launches completed work or treats zero as an error. |
| New unfinished dependency appears only because file changed | File digest conflict wins; dependency is not silently folded into the queued command. | Queue mutates operator intent. |
| Active process exits normally | Slot releases only after process exit; next queued command revalidates before launch. | Next process overlaps or uses stale admission. |
| Active process exits abnormally or has unresolved `RunStarted` | Runtime view says only `no controlled finish observed`; queued commands pause for explicit operator attention rather than cascading automatically. | UI labels it completed/running without evidence or immediately launches the next mutation. |
| Dashboard restarts while prior child may still live | PID/process ownership is treated as control-plane evidence only; repository remains non-launchable until ownership is safely re-established. Unresolved `RunStarted` is not called `Running`. | Restart spawns a competing process based only on lost in-memory state. |

### Runtime launch and exact execution

| Scenario / failure window | Predicted outcome | Falsifier |
|---|---|---|
| Valid launch | Fixed configured executable, canonical config path, and validated selection are passed as an argv vector with `shell=False`; exactly one child process starts. | Browser input becomes executable/arguments or a shell command string is built. |
| Runtime executable missing/invalid | Typed `LAUNCH_FAILED`; no `RunStarted` is claimed. Queue slot releases safely. | Dashboard fabricates a run or emits an unhandled error. |
| Runtime rejects config/ownership before `RunStarted` | Command reports launch/pre-run failure separately; event view remains unchanged. | Dashboard invents a runtime outcome absent from the log. |
| Runtime-side selection validation fails after Dashboard validation | Process exits before workflow work; no issue outside the allowlist activates. | Dashboard validation is trusted as the only gate. |
| Selected run | Runtime scheduler considers only the validated allowlist plus already-completed dependencies; no unselected issue is activated. | Any unselected non-terminal issue receives a new lifecycle event. |
| Run-all | Runtime computes/validates all current non-terminal configured issues and preserves dependency/file order. | It relies solely on stale browser selection. |
| Issue succeeds | Per-issue events and final state come from the existing lifecycle; next selected issue may proceed. | Dashboard writes state directly. |
| Issue escalates | Event-derived terminal state is shown; it is not reported as completed. Remaining batch behavior follows the existing sequential orchestrator contract. | Escalation is hidden or rewritten as success. |
| Run budget stops before all selected issues | Existing `RunFinished` evidence and untouched issue states are shown honestly; no skipped issue is marked complete. | Dashboard claims the whole selection ran. |
| Controlled runtime exit | Exactly the existing matching `RunFinished` outcome is displayed. | Process exit code overrides contradictory event evidence. |
| Abrupt runtime death after `RunStarted` | No `RunFinished` is synthesized; display remains `no controlled finish observed`. | Dashboard fabricates terminal evidence. |
| Dashboard dies while child runs | Child/recovery behavior must obey the accepted launcher ADR; target event log and workspace lease remain runtime-owned. | Dashboard writes/repairs the log or bypasses workspace ownership. |

### API, UI, and security

| Scenario | Predicted outcome | Falsifier |
|---|---|---|
| Configured Issues page loads | Shows source path/revision, issue details, event-derived state, dependency information, row selection, and parser warning. | State comes from source status or controls are enabled under unavailable evidence. |
| Select one/many/all | Accessible checkboxes preserve explicit selection across ordinary refresh; run action shows exact count and blockers before submission. | Refresh changes intent invisibly or selection is pointer-only. |
| Confirmation | Names repository, mode, ordered issue IDs/count, terminal exclusions, and run-level budget context before mutation. | One click starts a process without review. |
| Refusal | Focus moves to a visible summary containing every issue-specific reason; no partial queue entry. | Only toast/color/first error communicates failure. |
| Queued | Shows FIFO position as Dashboard command state, not fabricated runtime progress. | UI displays a run ID before `RunStarted` exists. |
| Running/history display | Uses indexed `RunStarted`/`RunFinished` and issue events; unresolved runs retain existing honest wording. | PID/process exit is presented as authoritative workflow state. |
| Request schema | Strict body (`extra=forbid`), bounded issue count/ID bytes/body size, canonical repository ID, and expected file revision. | Unknown fields, oversized payloads, or path/executable arguments pass through. |
| Cross-origin/host attack | Existing loopback Host/Origin and body-size protections cover every new mutation route; no CORS enablement. | A non-loopback origin can enqueue a run. |
| Injection-shaped issue ID/path | Values remain data in argv/API/HTML; no shell, SQL, path traversal, or raw HTML interpretation. | Crafted content changes command structure or DOM execution. |
| Sensitive output | UI exposes bounded, redacted launch diagnostics only; environment variables/secrets are never persisted or rendered. | API keys or full environment appear in DB/API/logs. |
| Responsive/accessibility states | Keyboard selection/actions, visible focus, screen-reader labels/status, reduced motion, 200% text, and 320/768/1024/1440 layouts remain usable. | Any required action becomes pointer-only, clipped, or unlabeled. |

## Required evidence gate

Before implementation, an ADR/spec must resolve the Dashboard control boundary,
the runtime exact-selection interface, persisted queue ownership, launcher
crash behavior, and whether the frozen event schema remains unchanged. Then:

1. Write and run the RED tests listed in
   `docs/plans/dashboard-issue-run-control-failing-tests.md`; record that each
   fails for the intended missing behavior, not due to fixture/import errors.
2. Implement in vertical slices and turn only the corresponding RED group
   green before proceeding.
3. Run focused unit and Dashboard tests, then the combined suite.
4. Run the existing durability harness unchanged for seeds 42 and 1337 and
   retain raw stdout/stderr and exit codes.
5. Perform real-browser verification and a fresh-context security/durability
   review. Any newly discovered failure window amends this matrix before the
   matching source mutation.

