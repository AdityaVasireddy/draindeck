# Session Handoff — Gap 4 shipped, issue-19 premise corrected, Gap 1 confirmed live (issue 26 shipped with its own test unrun)
Continues from: `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-05_session33-issue23-24-shipped-issue25-hand-landed.md` — no conflicts (this session's findings extend session-33's Gap 1/2/3 record with live evidence; nothing here contradicts it)

## Objective
Session-33 left three logged gaps (headless child can't self-verify via Bash; fixed validation-command list excludes new test files; turn-budget escalation) and an unresolved question about whether issue 19's decomposition was ever a real complexity assessment. This session closed the smallest gap (persist `num_turns`), corrected the issue-19 record with a source-level trace, then ran one live, deliberately self-verifying issue against StockPhotoAgent to test Gap 1 directly — and got a more serious result than expected: the issue shipped anyway, with its own acceptance test never executed by anyone in the pipeline.

## Current Status
- Completed: Gap 4 (num_turns persistence) implemented, gated, committed. NEXT.md correction for issue-19 committed. Live diagnostic run executed end-to-end on StockPhotoAgent issue 26 (shipped). Hand-verification of the shipped test file. Stale residue ref from this session's own setup mistake cleaned up.
- In Progress: none — all three tasks this session reached a committed or reported end state.
- Blocked: Gap 1 + Gap 2 fix is not started; explicitly deferred to next session as a paired five-gate item (see Next Action).

## Decisions & Rationale
- Added `"num_turns": result.num_turns` to the `common` dict in `src/runtime/loop.py` (the dict all four `ExecutionFinished` payload variants build from) rather than only the turn-budget-branch payload — so normal-exit, timeout, and crash paths also carry it, giving turn-budget pressure visibility before an issue ever escalates. Committed `8e92e87`.
- Appended a dated correction section to `NEXT.md` (append-only, no edits to prior content) rather than editing session-32/33's original text — the project's own convention is corrections-as-new-dated-sections, and doc-03/CLAUDE.md discipline treats event history as immutable, so the record norm carries over to narrative docs too. Committed `552f4b9`.
- Landed StockPhotoAgent issue 26 as a git commit (`0fbee33`) rather than a live file edit before firing the run, after the first attempt (live edit) was silently archived by the reconciler's dirty-workspace check and produced a 0-issue no-op run — see Knowledge Captured.

## Key Files
- `C:\Projects\issue-runtime\src\runtime\loop.py` — Gap-4 change, one line in the `common` dict inside `_execute` (~line 223 area, confirmed via this session's edit).
- `C:\Projects\issue-runtime\NEXT.md` — correction section appended this session, dated 2026-08-05, titled "CORRECTION: issue-19 decomposition premise (session 34)".
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — the ADR-21/ADR-22 fence (`_command()`, `_DEFAULT_PERMISSION_MODE`, `_DENY_TOOLS`); untouched this session, but this is the file next session's Gap 1 fix will need to change.
- `C:\Projects\issue-runtime\config.yaml` — `project.validation.commands` (Gap 2's fixed 5-file list); untouched this session.
- `C:\Projects\StockPhotoAgent\Issues.md` — issue 26 committed as `0fbee33` on `agent-work`.
- `C:\Projects\issue-runtime\state\artifacts\26-e1\transcript.jsonl` — full transcript of the live diagnostic run, session_id `a42c38e1-7750-420a-a830-59ee598ee264`; the primary evidence for Gap 1 confirmation.

## Next Action
Open a five-gate session to fix Gap 1 and Gap 2 together as one paired change to the ADR-21/ADR-22 engine fence in `src/runtime/engine/claude_headless.py` and the validation-command-list mechanism in `config.yaml`/its consumer — do not fix either alone.
Done when: a StockPhotoAgent issue that adds a new test file ships only after that new test file has actually been executed and passed by some verifiable mechanism (child self-run or orchestrator validation discovering it), confirmed by reading the resulting transcript/event log rather than by re-running config-driven code that can't discriminate the fix from a no-op — and the durability harness still passes 60/60 on both seed 42 and seed 1337 afterward.

## Assumptions
- HIGH confidence: Gap 4 fix is correct and complete — verified by 117/117 unit tests, 60/60 both harness seeds (independently counted, not the harness's own summary line), and first live use on issue 26 recording `num_turns:10`.
- HIGH confidence: the issue-19 decomposition-premise correction is accurate — based on a full recursive grep across all 30 `.py` files under `src/` (not the earlier two-level grep, which the reviewer flagged as potentially incomplete), showing exactly one code path writes `"needs-decomposition"`/`"decompose"`, unconditionally, whenever `result.num_turns >= self.cfg.engine.max_turns` fires — and issue 19's own `ExecutionFinished` event carries `exit_status: 0` with that taxonomy, meaning it entered that branch and no other.
- HIGH confidence: Gap 1 is real and reproducible — witnessed directly in one live transcript (4/4 pytest denials, `non_execution_kind: user-rejected`, child's own closing message asking for approval it can't receive).
- HIGH confidence: the Gap 1 + Gap 2 compound finding (issue 26 shipped with its test unexecuted) is accurate — traced through the full event chain (`ExecutionFinished` → `ValidationPassed` → `ReviewApproved` → `CommitCreated` → `IssueCompleted`) and the `ValidationPassed` event's own `gate_results` payload, which names the exact 5-file command that ran and does not include `tests/test_truncate_description.py`.
- MED confidence: the fix in commit `3548744` (`truncate_description`) is itself correct — hand-verified this session (3/3 passed), but this is one manual run under one interpreter, not the breadth of testing a real correctness review would apply.
- LOW confidence, flagged not investigated: whether `refs/attempts/_recovery/reconciler-86` really originates from issue 11's append (session dated 2026-08-01, 6-line diff matches that era, but not traced further this session).

## Knowledge Captured
- The reconciler's dirty-workspace check fires unconditionally at startup, before checkout and ingest, and cannot distinguish an operator's manual edit to a target-repo tracked file from a crashed child's uncommitted residue: it archives the dirty state to a preserved ref (`refs/attempts/_recovery/reconciler-<event_id>`) and hard-resets the tree either way. Consequence, reproduced this session: appending a new issue to `Issues.md` as a live uncommitted edit and firing `run` ingests **zero** new issues — the edit is archived-and-reset before the parser reads the file. New issues must be landed as a commit on the target repo's branch (`agent-work`) before firing a run, matching how issues 7-25 arrived historically. Not a bug — this is the dirty-workspace mechanism behaving as designed when it can't distinguish intent — but a non-obvious operational gotcha for whoever appends the next issue.
- `--permission-mode acceptEdits` + `--setting-sources ""` (ADR-21/ADR-22) blocks **all** child-initiated Bash execution, not just risky commands — a plain `pytest` invocation with no chaining was denied identically to a `cd ... && pytest ...` chained command. The only Bash call that succeeded in the issue-26 transcript was a read-only `ls`.
- Gap 1 does not always manifest as turn-budget escalation. Issues 19 and 25 (prior sessions) hit the 30-turn cap and escalated loudly. Issue 26 gave up after 4 denied attempts at only 10 turns and shipped instead — same root cause, two different failure shapes. The silent-ship shape is more dangerous: it produces no escalation signal, only a diff-reviewed, seemingly-normal commit.

## Architecture Changes
None this session beyond the one-line Gap-4 event-payload addition (see Decisions & Rationale) — no control-flow or schema changes.

## Testing / Verification Performed
- PASS: `.venv\Scripts\python.exe -m pytest tests\unit -q` — 117 passed (post Gap-4 edit).
- PASS: `tests\crash\harness.py %TEMP%\ch 42` — `ALL 60 SCENARIOS PASSED`, independently recounted via `Select-String -Pattern '^PASS'` → 60.
- PASS: `tests\crash\harness.py %TEMP%\ch 1337` — `ALL 60 SCENARIOS PASSED`, independently recounted via `Select-String` → 60.
- PASS: `git diff --unified=0 -- NEXT.md` after the correction append — exactly 1 hunk, all `+` lines, 0 deletions.
- PASS: `git diff --stat config.yaml` after reverting the `max_executions_per_run` scoping edit (both the failed first attempt and the successful second attempt) — empty output both times, confirming full revert.
- PASS: `C:\Projects\issue-runtime\.venv\Scripts\python.exe -m pytest tests\test_truncate_description.py -v` from `C:\Projects\StockPhotoAgent` — 3 passed (`test_exactly_200_chars_returned_unchanged`, `test_201_chars_truncated_to_200`, `test_short_input_returned_unchanged`), run by hand this session, out-of-band from the pipeline.
- NOT TESTED: whether the Gap-1/Gap-2 pattern reproduces on a different kind of new-file issue (only one live case observed); whether `refs/attempts/_recovery/reconciler-86`'s provenance is actually issue 11 (not traced).

## Outstanding Issues
- Commit `3548744` on StockPhotoAgent's `agent-work` shipped with `tests/test_truncate_description.py` never executed by the pipeline (neither child nor orchestrator validation ran it) — hand-verified passing this session, but that verification is a human/session-level check, not a pipeline gate. Same category as issue 25's hand-verification in session 33.
- `refs/attempts/_recovery/reconciler-86` (StockPhotoAgent repo, dated 2026-08-01, 6-line `Issues.md` diff) is a pre-existing stale residue ref, left untouched this session (out of scope), not yet cleaned up.

## Risks
- Gap 1 + Gap 2 together mean any future issue that adds a new test file can ship with that test never executed by anything except an LLM diff review (qwen) — if the fix in such a case were subtly wrong, nothing in the current pipeline would catch it before merge to `agent-work`.

## Runtime & System State
- Commit at handoff (issue-runtime, `master`): `8e92e87` (Gap 4) is the tip prior to this handoff's own commit.
- Commit at handoff (StockPhotoAgent, `agent-work`): `3548744` (issue 26 shipped) is the tip.
- No long-lived processes, dev servers, or open worktrees from this session.
- No memory files updated this session.

## Open Questions
**Needs User Input**
- [non-blocking] Should `refs/attempts/_recovery/reconciler-86` be investigated and cleaned up, or left as historical residue indefinitely? Not urgent — it doesn't affect current runs.

**Model Uncertainty**
- Whether the Gap 1 + Gap 2 fix should relax the Bash fence (allow a narrow, explicitly-scoped test-execution permission) or instead give the orchestrator's own validation step a way to discover and run new test files automatically (or both) — not analyzed this session, deferred to the five-gate opener.
