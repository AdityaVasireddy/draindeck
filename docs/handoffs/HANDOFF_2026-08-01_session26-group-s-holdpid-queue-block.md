# Session Handoff — Group S hold_pid redesign applied (uncommitted); S-A′ blocked on issue-11 queue precedence

## Objective
Continue item-9's Group S (live orphan-crash witness against real StockPhotoAgent): close the
open "interpreter-shape" question (does Layer 1's leaf resolution work under the real
`claude.CMD → cmd.exe → node` production tree?) via a fresh dangling-execution fixture, while
respecting the entrypoint-scope discipline (`recover` vs `run`) written up after the session-25
overrun. Two live spawns this session exposed that the original leaf-resolution witness is
racy in two distinct ways, motivating a hold-alive redesign (`hold_pid`), and separately exposed
that the orchestrator's issue-selection logic blocks the intended fixture issue (12) behind an
already-in-flight issue (11) that hasn't exhausted its retries yet.

## Current Status
- Completed: interpreter-feasibility question resolved (Layer 1 walks descendants of the
  spawned `claude` shim's own pid, never the orchestrator's own interpreter — the orchestrator
  runs safely under `.venv`; `C:\Python314` was confirmed unable to run the orchestrator at all,
  regardless — it has `pydantic` but not `pyyaml`, and the `runtime` package isn't on its path
  there). Issue-11 and issue-12 both ingested cleanly into the event log (events 86 and 89),
  each verified with a byte-identical-prefix check on `state/events.jsonl` before/after. The
  `hold_pid` mechanism (orchestrator-spawned companion process, blocks on `sentinel_resume`,
  bounded wait for its own `hold_ready` marker before being advertised) was designed, gated in
  two review rounds, and applied to `claude_headless.py` (stays uncommitted).
- In Progress: S-A′'s gate (d) — witnessing a real, production-shape leaf (the pytest
  subprocess issue-12's acceptance criterion asks for) alive at witness time — not yet achieved.
  Two live spawns happened this session; neither actually reached issue-12 (see Outstanding
  Issues). 0 of the ≤2 authorized S-A′ attempts against issue-12 have actually been consumed.
- Blocked: issue-12 cannot be spawned until issue-11 leaves `ACTIVE` state (one more retry then
  escalation, or a deliberate manual resolution — undecided, see Open Questions).

## Decisions & Rationale
- `hold_pid` mechanism (orchestrator spawns its own companion process that blocks on
  `sentinel_resume`) — approved to replace relying on the real, ephemeral `claude`-tree leaf
  process for the witness gate, because that leaf proved racy in two independent ways this
  session (see Testing/Verification). Lives in
  `%USERPROFILE%\Projects\issue-runtime\src\runtime\engine\claude_headless.py`, inside
  `_sentinel_pause` — applied but deliberately left uncommitted.
- Bounded wait for `hold_ready` before advertising `hold_pid` in `sentinel_ready` — closes a
  write-ordering hole (a returned pid from `Popen` only proves the process was created, not that
  its blocking loop was reached). Chosen over a witness-side double-check because it guarantees
  the property once, in code, rather than requiring every future witness to remember two checks.
- Miss-cleanup default corrected to `taskkill /PID <pid> /T /F` (not writing `sentinel_resume`)
  on an S-A′ witness miss — because the entrypoint is `run`, and a silent resume-on-miss would
  let the paused issue complete and merge to `agent-work` unauthorized, the same shape as the
  session-25 overrun this project already burned once on.
- Issue-12's fixture body includes a real pytest acceptance criterion (StockPhotoAgent's own
  validation command from `config.yaml`) rather than a synthetic sleep — the goal is a
  naturally-occurring long-lived real subprocess under the production tree, not fabricated work.

## Key Files
- Plan: `%USERPROFILE%\.claude\plans\group-s-s-a-wild-toucan.md` — S-A′ hold-alive design, the
  applied diff, and the dual-witness sequence (most current plan driving next steps).
- `%USERPROFILE%\.claude\plans\polymorphic-leaping-moth.md` — earlier Group S plan; interpreter-
  feasibility resolution (orchestrator under `.venv` is safe regardless of the shape question).
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — `_sentinel_pause`
  carries the applied, uncommitted `hold_pid` diff.
- `%USERPROFILE%\Projects\issue-runtime\scratch\ingest_only.py` — untracked driver used to land
  issue-11 and issue-12 without ever constructing `Orchestrator` (so it cannot spawn/merge).
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\loop.py` — `_next_actionable` (~112-122,
  issue-selection order) and `_spawn_or_escalate` (~159-168, attempt-cap/escalation logic), both
  read in full this session to answer the queue-precedence question.
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\state\transitions.py` — `_escalation`
  (~22-27): maps a cap-hit escalation to the terminal `NEEDS_HUMAN` state.
- `%USERPROFILE%\Projects\issue-runtime\src\runtime\events\projections.py` — `attempts()`
  (~81-82): counts all executions regardless of outcome.

