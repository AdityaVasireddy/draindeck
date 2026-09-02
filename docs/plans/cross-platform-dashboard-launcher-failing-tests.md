# Cross-Platform Dashboard Launcher: RED Test Inventory

Status: implemented — all nine tests below are GREEN against
`src/draindeck_dashboard/launcher.py`. This file is kept as the historical
RED-test inventory; see `docs/32-cross-platform-dashboard-launcher-outcome-matrix.md`
for the current implementation status.

## Test-first contract

The initial implementation commit must not be made until the tests below have
been observed failing as assertions against the absent launcher. The intended
shared implementation boundary is `src/draindeck_dashboard/launcher.py`; each
test currently asserts that this boundary exists before exercising its stated
outcome. That makes the initial failure deliberate and collection-safe.

| Test file | RED contract |
| --- | --- |
| `tests/unit/test_dashboard_bootstrap_config_boundary.py` | Launcher does not create or write target configuration and routes target configuration through the shared service. |
| `tests/unit/test_dashboard_bootstrap_consent.py` | A per-invocation explicit-consent gate precedes every install/elevation attempt. |
| `tests/unit/test_dashboard_bootstrap_platform_installers.py` | Windows, macOS, and Linux adapters choose only supported package-manager/elevation behavior. |
| `tests/unit/test_dashboard_bootstrap_recovery.py` | Partial failure is reported and retry is idempotent without automatic uninstall. |
| `tests/unit/test_dashboard_bootstrap_process_ownership.py` | Reuse, collision refusal, and stop apply only to launcher-owned processes. |
| `tests/unit/test_dashboard_bootstrap_readiness.py` | Browser launch waits for the exact loopback health-response contract. |
| `tests/dashboard/test_dashboard_run_readiness.py` | Dashboard-ready and Run-ready are independently represented. |
| `tests/dashboard/js/test_dashboard_run_readiness_ui.mjs` | The browser UI renders the independent readiness states. |
| `tests/integration/test_dashboard_launcher_fast_path.py` | Dependency-present fast path has a measurable 180-second browser-readiness target. |

## Required manual proof, not a CI substitute

`tests/manual/dashboard_launcher_launch_register_select_run.md` will be added
with implementation, not in this RED-only change. On a supported host, it uses
a disposable Git fixture and controlled safe executor to prove:

```text
launch -> Dashboard ready -> register -> select one issue -> Run selected
```

The expected evidence is exactly one queue command, one Draindeck runtime
process, and the expected `events.jsonl` lifecycle.
