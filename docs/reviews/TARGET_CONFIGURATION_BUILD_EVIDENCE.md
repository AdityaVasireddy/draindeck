# Dashboard-Controlled Target Configuration (ADR-29) — Build Evidence

**Status:** READY FOR USER REVIEW (2026-08-30). No merge or push was performed.

## Scope and boundary

`runtime.init.service` is the sole policy and mutation gate for controlled
target configuration writes (ADR-29, `docs/08` §5k). CLI `cmd_init` and a new
Dashboard REST surface (`/api/target-configurations*`,
`/api/repositories/{id}/configuration`) both delegate to it; neither adapter
imports `GitCliAdapter`, `WorkspaceLease`, `write_config`, or `os.replace`
directly (mechanically checked — see "Architecture boundary tests" below).
`src/runtime` outside `runtime/init/` and Doc 03 are untouched.

**Provenance note:** the `src/runtime/init/service.py` draft, the CLI/
Dashboard wiring, and the planning artifacts already existed uncommitted in
the working tree at session start, written before the planning-gate commit
sequence below. The user explicitly authorized treating that draft as
legitimate in-progress work and continuing under it, rather than discarding
and rebuilding from a clean gate. Everything from the Unit 0 commit onward
was committed by, and is attributable to, this session.

## Local checkpoint-commit series

`9c66305` (Unit 0: ADR-29 accepted, planning artifacts) through `5ac81af`
(final test addition) on `master`, `Draindeck` repository, ~13 commits.
**No merge or push has occurred.**

## Verification performed (all VERIFIED live this session, `.venv\Scripts\python.exe`)

- `pytest tests\unit -q` — **585 passed**.
- `pytest tests\dashboard -q` — **519 passed** (1 pre-existing third-party
  deprecation warning, unrelated to this change).
- `pytest tests\unit tests\dashboard -q` — **1104 passed** combined.
- `tests\crash\harness.py <dir> 42` — **ALL 60 SCENARIOS PASSED**.
- `tests\crash\harness.py <dir> 1337` — **ALL 60 SCENARIOS PASSED**.
- `git diff --check` — clean at every commit in the series.
- Real-browser verification (Chrome, against a real scratch Git repository,
  not a mock): New Target end-to-end (path entry, stack detection populating
  the validation command, preview predicting branch CREATE with the
  confirmation gate correctly blocking Apply until checked, successful apply
  creating the real branch and config file and registering the repository);
  Edit Configuration end-to-end (loading and round-tripping the exact current
  config including an advanced-only field no essential form field exposes,
  successful save, and a simulated concurrent external edit correctly
  surfacing the conflict message while leaving the concurrently-written file
  completely untouched on disk).

**Earlier in this session, `pytest` was run without the project's `.venv`
interpreter and produced misleading "passing" results against an unrelated,
independent, stale checkout on this machine
(`...\OneDrive\Documents\Issue-Runtime\draindeck-intake-worktree`) rather
than this repository.** That was caught before being reported as final and
corrected; every number in this document is from the correct interpreter
against this repository. See the session's git history for the specific
correction point if relevant.

## Real defects found and fixed this session (not merely reviewed — all fixed test-first before commit)

1. **Branch mutation ordered before the digest-conflict and environment-
   validation checks** in the pre-existing service draft — violated the
   outcome matrix's "old config and branch remain unchanged" guarantee on a
   stale digest. Fixed: digest check now precedes any Git mutation.
2. **Abandoned lease returned `WORKSPACE_LEASE_UNAVAILABLE`** instead of the
   outcome-matrix-mandated `RECOVERY_REQUIRED`. Fixed.
3. **Torn/corrupt authoritative log returned `RECOVERY_REQUIRED`** instead of
   the outcome-matrix-mandated `RUNTIME_STATE_UNSAFE`. Fixed.
4. **The CLI performed its own branch checkout and dirty-worktree check
   directly via `GitCliAdapter`**, entirely bypassing the shared service —
   ADR-29's branch-management policy was dead code for the CLI path, and the
   outcome matrix's "CLI vs Dashboard apply" row was false in practice. Fixed:
   `cmd_init` now routes fully through `apply_target_configuration`; two new
   architecture-boundary tests guard against recurrence.
