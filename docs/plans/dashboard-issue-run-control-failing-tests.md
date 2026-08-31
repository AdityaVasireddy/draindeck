# Dashboard issue selection and run control — planned RED tests

**Status:** Test inventory only, written 2026-08-30. No test below has been
created or run. No test result is claimed. Each test must first fail for the
named missing behavior before its production slice is implemented.

**Normative prediction:**
`docs/31-dashboard-issue-run-control-outcome-matrix.md`.

The names below are proposed stable pytest names. Tests should assert outcomes
and durable state, not private call order, except for explicit architecture and
single-launch boundary tests.

## RED 0 — architecture and frozen-contract gate

Proposed file: `tests/dashboard/test_issue_run_control_architecture.py`

- `test_dashboard_control_requires_accepted_adr_and_updated_product_boundary`
- `test_core_runtime_does_not_import_fastapi_or_dashboard_modules`
- `test_dashboard_never_writes_or_parses_events_jsonl_directly`
- `test_dashboard_does_not_mutate_git_target_or_workspace_lease`
- `test_no_new_run_lifecycle_payload_key_without_doc03_amendment`
- `test_run_launcher_uses_fixed_argv_without_shell`

Expected initial RED reason: no accepted control ADR/spec, launcher boundary,
or exact-selection contract exists. This group must not be made green by a
test exemption or by weakening the existing read-only assertions.

## RED 1 — registration owns a validated canonical config path

Proposed files:

- `tests/dashboard/test_repositories.py`
- `tests/dashboard/test_app_repositories_api.py`
- `tests/dashboard/test_migrations.py`

Planned tests:

- `test_registration_requires_absolute_config_path`
- `test_registration_rejects_missing_config_without_database_row`
- `test_registration_rejects_directory_and_non_regular_config`
- `test_registration_rejects_invalid_yaml_with_clear_error`
- `test_registration_rejects_non_mapping_and_schema_invalid_config`
- `test_registration_uses_runtime_load_config_not_dashboard_yaml_schema`
- `test_registration_rejects_noncanonical_config_location`
- `test_registration_rejects_config_for_different_project_repository`
- `test_registration_canonicalizes_and_persists_config_path`
- `test_registration_derives_log_path_with_resolve_event_log_path`
- `test_registration_remains_atomic_when_config_validation_fails`
- `test_duplicate_canonical_config_or_log_path_is_conflict`
- `test_repository_migration_adds_config_path_without_losing_existing_rows`
- `test_legacy_registration_without_config_is_observation_only_until_repaired`
- `test_repository_api_returns_config_path_and_capability_state`
- `test_unregister_deletes_queue_control_rows_but_never_target_files`

Expected initial RED reason: repository registration currently accepts only
project/log paths and does not require or persist a runtime config path.

## RED 2 — configured issue reader reuses the existing parser

Proposed files:

- `tests/dashboard/test_configured_issues.py`
- `tests/dashboard/test_app_configured_issues_api.py`
- `tests/dashboard/test_dependency_carveout.py`

Planned tests:

- `test_relative_issues_file_resolves_against_config_project_repository`
- `test_issues_file_resolution_is_independent_of_dashboard_cwd`
- `test_absolute_issues_file_matches_runtime_path_semantics`
- `test_config_and_issues_file_are_reread_after_registration`
- `test_missing_issues_file_returns_typed_error_not_partial_list`
- `test_directory_unreadable_and_invalid_utf8_issue_files_fail_loud`
- `test_malformed_heading_and_duplicate_id_surface_existing_parser_error`
- `test_configured_issue_reader_delegates_to_runtime_issues_md_parse`
- `test_configured_issue_reader_has_no_second_heading_or_dependency_parser`
- `test_configured_issues_preserve_file_order_and_all_parser_fields`
- `test_response_includes_sha256_revision_of_exact_issue_file_bytes`
- `test_bulleted_depends_on_is_not_invented_and_warning_is_returned`
- `test_unbulleted_depends_on_is_returned_exactly`
- `test_source_status_text_never_sets_runtime_state`
- `test_issue_without_event_is_not_ingested_not_pending`
- `test_event_issue_removed_from_file_remains_in_historical_views_only`
- `test_active_event_issue_missing_from_file_blocks_control`
- `test_corrupt_inconsistent_unavailable_or_rebuilding_projection_disables_control`
- `test_api_returns_issue_text_even_when_runtime_state_is_unavailable`

