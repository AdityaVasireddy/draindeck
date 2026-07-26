# Session Handoff — Step-3 precondition #1 (real validation command) closed; two-repo session

## Objective
Close the Step-3 preconditions blocking issue-runtime's live smoke, starting with the StockPhotoAgent-side gaps. This session spanned both repos: StockPhotoAgent needed a non-vacuous, safe-to-run offline test suite before issue-runtime could point a real validation command at it.

## Current Status
- Completed: Precondition #1 (real validation command) — MET and committed on issue-runtime (`445a80a`). StockPhotoAgent's offline test suite (precondition #4's test-side) — committed there (`5880306`).
- In Progress: none.
- Blocked: Precondition #4 (baseline green) is unblocked but not met — see Next Action.

## Decisions & Rationale
- Replaced issue-runtime's stale validation command (`tests\qc\test_qc_rules.py`, 0 items collected, exit 5) with an explicit five-file command — because ADR-23 rule 2 requires named file targets, not a bare directory/glob; `pytest.ini`'s `testpaths=tests` is a discovery root, not a pin, so a future stray file or `conftest.py` could get silently swept into a bare-dir command. Lives in `C:\Projects\issue-runtime\config.yaml` under `project.validation.commands`, committed at `445a80a`.
- Used `C:\Python314\python.exe` as the absolute interpreter, not a project-local venv — because StockPhotoAgent has no `.venv`/venv directory; `C:\Python314` is the interpreter with StockPhotoAgent's `requirements.txt` actually installed (confirmed via `pip list` this session).
- Verified the command by parsing it back out of the on-disk `config.yaml` (not retyping it) and running it through `subprocess.run(cmd, shell=True)` with the same call shape as `Validator._run_once` — because a shell-escaping bug in the command string is exactly the kind of thing that looks fine typed by hand but breaks under the real invocation path.
- Deferred the commit mid-session pending explicit user confirmation, per this session's working style; committed only after a follow-up confirmation. Flagging this because it means "verified" and "committed" were briefly out of sync — worth remembering if reconstructing session timeline later.

## Key Files
- `C:\Projects\issue-runtime\config.yaml` — `project.validation.commands`, the change this session's issue-runtime commit is about.
- `C:\Projects\StockPhotoAgent\pytest.ini` — new this session (per user's summary), sets `testpaths=tests` so bare `pytest` invocations can't recurse into `scripts/debugging/`.
- `C:\Projects\StockPhotoAgent\tests\` — five test files targeted by the new validation command: `test_qc_rules.py`, `test_csv_generator.py`, `test_metadata_normalize.py`, `test_validate_batch.py`, `test_qc_engine.py`.

## Next Action
Run the real baseline-green check (Step-3 precondition #4): execute issue-runtime's `config.yaml` validation command (commit `445a80a`) **without** `--collect-only` against StockPhotoAgent (commit `5880306`), and witness a full pass — exit 0, 26 passed, not just collected. Collection-verified is not run-verified; this session only proved collection. Once that's witnessed, move to preconditions #2 (confirm Ollama is up and serving `qwen2.5-coder`, not `qwen2.5vl`) and #3 (confirm `Issues.md` is authored).

## Testing / Verification Performed
- PASS: `C:\Python314\python.exe -m pytest tests\test_qc_rules.py tests\test_csv_generator.py tests\test_metadata_normalize.py tests\test_validate_batch.py tests\test_qc_engine.py --collect-only -q` — returncode 0, 26 tests collected. Run via `subprocess.run(shell=True)` from `C:\Python314\python.exe`, cwd `C:\Projects\StockPhotoAgent`, with the command string parsed directly out of the on-disk `config.yaml` after commit.
- NOT TESTED: the actual test run (no `--collect-only`) — whether all 26 tests pass, not just collect, has not been witnessed against the on-disk config this session. Per the user's summary, StockPhotoAgent's own commit message states "26 pass, both scopes" but that was not independently re-verified in this session against the exact command now in `config.yaml`.

## Outstanding Issues
- issue-runtime's working tree carries two unrelated modified files not part of this session's work: `knowledge/.sweep/sweep.log` and `knowledge/issue-runtime/2026-07-13.md`, plus two untracked handoff docs (`HANDOFF_2026-07-24_adr22-repin-settings-fix-model-reinstate.md`, `HANDOFF_2026-07-25_session15-adr23-phase2-mechanism-landed.md`). These were deliberately left unstaged and out of this session's commit — a future `git add -A` must not absorb them into an unrelated commit.

## Deferred Work
- Preconditions #2 (Ollama/qwen2.5-coder) and #3 (Issues.md authored) — status unknown, not touched this session, deferred to next session per the precondition order.
- ADR-23 Phase 2 end-to-end differential (from session 15) remains deferred behind its three-part AND: env-witness script, precondition #4 non-vacuity, and a live-observed "before" state. This session closed #4's test-side (non-vacuous suite exists and collects), but the other two blockers (env-witness script, live-observed "before") are unchanged and still open.

## User Constraints
- Do not touch `src/` when working config-only decisions (this session's config change was explicitly config-only, per the user's framing).
- ADR-19 kill criteria are frozen and must never be tuned to dodge a verdict (standing project rule, not specific to this session).
- Keep `ANTHROPIC_API_KEY` unset so `claude -p` bills the Pro subscription, not the API (standing project rule).

## Runtime & System State
- Commit at handoff (issue-runtime): `445a80a`
- Commit referenced (StockPhotoAgent): `5880306` (per user-supplied summary this session; not independently re-verified via `git log` in this session per the handoff skill's verification boundary)
- Background processes: none started this session.
- Dev servers / ports: none.
- Open branches / worktrees: none opened this session.
- Memory files updated: none.

## Open Questions
**Needs User Input**
- None outstanding — precondition #1 confirmed closed and committed with your sign-off.

**Model Uncertainty**
- Whether the full (non-collect-only) StockPhotoAgent test run actually passes against the exact command now in `config.yaml` — this session verified collection only, not a full run, against that exact on-disk string.
- Current state of preconditions #2 (Ollama/qwen2.5-coder) and #3 (Issues.md) — not checked this session, carried forward as unknown from before this session began.
