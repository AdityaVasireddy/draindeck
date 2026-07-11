# NEXT

## Resume point
Session 3 complete AND verified on Windows. The git boundary is real:
`RepositoryAdapter` + `GitCliAdapter` (object-DB `merge_to`), the three
reconciler seams bound via `recovery/bindings.py` (checks 2 and 3 no longer
SKIPPED), and the kill-9 harness rebuilt on a real temp git repo. See doc 11.

Verified THIS session (Windows, git 2.53.0, `.venv` python):
- 58/58 unit tests (`python -m pytest tests\unit -q`).
- 50/50 harness scenarios on seeds 42 AND 1337
  (`python tests\crash\harness.py %TEMP%\ch [seed]`).
- Mutations M1 (lazy preserve_residue → I-m red) and M2 (drop clean -fd →
  test_reset_hard_removes_untracked red) both confirmed to fail, then reverted.
- Also fixed a real Windows bug in the harness: cp1252 console couldn't encode
  `→`/`—`; it now forces UTF-8 on stdout/stderr.

## Verify commands (updated)
- Unit: `python -m pytest tests\unit -q`  (expect 58)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 50;
  self-calibrates its kill window. Uses a real temp git repo per scenario, so
  it is minutes, not seconds. `... %TEMP%\ch 42 <point>` filters to one crash
  point for fast iteration.)

## Still open (pre-Phase-1-gate config gaps, not blockers)
- Fill `project.validation.commands` in config.yaml with StockAgent's real test
  command; resolve StockAgent vs StockPhotoAgent directory name (config.example
  still carries the ⚠ note).
- `delete_attempt_refs` (ADR-15 GC) is implemented but not wired — belongs to
  the orchestrator's post-IssueCompleted step.

## Session 4 (per doc 07 ordering)
Engine wrapper (`engine/claude_headless.py`) as a concrete class (ADR-08):
spawn `claude -p` in the workspace, enforce max_turns/timeout, ADR-18 env
hygiene (strip ANTHROPIC_API_KEY in subscription mode). Provisional interface
sketch in doc 11 §4. The orchestrator loop can reuse the harness worker's
`step()` shape with real seams substituted (engine at EXECUTING, validation at
VALIDATING, reviewer at REVIEWING, merge_to behind the I3 gate).
