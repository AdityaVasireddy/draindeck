# Session Handoff — Step-3 live smoke: first real run against StockPhotoAgent

## Objective
Run the first-ever live end-to-end Step-3 smoke test — the real `cmd_run` entrypoint
against the real `StockPhotoAgent` target repo — after a read-only precondition sweep
confirmed all five of Step 3's own preconditions mechanically satisfied. The underlying
question: does the whole system (checkout → recovery → health checks → ingest → the
orchestrator loop → commit-on-approval) actually work end-to-end against a real repo,
not just in unit tests or scratch dry-runs, and at what attempt-1 rate and cost.

## Current Status
- Completed: Live smoke ran to completion (exit 0). 5/5 real `StockPhotoAgent` issues
  drained, each on attempt 1, each independently cross-checked against `agent-work`'s own
  git history (not taken from engine/reviewer self-report). Proxy cost $0.3106/shipped
  issue. NEXT.md and `docs/14-session6-phase2-gate.md` updated with full evidence and two
  new filed follow-up items. Handoff (this file) written.
- Completed: Two follow-up items filed — a fix-before-Phase-2 defect (working tree left
  on the last issue's attempt branch after a clean drain) and a named-but-not-blocking gap
  (orphan-crash recovery path still never witnessed).
- Blocked: Nothing is blocked. The reviewer (relayed by Adi) is reviewing the NEXT.md /
  docs/14 diffs before authorizing a commit — per standing rule, no commit happens until
  that explicit authorization arrives.

## Decisions & Rationale
- **Branch-restore defect classified fix-BEFORE-Phase-2, not file-and-defer** — because
  Phase-2 is a supervised metric-capture run, and a deterministic dirty-tree-at-rest
  breaks the "work lives on `agent-work`, tree is on `agent-work`" assumption any observer
  or crash-recovery makes. This is the same harness-masking shape (a startup reset hiding
  an uncleaned prior end-state) that ADR-20 Amendment 1 already closed for the ingest
  branch-check gap — the same discipline applies: fix it, and re-run the full durability
  harness (60/60 both seed 42 and seed 1337) in the implementing session, not a
  drive-by one-liner. Decision made by the reviewer this session; recorded in
  `docs/14-session6-phase2-gate.md` §2.9 and `NEXT.md` §2 item 8.
- **Orphan-crash recovery gap filed as named-not-blocking, not fix-before-Phase-2** —
  because nothing has actually broken; every run to date (including this one) is
  happy-path only, so this is an absence of evidence, not evidence of a problem. It must
  not be carried silently as "works," but it does not gate Phase-2 the way the
  deterministic branch-left-dirty defect does. Recorded in `NEXT.md` §2 item 9.
- **Working tree deliberately left on `issue/5` (not restored to `agent-work`)** — per
  explicit instruction, so the defect could be filed from the observed dirty state rather
  than a healed one. Do not `git checkout agent-work` in `C:\Projects\StockPhotoAgent`
  without new instruction; that would destroy the evidence trail for the filed defect.
- **A green live-smoke run does not, by itself, count as an ADR-19 verdict** — restated
  explicitly in NEXT.md §1 and doc 14 §2.9 because `experiment.sample_size` is 20 and this
  run was n=5; this is a positive smoke signal consistent with the kill-criteria
  thresholds, not a pass of the kill-criteria itself.

## Key Files
- `C:\Projects\issue-runtime\docs\14-session6-phase2-gate.md` §2.9 (new section, added
  this session) — full evidence: precondition sweep results, exact run command, raw
  stdout, the attempt-1/cost table, the event-log↔git-ref cross-check table, the
  root-cause trace for the branch-restore defect (with the two `checkout_branch` call
  sites and both candidate exit-path code blocks quoted), and the classification
  rationale.
- `C:\Projects\issue-runtime\NEXT.md` §1 (current gate, rewritten this session), §2 items
  7 (marked resolved), 8 (new — branch-restore defect), 9 (new — orphan-recovery gap), §6
  (pointer index, new line added).
- `C:\Projects\issue-runtime\src\runtime\loop.py:204` — `self.adapter.checkout_branch(f"issue/{issue}",
  create_from=base)`, inside `_commit_sequence`; the per-issue checkout with no matching
  restore call anywhere in the codebase. This is the root cause of the surface-3 defect.
- `C:\Projects\issue-runtime\src\runtime\loop.py:98-110` — `Orchestrator.run()`'s own exit
  path (bare `while True`, returns the moment the queue drains); one candidate location
  for the eventual fix.
- `C:\Projects\issue-runtime\src\runtime\main.py:189` — the step-5b startup checkout of
  `cfg.project.branch`; confirmed this only runs at startup and therefore masks the
  *previous* run's dirty end-state at the *start* of the *next* run — it does not fix the
  end-state itself.
- `C:\Projects\issue-runtime\src\runtime\main.py:250-262` — `cmd_run`'s own code after
  `orch.run()` returns; the other candidate fix location, currently only prints metrics
  and returns, touches nothing branch-related.
- `C:\Projects\issue-runtime\state\events.jsonl` — the raw event log from this run (45
  events, run_id `run-20260727T134427Z`); the primary evidence artifact the reviewer ruled
  from. Note this resolves cwd-relative (via bare `Path(cfg.event_log.path)` in
  `cmd_run`), not joined with `cfg.project.repository` — it lives under `issue-runtime`,
  not under the target repo, which was itself a small correction made mid-session (the
  reviewer's draft command initially assumed the opposite location).

## Next Action
Implement the surface-3 fix — restore `cfg.project.branch` in the normal-exit path
(`Orchestrator.run()`'s return in `loop.py`, or `cmd_run`'s teardown after `orch.run()`
returns in `main.py`) — and re-run the full durability harness to 60/60 on both seed 42
and seed 1337 in that same session, before proceeding to Phase-2. This is blocked on
nothing except being picked up; it does not require new user input to start, though the
implementation itself will need the reviewer's approval before commit, per the standing
no-commit rule.

## Testing / Verification Performed
- PASS: Live smoke run itself — exit code 0, `[health] baseline green`, `[ingest] 5 new
  issue(s)`, `[metrics] executions_this_run=5 proxy_dollars_this_run=$1.5532`.
- PASS: Event-log↔git-ref cross-check — all 5 `CommitCreated.merge_commit` hashes
  independently confirmed reachable from `agent-work` via direct `git log`/`git
  rev-parse`, not taken from engine or reviewer self-report.
- PASS: Precondition sweep (validation command, Ollama model at the correct Docker
  endpoint, `Issues.md` existence/format, target repo branch/cleanliness, `.gitignore`
  hygiene) — all five read-only-verified immediately before authorization.
- NOT TESTED: Orphan-crash recovery path — no crash occurred this run; this remains
  entirely unwitnessed (see Risks).
- NOT TESTED: The surface-3 fix itself — not yet implemented, so the durability harness
  has not been re-run against it this session.

## Outstanding Issues
- **Working tree left on the last processed issue's attempt branch after a clean drain,
  not on `cfg.project.branch`.** Manifested this session: `git status --porcelain=v1
  --branch` on `C:\Projects\StockPhotoAgent` read `## issue/5` after the run completed,
  confirmed deterministic (not incidental) by tracing both `checkout_branch` call sites
  and finding no restore call in either `Orchestrator.run()`'s or `cmd_run`'s exit path.
  `agent-work` itself is unaffected and correct (its tip matches the event log exactly) —
  this is a workspace-state defect, not data loss. Classified fix-BEFORE-Phase-2 (see
  Decisions & Rationale). Full trace: doc 14 §2.9; filed as NEXT.md §2 item 8. Currently
  left in its dirty state (`issue/5` checked out) intentionally — do not heal without new
  instruction.

## Risks
- **Orphan-crash recovery path has never been positively witnessed.** Every run to date,
  including this session's live smoke, is happy-path only (no crash occurred), so the
  reconciler's reap/no-double-commit behavior remains untested against a real fault. If a
  `claude -p` execution is killed mid-run in production before this is deliberately
  witnessed, the actual recovery behavior is unknown, not merely unverified-but-presumed-
  fine. Filed as NEXT.md §2 item 9 (named, not blocking Phase-2, but must not be carried
  silently as "works").

## User Constraints
- No commit without explicit per-commit authorization (standing project rule) — nothing
  was committed this session; `NEXT.md` and `docs/14-session6-phase2-gate.md` remain
  modified-but-uncommitted pending the reviewer's ruling on the diffs, then Adi's explicit
  go-ahead.
- Do not run a second live smoke, and do not manually check out `agent-work` in the
  target repo — the current dirty state (`issue/5` checked out) is the evidence for the
  filed surface-3 defect and must be preserved until the reviewer/user says otherwise.

## Runtime & System State
- Commit at handoff: `ebad895` (unchanged this session — no new commits made).
- Working tree (`issue-runtime`): `NEXT.md` and `docs/14-session6-phase2-gate.md`
  modified, not staged/committed (`git status --porcelain=v1` showed exactly these two
  files as ` M`).
- Background processes: none currently running. The live smoke run itself was launched
  via a backgrounded shell command this session and has already completed (exit code 0,
  observed via its task-completion notification and by reading its output file); nothing
  is left running.
- Target repo (`C:\Projects\StockPhotoAgent`): working tree currently checked out on
  `issue/5` (intentionally left, see User Constraints), `agent-work` at `cf5cd8c`
  (confirmed via `git rev-parse agent-work` this session), 5 new commits on `agent-work`
  from this run (`fa1aa56`, `7789ba1`, `974e912`, `2995ca5`, `cf5cd8c`, each a `merge N`
  commit produced by the runtime's own commit-on-approval logic, not a manual action).
- Memory files: none updated this session.

## Open Questions

**Model Uncertainty**
- The mangled `�` character observed in the captured stdout's `[done]` line (in place of
  what is almost certainly an em-dash, given the event log correctly stores `\u2014` at
  the same logical position) is assumed to be a console-codepage/UTF-8 capture artifact.
  This was not independently root-caused this session (e.g. by checking the actual
  codepage of the shell that captured the background task's output) — flagging as an
  assumption, not a verified cause.