Expected initial RED reason: Dashboard issue APIs currently project only event
history and do not read the registered runtime config or configured issue file.

## RED 3 — pure batch admission and deterministic ordering

Proposed file: `tests/unit/test_issue_selection.py`

Use pure inputs: parser `IssueSpec` values plus an authoritative map of
`IssueState`. No filesystem, subprocess, SQLite, or browser is needed.

Planned tests:

- `test_selected_empty_refuses_without_plan`
- `test_selected_unknown_ids_are_all_reported`
- `test_selected_duplicate_ids_refuse_without_silent_dedupe`
- `test_selected_terminal_issues_are_all_reported_and_none_run`
- `test_selected_done_dependency_need_not_be_selected`
- `test_selected_unfinished_dependency_in_selection_is_allowed`
- `test_selected_unfinished_dependency_outside_selection_refuses_whole_batch`
- `test_selected_reports_every_missing_dependency_for_every_issue`
- `test_unknown_dependency_is_unfinished_and_blocks`
- `test_dependency_absent_from_file_but_done_in_events_is_satisfied`
- `test_needs_human_or_decomposition_dependency_is_not_done`
- `test_self_dependency_reports_cycle`
- `test_multi_issue_dependency_cycle_reports_all_members`
- `test_selected_active_issue_is_included_once`
- `test_omitted_active_issue_refuses_new_selection`
- `test_dependency_order_is_topological`
- `test_file_order_breaks_topological_ties_deterministically`
- `test_run_all_includes_every_nonterminal_issue`
- `test_run_all_excludes_terminal_issues_with_state_counts`
- `test_run_all_all_terminal_is_successful_noop`
- `test_run_all_empty_file_is_successful_noop`
- `test_run_all_includes_full_nonterminal_dependency_chain`
- `test_run_all_refuses_unfinished_dependency_outside_result_set`
- `test_admission_never_reads_status_text_for_state`

Expected initial RED reason: no exact-selection planner exists; the current
orchestrator scans every projected issue in `IssueCreated` order.

## RED 4 — runtime exact allowlist and lifecycle preservation

Proposed files:

- `tests/unit/test_main_issue_selection.py`
- `tests/unit/test_loop_issue_selection.py`
- `tests/unit/test_run_lifecycle_wire_format.py`
- `tests/unit/test_no_downgrade_and_observer_exemption.py`

Planned tests:

- `test_run_cli_accepts_repeated_issue_ids_as_exact_selection`
- `test_run_cli_without_selection_preserves_existing_cli_behavior`
- `test_runtime_revalidates_selection_after_workspace_ownership_and_recovery`
- `test_runtime_selection_refusal_occurs_before_issue_activation`
- `test_runtime_selection_refusal_does_not_emit_runstarted_or_runfinished`
- `test_runtime_never_activates_unselected_pending_issue`
- `test_runtime_resumes_selected_active_issue_before_later_selected_issue`
- `test_runtime_refuses_when_active_issue_is_outside_allowlist`
- `test_runtime_selected_dependency_runs_before_dependent`
- `test_runtime_independent_selected_issues_use_file_order`
- `test_runtime_selected_queue_drained_ignores_unselected_actionable_issues`
- `test_runtime_run_all_uses_current_nonterminal_set`
- `test_runtime_run_all_zero_nonterminal_is_clean_noop`
- `test_runtime_dependency_block_is_named_not_reported_queue_drained`
- `test_one_batch_emits_at_most_one_runstarted_and_one_controlled_runfinished`
- `test_selection_does_not_change_existing_runstarted_closed_schema`
- `test_observer_and_old_logs_remain_compatible_when_schema_is_unchanged`
- `test_budget_is_shared_across_the_whole_selected_batch`
- `test_escalated_selected_issue_does_not_mark_batch_item_completed`
- `test_unprocessed_selected_issues_remain_unchanged_after_budget_stop`