5. **The spec's "detected defaults" UX had no corresponding API surface** —
   the Dashboard would have needed to reimplement stack detection and YAML
   templating/escaping in JavaScript. Fixed: added
   `GET .../detect` / `POST .../render`, both reusing the exact
   `runtime.init.detect`/`generate` modules the CLI already uses.
6. **Preview could not predict the branch effect** (`prepare_target_configuration`
   did zero Git reads), so the UI had no way to show the spec-required
   explicit branch warning before apply. Fixed: preview now performs a
   read-only branch-effect prediction; a prediction failure degrades to
   `"UNKNOWN"` rather than blocking the preview, since apply remains the sole
   authority and rechecks itself immediately before mutating.
7. **(Live-browser-found) Edit Configuration showed a "Work branch" field
   that looked editable but was silently ignored** — Edit mode always submits
   the YAML textarea directly, never the essential fields. Removed the field
   for Edit mode; the branch name shown in the warning banner is now read
   directly out of the previewed YAML text in both modes.
8. **(Live-browser-found) A genuine CSS cascade bug**: `.field { display:
   flex }` (class selector) and the browser's own `[hidden] { display: none
   }` (attribute selector) tie in specificity, so the later-loaded author
   rule silently won — a `hidden`-flagged, `.field`-classed branch-
   confirmation checkbox stayed visible and checked despite `hidden = true`
   being correctly set on the DOM node. Fixed with a `[hidden] { display:
   none !important; }` reset in `base.css`, which also protects the app's
   other pre-existing `.hidden` toggles (search listbox, execution
   transcript/diff panels) from the same latent risk — this was not
   introduced by this session, only newly exposed by it.

## Outcome-matrix coverage

Every row in `docs/30-controlled-target-configuration-outcome-matrix.md` has
a focused regression test except:

- **pre_execution_untracked baseline capture, recovery config preservation,
  and `git clean -fd` ignored-config survival** — these are pre-existing
  runtime/recovery behaviors this feature relies on but does not modify (no
  file under `src/runtime/recovery.py`, `events/log.py`'s recovery path, or
  the reconciler was touched). Not independently re-tested; regression
  coverage is the durability harness's 60/60 pass on both seeds, not a new
  ADR-29-specific test.

## Known limitation, not resolved

**Responsive-breakpoint (320/768/1024/1440 CSS-pixel) and 200%-zoom live
verification was not completed.** This browser automation environment does
not honor window-resize requests — `window.innerWidth` stayed fixed
regardless of the `resize_window` call, confirmed via direct JS inspection,
across two independently created tabs. This is a tool/environment
limitation, not a code gap: the new markup reuses the same `.field`/
`max-width`-container patterns already shipped and live-verified at those
breakpoints elsewhere in this dashboard (per
`docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`), but that is an
inference from pattern reuse, not a live pixel check on the new pages
specifically. Keyboard-only operation was not independently driven end-to-end
either (every control is a native `<input>`/`<button>`/`<textarea>`/
`<label for>`, which is keyboard-operable by construction, but this was not
proven by driving Tab/Enter/Space through the flow live).

## Independent review

No separate fresh-context reviewer agent was run. Adversarial review was
performed continuously during the build (doubt-driven-development) rather
than as a single end-of-build pass — see the eight findings above, each
caught and fixed before being trusted. The user should treat this as a
lighter review posture than a dedicated fresh-context pass and decide whether
one is wanted before merge, particularly given the safety-critical nature of
the branch/config-write mechanism.

## VERIFIED vs ASSUMED summary

**VERIFIED this session:** all automated test suites (1104 combined),
durability harness (120/120 scenarios across two seeds), `git diff --check`
at every commit, and the New Target / Edit Configuration golden paths plus
the digest-conflict remediation path, all live in a real browser against a
real Git repository with real file-system/branch assertions after each step.

**ASSUMED, not verified this session:** 320/768/1024/1440px and 200%-zoom
responsive behavior (environment limitation, above); keyboard-only operation
end-to-end; a dedicated fresh-context adversarial review pass.