## Next Action
Decide the S-A′ re-plan fork before any further spawn: let issue-11 exhaust naturally (one more
retry, `11-e3`, then escalation frees issue-12 — but burns cycles and produces another unplanned
crash/residue event first) vs. force issue-11 terminal directly (undesigned this session, its
own gated decision). Before that, also review the StockPhotoAgent branch/commit state surfaced
in Outstanding Issues below — it was not touched or corrected this session.

## Knowledge Captured
- `_next_actionable` (loop.py) returns any `ACTIVE` issue unconditionally before considering any
  `PENDING` issue, regardless of ingest/dict order — an issue keeps "in flight" priority until it
  reaches a terminal state (`DONE`, or `NEEDS_HUMAN`/`NEEDS_DECOMPOSITION` via escalation).
- `attempts()` counts every execution ever spawned for an issue regardless of outcome — a
  crash-then-retry cycle consumes the same attempt budget as a clean rejection.
- Exhaustion path: `attempts >= max_attempts_per_issue` (3) → `ISSUE_ESCALATED(reason=cap-hit)`
  → `IssueState.NEEDS_HUMAN` (terminal) → removed from the selectable queue. This is the only
  mechanism found this session that frees a blocked issue for another to take its place.
- Layer 1's leaf-resolution root is the spawned `claude` shim's own pid, never the orchestrator's
  own pid/interpreter — the venv-vs-`C:\Python314` pin question does not apply to where the
  orchestrator itself runs.
- The venv redirector-stub's "extra process per invocation" behavior (previously only inferred
  from an older handoff) was directly observed live this session: `hold_proc` (spawned via
  `sys.executable` from a `.venv`-run orchestrator) itself produced a child process; both were
  reaped together by the same tree-kill.