Expected initial RED reason: `runtime.main run` has no selection input and
`Orchestrator._next_actionable` scans the complete projection.

## RED 5 — run-request API is strict, exact, and race-safe

Proposed files:

- `tests/dashboard/test_issue_run_api.py`
- `tests/dashboard/test_security_hardening.py`

Planned tests:

- `test_run_selected_requires_nonempty_unique_issue_ids_and_revision`
- `test_run_all_rejects_client_supplied_issue_ids`
- `test_unknown_request_fields_are_422`
- `test_oversized_issue_count_id_and_body_are_rejected_before_planning`
- `test_issue_revision_conflict_queues_nothing`
- `test_selected_refusal_returns_all_blockers_in_typed_envelope`
- `test_selected_terminal_refusal_queues_nothing`
- `test_run_all_returns_terminal_exclusion_summary`
- `test_run_all_zero_result_returns_noop_without_queue_or_process`
- `test_api_rechecks_current_event_state_not_source_status`
- `test_api_never_accepts_executable_config_or_issue_path_from_run_body`
- `test_non_loopback_host_and_origin_cannot_enqueue_run`
- `test_cors_remains_disabled_for_run_routes`
- `test_security_headers_wrap_success_and_failure_responses`
- `test_injection_shaped_issue_id_remains_data`
- `test_html_shaped_issue_text_is_escaped_in_api_consumer_contract`
- `test_run_api_does_not_persist_environment_or_secrets`

Expected initial RED reason: no run-request API or mutation model exists.

## RED 6 — one-process-per-repository FIFO queue

Proposed files:

- `tests/dashboard/test_run_queue.py`
- `tests/dashboard/test_run_launcher.py`
- `tests/dashboard/test_migrations.py`

Planned tests:

- `test_first_valid_command_for_repo_becomes_launch_candidate`
- `test_second_command_for_active_repo_is_persisted_fifo_without_spawn`
- `test_three_queued_commands_launch_in_submission_order`
- `test_different_repositories_may_each_launch_one_process`
- `test_atomic_claim_prevents_two_dashboard_workers_launching_same_command`
- `test_idempotency_key_prevents_double_click_duplicate_launch`
- `test_queue_survives_dashboard_restart`
- `test_dequeue_revalidates_issue_file_revision`
- `test_dequeue_selected_issue_now_terminal_refuses_exact_command`
- `test_dequeue_run_all_recomputes_terminal_exclusions`
- `test_dequeue_run_all_now_empty_completes_as_noop_without_spawn`
- `test_abnormal_prior_exit_pauses_later_commands_for_operator_attention`
- `test_normal_process_exit_releases_slot_then_revalidates_next_command`
- `test_lost_process_handle_never_implies_repository_is_launchable`
- `test_unresolved_runstarted_is_not_labeled_running`
- `test_unregister_with_active_process_refuses_and_does_not_orphan_control`
- `test_queue_rows_are_dashboard_owned_and_never_written_to_event_log`

Expected initial RED reason: no persistent command queue, repository-scoped
claim, or launcher ownership model exists.

## RED 7 — subprocess boundary and event-derived status

Proposed files:

- `tests/dashboard/test_run_launcher.py`
- `tests/dashboard/test_run_status.py`
- `tests/dashboard/test_app_sse_api.py`

Planned tests:

- `test_launcher_uses_configured_absolute_executable_and_canonical_config`
- `test_launcher_passes_selection_as_argv_with_shell_false`
- `test_launcher_starts_exactly_one_process_per_claimed_command`
- `test_missing_executable_is_typed_launch_failed_without_run_claim`
- `test_pre_run_runtime_exit_does_not_fabricate_runstarted_or_outcome`
- `test_new_run_is_correlated_only_after_observed_runstarted`
- `test_runtime_progress_is_derived_from_issue_and_run_events`
- `test_controlled_exit_uses_runfinished_over_process_exit_code`
- `test_abrupt_exit_preserves_no_controlled_finish_observed`
- `test_dashboard_never_synthesizes_runfinished`
- `test_diagnostics_are_bounded_and_secret_redacted`
- `test_status_changes_publish_existing_sse_refresh_signal`

