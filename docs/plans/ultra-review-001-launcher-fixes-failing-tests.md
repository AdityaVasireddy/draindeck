# ULTRA-REVIEW-001: Launcher Review Fixes — RED Test Inventory

Status: **RED, planning gate only**. Every test below has been run live
against the current, unmodified `src/` and observed failing for a genuine
behavioral reason (a wrong assertion outcome, or — for F-03 — an
uncaught, leaked `ProcessLookupError` traceback), never a collection or
import error. See `docs/35-ultra-review-001-launcher-fixes-outcome-matrix.md`
for the corresponding outcome-matrix rows and root-cause locations, and
the final report for the raw pytest/node output this inventory summarizes.

No `src/` file has been changed. No commit, merge, or push has been
performed.

## Test-first contract

`python -m pytest` (bare) is unaffected by every file in this table:
`pyproject.toml`'s `testpaths = ["tests/unit", "tests/intake"]` already
excludes all of `tests/dashboard/` (see NEXT.md's own separate
`python -m pytest tests\dashboard -q` verify command for the ~763
pre-existing tests there). Every new RED test below lives under
`tests/dashboard/`, deliberately, so it is genuinely collected and run via
`python -m pytest tests/dashboard -q` (Python) or the existing
`tests/dashboard/test_static_js_contracts.py` Node wrapper (JS), while
never flipping the bare verify command.

| Finding | Test file | Test(s) | RED contract |
| --- | --- | --- | --- |
| F-01 | `tests/dashboard/test_launcher_readiness_malformed_ollama_response.py` | `test_readiness_endpoint_does_not_500_on_malformed_but_valid_ollama_json` (parametrized: `[]`, `null`, wrong-item-shapes, `models` not a list) | `GET /api/launcher/readiness?repoId=...` must not return HTTP 500 when Ollama's `/api/tags` returns valid-but-malformed-shape JSON. |
| F-02 | `tests/dashboard/test_launcher_readiness_event_loop_blocking.py` | `test_launcher_readiness_ollama_probe_does_not_block_concurrent_requests` | A concurrent, unrelated `GET /api/health` must stay responsive (< 0.2s) while `GET /api/launcher/readiness` is blocked inside a slow (0.4s) synchronous Ollama probe. |
| F-03 | `tests/dashboard/test_launcher_stop_kill_safety.py` | `test_stop_dashboard_survives_a_posix_identity_check_to_kill_race_and_cleans_up_state` | A `ProcessLookupError` raised by `terminate()` after ownership was already proven must not propagate out of `_cmd_stop`, and the stale `launcher-state.json` must still be cleaned up. |
| F-04 | `tests/dashboard/test_launcher_stop_kill_safety.py` | `test_terminate_process_never_calls_os_kill_with_an_invalid_pid` | `terminate_process(pid)` for `pid` in `{0, -1, -4242}` must never call `os.kill` with that PID. |
| F-04 | `tests/dashboard/test_launcher_stop_kill_safety.py` | `test_spawn_under_lock_never_terminates_the_unverified_occupant_sentinel_pid` | A `launcher-state.json` recording `pid: -1` (colliding with `_resolve_process_action`'s own internal unverified-occupant sentinel) must never reach `terminate_process` via `_spawn_dashboard_under_lock`'s `RESTART_STALE_OWNED` path. |
| F-05 | `tests/dashboard/test_launcher_install_homebrew_elevation.py` | `test_homebrew_elevation_correctly_distinguishes_formula_from_cask` | On Homebrew, `ollama`/`git` (formula installs) must report `may_prompt_elevation=False`; `claude` (the `--cask claude-code` install) must report `may_prompt_elevation=True`. |
| F-06 | `tests/dashboard/js/test_dialog_cancel_wiring.mjs` (via `tests/dashboard/test_static_js_contracts.py`) | `testReviewerModelDialogCancelCloses` | Clicking "Cancel" in the reviewer-model pull confirmation dialog (`components/shell.js`) must close it. |
| F-06 | `tests/dashboard/js/test_dialog_cancel_wiring.mjs` (via `tests/dashboard/test_static_js_contracts.py`) | `testRunControlConfirmDialogCancelCloses` | Clicking "Cancel" in the run-control "Confirm run" dialog (`pages/run-control.js`) must close it. |

Supporting file (not a test itself): `tests/dashboard/js/dom_shim.mjs` — a
minimal, self-contained DOM shim (project convention: see
`test_dashboard_run_readiness_ui.mjs`/`test_proxy_cost_render.mjs` for the
lighter single-file precedent) so the F-06 tests drive the REAL,
exported `mountLauncherReadiness`/`render` entry points end-to-end
(real click handlers, real `openDialog` close mechanics), not a
reconstruction of the dialog wiring under test.

## Genuine-RED confirmation

Each test above was run individually and in its file group with
`python -m pytest tests/dashboard/test_launcher_*.py -v` / `node
tests/dashboard/js/test_dialog_cancel_wiring.mjs` and observed to fail on
the specific assertion documented in its own docstring/inline comment —
never on an `ImportError`, `ModuleNotFoundError`, or collection error. The
F-03 test's failure is a leaked `ProcessLookupError` traceback itself
(the exact defect described in finding 3), not an `assert` line — this is
intentional: the raw traceback IS the RED evidence for "must not leak a
traceback."

`python -m pytest` (bare) was re-run after adding every file in this
table and remained unchanged at **841 passed, 3 skipped** (the pre-change
baseline), confirming the placement choice above holds.