- `adapter.checkout_branch(f"issue/{issue}", create_from=base)` (loop.py:204) is a hard
  branch reset+checkout to `base`. Any uncommitted working-tree edit made after `base` and not
  captured elsewhere is discarded by this call. Discovered this session: an Issues.md edit
  (issue-12's fixture entry) was silently discarded this way when `11-e2` was spawned, because
  `base` predates that edit. This did not affect issue-12's event-log record — `IssueCreated`
  (event 89) had already frozen the correct body/acceptance_criteria before the discard.
- Sentinel-pause misses now have two independently-observed, distinct failure modes: (1) a leaf
  resolves via the 3-poll stability check but exits before an external witness's round-trip
  catches it (`11-e1`, first attempt), and (2) the descendant chain never stabilizes at all
  within the 10s/20-poll cap (`11-e2`, this session — `leaf_worker_reason`: "leaf did not repeat
  for 3 consecutive polls within 9 poll(s) / 10.0s cap").

## Assumptions
- MED confidence: issue-12's stored `acceptance_criteria` (frozen in event 89) will still be
  used correctly by `build_prompt` whenever it's eventually spawned, despite the on-disk
  Issues.md no longer containing that entry — based on `_ingest_issues` storing the content into
  the event payload and `issue_meta` being populated from `IssueCreated` (projections.py:142-146),
  not from re-reading Issues.md. NOT independently verified by reading `context/pack.py`'s
  `build_prompt` this session.
- LOW confidence: the origin of commit `1e064817f3c1d1441685192ea8751c84064360b1`
  ("history(auto): StockPhotoAgent 2026-07-31") now sitting at the tip of `agent-work`. Its
  timestamp (2026-07-31 16:13:33 -0400) predates this session's own activity, and no `git
  commit` against StockPhotoAgent was run by me this session — but I have no direct visibility
  into what created it (a user action outside this session, or some external automated
  tooling). Discovered only while investigating why an authored Issues.md edit had disappeared.

## Testing / Verification Performed
- PASS: `claude_headless.py` AST-parses cleanly after the `hold_pid` diff was applied
  (`ast.parse` succeeded).
- PASS: `scratch/ingest_only.py` run twice under `.venv` (once for issue-11, once for issue-12),
  each time appending exactly one new `IssueCreated` event with a byte-identical prefix on the
  prior lines of `state/events.jsonl` (verified via `head`+`diff` both times).
- PASS: `hold_pid` gates (a) `sentinel_ready`/`hold_ready` present + `sentinel_resume` absent,
  (b) `hold_pid` non-null, (c) `tasklist` confirms `hold_pid` alive — all three held on the one
  live spawn that used the new design (`11-e2`).
- NOT TESTED: gate (d), the real production-shape pytest-leaf witness — zero successful
  witnesses across two distinct spawns; neither spawn actually reached issue-12, so the pytest
  acceptance criterion was never in play for either attempt.
- NOT TESTED: whether issue-12's frozen `acceptance_criteria` correctly surfaces in a future
  `build_prompt` call (see Assumptions).

## Outstanding Issues
- StockPhotoAgent is currently checked out on branch `issue/11` (tip
  `1e064817f3c1d1441685192ea8751c84064360b1`, same commit as `agent-work`'s current tip), not
  `agent-work`. The orchestrator's shutdown `finally` block (which restores `cfg.project.branch`
  on every exit path) never ran, because the orchestrator was hard-killed
  (`taskkill /T /F`) rather than exiting gracefully. `src/common/paths.py` is dirty on top of
  that commit (`11-e2`'s unfinished edit). Not restored or touched this session — next session
  should decide how to handle it before further Group S work.
- `agent-work`'s tip has advanced to `1e064817f3c1d1441685192ea8751c84064360b1`
  ("history(auto): StockPhotoAgent 2026-07-31"), one commit ahead of `b66e795` (the merge-10
  commit the prior handoff described as current). See Assumptions for what is/isn't known about
  its origin.
- An authored Issues.md edit (issue-12's fixture entry) was discarded from the working tree by
  `11-e2`'s spawn (see Knowledge Captured) — confirmed via `git show <commit>:Issues.md` on both
  `b66e795` and `1e064817f...`: neither ever contained issue-11 or issue-12; both fixture
  entries only ever existed as uncommitted working-tree edits. No functional impact on the event
  log (see Assumptions for the one open question this leaves).
- `11-e2` is dangling (`EXECUTING`, no terminal event) in `state/events.jsonl` — will be caught
  by the next `run` invocation's unconditional startup recovery exactly as `11-e1` was. No
  `refs/attempts/11/11-e2` ref exists yet — residue isn't preserved anywhere but the raw working
  tree, since `set_attempt_ref` only runs inside `_execute` after `engine.run()` returns, which
  never happened for this killed execution.

## Risks
- Re-running the `run` entrypoint without first resolving the branch/commit state above will,
  per Knowledge Captured, recover `11-e2` (another real `ExecutionCrashed` + residue event) and
  spawn `11-e3` — still not issue-12 — consuming issue-11's last allowed attempt before any
  S-A′ progress is made.

## User Constraints
- No commit without explicit per-commit authorization (standing).
- `claude_headless.py` stays uncommitted until Group S passes (standing; the `hold_pid` diff was
  applied but deliberately kept uncommitted this session).
- Entrypoint scope: `recover` only for recovery-only gated phases, never `run` (standing,
  CLAUDE.md hard rule, written up after the session-25 overrun).
- S-A′ bounded to ≤2 attempts against issue-12 specifically before falling back to the
  source-only-basis option — authorized this session; 0 of 2 have actually been consumed, since
  both live spawns landed on issue-11 instead of issue-12.
- No StockPhotoAgent commit or branch mutation without explicit authorization (standing) —
  applies directly to the branch-restore and `agent-work`-tip questions above; not acted on.

## Runtime & System State
- Commit at handoff (issue-runtime), prior to this handoff's own commit: `15af037`.
- Background processes: none currently running. Two background orchestrator runs were started
  and later hard-killed this session (`taskkill /PID 43516 /T /F` and
  `taskkill /PID 69116 /T /F`); both confirmed reaped via `tasklist` showing no matching task.
- Dev servers / ports: none started or stopped. Ollama reviewer endpoint (`localhost:11434`) not
  touched this session.
- Open branches / worktrees: StockPhotoAgent currently on `issue/11`
  (tip `1e064817f3c1d1441685192ea8751c84064360b1`), not `agent-work` — see Outstanding Issues.
- Memory files updated: none this session.

## Deferred Work
- S-A′'s actual dual witness against issue-12 — deferred until issue-11 is resolved out of
  `ACTIVE` (see Next Action / Open Questions).
- Reading `context/pack.py`'s `build_prompt` to confirm it uses `issue_meta` rather than
  re-reading Issues.md — deferred, flagged as an assumption instead.
- Investigating the origin of the "history(auto)" commit on `agent-work` — deferred, flagged as
  a low-confidence unknown.

## Open Questions
**Needs User Input**
- S-A′ re-plan fork: let issue-11 exhaust naturally (one more retry, `11-e3`, then escalation —
  frees issue-12 but burns cycles and produces another unplanned crash/residue event first), or
  force issue-11 terminal directly now (undesigned this session, its own gated decision)?
- Should StockPhotoAgent be restored to `agent-work` (and what should happen to the dirty
  `src/common/paths.py` edit and the now-unused `issue/11` branch) before any further Group S
  work?
- Is the "history(auto)" commit on `agent-work` expected/benign, or does it need investigation?

**Model Uncertainty**
- Whether `build_prompt` actually reads from `issue_meta` (projection) rather than re-reading
  Issues.md when constructing a prompt for an already-ingested issue — inferred from
  `_ingest_issues`/`projections.py`, not directly verified by reading `context/pack.py` this
  session.
- The exact origin/trigger of the "history(auto): StockPhotoAgent 2026-07-31" commit — no direct
  visibility into what created it.
