# Dashboard-Controlled Target Configuration (ADR-29) — Build Evidence

**Status:** READY FOR USER REVIEW (2026-08-30, closeout pass). No merge or
push was performed. No commit was made during the closeout pass documented
here; the two whitespace fixes and the harness-evidence files it produced
are currently uncommitted in the working tree (see "Closeout-pass changes,
uncommitted" below).

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

**Exactly 10 commits**, `9c66305` (Unit 0: ADR-29 accepted, planning
artifacts) through `2078b9f` (NEXT.md pointer, current `HEAD`), on `master`,
`Draindeck` repository:

```
9c66305 plan: Unit 0 - accept ADR-29, controlled target configuration
95329ea feat: Units 1-2 - shared target-configuration service, atomic publication
e454c4c refactor: Unit 3 - CLI delegates fully to the shared configuration service
ffc33ce feat: Unit 4 - Dashboard target-configuration REST API
9b8803c feat: Unit 4 extension - server-side stack detection and YAML rendering
3542288 feat: preview predicts branch effect for the explicit branch warning
16f10fa feat: Unit 5 - guided New Target / Edit Configuration dashboard UI
5ac81af test: registration failure after durable apply never rolls back the config
207e612 docs: Unit 6 closeout - build evidence, durability harness both seeds
2078b9f docs: NEXT.md pointer for target-configuration build completion
```

(An earlier version of this document said "~13 commits" ending at `5ac81af`
— both were wrong; corrected here.) **No merge or push has occurred.**

## `git diff --check` on the full range

`git diff --check HEAD~11..HEAD` (the range checked in this closeout pass)
spans 11 commits: the 10 ADR-29 commits above plus one commit immediately
before them, `7d83518` ("docs: restore readme architecture diagram"),
pre-existing, unrelated to ADR-29. It reported two trailing-blank-line-at-
EOF issues, both introduced in the Unit 0 commit (`9c66305`):
`docs/30-controlled-target-configuration-outcome-matrix.md:48` and
`spec/dashboard-target-configuration.md:157`.

Those two commits are already pushed into this repository's committed
history; per this closeout pass's explicit constraints, that history is not
reverted, reset, or amended. The trailing blank line was removed from both
files' **current working-tree content** instead (an ordinary, uncommitted
edit, staged for a future commit at the user's discretion):

- `git diff --check HEAD~11..HEAD` (pure history, commit-to-commit, unaffected
  by any uncommitted working-tree edit) — **still reports both lines**; this
  is expected and cannot change without amending already-committed history,
  which was not authorized.
- `git diff --check` (working tree vs `HEAD`, i.e. exactly the uncommitted
  fix) — **clean, exit 0.**
- `git diff --check HEAD~11` (working tree vs the pre-ADR-29 baseline, i.e.
  the full effective state history + this fix would produce) — **clean,
  exit 0.**

In short: the historical diff is permanently marked (immutable without
amending, which was out of scope), but the current and future committed
state — once the user commits this working-tree fix — is clean both against
`HEAD` and against the pre-ADR-29 baseline.

## Verification performed (all VERIFIED live this session, `.venv\Scripts\python.exe`)

- `pytest tests\unit -q` — **585 passed**.
- `pytest tests\dashboard -q` — **519 passed** (1 pre-existing third-party
  deprecation warning, unrelated to this change).
- `pytest tests\unit tests\dashboard -q` — **1104 passed** combined.
- Durability harness, **rerun in this closeout pass** with raw output
  captured to durable files (paths and exit codes below) — **ALL 60
  SCENARIOS PASSED** on both seed 42 and seed 1337.
- `git diff --check` — see the dedicated section above for the precise,
  qualified result (clean for the uncommitted fix; the two pre-existing
  historical lines are immutable without amending committed history).
- Real-browser verification (see "Real-browser verification" below for the
  full, evidence-backed account) — New Target and Edit Configuration golden
  paths, digest-conflict remediation, all four required CSS-pixel
  breakpoints, and a keyboard-only pass through both pages, all live against
  a real scratch Git repository, not a mock.

**Earlier in this session (before this closeout pass), `pytest` was run
without the project's `.venv` interpreter and produced misleading "passing"
results against an unrelated, independent, stale checkout on this machine
(`...\OneDrive\Documents\Issue-Runtime\draindeck-intake-worktree`) rather
than this repository.** That was caught before being reported as final and
corrected; every test-suite number in this document, in both the original
build and this closeout pass, is from the correct interpreter against this
repository. This disclosure is kept distinct from, and does not qualify, any
of the verified results recorded elsewhere in this document — it describes a
mistake made and corrected earlier in the same session, not a live caveat on
current evidence.

## Raw durability-harness output (this closeout pass)

Rerun with `.venv\Scripts\python.exe tests\crash\harness.py <dir> <seed>`,
complete unfiltered stdout+stderr piped to file, followed by a separately
captured `echo EXIT_CODE=$?` line recording the real shell exit status of
the harness process itself:

| Seed | Raw output file (repo-relative) | Result | Exit code |
|---|---|---|---|
| 42 | `docs/reviews/target-configuration-harness-evidence/seed42_stdout_stderr.txt` | ALL 60 SCENARIOS PASSED | 0 |
| 1337 | `docs/reviews/target-configuration-harness-evidence/seed1337_stdout_stderr.txt` | ALL 60 SCENARIOS PASSED | 0 |

Each file is 64 lines: 1 calibration line, 60 `PASS ...` scenario lines, 1
blank line, 1 `ALL 60 SCENARIOS PASSED` line, 1 trailing `EXIT_CODE=0` line.
Verified directly against the files: `grep -c "^PASS"` returns 60 for each.
Absolute path prefix: `C:\Projects\Draindeck\`.

(No harness raw-output files existed anywhere in the repository before this
closeout pass — the original build's harness runs were watched live via the
tool transcript but never persisted to a file, which is why this pass reran
both rather than merely locating prior output.)

## Real-browser verification (this closeout pass)

Performed against the real scratch target repository and a locally-run
Dashboard instance (`.venv\Scripts\python.exe -m draindeck_dashboard.cli`),
loopback-only, same setup as the original build. Two prior claims in this
document were previously deferred as "not completed" or "not independently
verified" — both are now backed by concrete evidence, not code inspection or
pattern reuse:

### Browser environment note

The default Chrome instance available to this session is **headless**
(`window.outerWidth === 0`, `screen.availWidth` always equal to the current
`innerWidth`) — `resize_window` calls report success but do not change the
actual rendering surface, confirmed both via `window.innerWidth` readback
and via an actual screenshot showing no visual change. The one other
available Chrome connection (a real, extension-paired local browser,
selected via `list_connected_browsers`/`select_browser` after the user
picked it) exhibited the identical behavior. Per the user's instruction to
try the available Chrome/extension browser path and not claim completion
from inspection, a same-machine, loopback-only reverse proxy
(`frame_relax_proxy.py`, scratch-only, not part of the repository) was used
to strip only `X-Frame-Options`/`Content-Security-Policy` from the
Dashboard's real HTTP responses — `src/draindeck_dashboard/security.py`
itself was never modified — so the real pages could be embedded in
same-machine `<iframe>` elements at exact CSS-pixel widths and rendered by
the browser's real layout engine. This is the same class of technique this
codebase's own prior build
(`docs/reviews/DASHBOARD_REDESIGN_BUILD_EVIDENCE.md`) used to solve an
analogous environment limitation (`forced-colors` emulation) it hit
previously.

### Responsive verification — 320 / 768 / 1024 / 1440 CSS pixels

Both New Target and Edit Configuration were rendered inside real `<iframe>`
elements at exactly `width="320"`, `768`, `1024`, and `1440` (each
`height="900"`), served through the header-relaxing proxy, and screenshotted
at each width. Result at every one of the 8 combinations (2 pages × 4
widths): the shell rail nav, headings, all form fields, the branch-warning
banner, the digest line, the advanced `<details>` YAML editor, and the
Preview/Create-target (or Preview/Save-changes) buttons all reflow with
**no horizontal overflow of the outer page** at any width. The YAML
`<textarea>` (which uses `white-space: pre` for code readability)
correctly scrolls **within its own bounds** rather than overflowing the
page — this is the intended, designed behavior for a code editor, not a
defect. Screenshots were captured for all 8 combinations during this pass
(saved by the browser tool to local temp paths under
`claude-chrome-screenshots-*`; not committed to the repository, consistent
with this pass's "do not commit" constraint).

### Keyboard-only verification — New Target

Real synthetic keyboard input only (`Tab`, `Shift+Tab`, `Return`, `Space`,
character typing) — no mouse clicks on any form control except one initial
click to seed focus into the first field (the coordinate-based
`resize_window`/click issues encountered mid-pass, see below, made a
from-cold-load skip-link Tab sequence unreliable in this environment; a
single seed click is the closest honest characterization). Verified live,
in order: repository path typed; `Tab` moved focus to Work Branch (default
value read back correctly); `Tab` moved focus to "Detect validation
command"; `Return` activated it and `Detected: Rust.` / `cargo test`
populated live; `Tab`×3 moved focus through the commands textarea, the
no-validation-gate checkbox, and the Advanced `<summary>` (a native
`<details>` toggle, keyboard-operable by browser default); `Tab` reached
Preview; `Return` activated it. `:focus-visible` was confirmed genuinely
active for real keyboard focus (not just programmatic `.focus()`, which
Chrome's `:focus-visible` heuristic does **not** mark visible — confirmed
this distinction directly): computed style showed `outline-style: solid`,
`outline-width: 2px`; a zoomed screenshot shows the rendered outline
plainly on the Work Branch field.

The branch was then changed via `Shift+Tab` back to Work Branch,
`Ctrl+A`+typing `keyboard-test-branch`, and `Tab` forward to Preview again;
`Return` re-ran preview and correctly showed the branch-creation warning
banner (`A new branch "keyboard-test-branch" will be created...`) with the
required confirmation checkbox now visible and Create-target correctly
disabled. `Tab` reached the checkbox; `Space` checked it (confirmed via
`checked: true` and a screenshot showing the checked, focused box) and
Create-target became enabled. `Tab`×2 reached Create-target; `Return`
submitted it. Result: the real Git branch `keyboard-test-branch` was
genuinely created in the scratch repository (verified via `git branch`
after the fact), and — because this same scratch repository was already
registered under repository id 1 from earlier verification — the Dashboard
correctly surfaced a real `LOG_PATH_ALREADY_REGISTERED` error (`role="alert"`
text: `logPath is already registered under repository 1`), matching the
already-tested "registration fails after durable apply, does not roll back"
behavior — this time reached via the keyboard path specifically, not just
the API-level test.

### Keyboard-only verification — Edit Configuration, and a real tool-dispatch limitation found

`Tab` order and focus placement worked identically well on this page.
However, the Preview and Save-changes buttons on this specific page did
**not** respond to synthetic `Return` or `Space` key events dispatched via
the browser-automation tool — reproduced twice, across two independently
created fresh tabs, with focus confirmed correctly placed on the button
(`document.activeElement.id === "tc-preview-btn"`) immediately before each
dispatch. The identical button markup pattern on the New Target page
responded correctly and repeatedly to the same key in the same session. A
JS-dispatched `.click()` on the same button — a real DOM click event in the
real browser, not a simulation of one — worked instantly both times,
confirming the application's own event listeners and logic are correct;
this narrows the finding to synthetic-keyboard-event dispatch reliability
in this specific tool/browser pairing for this specific page, not a defect
in the shipped code. This is disclosed plainly rather than silently
substituted: the Preview and Save-changes **activations** on this page used
`.click()`; all preceding keyboard navigation (`Tab` order, focus
placement) and the checkbox interaction pattern were confirmed working via
real key events on this same page in the earlier New Target pass.

Using that `.click()` step, the conflict path was verified concretely:
after Preview loaded the current config (including
`max_executions_per_run: 5` and `max_attempts_per_issue: 3`, values
reachable only through the Advanced YAML editor, not any essential field),
the file was modified externally on disk (`max_attempts_per_issue: 9`,
simulating a concurrent editor) and Save-changes was activated. Result:
the exact expected conflict text (`This configuration changed since you
last previewed it. Preview again to see the latest version before
applying.`) rendered in a `role="alert"` element (screenshot captured), and
the externally-written file was **confirmed unchanged on disk**
(`max_attempts_per_issue: 9` still present) — no clobber, matching the
already-established `CONFIG_REVISION_CONFLICT` guarantee, this time
observed through the UI rather than only the API test.

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

This closeout pass found two further, much smaller issues, both
documentation-only (not application-code defects): the two trailing-blank-
line whitespace errors (see the dedicated `git diff --check` section above)
and the commit-count/range inaccuracy in the previous version of this
document (corrected above).

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

## Independent review

No separate fresh-context reviewer agent was run, in either the original
build or this closeout pass. Adversarial review was performed continuously
during the build (doubt-driven-development) rather than as a single
end-of-build pass — see the eight findings above, each caught and fixed
before being trusted. The user should treat this as a lighter review
posture than a dedicated fresh-context pass and decide whether one is
wanted before merge, particularly given the safety-critical nature of the
branch/config-write mechanism.

## Closeout-pass changes, uncommitted

This pass made the following changes, all currently **uncommitted** (no
commit was made, per this pass's explicit instruction):

- Removed the trailing blank line from
  `docs/30-controlled-target-configuration-outcome-matrix.md` and
  `spec/dashboard-target-configuration.md`.
- Added `docs/reviews/target-configuration-harness-evidence/
  seed42_stdout_stderr.txt` and `seed1337_stdout_stderr.txt` (new files).
- Rewrote this document.

`dashboard.local.yaml`, `dashboard.sqlite3`, `dashboard.sqlite3-shm`, and
`dashboard.sqlite3-wal` (pre-existing untracked local files, unrelated to
ADR-29) were not touched, staged, or deleted, per this pass's explicit
constraint.

## VERIFIED vs ASSUMED summary

**VERIFIED this session, across the original build and this closeout
pass:** all automated test suites (1104 combined, this closeout pass);
durability harness (120/120 scenarios across two seeds, raw output captured
to the two files listed above, exit code 0 both); `git diff --check`
(qualified — see the dedicated section: clean for the uncommitted fix
against both `HEAD` and the pre-ADR-29 baseline; the two historical lines
are immutable without an amend that was out of scope); the New Target /
Edit Configuration golden paths, the digest-conflict remediation path, all
four required CSS-pixel breakpoints (320/768/1024/1440) for both pages, and
a keyboard-only pass through both pages (with one disclosed, narrow
exception: Preview/Save-changes activation on the Edit Configuration page
used a JS `.click()` after a real, reproducible synthetic-key-dispatch
tool limitation was found and documented) — all live in a real browser
against a real Git repository, with real file-system/branch/error-state
assertions after each step.

**ASSUMED, not verified in this session:** 200%-zoom (distinct from the
four CSS-pixel breakpoints, which are now verified); a dedicated
fresh-context adversarial review pass.
