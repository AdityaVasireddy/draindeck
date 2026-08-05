# Session Handoff — issue-19's 23/24/25 decomposition consumed: 23 and 24 shipped through the live pipeline, 25 hand-merged after a turn-budget escalation
Continues from: C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-04_session32-issue19-decomposed-stockphotoagent-hygiene.md — no conflicts (that handoff decomposed issue-19 into 23/24/25 and closed out its own scope; this session is the first to actually run that queue live)

## Objective
Cold-started from issue-runtime HEAD d4135bf (verified clean) and StockPhotoAgent `agent-work` at 1c9c8d5 (verified clean), with issues 23/24/25 queued but never run. Worked under the same EXECUTOR-under-strict-gate protocol as prior sessions (raw output only, explicit go-ahead before every live `cmd_run` or repo mutation) to drain that queue via three separate live single-issue runs, investigate an escalation that occurred on the third, and land its result by an alternate path once the escalation's root cause was understood.

## Current Status
- Completed:
  - Issue 23 (extract `derive_country` helper): live `cmd_run`, shipped through the full pipeline — `ExecutionFinished` → `ValidationPassed` (26/26 tests) → `ReviewApproved` (qwen) → `CommitCreated`. Work commit `b19f0d3`, merge commit `ec888d1`. Cost $0.4729.
  - Issue 24 (route the three call sites through `derive_country`): same full pipeline. Work commit `8aa5974`, merge commit `db504eb`. Cost $0.5180. Diff touched `src/csv_generator.py` (42 lines changed, net removal — the inline Getty/Pond5 logic replaced by calls to the shared helper) and `src/utils/review_manager.py` (9 lines changed).
  - Issue 25 (unit tests pinning the unified behavior): escalated by the orchestrator's turn-budget guard before validation or review ever ran (see Outstanding Issues / Architecture Changes). Investigated read-only, then hand-merged onto `agent-work` by explicit authorization after independent verification. Merge commit `f1e816e`, second parent `2978c48` (the escalated execution's own preserved attempt-ref commit), adds `tests/test_country_derivation.py` (+79 lines, 5 tests). StockPhotoAgent `agent-work` tip is now `f1e816e`.
  - issue-runtime `NEXT.md`: appended two dated Session-33 notes (reviewer-rationale-not-persisted + `run`-has-no-per-issue-flag; and the full issue-25 hand-land record with its three-gap analysis), committed at `f5e8d75`.
- In Progress: none — every gated task this session reached a definite outcome (shipped, hand-landed, or explicitly logged as an open gap).
- Blocked: none.
- Not yet built: no fix has been written for any of the three gaps this session surfaced (see Outstanding Issues) — they are diagnosed and recorded only.

## Decisions & Rationale
- Single-issue scoping for all three live runs was done via a temporary `config.yaml` edit (`budget.max_executions_per_run` 10→1→10), working-tree only, reverted to an empty `git diff` immediately after each run, never committed — because `python -m runtime.main run` exposes only `--config`/`--skip-baseline`, no per-issue flag, and the orchestrator's `while True` loop with dependency-driven readiness would otherwise have risked cascading into the next issue in the chain within the same invocation.
- Issue 25 was landed by hand-merge rather than by fixing the underlying gap and re-running the pipeline. Rationale: the escalation's root cause is a `src/`-level engine permission-posture change (`claude_headless.py`'s `--permission-mode`/`--setting-sources` construction), which per this project's process rules is a five-gate change requiring a full 60/60-both-seeds durability harness re-run before landing — judged not worth spending this session on, given the 5 tests were already independently verified passing against the real target tree both before and after the merge.
- The hand-merge commit message and the `NEXT.md` note both explicitly flag the provenance asymmetry (no `ReviewApproved`, no `ValidationPassed` event for issue 25, unlike 23/24) rather than letting it read as a normal pipeline ship — this was an explicit instruction from Adi, not an inference.

