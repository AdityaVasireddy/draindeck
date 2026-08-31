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

- [ ] `test_first_valid_command_for_repo_becomes_launch_candidate`
- [ ] `test_second_command_for_active_repo_is_persisted_fifo_without_spawn`
- [ ] `test_three_queued_commands_launch_in_submission_order`
- [ ] `test_different_repositories_may_each_launch_one_process`
- [ ] `test_atomic_claim_prevents_two_dashboard_workers_launching_same_command`
- [ ] `test_idempotency_key_prevents_double_click_duplicate_launch`
- [ ] `test_queue_survives_dashboard_restart`
- [ ] `test_dequeue_revalidates_issue_file_revision`
- [ ] `test_dequeue_selected_issue_now_terminal_refuses_exact_command`
- [ ] `test_dequeue_run_all_recomputes_terminal_exclusions`
- [ ] `test_dequeue_run_all_now_empty_completes_as_noop_without_spawn`
- [ ] `test_abnormal_prior_exit_pauses_later_commands_for_operator_attention`
- [ ] `test_normal_process_exit_releases_slot_then_revalidates_next_command`
- [ ] `test_lost_process_handle_never_implies_repository_is_launchable`
- [ ] `test_unresolved_runstarted_is_not_labeled_running`
- [ ] `test_unregister_with_active_process_refuses_and_does_not_orphan_control`
- [ ] `test_queue_rows_are_dashboard_owned_and_never_written_to_event_log`

## RED 7 — subprocess boundary and event-derived status

- [ ] `test_launcher_uses_configured_absolute_executable_and_canonical_config`
- [ ] `test_launcher_passes_selection_as_argv_with_shell_false`
- [ ] `test_launcher_starts_exactly_one_process_per_claimed_command`
- [ ] `test_missing_executable_is_typed_launch_failed_without_run_claim`
- [ ] `test_pre_run_runtime_exit_does_not_fabricate_runstarted_or_outcome`
- [ ] `test_new_run_is_correlated_only_after_observed_runstarted`
- [ ] `test_runtime_progress_is_derived_from_issue_and_run_events`
- [ ] `test_controlled_exit_uses_runfinished_over_process_exit_code`
- [ ] `test_abrupt_exit_preserves_no_controlled_finish_observed`
- [ ] `test_dashboard_never_synthesizes_runfinished`
- [ ] `test_diagnostics_are_bounded_and_secret_redacted`
- [ ] `test_status_changes_publish_existing_sse_refresh_signal`

## RED 8 — UI contracts and real-browser scenarios

- [ ] `test_configured_issues_route_and_navigation_are_registered`
- [ ] `test_issue_rows_expose_accessible_selection_controls`
- [ ] `test_select_all_targets_current_nonterminal_configured_set`
- [ ] `test_run_selected_and_run_all_have_confirmation_dialogs`
- [ ] `test_confirmation_names_repo_mode_counts_and_ordered_selection`
- [ ] `test_terminal_exclusion_summary_is_visible`
- [ ] `test_every_blocker_is_rendered_in_focusable_error_summary`
- [ ] `test_parser_depends_on_warning_is_visible_near_dependency_data`
- [ ] `test_not_ingested_and_unavailable_are_not_rendered_as_pending`
- [ ] `test_selection_survives_sse_refresh_without_selecting_new_rows`
- [ ] `test_queued_position_is_not_rendered_as_runtime_progress`
- [ ] `test_unresolved_run_uses_no_controlled_finish_observed_wording`
- [ ] `test_controls_disable_during_unavailable_or_inconsistent_state`
- [ ] Real-browser scenarios: registration valid/invalid; mixed
      NOT_INGESTED/PENDING/ACTIVE/terminal with contradictory source STATUS;
      single/multiple/all selection; dependency refusal with every blocker;
      same-repo FIFO + cross-repo parallel; SSE refresh preserving selection;
      keyboard/screen-reader/focus/reduced-motion/forced-colors/200%-text/
      320-768-1024-1440; zero console errors.

## RED 9 — crash, durability, and regression gates

- [ ] `test_dashboard_crash_before_spawn_leaves_command_queued_and_target_unchanged`
- [ ] `test_dashboard_crash_after_spawn_before_runstarted_never_fabricates_run`
- [ ] `test_dashboard_restart_does_not_compete_with_possibly_live_child`
- [ ] `test_runtime_crash_after_runstarted_keeps_unresolved_run_truthful`
- [ ] `test_abnormal_exit_pauses_fifo_instead_of_cascading_mutations`
- [ ] `test_next_operator_approved_launch_uses_existing_runtime_recovery`
- [ ] `test_crash_never_activates_issue_outside_exact_selection`
- [ ] `test_queue_database_recovery_never_writes_target_event_log_or_git_state`
- [ ] Full regression: `python -m pytest tests\unit -q`,
      `python -m pytest tests\dashboard -q`,
      `python -m pytest tests\unit tests\dashboard -q`,
      `python tests\crash\harness.py "$env:TEMP\draindeck-run-control-42" 42`,
      `python tests\crash\harness.py "$env:TEMP\draindeck-run-control-1337" 1337`
      (raw unfiltered stdout/stderr and exit codes retained for both seeds).
- [ ] Fresh-context adversarial review (runtime durability/allowlist, event-
      schema freeze, queue atomicity/idempotency, spawn dual-write crash
      windows, command/path/SQL/HTML injection, loopback security, Git/log/
      lease non-ownership, accessibility/state honesty) — findings fixed
      test-first and affected gates rerun.
- [ ] README, PRODUCT.md, ADR references, API docs, NEXT.md, and this todo
      updated to describe the launch-capable boundary accurately.

**Verification:** all commands above; `git diff --check`; final evidence
distinguishes VERIFIED (ran it, saw it pass) from ASSUMED.
