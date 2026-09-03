# ULTRA-REVIEW-001: Launcher Review Fixes — Outcome Matrix

Status: **planning gate only**. This document, together with
`docs/plans/ultra-review-001-launcher-fixes-failing-tests.md`, is the
approved pre-implementation gate for the six unique launcher-review
findings tracked as `Issues.md` issue `ULTRA-REVIEW-001`. Finding 7 from
the review is a duplicate of finding 2 and has no separate row here.

**No `src/` file has been changed to produce this document.** Every row
below is backed by a RED test (failing for a genuine behavioral reason,
not a collection/import error) already committed to the working tree and
run live — see the failing-test inventory for the exact test names and
`tasks/todo.md`/the final report for raw output. Implementation is
explicitly out of scope until the user approves this gate.

## Scope

All six findings are inside `src/draindeck_dashboard/` (the Dashboard
launcher and its UI) — the cross-platform one-click launcher documented in
`docs/32-cross-platform-dashboard-launcher-outcome-matrix.md`. No finding
touches `src/runtime`, and this gate makes no launcher *behavior* change
(RED tests observe current behavior; none of them are wired into any
default-run suite that would flip CI red — see "Test placement" below).

## Outcome matrix

| ID | Given | When | Then |
| --- | --- | --- | --- |
| F-01 | Ollama's `GET /api/tags` returns syntactically valid JSON shaped nothing like `{"models": [{"name": ...}, ...]}` (`[]`, `null`, or a `models` array whose entries aren't dicts) | The Dashboard checks whether a repository's configured reviewer model is present (`GET /api/launcher/readiness?repoId=...`) | The endpoint reports the reviewer model as not present (`runReady: false`, `"reviewer-model"` in `missing`) with a normal 200 response — never an unhandled exception / 500. |
| F-02 | A repository's configured Ollama endpoint is slow or unreachable | The Dashboard's readiness probe (`check_reviewer_model_present`) is checking that repository's reviewer model | The synchronous network probe never blocks the asyncio event loop — every other concurrent request the Dashboard process is serving (health checks, SSE, unrelated API calls) stays responsive for its own normal latency, independent of how long the probe takes. |
| F-03 | `stop_dashboard` has just proven ownership of a launcher-owned Dashboard process via a fresh identity-token round-trip, and that process exits on its own (crash, external signal, self-shutdown) in the narrow window before `terminate()` actually runs | The operator (or `--stop`) requests the Dashboard be stopped | `POSIX os.kill`'s resulting `ProcessLookupError` is treated as "already stopped," not leaked as an unhandled traceback; the stale `launcher-state.json` record is still cleaned up (unlinked), exactly as it would be for a normal `STOPPED` result. |
| F-04 | A PID that is invalid, zero, negative, or equal to the internal "unverified port occupant" sentinel (`-1`) is present anywhere a termination decision is made — including via a corrupted/legacy `launcher-state.json` | The launcher resolves what to do about its recorded process (`--stop`, or the `RESTART_STALE_OWNED` path in `_spawn_dashboard_under_lock`) | That PID is refused/validated before ever reaching `os.kill` — POSIX `os.kill(pid, sig)` for `pid <= 0` targets an entire process **group**, not the intended single process, so a corrupted-state PID must never reach it unguarded. |
| F-05 | The launcher builds its missing-prerequisite manifest on macOS (Homebrew) | A formula install (`ollama`, `git`) vs. the Claude Code **cask** install (`brew install --cask claude-code`) is shown to the operator | Elevation messaging correctly distinguishes the two: a Homebrew **formula** install is reported as not needing elevation (Homebrew's own no-sudo design), and the Claude Code **cask** install — the one item here that can actually prompt for elevation — is reported as may-prompt-elevation. |
| F-06 | An operator opens the reviewer-model "Pull configured reviewer model" confirmation dialog, or the run-control "Confirm run" dialog | They click that dialog's "Cancel" button | The dialog closes (its backdrop is removed, focus returns), exactly like every other confirmation dialog in the Dashboard (`confirmAndAcknowledge`, `confirmAndCancel`, `confirmAndResume` in `pages/run-control.js`, which already wire `onClick: () => close()` on their own Cancel/Keep buttons). |

## Root-cause locations (for the implementation gate, not fixed here)

| ID | File(s) |
| --- | --- |
| F-01 | `src/draindeck_dashboard/launcher_readiness.py` — `check_reviewer_model_present` (its `except` clause omits `AttributeError`, which a malformed-shape body raises from `body.get(...)`/`entry.get(...)`). |
| F-02 | `src/draindeck_dashboard/app.py` — `async def launcher_readiness(...)` (calls `evaluate_repository_run_readiness` synchronously, no `run_in_threadpool`/`asyncio.to_thread`); `src/draindeck_dashboard/launcher_readiness.py` — `check_reviewer_model_present` (blocking `urllib.request.urlopen`). |
| F-03 | `src/draindeck_dashboard/launcher.py` — `stop_dashboard`, `_cmd_stop`, `terminate_process` (POSIX branch: bare `os.kill(pid, signal.SIGTERM)`, no `ProcessLookupError` handling). |
| F-04 | `src/draindeck_dashboard/launcher.py` — `terminate_process` (no PID validation, unlike `is_process_alive`'s explicit `pid <= 0` guard); `_spawn_dashboard_under_lock`'s `RESTART_STALE_OWNED` branch (calls `terminate_process(existing.pid)` with an unvalidated, disk-loaded PID). |
| F-05 | `src/draindeck_dashboard/launcher_install.py` — `detect_missing_prerequisites` (`may_prompt_elevation=installer.package_manager != "brew" or name != "claude"`). |
| F-06 | `src/draindeck_dashboard/static/js/components/shell.js` — `_confirmAndPullReviewerModel`'s "Cancel" action spec (no `onClick`); `src/draindeck_dashboard/static/js/pages/run-control.js` — `confirmAndSubmit`'s "Cancel" action spec (same bare shape). |

## Test placement (why the bare verify command still passes)

`pyproject.toml`'s `[tool.pytest.ini_options]` sets
`testpaths = ["tests/unit", "tests/intake"]`, so a bare
`python -m pytest` never collects `tests/dashboard/` at all (this is
already true of the ~763 pre-existing Dashboard tests, run instead via
`python -m pytest tests/dashboard -q`, per `NEXT.md`'s own verify
commands). All eleven new RED tests for this gate (nine Python + two JS,
one Python file covers F-03 and F-04 together) are therefore placed under
`tests/dashboard/` — genuinely failing when run explicitly, without
flipping the bare gate command red. See the failing-test inventory for
the exact list and the final report for live RED output from both
`python -m pytest` (unaffected, 841 passed / 3 skipped, unchanged from
baseline) and the explicit RED-test run.