## Key Files
- `C:\Projects\issue-runtime\NEXT.md` — Session-33 notes appended and committed (`f5e8d75`): the reviewer-rationale/run-scope-flag gap entry, and the full issue-25 hand-land record (reason, provenance asymmetry, three-gap analysis). This is the authoritative detailed record for everything in this handoff's Outstanding Issues section — read it before acting on any of the three gaps.
- `C:\Projects\issue-runtime\src\runtime\loop.py` (`_execute()`, roughly lines 197-256) — the turn-budget escalation branch that fired for issue 25: `EXECUTION_FINISHED(outcome=REJECTED)` + `IssueEscalated` emitted inline, no call to `_validate()` in that branch. Read this before touching escalation routing.
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` (`_command()`, roughly lines 242-269) — `--permission-mode acceptEdits` + `--setting-sources ""` construction; this is the root cause of the headless child's inability to self-verify via Bash. Read this before touching engine permission posture.
- `C:\Projects\issue-runtime\config.yaml` — `budget.max_executions_per_run` is back at `10` (net-unchanged from session start; each of the three temporary edits was reverted). `project.validation.commands` is unchanged, still a fixed 5-file list that does not include `tests/test_country_derivation.py`.
- `C:\Projects\StockPhotoAgent\src\csv_generator.py`, `C:\Projects\StockPhotoAgent\src\utils\review_manager.py` — issue 23/24's actual targets, now routed through the shared `derive_country` helper.
- `C:\Projects\StockPhotoAgent\tests\test_country_derivation.py` — issue 25's new test file (hand-merged, 5 tests, verified passing).

## Next Action
Cold-start re-verify both repo tips before doing anything else: issue-runtime HEAD should be this handoff's own commit SHA (see Step 3 of this session's close, not yet pasted at the time this file was written), and StockPhotoAgent `agent-work` tip should be `f1e816e`.
Done when: `git -C C:\Projects\issue-runtime rev-parse HEAD` and `git -C C:\Projects\StockPhotoAgent rev-parse agent-work` both return the expected SHAs and both `git status --porcelain --branch` calls show a clean tree — a mismatch on either means STOP before touching anything, per this project's standing cold-start protocol.

## Assumptions
- HIGH — issues 23 and 24 are correctly shipped through the real pipeline: verified directly this session via raw `state/events.jsonl` lines (`ValidationPassed`→`ReviewApproved`→`CommitCreated`→`IssueCompleted` chains for both), raw `git show --stat` on both work and merge commits, and raw pytest tails (26/26 passed) — not inferred from orchestrator stdout alone.
- HIGH — issue 25's escalation is a turn-budget artifact, not a genuine content/decomposition problem: verified by tracing the actual guarding conditional in `loop.py` (`result.num_turns >= self.cfg.engine.max_turns`), confirming `num_turns:33` against `max_turns:30` from the live transcript and config, and confirming the branch never calls `_validate()` — this is source-level verification, not inference from the taxonomy label.
- HIGH — the 5 hand-merged tests genuinely pass against the real target tree: verified twice this session via direct `pytest -v` runs (once with the file checked out standalone against pre-merge HEAD, once against the actual post-merge HEAD `f1e816e`), both `5 passed`, returncode 0.
- MED — the permission-posture gap (`acceptEdits` + empty `--setting-sources`) is the sole root cause of the child's inability to self-verify, rather than one contributing factor among several: based on reading `_command()`'s construction and cross-referencing every denied Bash call in the issue-25 transcript (15 denials, including a trivial `python -c` sanity check and one `dangerouslyDisableSandbox: true` attempt, all `user-rejected`) — strong but not exhaustively tested against every possible Bash invocation shape.
- LOW — no other issue in the current backlog (13-22, already completed in prior sessions) hit this same permission wall: not re-investigated this session; those issues shipped in session 22's live smoke before this session existed, and their transcripts were not re-read here.

## Testing / Verification Performed
- PASS: issue 23 validation — `state/artifacts/23-e1/validation/0.log` raw pytest tail, `26 passed`, event log `gate_results[0].passed: true`.
- PASS: issue 24 validation — `state/artifacts/24-e1/validation/0.log` raw pytest tail, `26 passed`, event log `gate_results[0].passed: true`.
- PASS: issue 25's 5 new tests, pre-merge — checked `tests/test_country_derivation.py` out of commit `2978c486` into the then-current `agent-work` tree (HEAD `db504eb`), ran `C:\Python314\python.exe -m pytest tests/test_country_derivation.py -v`, `5 passed`, returncode 0, then fully reverted the working tree (confirmed via `git status --porcelain --branch` showing `## agent-work` with no entries).
- PASS: issue 25's 5 new tests, post-merge — same command against the actual merge commit `f1e816e`, `5 passed`, returncode 0.
- PASS: config.yaml revert after each of the three temporary `max_executions_per_run` edits — `git diff -- config.yaml` showed empty output each time, confirmed via raw diff, not assumed.
- NOT TESTED: issue-runtime's 60/60-both-seeds durability harness — not re-run this session; no `src/` changes were made (only `NEXT.md`, a documentation file).
- NOT TESTED: issue-runtime's 117-unit test suite — not re-run this session, same reason (no `src/` changes).

