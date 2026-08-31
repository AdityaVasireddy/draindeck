# Todo: Dashboard issue selection and run control

**Status:** Documentation checkpoint complete 2026-08-30; `src/` implementation
not yet started. No merge or push will occur.

Legend: `[ ]` pending · `[~]` in progress · `[x]` verified complete

## Planning gate

- [x] ADR-30 accepted (docs/adr/ADR-30-*.md; also docs/08 §5l).
- [x] `spec/dashboard-issue-run-control.md` accepted.
- [x] Outcome matrix (`docs/31-dashboard-issue-run-control-outcome-matrix.md`)
      and RED test inventory
      (`docs/plans/dashboard-issue-run-control-failing-tests.md`) recovered,
      verified byte-for-byte against source (SHA-256 matched), and committed
      before any `src/` edit.
- [x] Explicit local checkpoint-commit authority recorded before
      implementation.
- [x] Baseline verified live on `feature/dashboard-issue-run-control`
      (branched from `master` `1ae07a5`): `python -m pytest tests\unit -q`
      → 589 passed; `python -m pytest tests\dashboard -q` → 515 passed.
- [x] Dependency-branch check: current `master` already contains everything
      ADR-30 depends on (`runtime.config.load_config`/
      `resolve_event_log_path`, `runtime.queue.issues_md.parse`, the SQLite
      migration mechanism at `SCHEMA_VERSION=3`); no other branch required as
      a base. `repositories` table confirmed to have only
      `project_path`/`log_path`/`canonical_log_path` — no `config_path` — so
      RED 1's stated premise is confirmed true, not assumed.
- [x] Pre-existing `tasks/plan.md`/`tasks/todo.md` (ADR-29 target-configuration
      build, BUILD COMPLETE, pending user review) preserved at
      `docs/plans/dashboard-target-configuration-{plan,todo}.md` with the two
      live pointers to them (docs/08 §5k, spec/dashboard-target-configuration.md)
      updated to the new path. Not discarded, not marked complete beyond its
      own recorded status.

## RED 0 — architecture and frozen-contract gate

- [x] `test_dashboard_control_requires_accepted_adr_and_updated_product_boundary`
      — genuine RED->GREEN: package docstring updated to name ADR-30 and drop
      the "read-only observability UI" claim.
- [x] `test_core_runtime_does_not_import_fastapi_or_dashboard_modules` —
      architecture-invariant guard, passed on first run (no violation exists).
- [x] `test_dashboard_never_writes_or_parses_events_jsonl_directly` —
      architecture-invariant guard, passed on first run.
- [x] `test_dashboard_does_not_mutate_git_target_or_workspace_lease` —
      architecture-invariant guard, passed on first run.
- [x] `test_no_new_run_lifecycle_payload_key_without_doc03_amendment` —
      architecture-invariant guard (reuses the same closed-payload assertion
      as `tests/unit/test_run_lifecycle_wire_format.py`), passed on first run.
- [x] `test_run_launcher_uses_fixed_argv_without_shell` —
      architecture-invariant guard, passed on first run.

Verified: `python -m pytest tests\dashboard\test_issue_run_control_architecture.py -v`
(6/6 passed after the docstring fix) and
`python -m pytest tests\unit tests\dashboard -q` (1110 passed, up from 1104
baseline).

## RED 1 — registration owns a validated canonical config path

All 16 implemented in `tests/dashboard/test_repositories.py`,
`tests/dashboard/test_app_repositories_api.py`, and
`tests/dashboard/test_migrations.py`. Genuine RED confirmed by stashing the
`repositories.py`/`migrations.py` production changes and re-running: 18
failures (16 new + 2 pre-existing-but-now-exercised-differently), all for the
missing `config_path` column/kwarg — no import/collection errors — then
restored to GREEN.

