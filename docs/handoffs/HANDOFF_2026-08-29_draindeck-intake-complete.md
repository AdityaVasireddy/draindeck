# Handoff — Draindeck Intake v1 complete

**Branch:** `codex/draindeck-intake`

**Baseline:** `4357b4a`
**Status:** ready for user review; neither merged nor pushed.

Implemented `draindeck_intake`, an optional one-way CLI that compiles local
`Issues.md`, GitHub Issues, Jira Cloud enhanced JQL, or Linear issues to a
deterministic managed `Issues.md`. The package uses a canonical immutable model,
bounded collection, strict adapter validation, environment-only credentials,
and JSON CLI envelopes. It does not alter `src/runtime` or Doc 03.

Final verification: Intake **77 passed, 1 skipped** (Windows cannot create a
test symlink); standalone Dashboard **496 passed**; Intake compile check and
CLI help passed. The prior durability harness passed all 60 scenarios for seeds
42 and 1337. See
`docs/reviews/DRAINDECK_INTAKE_BUILD_EVIDENCE.md` for review dispositions and
the inherited clean-worktree `runtime.state` limitation that prevents combined
core-suite collection.

Next action: inspect the evidence and the final diff, then explicitly request
merge if acceptable. Do not treat provider snapshots as workflow authority
after issue IDs have entered the event log.