## Outstanding Issues
- Headless child cannot self-verify via Bash under the current engine permission posture (`--permission-mode acceptEdits` + `--setting-sources ""` in `claude_headless.py`'s `_command()`). Manifested concretely this session: issue 25's execution attempted `pytest` (and even a trivial `python -c` sanity check) 15+ times via Bash, every attempt denied with `"This command requires approval"` / `non_execution_kind: user-rejected`, zero successful executions. Full detail in `NEXT.md`'s Session-33 issue-25 note. Not fixed this session — would be a five-gate `src/` change (60/60 durability harness re-run required).
- `config.yaml`'s `project.validation.commands` is a fixed, hardcoded file list that does not include `tests/test_country_derivation.py` (or any other newly-added test module by construction — it names files individually rather than discovering `tests/`). Consequence: even if issue 25 had reached the orchestrator's own validation gate, the new tests would not have been exercised by it. Not fixed this session.
- Turn-budget escalation is a distinct third gap chained off the permission gap: a child that cannot self-verify via Bash will predictably burn its `max_turns` budget (30) retrying and get escalated as `needs-decomposition` (via `loop.py`'s turn-budget branch) before validation is ever reached — confirmed from source this session, not inferred from the taxonomy label alone. Not fixed this session.
- Reviewer verdict rationale (the Qwen reviewer's `severity`/`feedback[]`) is not persisted anywhere retrievable after a run — only `verdict` (APPROVE/REJECT) survives into the event log. Logged as a Session-33 `NEXT.md` note; not new this session's discovery of the mechanism, but first time it's a tracked item. Not fixed.
- Issue 25 has no `ReviewApproved` or `ValidationPassed` event in the event log despite its tests now being merged onto `agent-work` — a permanent provenance asymmetry versus issues 23/24, accepted explicitly by Adi rather than resolved. Any future audit of "what shipped through the runtime" for this repo needs to account for this gap.

## User Constraints
- No live `cmd_run` / issue execution without Adi's explicit fresh go-ahead each time, scoped to the specific issue named — approval does not carry over between issues or sessions. Enforced strictly this session (three separate authorizations for 23, 24, 25).
- Raw, unsummarized terminal/event-log output required on every commit-adjacent or investigative turn — enforced throughout.
- Single-issue scoping must guarantee no cascade into the next issue in a dependency chain — satisfied via the temporary `max_executions_per_run` maneuver, reverted every time.
- No commit without explicit authorization, scoped to that specific commit — both the `NEXT.md` commit and the StockPhotoAgent hand-merge were separately, explicitly authorized this session.
- issue-runtime `src/` changes require 60/60 both seeds (42, 1337) before merge — not applicable this session, no `src/` changes made.

## Runtime & System State
- Commit at handoff (issue-runtime, master): `f5e8d75` (NEXT.md commit; this handoff file itself is committed in a separate step immediately after, per this session's explicit ordering instruction).
- Commit at handoff (StockPhotoAgent, agent-work): `f1e816e`.
- Long-lived processes: none started this session.
- Dev servers / ports: none.
- Open branches / worktrees: none created; both repos on their existing default branches (master / agent-work).
- Memory files updated: none this session.

## Deferred Work
- S-E full-nine-merge witness sweep — still only 1 of 9 merges witnessed (commit `779fb3e`, per prior sessions); untouched this session.
- Layer-2 `capture_work_liveness` movement-across-kill design question — still open since session 31, untouched this session, still awaiting Adi's design decision (long single-write target vs. close as snapshot-capability-delivered).
- Fixing any of the three gaps named in Outstanding Issues (permission posture, validation-command-list, turn-budget chaining) — all explicitly deferred pending a future gated session; the permission-posture fix in particular requires five-gate treatment (ADR-level change + 60/60 durability harness).

## Open Questions
**Needs User Input**
- [non-blocking] Which of the three Session-33 gaps (if any) to prioritize fixing next, versus continuing with S-E full-nine-merge witness or the Layer-2 design question — Adi's call, none implied by this session's work.
- [non-blocking] Layer-2 `capture_work_liveness` design direction — carried forward unresolved from session 31, still needs Adi's decision.

**Model Uncertainty**
- Whether any of the already-shipped issues 13-22 (from session 22's earlier live smoke, before this session existed) would hit the same permission-gap wall if their executions had needed to self-verify via Bash — not re-investigated this session; those transcripts were not re-read.