- [x] `test_registration_requires_absolute_config_path`
- [x] `test_registration_rejects_missing_config_without_database_row`
- [x] `test_registration_rejects_directory_and_non_regular_config`
- [x] `test_registration_rejects_invalid_yaml_with_clear_error`
- [x] `test_registration_rejects_non_mapping_and_schema_invalid_config`
- [x] `test_registration_uses_runtime_load_config_not_dashboard_yaml_schema`
- [x] `test_registration_rejects_noncanonical_config_location`
- [x] `test_registration_rejects_config_for_different_project_repository`
- [x] `test_registration_canonicalizes_and_persists_config_path`
- [x] `test_registration_derives_log_path_with_resolve_event_log_path`
- [x] `test_registration_remains_atomic_when_config_validation_fails`
- [x] `test_duplicate_canonical_config_or_log_path_is_conflict` — tests the
      `canonical_config_path` uniqueness constraint specifically (re-registering
      the same repository's canonical config a second time), since a config's
      canonical location is a pure function of `project_path` and therefore
      cannot literally collide across two *different* repositories the way
      `canonical_log_path` can.
- [x] `test_repository_migration_adds_config_path_without_losing_existing_rows`
      (in test_migrations.py; plus an added
      `test_canonical_config_path_column_is_unique_when_present`)
- [x] `test_legacy_registration_without_config_is_observation_only_until_repaired`
- [x] `test_repository_api_returns_config_path_and_capability_state`
- [x] `test_unregister_deletes_queue_control_rows_but_never_target_files` —
      **reconciled**: no Dashboard-owned queue table exists yet (arrives in
      Unit 7 / RED 6). Implemented now as the currently-testable half (delete
      never touches target files/repo); will be extended in Unit 7 to also
      assert queue-row cleanup once that table exists.

Also fixed 4 pre-existing tests whose literal `SCHEMA_VERSION`/`3` pins went
stale from the SCHEMA_VERSION 3->4 bump (`test_fresh_database_lands_directly_at_v2_with_all_new_tables`
in test_migrations.py; `test_schema_version_is_3` renamed
`test_schema_version_is_at_least_3`, and two literal-`3` assertions changed to
compare against `SCHEMA_VERSION`, in test_proxy_cost_migration.py) — same
category of fix as any additive schema bump requires, not a weakening.

Verified: `python -m pytest tests\dashboard\test_repositories.py
tests\dashboard\test_app_repositories_api.py tests\dashboard\test_migrations.py
tests\dashboard\test_proxy_cost_migration.py -q` all green;
`python -m pytest tests\unit tests\dashboard -q` -> 1130 passed (up from 1110).

## RED 2 — configured issue reader reuses the existing parser

All 19 implemented in `tests/dashboard/test_configured_issues.py`, plus 3
API-level tests in `tests/dashboard/test_app_configured_issues_api.py`. New
module `src/draindeck_dashboard/configured_issues.py` reads the materialized
`issue_views` table (same read model `api_queries.cross_repository_issues`
uses), scoped to the read model's own current generation — never a
per-request full-evidence recompute — and delegates all parsing to
`runtime.queue.issues_md.parse` (verified structurally: exactly one compiled
regex in the module, used only to disclose the bulleted-`Depends-On:`
gotcha). Genuine RED confirmed: the module didn't exist yet, so the test
file failed to import (`ModuleNotFoundError`) rather than collecting —
the clearest possible form of "missing behavior," not a fixture/typo
accident — before the module was created and all 19+3 went GREEN.

- [x] `test_relative_issues_file_resolves_against_config_project_repository`
- [x] `test_issues_file_resolution_is_independent_of_dashboard_cwd`
- [x] `test_absolute_issues_file_matches_runtime_path_semantics`
- [x] `test_config_and_issues_file_are_reread_after_registration`
- [x] `test_missing_issues_file_returns_typed_error_not_partial_list`
- [x] `test_directory_unreadable_and_invalid_utf8_issue_files_fail_loud` —
      directory and invalid-UTF-8 cases are live; a genuine
      permission-denied case is not reliably simulatable on Windows from a
      test process running as file owner, so `ISSUES_FILE_UNREADABLE`'s
      `OSError` branch is covered by inspection, documented in the test.
- [x] `test_malformed_heading_and_duplicate_id_surface_existing_parser_error`
- [x] `test_configured_issue_reader_delegates_to_runtime_issues_md_parse`
- [x] `test_configured_issue_reader_has_no_second_heading_or_dependency_parser`
- [x] `test_configured_issues_preserve_file_order_and_all_parser_fields`
- [x] `test_response_includes_sha256_revision_of_exact_issue_file_bytes`
- [x] `test_bulleted_depends_on_is_not_invented_and_warning_is_returned`
- [x] `test_unbulleted_depends_on_is_returned_exactly`
- [x] `test_source_status_text_never_sets_runtime_state`
- [x] `test_issue_without_event_is_not_ingested_not_pending`
- [x] `test_event_issue_removed_from_file_remains_in_historical_views_only`
- [x] `test_active_event_issue_missing_from_file_blocks_control` — the
      reader's contribution only: exposes `activeIssuesOutsideFile`; the
      planner in RED 4 is what actually refuses the batch on it.
- [x] `test_corrupt_inconsistent_unavailable_or_rebuilding_projection_disables_control`
- [x] `test_api_returns_issue_text_even_when_runtime_state_is_unavailable`

Verified: `python -m pytest tests\dashboard\test_configured_issues.py
tests\dashboard\test_app_configured_issues_api.py -q` -> 22 passed.
`python -m pytest tests\unit tests\dashboard -q` -> 1152 passed (up from 1130).

## RED 3 — pure batch admission and deterministic ordering

All 24 implemented in `tests/unit/test_issue_selection.py`. New module
`src/runtime/queue/selection.py` (`plan_selected`/`plan_run_all`, pure —
IssueSpec + state map in, PlanResult out; never reads `.body`, structurally
verified). Lives in `runtime.queue`, not Dashboard, so both the Dashboard API
(RED 5) and runtime CLI re-validation (RED 4) import the same implementation
without runtime ever importing Dashboard. Genuine RED confirmed: moved the
module aside and re-ran — `ModuleNotFoundError` at collection (module didn't
exist), restored and all 24 passed.

- [x] `test_selected_empty_refuses_without_plan`
- [x] `test_selected_unknown_ids_are_all_reported`
- [x] `test_selected_duplicate_ids_refuse_without_silent_dedupe`
- [x] `test_selected_terminal_issues_are_all_reported_and_none_run`
- [x] `test_selected_done_dependency_need_not_be_selected`
- [x] `test_selected_unfinished_dependency_in_selection_is_allowed`
- [x] `test_selected_unfinished_dependency_outside_selection_refuses_whole_batch`
- [x] `test_selected_reports_every_missing_dependency_for_every_issue`
- [x] `test_unknown_dependency_is_unfinished_and_blocks`
- [x] `test_dependency_absent_from_file_but_done_in_events_is_satisfied`
- [x] `test_needs_human_or_decomposition_dependency_is_not_done`
- [x] `test_self_dependency_reports_cycle`
- [x] `test_multi_issue_dependency_cycle_reports_all_members`
- [x] `test_selected_active_issue_is_included_once`
- [x] `test_omitted_active_issue_refuses_new_selection`
- [x] `test_dependency_order_is_topological`
- [x] `test_file_order_breaks_topological_ties_deterministically`
- [x] `test_run_all_includes_every_nonterminal_issue`
- [x] `test_run_all_excludes_terminal_issues_with_state_counts`
- [x] `test_run_all_all_terminal_is_successful_noop`
- [x] `test_run_all_empty_file_is_successful_noop`
- [x] `test_run_all_includes_full_nonterminal_dependency_chain`
- [x] `test_run_all_refuses_unfinished_dependency_outside_result_set`
- [x] `test_admission_never_reads_status_text_for_state`

Verified: `python -m pytest tests\unit\test_issue_selection.py -q` -> 24
passed. `python -m pytest tests\unit tests\dashboard -q` -> 1176 passed (up
from 1152).

## RED 4 — runtime exact allowlist and lifecycle preservation

Implemented in `tests/unit/test_loop_issue_selection.py` (Orchestrator level)
and `tests/unit/test_main_issue_selection.py` (CLI/argparse + `_validate_selection`
+ full-mock `cmd_run` level). `runtime.main` gains `--issue`(repeatable)/
`--all-issues` (argparse mutual-exclusion group) + `--issues-digest`;
`_validate_selection(args, cfg, proj)` re-reads the issue file fresh, checks
the digest, and re-validates through the RED 3 planner — called from
`_run_after_startup` strictly before `_emit_run_started`, using `proj`
already fully recovered/replayed at that point. `Orchestrator.__init__` gains
`allowed_issue_ids: frozenset[str] | None = None`; `_next_actionable` skips
any id outside it. A valid zero-item `--all-issues` batch raises
`SelectionRunAllEmpty`, caught in `_run_after_startup` to return 0 before any
`RunStarted`.

Genuine RED confirmed: stashed `main.py`/`loop.py`, re-ran both new test
files — `ImportError: cannot import name 'SelectionRunAllEmpty'` at
collection for the main-level tests, `TypeError: unexpected keyword argument
'allowed_issue_ids'` for the loop-level tests (not fixture accidents) —
then restored to GREEN.

- [x] `test_run_cli_accepts_repeated_issue_ids_as_exact_selection`
- [x] `test_run_cli_without_selection_preserves_existing_cli_behavior`
- [x] `test_run_cli_issue_and_all_issues_are_mutually_exclusive` (added —
      argparse's own mutually-exclusive group enforces this structurally)
- [x] `test_runtime_revalidates_selection_after_workspace_ownership_and_recovery`
- [x] `test_runtime_selection_refusal_occurs_before_issue_activation` —
      as `..._and_emits_nothing`, verified structurally (no `log.append`/
      `_emit_run_started`/`ISSUE_ACTIVATED` anywhere in `_validate_selection`)
- [x] `test_runtime_selection_refusal_does_not_emit_runstarted_or_runfinished`
      — same test as above; the function never touches an EventLog at all
- [x] `test_runtime_never_activates_unselected_pending_issue` (both a pure
      `_validate_selection` version and a full `Orchestrator.run()` version)
- [x] `test_runtime_resumes_selected_active_issue_before_later_selected_issue`
- [x] `test_runtime_refuses_when_active_issue_is_outside_allowlist`
- [x] `test_runtime_selected_dependency_runs_before_dependent` — covered by
      RED 3's planner tests; the Orchestrator itself doesn't consume
      `ordered_ids`, only the allowlist SET, since dependency ordering at
      execution time is already enforced by the pre-existing `deps_met()`
      gate regardless of selection.
- [x] `test_runtime_independent_selected_issues_use_file_order`
- [x] `test_runtime_selected_queue_drained_ignores_unselected_actionable_issues`
- [x] `test_runtime_run_all_uses_current_nonterminal_set`
- [x] `test_runtime_run_all_zero_nonterminal_is_clean_noop`
- [x] `test_runtime_dependency_block_is_named_not_reported_queue_drained` —
      covered by RED 3's blocker-reporting tests plus
      `test_selection_reports_every_blocker_not_just_first` here.
- [x] `test_one_batch_emits_at_most_one_runstarted_and_one_controlled_runfinished`
      — unchanged existing `_run_after_startup` control flow (one call site
      each), not modified by this unit; selection only gates entry before it.
- [x] `test_selection_does_not_change_existing_runstarted_closed_schema` —
      covered by RED 0's `test_no_new_run_lifecycle_payload_key_without_doc03_amendment`
      and the pre-existing `test_run_started_exact_closed_payload_keys`;
      `_run_started_payload` was not touched by this unit.
- [x] `test_observer_and_old_logs_remain_compatible_when_schema_is_unchanged`
      — same reasoning; `tests/unit/test_no_downgrade_and_observer_exemption.py`
      re-verified unchanged/green.
- [x] `test_budget_is_shared_across_the_whole_selected_batch` — unchanged:
      one `BudgetManager` is still constructed once per run regardless of
      selection, not per-issue.
- [x] `test_escalated_selected_issue_does_not_mark_batch_item_completed` /
      `test_unprocessed_selected_issues_remain_unchanged_after_budget_stop`
      — unchanged existing `step()`/budget-hard-stop control flow; the
      allowlist is purely a filter over which issue `_next_actionable`
      returns, never a rewrite of what happens once one is returned.

Verified: `python -m pytest tests\unit\test_loop_issue_selection.py
tests\unit\test_main_issue_selection.py -q` -> 18 passed.
`python -m pytest tests\unit tests\dashboard -q` -> 1194 passed (up from
1176). Durability harness re-run on this change: `python tests\crash\harness.py
%TEMP%\draindeck-ch-42 42` -> ALL 60 SCENARIOS PASSED;
`python tests\crash\harness.py %TEMP%\draindeck-ch-1337c 1337` -> ALL 60
SCENARIOS PASSED (first attempt at a fresh `...-1337` path hit a transient
Windows `PermissionError` during scratch-directory cleanup before any
scenario ran — an environmental file-lock hiccup, not a code defect; retried
clean at a new path).

## RED 5 — run-request API is strict, exact, and race-safe

All 17 implemented in `tests/dashboard/test_issue_run_api.py` (19 tests
total, +2 for idempotency-key repeat/reuse). Adds SQLite v4->v5 migration
(`run_commands` table, control-plane only, never written to `events.jsonl`),
`src/draindeck_dashboard/run_queue.py` (`plan_run` wraps `get_configured_issues`
+ the RED-3 planner with digest/readiness checks; `enqueue_command` adds
idempotency-key dedup and the queue insert), and three routes:
`POST /api/repositories/{repoId}/run-plans` (validate only, no mutation),
`POST /api/repositories/{repoId}/run-commands` (idempotent enqueue,
`Idempotency-Key` header required), `GET .../run-commands[/{id}]`.

**Real bug found and fixed test-first during this unit:** the first draft
used `/api/repositories/{repoId}/runs` for the new enqueue/list routes,
which is also the path of the pre-existing runtime-run-history routes
(`GET .../runs` and `GET .../runs/{run_id}` in `views.py`/further down
`app.py`). Because FastAPI matches routes in registration order and mine
were registered first, they silently shadowed the existing routes, breaking
`test_app_views_api.py`'s and `test_app_redesign_api.py`'s run-history tests
(caught immediately by the full regression suite, not by RED 5's own tests,
since those all use a fresh repo with no runtime history to shadow).
Renamed to `/run-commands` throughout; full suite re-run confirmed clean.
Also had to switch `test_dashboard_never_writes_or_parses_events_jsonl_directly`
(RED 0) from a raw substring scan to an AST-based one that skips docstrings,
since `migrations.py`/`run_queue.py`'s own boundary-documenting prose ("this
table is never written to events.jsonl") was tripping the naive check —
same false-positive class as `__init__.py` earlier, fixed properly this time
instead of growing an allowlist forever.

- [x] `test_run_selected_requires_nonempty_unique_issue_ids_and_revision`
- [x] `test_run_all_rejects_client_supplied_issue_ids`
- [x] `test_unknown_request_fields_are_422`
- [x] `test_oversized_issue_count_id_and_body_are_rejected_before_planning`
- [x] `test_issue_revision_conflict_queues_nothing`
- [x] `test_selected_refusal_returns_all_blockers_in_typed_envelope`
- [x] `test_selected_terminal_refusal_queues_nothing`
- [x] `test_run_all_returns_terminal_exclusion_summary`
- [x] `test_run_all_zero_result_returns_noop_without_queue_or_process`
- [x] `test_api_rechecks_current_event_state_not_source_status`
- [x] `test_api_never_accepts_executable_config_or_issue_path_from_run_body`
- [x] `test_non_loopback_host_and_origin_cannot_enqueue_run`
- [x] `test_cors_remains_disabled_for_run_routes`
- [x] `test_security_headers_wrap_success_and_failure_responses`
- [x] `test_injection_shaped_issue_id_remains_data`
- [x] `test_html_shaped_issue_text_is_escaped_in_api_consumer_contract`
- [x] `test_run_api_does_not_persist_environment_or_secrets`

Genuine RED confirmed: stashed `app.py`/`migrations.py`/`run_queue.py` and
re-ran -- 17 of 19 failed with real 404s (routes didn't exist), then
restored to GREEN.

Verified: `python -m pytest tests\dashboard\test_issue_run_api.py -q` -> 19
passed. `python -m pytest tests\unit tests\dashboard -q` -> 1213 passed (up
from 1194, and zero regressions after the route-rename fix).

## RED 6 — one-process-per-repository FIFO queue

All 17 implemented in `tests/dashboard/test_run_queue.py` (18 tests total,
+1 for `reconcile_ambiguous_claims_on_startup`). `run_queue.py` gains
`claim_next_launchable_command` (one atomic `BEGIN IMMEDIATE` transaction:
refuses if the repository already has any command in a blocking status --
`CLAIMED`/`LAUNCHED`/`LAUNCH_OWNERSHIP_UNKNOWN`/`ABNORMAL_EXIT` -- else
claims the earliest `QUEUED` row), `revalidate_claimed_command` (re-runs
`plan_run` at dequeue time: digest conflict or now-invalid selection ->
`REFUSED`; run-all recomputed to zero -> `COMPLETED` no-op; otherwise
unchanged, ready to launch), `reconcile_ambiguous_claims_on_startup` (any
row still `CLAIMED` at Dashboard startup -> `LAUNCH_OWNERSHIP_UNKNOWN`,
closing that repository to further automatic launch), and
`delete_commands_for_repository`. `app.py`'s `DELETE /api/repositories/{id}`
now refuses with `REPOSITORY_HAS_ACTIVE_RUN` (409) while any blocking-status
command exists, and only then deletes queue rows before the repository row.

- [x] `test_first_valid_command_for_repo_becomes_launch_candidate`
- [x] `test_second_command_for_active_repo_is_persisted_fifo_without_spawn`
- [x] `test_three_queued_commands_launch_in_submission_order`
- [x] `test_different_repositories_may_each_launch_one_process`
- [x] `test_atomic_claim_prevents_two_dashboard_workers_launching_same_command`
- [x] `test_idempotency_key_prevents_double_click_duplicate_launch` (Unit 6)
- [x] `test_queue_survives_dashboard_restart`
- [x] `test_dequeue_revalidates_issue_file_revision`
- [x] `test_dequeue_selected_issue_now_terminal_refuses_exact_command`
- [x] `test_dequeue_run_all_recomputes_terminal_exclusions`
- [x] `test_dequeue_run_all_now_empty_completes_as_noop_without_spawn`
- [x] `test_abnormal_prior_exit_pauses_later_commands_for_operator_attention`
- [x] `test_normal_process_exit_releases_slot_then_revalidates_next_command`
- [x] `test_lost_process_handle_never_implies_repository_is_launchable`
- [x] `test_unresolved_runstarted_is_not_labeled_running`
- [x] `test_unregister_with_active_process_refuses_and_does_not_orphan_control`
      (drives the real app.py route via TestClient)
- [x] `test_queue_rows_are_dashboard_owned_and_never_written_to_event_log`

**Documented scope boundary:** no background timer drains the queue in this
pass. Progression is triggered at two points: immediately after a successful
enqueue, and an explicit `POST .../run-commands/drain` the UI (RED 8) calls
opportunistically on its own SSE-triggered refresh. A repository whose
active command finishes between those triggers stays queued until the next
one — acceptable for the primary flows (submit-and-watch) but a real gap for
fully autonomous unattended draining; a periodic tick hooked into the
existing lease-gated `Scheduler` would close it and is a natural follow-up,
deliberately not attempted here to avoid modifying that already-delicate
lease-gated loop under this pass's time budget.

Genuine RED confirmed: stashed `run_queue.py`'s new functions (reverted to
Unit 6) and `app.py`, re-ran -- `ImportError:
cannot import name 'claim_next_launchable_command'` at collection, then
restored to GREEN.

Verified: `python -m pytest tests\dashboard\test_run_queue.py -q` -> 18
passed.

## RED 7 — subprocess boundary and event-derived status

All 12 implemented in `tests/dashboard/test_run_launcher.py` (13 tests
total, +1 end-to-end `try_launch_next` check). New module
`src/draindeck_dashboard/run_launcher.py` mirrors `observer_client.py`'s
established pattern exactly: `build_launch_argv` constructs a fixed argv
(`[executable, "run", "--config", ..., "--issues-digest", ..., ...selection]`),
`launch_claimed_command` spawns via `subprocess.Popen(argv, shell=False,
env=build_observer_env(os.environ), ...)`, reusing the observer's
allowlisted-environment helper unchanged. Process liveness/exit
reconciliation reuses `runtime.workspace_lease.probe_controller_identity`
(the exact same PID/creation-time mechanism the runtime uses for its own
orphan detection) as the cross-restart fallback when this process's own
in-memory `Popen` handle isn't available; a confirmed nonzero exit, or a
confirmed-dead process observed with no handle (exit code unknowable), both
become `ABNORMAL_EXIT` -- fail-closed, never assumed successful.

**Tests use real controlled fake executables** (`.bat` scripts written to
`tmp_path`, verified directly executable via `subprocess.Popen(shell=False)`
on this Windows/Python combination) rather than mocking `subprocess.Popen`
away -- a genuine OS process is spawned in every launcher test, with real
argv and real `shell=False`, per this unit's explicit instruction. No paid
engine and no real target repository is ever involved.

**RED-0 refinement required for this unit:** the RED 0 test
`test_dashboard_does_not_mutate_git_target_or_workspace_lease` originally
banned importing `runtime.workspace_lease` from the Dashboard at all.
ADR-30 decision 4 explicitly permits observing a recorded PID/creation-time
identity as control-plane evidence via the runtime's own mechanism ("grants
no authority to acquire or repair the runtime lease") -- so the test was
narrowed to ban only the *mutating* surface (nothing changed:
`runtime.repo.git_adapter` stays fully banned) while allowlisting the four
read-only identity-probe names (`probe_controller_identity`,
`ControllerIdentityResult`, `ControllerIdentityState`,
`WindowsProcessIdentityApi`) specifically. Re-verified green with the
narrowed check before and after `run_launcher.py`'s import.

- [x] `test_launcher_uses_configured_absolute_executable_and_canonical_config`
- [x] `test_launcher_passes_selection_as_argv_with_shell_false`
- [x] `test_launcher_starts_exactly_one_process_per_claimed_command` (real
      `.bat` spawn, verified via a marker file the fake process writes)
- [x] `test_missing_executable_is_typed_launch_failed_without_run_claim`
- [x] `test_pre_run_runtime_exit_does_not_fabricate_runstarted_or_outcome`
- [x] `test_new_run_is_correlated_only_after_observed_runstarted` --
      **reconciled**: no stdout run-ID correlation line is implemented in
      this pass (ADR-30 decision 5 makes it explicitly optional: "may be
      added"); `run_id_correlation` stays `NULL`/unused. Workflow status
      continues to come only from the pre-existing, independently tested
      `/api/repositories/{id}/runs` (event-derived) endpoint.
- [x] `test_runtime_progress_is_derived_from_issue_and_run_events`
- [x] `test_controlled_exit_uses_runfinished_over_process_exit_code`
- [x] `test_abrupt_exit_preserves_no_controlled_finish_observed`
- [x] `test_dashboard_never_synthesizes_runfinished`
- [x] `test_diagnostics_are_bounded_and_secret_redacted` (real subprocess
      whose stdout contains a fake secret string; confirmed it never reaches
      `refusalReason` or any `run_commands` column)
- [x] `test_status_changes_publish_existing_sse_refresh_signal` -- confirmed
      by absence: `run_launcher.py` imports no SSE mechanism at all, relying
      entirely on the Dashboard's existing generic database-change tailer.

Genuine RED confirmed: moved `run_launcher.py` aside, re-ran --
`ModuleNotFoundError: No module named 'draindeck_dashboard.run_launcher'` at
collection, then restored to GREEN.

Verified: `python -m pytest tests\dashboard\test_run_launcher.py -q` -> 13
passed. Combined: `python -m pytest tests\unit tests\dashboard -q` -> 1244
passed (up from 1213). Durability harness not re-run for this unit --
no file under `src/runtime` changed (only a pre-existing read-only runtime
function is now called from Dashboard code); the harness exercises
runtime crash-safety, which this unit does not touch.

## RED 8 — UI contracts and real-browser scenarios

New page `src/draindeck_dashboard/static/js/pages/run-control.js` (route
`/repositories/{repoId}/run-control`, nav link added to
`repository-detail.js`) plus a new reusable accessible modal
`components/dialog.js` (role="dialog", aria-modal, Tab/Shift+Tab focus trap,
Escape-to-close with focus returned to the invoking control -- all
live-browser-verified, see below). Structural/static contracts locked into
`tests/dashboard/test_run_control_ui_contract.py` (14 tests),
`tests/dashboard/js/test_run_control_page.mjs` (7 Node tests against the
pure `planRefusalLines`/`queueModeSummaryText`/`queueStatusText` exports),
and two additions to `test_app_shell_contract.py`.
`configured_issues.py`'s response gained a `budget` object (from the loaded
config, for the confirmation dialog's run-level budget line).

- [x] `test_configured_issues_route_and_navigation_are_registered`
- [x] `test_issue_rows_expose_accessible_selection_controls`
- [x] `test_select_all_targets_current_nonterminal_configured_set`
- [x] `test_run_selected_and_run_all_have_confirmation_dialogs`
- [x] `test_confirmation_names_repo_mode_counts_and_ordered_selection`
- [x] `test_terminal_exclusion_summary_is_visible`
- [x] `test_every_blocker_is_rendered_in_focusable_error_summary`
- [x] `test_parser_depends_on_warning_is_visible_near_dependency_data`
- [x] `test_not_ingested_and_unavailable_are_not_rendered_as_pending`
- [x] `test_selection_survives_sse_refresh_without_selecting_new_rows`
- [x] `test_queued_position_is_not_rendered_as_runtime_progress`
- [x] `test_unresolved_run_uses_no_controlled_finish_observed_wording` --
      **reconciled**: run-control.js deliberately renders no runtime workflow
      outcome text at all; the phrase remains exclusively in `format.js`/
      `runs.js` (already implemented, already tested), verified here by
      reference.
- [x] `test_controls_disable_during_unavailable_or_inconsistent_state`

### Real-browser verification (live, this session)

Ran the Dashboard against a real temp environment (`uvicorn` on
`127.0.0.1:8420`, three registered repositories, a controlled fake `.bat`
"draindeck executable" -- no paid engine, no real target mutation), driven
via `mcp__claude-in-chrome__*`:

- Mixed `PENDING`/`ACTIVE`/`DONE`/`NEEDS_HUMAN`/`NOT_INGESTED` states render
  honestly; bulleted-`Depends-On:` and active-issue-outside-file warnings
  both visible.
- `Run selected` refusal (an ACTIVE issue omitted) renders a focusable error
  summary and moves focus to it (`document.activeElement.id ===
  "run-control-errors"`, confirmed via JS); re-selecting the active issue
  narrows the error to just the truly-unresolvable `orphan-active` case
  (no row exists for it -- an intentional hard block per doc 31's "An ACTIVE
  missing-file issue blocks new starts", not a UI gap).
- `Run all` refusal (unfinished dependency outside the run-all set) reports
  the exact blocker.
- A genuinely valid `Run all` opens the confirmation dialog with repository
  path, mode, ordered issue list/count, terminal exclusions, and run-level
  budget all present; autofocus lands on "Start run"; Shift+Tab from there
  wraps to "Cancel" (focus trap confirmed); Escape closes and returns focus
  to the invoking button.
- Confirming actually enqueued, auto-claimed, and **launched a real
  subprocess** against the fake `.bat` executable -- the queue showed
  `LAUNCHED`.
- A repository with no read model yet (`UNAVAILABLE` state) has
  `run-control-run-selected`/`run-control-run-all`/`run-control-select-all`
  all `disabled === true`.
- Zero console errors/exceptions across the entire session.

**Two real bugs found and fixed test-first from this live testing:**
1. The queue rendered the literal text `"ALLnull"` for a run-all command --
   a ternary `null` (no `refusalReason`) was passed to native
   `Element.append()`, which stringifies non-Node arguments
   (`String(null) === "null"`). Fixed by extracting `queueModeSummaryText`/
   `queueStatusText` as pure functions and switching to a conditional
   `appendChild`; regression-tested in the new `.mjs` file.
2. The configured-issues table had no `.ledger-table-wrapper`
   (`overflow-x: auto`) around it, unlike every other table in this
   codebase (`issues.js` etc.) -- on a narrow viewport it would have forced
   page-level horizontal scroll. Fixed by wrapping it, matching the
   established pattern exactly.

**Documented tooling limitation, not a page defect:** native keyboard
activation (Tab moving focus, Space toggling a native `<input
type="checkbox">`) did not fire via this session's CDP-synthesized key
events, even though the dialog's *own* JS-level keydown listener (Escape,
Shift+Tab focus-trap) responded correctly to the same synthesized events.
Diagnosed systematically: focus state, tabIndex (0), aria-label, and
disabled state are all structurally correct on the checkbox, mouse/pointer
activation of the identical control works and fires the real `change`
handler, and no code intercepts or prevents default keyboard behavior --
the gap is specifically in native default-action synthesis via this CDP
path, not in the page. This mirrors the project's own precedent for the
`forced-colors: active` gap in `docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`
(a tooling/session boundary no available mechanism could bridge, not a
functional defect). Responsive-breakpoint resize (`resize_window` to 320px)
also did not visibly change the viewport in this session; the table-wrapper
fix above was made defensively given that gap, and this page reuses the
exact same CSS framework/breakpoints already live-verified for every other
table/dialog on 320/768/1024/1440 and 200% text elsewhere in this app.

Verified: `python -m pytest tests\dashboard\test_run_control_ui_contract.py
tests\dashboard\test_app_shell_contract.py tests\dashboard\test_static_js_contracts.py -q`
-> 41 passed. `node tests\dashboard\js\test_run_control_page.mjs` -> 7
passed directly. Combined: `python -m pytest tests\unit tests\dashboard -q`
-> 1260 passed (up from 1244).

## RED 9 — crash, durability, and regression gates

New `tests/crash/run_control_harness.py` (run directly, not pytest-collected
-- mirrors `harness.py`/`run_lifecycle_harness.py`'s own convention).
Simulated by direct-state manipulation and fresh-connection reconstruction
rather than a real OS-level kill, matching the exact scoping precedent
`run_lifecycle_harness.py`'s own docstring states for its fixture rows: the
Dashboard's crash window is one atomic SQLite transaction (the claim)
followed by one OS spawn call, not a multi-step external mutation the way
the runtime's git operations are -- every reachable outcome of that boundary
is exercised directly. A real controlled fake `.bat` executable is used
wherever a subprocess is actually spawned.

- [x] `test_dashboard_crash_before_spawn_leaves_command_queued_and_target_unchanged`
- [x] `test_dashboard_crash_after_spawn_before_runstarted_never_fabricates_run`
- [x] `test_dashboard_restart_does_not_compete_with_possibly_live_child`
- [x] `test_runtime_crash_after_runstarted_keeps_unresolved_run_truthful` --
      **reconciled**: this is runtime (not Dashboard) behavior, unchanged by
      this feature and already exhaustively covered by
      `tests/crash/run_lifecycle_harness.py` and the main durability
      harness, both re-run clean this unit (below).
- [x] `test_abnormal_exit_pauses_fifo_instead_of_cascading_mutations`
- [x] `test_next_operator_approved_launch_uses_existing_runtime_recovery` --
      verified there is no second, recovery-specific launch code path: an
      operator-cleared command re-enters the exact same
      claim/launch_claimed_command flow as any other command.
- [x] `test_crash_never_activates_issue_outside_exact_selection` -- the
      allowlist is re-derived fresh from argv + the current issue file on
      every runtime invocation (RED 4) and is never itself persisted by the
      queue beyond the exact `issueIds` column ADR-30 specifies; verified
      that column round-trips exactly across a simulated crash/restart.
- [x] `test_queue_database_recovery_never_writes_target_event_log_or_git_state`

### Fresh-context adversarial review (this session)

Reviewed against every named axis; two real findings, both fixed test-first:

1. **Queue atomicity and idempotency (real bug, CONFIRMED and fixed).** A
   genuine double-click race: two concurrent `enqueue_command` calls could
   both pass the idempotency-key SELECT check before either committed its
   INSERT, so the second raised an uncaught `sqlite3.IntegrityError` (a
   500) instead of returning the first's row. Reproduced reliably (7/8
   racing threads failed on every one of 3 runs against the un-fixed code).
   Fixed: `enqueue_command` now catches `IntegrityError` and falls back to
   fetching the row `ux_run_commands_repo_idempotency` (the real
   enforcement point) shows actually won the race, re-raising only if the
   constraint fired for some other reason. Regression test
   (`test_concurrent_double_click_same_idempotency_key_creates_exactly_one_row`,
   8 real threads + a `Barrier`) confirmed failing against the reverted
   code, then passing after the fix.
2. **Queue atomicity, weaker coverage (fixed, not a defect).** The existing
   `test_atomic_claim_prevents_two_dashboard_workers_launching_same_command`
   reused one connection twice, which doesn't exercise SQLite's real
   cross-connection locking. Added
   `test_concurrent_claims_from_two_real_connections_never_double_claim`
   (2 real threads, 2 real connections, 5 commands) -- confirmed
   `BEGIN IMMEDIATE` correctly serializes genuine concurrent claimants with
   no double-claim and no lost update.

Also added, no defect found: `test_run_command_id_cannot_be_read_across_repositories`
(a command from repo A is a 404 through repo B's route) and
`test_non_loopback_host_cannot_call_drain_route` (the new
`/run-commands/drain` route inherits `LoopbackOnlyMiddleware` like every
other route, confirmed explicitly since it wasn't covered by RED 5's
security tests, which predate that route). SQL-injection surface reviewed
by inspection: every `f"..."` SQL string in `run_queue.py`/`configured_issues.py`
interpolates only static column-name constants or generated `?` placeholders,
never request data, matching the codebase's existing pattern throughout
`api_queries.py`.

### Full regression and durability (this session, after all fixes above)

- [x] `python -m pytest tests\unit -q` -> 631 passed
- [x] `python -m pytest tests\dashboard -q` -> 629 passed
- [x] `python -m pytest tests\unit tests\dashboard -q` -> 1264 passed
- [x] `python tests\crash\harness.py "$env:TEMP\draindeck-final-42" 42` ->
      ALL 60 SCENARIOS PASSED
- [x] `python tests\crash\harness.py "$env:TEMP\draindeck-final-1337" 1337`
      -> ALL 60 SCENARIOS PASSED
- [x] `python tests\crash\run_control_harness.py` -> ALL RUN-CONTROL CRASH
      SCENARIOS PASSED (15/15)
- [x] README.md, PRODUCT.md, NEXT.md, `tasks/plan.md` (this file's
      companion) updated to describe the launch-capable boundary accurately;
      final evidence written to
      `docs/reviews/DASHBOARD_ISSUE_RUN_CONTROL_BUILD_EVIDENCE.md`.

**Verification:** all commands above; `git diff --check` clean; this todo
distinguishes VERIFIED (ran it, saw it pass, shown above) from nothing left
ASSUMED for this unit.

## Build complete

**Status: BUILD COMPLETE 2026-08-31 (Units 0-9, 11 commits), pending user
review before merge.** No merge, push, or PR was performed. Full evidence:
`docs/reviews/DASHBOARD_ISSUE_RUN_CONTROL_BUILD_EVIDENCE.md`. Every
contracted RED-inventory test is implemented or explicitly reconciled
(documented inline above at the point it occurs); three real bugs were
found and fixed test-first (a route collision, a live-browser-found
rendering defect, and a fresh-context-review-found concurrency race); one
item remains genuinely open by tooling limitation, not omission (native
keyboard/viewport-resize browser-automation verification — see RED 8's
entry above and the evidence document for the full diagnostic trail).
