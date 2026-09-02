# Cross-Platform Dashboard Launcher Outcome Matrix

Status: implemented. The shared, testable implementation is
`src/draindeck_dashboard/launcher.py`, invoked through the tracked entry
points `Start-DraindeckDashboard.cmd` (Windows), `Start-DraindeckDashboard.command`
(macOS), and `start-draindeck-dashboard.sh` (Linux). Every outcome below
has a corresponding automated test (see
`docs/plans/cross-platform-dashboard-launcher-failing-tests.md` for the
mapping) except L-14, which is the opt-in manual proof at
`tests/manual/dashboard_launcher_launch_register_select_run.md`.

## Scope and ownership

The target-runtime configuration source of truth is exactly
`<target-repository>/.draindeck/config.local.yaml`. The launcher must never
write it. Creation or modification is owned exclusively by
`runtime.init.service.apply_target_configuration()`.

The launcher must not create `dashboard.local.yaml`. Dashboard process values
(loopback host, port, Dashboard SQLite location, and Draindeck executable) are
constructed in memory from explicit launcher arguments. PID, log, SQLite
files, and the recorded process's startup-generation timestamp
(`startedAtEpochSeconds`, used only to detect a normal not-yet-listening
startup window per L-15) are operational state, never a second target
configuration source.

## Outcomes

| ID | Given | When | Then |
| --- | --- | --- | --- |
| L-01 | A target configuration is absent or needs update | The launcher starts | It performs no target-config write; only the shared target-configuration service may publish `.draindeck/config.local.yaml`. |
| L-02 | The launcher is started | It prepares Dashboard settings | No persistent `dashboard.local.yaml` is created. |
| L-03 | Prerequisites are missing | The operator declines the displayed install manifest | No install, elevation, model pull, or server start occurs. |
| L-04 | The operator consents to a displayed manifest | A system package is required | The supported OS adapter invokes only its package manager and requests elevation only for that package operation. |
| L-05 | A supported package manager is absent or unsupported | Installation is requested | The launcher reports a recoverable, actionable failure without attempting an untrusted fallback. |
| L-06 | A system, Python, or model step fails partway through | The launcher exits or is rerun | It reports the failing step, retains diagnostic state, never uninstalls packages automatically, and resumes idempotently. |
| L-07 | A healthy launcher-owned Dashboard already exists | The launcher starts again | It reuses that process and starts no duplicate server. |
| L-08 | Another process occupies the desired port | The launcher starts | It never kills or trusts that process; it reports the port collision and does not open a browser. |
| L-09 | The launcher starts a Dashboard child | It opens a browser | The child is alive, listening on the expected loopback address, and `GET /api/health` returns HTTP 200 with exactly `{"status":"ok"}`. |
| L-10 | Dashboard dependencies work but Claude, Ollama, or the model is unavailable | Dashboard health succeeds | Dashboard is marked ready and Run is marked not ready with the failing prerequisite; no false success claim is made. |
| L-11 | The compatible environment, tools, model, and prior healthy `.venv` are present | The fast-path launcher is invoked | The verified Dashboard-ready browser-open path completes within 180 seconds; cold install reports progress but has no time guarantee. |
| L-12 | A path or target-repository-derived value contains shell metacharacters | The launcher invokes tools | Arguments are passed as an argv vector, never interpolated into a shell command. |
| L-13 | A stop or status request names a PID | The launcher acts on it | It affects only a validated launcher-owned PID. |
| L-14 | A supported host has completed dependency setup | The manual smoke runs | The operator launches the Dashboard, registers a disposable fixture repo, selects one issue, runs it, and observes one command, one runtime process, and the expected `events.jsonl` lifecycle. |
| L-15 | A launcher-owned Dashboard was just started (fresh startup-generation timestamp, recorded PID alive) but has not yet bound its port | The launcher starts again during that window | It never treats this as a free port to start a duplicate; it waits, bounded by the remaining 180s startup-readiness contract and outside the operation lock, for the already-starting child to become verifiably ready, then reuses it. An expired or legacy (no-timestamp) record is never granted this trust -- it falls through to normal start logic without touching the recorded PID. |

## Consent and readiness contract

Before every system-install attempt, the launcher must show the exact missing
items, source, and command and receive affirmative consent for that invocation.
Windows invokes `winget` as the current user and lets package UAC prompt if
needed. macOS invokes Homebrew and permits its terminal `sudo` prompt only
after consent. Linux detects `apt`, `dnf`, `pacman`, or `zypper` and validates
interactive `sudo` only after consent. The Dashboard/runtime itself never runs
elevated. Claude sign-in and a large Ollama model pull remain separate,
explicitly confirmed interactive actions.

The browser wait is satisfied only by L-09. External reviewer readiness is
reported separately from Dashboard readiness.
