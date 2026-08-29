# Draindeck Intake v1 — Build Evidence

**Status:** READY FOR USER REVIEW (2026-08-29). No merge or push was performed.

## Scope and boundary

The `draindeck_intake` package is an optional one-way preflight compiler from
local `Issues.md`, GitHub Issues, Jira Cloud, or Linear to a deterministic,
managed `Issues.md`. It has no runtime, event-log, Dashboard, or Doc 03
integration. The source boundary was mechanically checked: the diff from
baseline `4357b4a` contains no `src/runtime` or
`docs/03-state-machine-and-event-schema.md` change.

The approved local checkpoint series is `148c49f` through this final Unit 7
commit on `codex/draindeck-intake`. No dependency was added and no live
credentialed provider request was made.

## Verification performed

- `C:\Projects\Draindeck\.venv\Scripts\python.exe -m pytest tests\intake -q -p no:cacheprovider`
  — **77 passed, 1 skipped**. The skipped test is the symbolic-link rejection
  case; this Windows session does not permit symlink creation. The rejection
  branch remains covered by code review, while normal managed-output behavior
  and competing Intake lock rejection are tested.
- `C:\Projects\Draindeck\.venv\Scripts\python.exe -m pytest tests\dashboard -q -p no:cacheprovider`
  — **496 passed** (one pre-existing third-party deprecation warning).
- `C:\Projects\Draindeck\.venv\Scripts\python.exe -m compileall -q src\draindeck_intake`
  — passed.
- `C:\Projects\Draindeck\.venv\Scripts\python.exe -m draindeck_intake.cli --help`
  with the worktree `src` on `PYTHONPATH` — passed.
- The existing durability harness was run from the original checkout, whose
  ignored local `runtime.state` implementation is required by the inherited
  core harness: all 60 scenarios passed for each of seeds **42** and **1337**.
- `git diff --check` and the dedicated Intake architecture-carveout test are
  final gates for whitespace and frozen-core ownership.

## Independent review and dispositions

A fresh-context review found eight material concerns. All implementation
findings were fixed test-first: Unicode line-boundary injection is rejected or
quoted safely; incomplete HTTP reads become sanitized transport failures;
GitHub consumes a bounded run of PR-only pages; GitHub's explicit API version
is current; Jira validates `isLast` and `nextPageToken` consistency; Linear
detects truncated label connections; and managed output serializes cooperating
Intake publishers then revalidates the destination before replacement.

The remaining timeout finding was a wording issue rather than an unbounded
socket: the standard library parameter is now documented accurately as a
per-operation socket timeout, not a whole-sync deadline.

## Known inherited/environment limits

- Clean baseline commit `4357b4a` lacks tracked `src/runtime/state`, although
  tracked core tests import it. Therefore `tests\unit` and a combined
  `tests\intake tests\dashboard` collection fail in this isolated worktree
  before Intake behavior runs. Standalone Dashboard regression testing passes;
  no missing core files were copied or committed.
- `python -m build` is unavailable and the installed environment lacks the
  isolated `setuptools.build_meta` backend required for an offline wheel build.
  No build dependency was installed because the approved scope forbids new
  dependencies.
- Adjacent locking prevents concurrent cooperative Intake publication and
  destination revalidation detects changes before replacement. As with normal
  filesystem atomic replacement, it cannot forbid an uncooperating external
  writer from racing the final operating-system replacement.
