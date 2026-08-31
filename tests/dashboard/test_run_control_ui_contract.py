"""ADR-30 RED 8: static-markup/structural contracts for the selection/run-
control UI. Interactive behavior (checkbox selection, select-all targeting,
confirmation-dialog content, error-summary population, SSE-refresh selection
preservation, keyboard/focus/reduced-motion/forced-colors/200%-text/
responsive widths, zero console errors) is verified live in a real browser
per docs/plans/dashboard-issue-run-control-failing-tests.md RED 8's
"Required real-browser RED-to-GREEN scenarios" -- see
docs/reviews/DASHBOARD_ISSUE_RUN_CONTROL_BUILD_EVIDENCE.md for that
evidence. This file locks the static contract these behaviors depend on
into the regular suite, mirroring test_app_shell_contract.py's convention.
"""
from __future__ import annotations

from pathlib import Path

_JS_DIR = Path(__file__).parents[2] / "src" / "draindeck_dashboard" / "static" / "js"
_RUN_CONTROL_SOURCE = (_JS_DIR / "pages" / "run-control.js").read_text(encoding="utf-8")
_DIALOG_SOURCE = (_JS_DIR / "components" / "dialog.js").read_text(encoding="utf-8")


def test_issue_rows_expose_accessible_selection_controls():
    assert 'type: "checkbox"' in _RUN_CONTROL_SOURCE
    assert '"aria-label"' in _RUN_CONTROL_SOURCE
    assert "disabled: isTerminal" in _RUN_CONTROL_SOURCE  # a terminal row cannot be selected at all


def test_select_all_targets_current_nonterminal_configured_set():
    assert "run-control-select-all" in _RUN_CONTROL_SOURCE
    assert "_TERMINAL_STATES.has(issue.state)" in _RUN_CONTROL_SOURCE


def test_run_selected_and_run_all_have_confirmation_dialogs():
    assert "openDialog" in _RUN_CONTROL_SOURCE
    assert "Confirm run" in _RUN_CONTROL_SOURCE
    # both actions route through the same confirmAndSubmit/openDialog path --
    # neither can mutate without it.
    assert "confirmAndSubmit" in _RUN_CONTROL_SOURCE


def test_confirmation_names_repo_mode_counts_and_ordered_selection():
    for token in ("Repository", "Mode", "Issues to run", "Terminal exclusions", "Run-level budget"):
        assert token in _RUN_CONTROL_SOURCE, f"confirmation dialog is missing {token!r}"


def test_terminal_exclusion_summary_is_visible():
    assert "excludedLines" in _RUN_CONTROL_SOURCE
    assert "plan.excluded" in _RUN_CONTROL_SOURCE


def test_every_blocker_is_rendered_in_focusable_error_summary():
    assert 'tabindex: "-1"' in _RUN_CONTROL_SOURCE
    assert "summary.focus()" in _RUN_CONTROL_SOURCE
    assert 'role: "alert"' in _RUN_CONTROL_SOURCE
    for field in ("unknownIds", "duplicateIds", "terminalSelected", "blockers", "cycleMembers", "omittedActiveIds"):
        assert field in _RUN_CONTROL_SOURCE, f"error summary never reports {field!r}"


def test_parser_depends_on_warning_is_visible_near_dependency_data():
    assert "parserWarning" in _RUN_CONTROL_SOURCE
    assert "Depends-On" in _RUN_CONTROL_SOURCE


def test_not_ingested_and_unavailable_are_not_rendered_as_pending():
    assert '"chip chip--"' not in _RUN_CONTROL_SOURCE  # (a literal typo-guard; real check below)
    assert "NOT_INGESTED" in _RUN_CONTROL_SOURCE and "UNAVAILABLE" in _RUN_CONTROL_SOURCE
    # the state chip renders issue.state verbatim -- never a hardcoded "PENDING"
    # substitution for either presentation state.
    assert '"PENDING"' not in _RUN_CONTROL_SOURCE.replace('_STATE_TONE', '')


def test_selection_survives_sse_refresh_without_selecting_new_rows():
    assert "root.__runControlSelection" in _RUN_CONTROL_SOURCE
    assert "export async function refresh" in _RUN_CONTROL_SOURCE
    # refresh() never does `new Set()` -- only render() (a real navigation) does.
    render_start = _RUN_CONTROL_SOURCE.index("export async function render")
    refresh_start = _RUN_CONTROL_SOURCE.index("export async function refresh")
    assert "new Set()" in _RUN_CONTROL_SOURCE[render_start:refresh_start]
    assert "new Set()" not in _RUN_CONTROL_SOURCE[refresh_start:]


def test_queued_position_is_not_rendered_as_runtime_progress():
    assert "queuePosition" in _RUN_CONTROL_SOURCE
    assert "renderQueue" in _RUN_CONTROL_SOURCE
    # the queue section never imports or renders workflow outcome vocabulary
    assert "RunFinished" not in _RUN_CONTROL_SOURCE and "RunStarted" not in _RUN_CONTROL_SOURCE


def test_unresolved_run_reuses_the_canonical_no_controlled_finish_wording():
    """ADR-30 review blocker 1: run-control.js now DOES render a runtime
    outcome for a COMPLETED (process-exit-0) queue command -- process-exit
    facts and runtime workflow outcome must be shown as two distinct axes,
    never one implying the other. It reuses format.js's own canonical
    `runDisplayOutcome`/`NO_CONTROLLED_FINISH_TEXT` (the same helper the
    event-derived /runs endpoint already uses) rather than a second,
    hardcoded copy of the wording, so an unresolved run is never labelled
    "Running" here either."""
    format_source = (_JS_DIR / "format.js").read_text(encoding="utf-8")
    assert "no controlled finish observed" in format_source
    assert "no controlled finish observed" not in _RUN_CONTROL_SOURCE  # never hardcoded a second time
    assert "runDisplayOutcome" in _RUN_CONTROL_SOURCE  # reuses the canonical helper


def test_controls_disable_during_unavailable_or_inconsistent_state():
    assert "controlsDisabled" in _RUN_CONTROL_SOURCE
    assert 'data.readModelStatus !== "READY"' in _RUN_CONTROL_SOURCE


def test_dialog_component_is_keyboard_trapped_and_returns_focus():
    assert "Escape" in _DIALOG_SOURCE
    assert "Tab" in _DIALOG_SOURCE
    assert "previouslyFocused" in _DIALOG_SOURCE
    assert 'role: "dialog"' in _DIALOG_SOURCE
    assert '"aria-modal"' in _DIALOG_SOURCE


def test_no_innerhtml_or_inline_style_in_run_control_or_dialog():
    for source, name in ((_RUN_CONTROL_SOURCE, "run-control.js"), (_DIALOG_SOURCE, "dialog.js")):
        assert "innerHTML" not in source, f"{name} must never assign innerHTML"
        assert ".style." not in source and "style:" not in source, f"{name} must not set inline style"