Expected initial RED reason: Dashboard currently launches only observer
subprocesses and has no runtime child/status boundary.

## RED 8 — UI contracts and real-browser scenarios

Proposed automated contract files:

- `tests/dashboard/test_static_js_contracts.py`
- `tests/dashboard/test_app_shell_contract.py`

Planned tests:

- `test_configured_issues_route_and_navigation_are_registered`
- `test_issue_rows_expose_accessible_selection_controls`
- `test_select_all_targets_current_nonterminal_configured_set`
- `test_run_selected_and_run_all_have_confirmation_dialogs`
- `test_confirmation_names_repo_mode_counts_and_ordered_selection`
- `test_terminal_exclusion_summary_is_visible`
- `test_every_blocker_is_rendered_in_focusable_error_summary`
- `test_parser_depends_on_warning_is_visible_near_dependency_data`
- `test_not_ingested_and_unavailable_are_not_rendered_as_pending`
- `test_selection_survives_sse_refresh_without_selecting_new_rows`
- `test_queued_position_is_not_rendered_as_runtime_progress`
- `test_unresolved_run_uses_no_controlled_finish_observed_wording`
- `test_controls_disable_during_unavailable_or_inconsistent_state`

Required real-browser RED-to-GREEN scenarios:

- Register a valid canonical config; reject missing, invalid, and wrong-repo
  configs with focus on the complete error.
- Display mixed `NOT_INGESTED`, `PENDING`, `ACTIVE`, and terminal issues while
  contradictory source `STATUS` text does not affect state.
- Select one, multiple, and all; confirm exact ordered scope and terminal
  exclusion counts.
- Show all missing dependencies grouped by selected issue and prove no request
  was queued.
- Queue a second batch for the same repository while another repository can
  launch concurrently.
- Refresh/SSE-update during selection without losing or expanding intent.
- Verify keyboard-only operation, screen-reader names/status, focus return,
  reduced motion, forced colors, 200% text, and widths 320/768/1024/1440.
- Verify zero console errors and expected API/network responses throughout.

Expected initial RED reason: the current Issues UI is observation-only and has
no configured-file selection or run controls.

## RED 9 — crash, durability, and regression gates

Proposed targeted files:

- `tests/crash/run_control_harness.py`
- `tests/dashboard/test_run_queue.py`

Planned targeted cases:

- `test_dashboard_crash_before_spawn_leaves_command_queued_and_target_unchanged`
- `test_dashboard_crash_after_spawn_before_runstarted_never_fabricates_run`
- `test_dashboard_restart_does_not_compete_with_possibly_live_child`
- `test_runtime_crash_after_runstarted_keeps_unresolved_run_truthful`
- `test_abnormal_exit_pauses_fifo_instead_of_cascading_mutations`
- `test_next_operator_approved_launch_uses_existing_runtime_recovery`
- `test_crash_never_activates_issue_outside_exact_selection`
- `test_queue_database_recovery_never_writes_target_event_log_or_git_state`

Required unchanged regression commands after feature groups are green:

```powershell
python -m pytest tests\unit -q
python -m pytest tests\dashboard -q
python -m pytest tests\unit tests\dashboard -q
python tests\crash\harness.py "$env:TEMP\draindeck-run-control-42" 42
python tests\crash\harness.py "$env:TEMP\draindeck-run-control-1337" 1337
```

The two durability runs must retain unfiltered stdout/stderr and exit codes.
They prove regression safety only; the targeted tests settle the new control
claims.

## RED execution order

1. RED 0: accept architecture/spec boundary.
2. RED 1-2: validated config registration and read-only configured issue view.
3. RED 3: pure selection/dependency planner.
4. RED 4: runtime exact allowlist.
5. RED 5: strict API admission.
6. RED 6-7: persistent queue, single launcher, event-derived status.
7. RED 8: UI and live browser workflow.
8. RED 9: crash/durability, full suites, and adversarial review.

For each group, retain the first focused pytest output showing the intended
RED assertion. A collection/import/fixture failure does not satisfy RED.

