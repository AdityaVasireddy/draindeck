# Session Handoff — Session 26→27 close: Path A shipped issue-11, issue-12 root-caused as a duplicate

## Objective
Continuation of session 26: finish read-only re-verification of the cold-start blockers left by
the prior handoff (unauthored `agent-work` commit, wrong branch, dangling `11-e2`), then execute
the one authorized `run` (Path A) to recover `11-e2` and exercise the native retry/ship path,
observing outcome rather than assuming it. After the run touched issue-12 unexpectedly, diagnose
why issue-12 produced two empty diffs and got escalated, without re-running anything. Scope for
this handoff commit: build repo (`issue-runtime`) only — no StockPhotoAgent commit, no commit of
the standing `hold_pid` diff.

## Current Status
- Completed: full read-only re-verification of the session-26 handoff against current tree state;
  cold-start blocker 1 (`1e06481`) diagnosed and accepted in place; one authorized `run` executed
  to completion (exit 0); issue-11 shipped via `11-e3`, merged to `agent-work` at `d663e32c`;
  issue-12's empty-diff/escalation outcome root-caused from artifacts and code, not by re-running.
- In Progress: none — session ends at a quiescent state (queue drained, no dangling execution,
  `state/events.jsonl` ends at a clean terminal event for both issue-11 and issue-12).
- Blocked: no further StockPhotoAgent `run` is authorized (Path A's go-ahead was single-use and is
  now spent, per standing constraint). Any further ADR-19 sampling needs both a fresh explicit
  go-ahead and a pool de-dup pass first (see Outstanding Issues).

## Decisions & Rationale
- Cold-start blocker 1 resolved: commit `1e06481` (`history(auto): StockPhotoAgent 2026-07-31`,
  knowledge-sweep note, `knowledge/StockPhotoAgent/2026-07-31.md` +34 lines, no code) is ACCEPTED
  IN PLACE as `agent-work`'s legitimate tip. Confirmed this session: `git show --stat 1e06481`
  touches only that one tracked knowledge file; `git check-ignore -v` on it exits 1 (tracked, not
  ignored); `git branch --contains 1e06481` lists both `agent-work` and `issue/11`. All future
  "clean agent-work" baselines must be `1e06481`, not `b66e795` — `b66e795` is stale by exactly
  this one benign commit.
- Path A (execute one `run`, let it recover `11-e2` and spawn `11-e3` natively) was chosen over
  manual escalation to preserve event-log integrity and exercise the real recovery path rather
  than hand-simulate it. Outcome exceeded the neutral prediction: `11-e3` succeeded outright
  (`ExecutionFinished` exit_status 0 → `ValidationPassed` → `ReviewApproved` → `CommitCreated`
  merge_commit `d663e32c` → `IssueCompleted`), rather than crashing again toward exhaustion.
- Issue-12 excluded from the ADR-19 sample as a byte-identical duplicate of issue-11. Verified
  this session by diffing both `IssueCreated` payloads (events 86, 89) programmatically: title and
  body strings compare equal. Verified moot-on-arrival: `git show d663e32c:src/common/paths.py`
  already contains the exact fix issue-12's body asks for (`logging.basicConfig` reading
  `[logging].log_level`), because issue-12 activated at `base_commit=d663e32c` — the merge commit
  `11-e3` itself produced. Left resting in `NEEDS_HUMAN` (`IssueEscalated`, event 109,
  `reason=duplicate-feedback`) — this is the correct terminal state for a diagnosed duplicate, not
  something to re-run.
- Ingest de-duplication gap logged as an ACCEPTED-KNOWN limitation, not something fixed this
  session: `_ingest_issues` (`src/runtime/main.py:127-148`) skips an id only if that exact id is
  already in `proj.issues` (`if spec.id in proj.issues: continue`) — there is no body/content
  hash check across ids. Issue-11/issue-12 is a live, witnessed instance of two distinct ids
  carrying an identical body.

## Key Files
- `C:\Projects\issue-runtime\src\runtime\recovery\reconciler.py` — `recover()` (lines 57-119),
  check-1 orphan handling (83-98): this is what fired on `11-e2` this run.
- `C:\Projects\issue-runtime\src\runtime\recovery\bindings.py` — `preserve_residue` (27-39,
  commits the dirty diff via `snapshot_commit` before any reset) and `check_dirty_workspace`
  (78-104, the later `reset_hard` call) — read in full this session to establish recovery
  ordering ahead of authorizing the run.
- `C:\Projects\issue-runtime\src\runtime\repo\git_adapter.py` — `snapshot_commit` (176-184,
  `git add -A` + `git commit --no-verify`, never checkout/reset/stash), `reset_hard` (203-205,
  `git reset --hard` + `git clean -fd`), `set_attempt_ref` (186-201).
- `C:\Projects\issue-runtime\src\runtime\context\pack.py` — `build_prompt` (21-61): confirms the
  full issue body (lines 26-29) and acceptance criteria (30-34) are injected into what the child
  `claude -p` session receives. This resolves the session-26 handoff's open "Model Uncertainty"
  item about whether `issue_meta` (not a re-read of `Issues.md`) feeds the prompt — confirmed by
  direct read this session.
- `C:\Projects\issue-runtime\src\runtime\main.py` — `cmd_run` (151-286, the full startup sequence:
  reap orphans → recover → checkout → health → ingest → loop) and `_ingest_issues` (127-148, the
  id-only de-dup gap cited above).
- `C:\Projects\issue-runtime\config.yaml` — reviewer endpoint/model (lines 42-54, with the
  Docker-vs-native-CLI note at 49-53) and the standing `StockAgent`/`StockPhotoAgent` name-mismatch
  comment (lines 1-3), re-read this session, still unresolved.
- `C:\Projects\issue-runtime\state\events.jsonl` — events 90-109 are this session's new activity
  (see Testing/Verification for the full sequence).
- `C:\Users\adity\.claude\projects\C--Projects-issue-runtime\memory\ollama_docker_not_native.md`
  (+ its `MEMORY.md` index entry) — written this session after an initial false-negative on
  `qwen2.5-coder:14b`'s presence.

## Next Action
Decide the post-Path-A direction: continue ADR-19 sampling with a fresh, de-duplicated issue
(requires both a new explicit `run` go-ahead — Path A's is spent — and a pool audit for further
duplicates first, per Outstanding Issues), or pursue Group S's still-outstanding gate (d), or take
the low-blast-radius `config.yaml` name-mismatch cleanup. No direction is authorized yet; this is
an open choice for the user, not a default to pick.

## Knowledge Captured
- Recovery's check-1 (`preserve_residue`) commits the exact dirty diff in place (`git add -A` +
  `git commit --no-verify` on current HEAD) *before* check-3's `reset_hard` runs — this session is
  the first production witness of that ordering against a real dirty StockPhotoAgent worktree.
  `refs/attempts/11/11-e2` (`00433c92e3...`, message `crash residue 11-e2`) was confirmed
  (`git show ... -- src/common/paths.py`) to contain both the `log_level` read and the
  `logging.basicConfig` call from the loose diff, before the workspace was reset to `1e06481`.
- `build_prompt` (`context/pack.py:26-29`) does inject the full issue body into the child's
  prompt — the previous handoff's open uncertainty about `issue_meta` vs. re-reading `Issues.md`
  is resolved: it's `issue_meta` (populated from the frozen `IssueCreated` payload), matching the
  MED-confidence assumption in that handoff.
- Ingest (`_ingest_issues`) performs no cross-issue de-duplication of any kind — only an exact-id
  check. Confirmed both by reading the code and by the issue-11/issue-12 witness: identical
  title+body under two ids each independently spawned attempts.
- The reviewer's Ollama model store lives in a Docker container (`ollama`, port 11434
  `localhost:11434`) — a separate model set from the native Windows Ollama CLI install. Verified
  this session via `docker exec ollama ollama list` and `curl http://localhost:11434/api/tags`,
  both showing `qwen2.5-coder:14b` (14.8B, Q4_K_M). An initial check against the native host CLI
  produced a false-negative for this exact model earlier in this session; the confusion is now
  captured in persistent memory (see Key Files) since `config.yaml:49-53` already documented one
  earlier occurrence of the identical mistake.
- Issue-12's own `base_commit` (`d663e32c`) is the merge commit issue-11's shipped fix produced —
  i.e., an issue can be moot at ingest time relative to another issue's fix landing between
  activation and the point it's actually picked up by the queue.

## Assumptions
- MED confidence: whether ADR-19's "attempt-1 success ≥30%" criterion should count issue-11
  (shipped on its 3rd attempt — `11-e1` crashed, `11-e2` crashed/orphaned, `11-e3` shipped) toward
  the numerator at all, or only toward the shipped denominator. Not resolved this session; the
  definition itself is ambiguous and is carried forward as an open question rather than decided
  unilaterally.

## Testing / Verification Performed
- PASS: Path A `run` executed to completion, exit code 0. Full stdout captured: `[recovery]
  crashed orphans: ['11-e2']` → `[recovery] reset workspace to 1e064817f3c1` → `[startup] checked
  out agent-work` → `[health] reviewer: reachable at http://localhost:11434` → `[ingest] 0 new
  issue(s); 11 total in queue` → `[done] queue drained` → `[metrics] executions_this_run=3
  proxy_dollars_this_run=$0.5414` → `[shutdown] restored agent-work`.
- PASS: event sequence 92-109 read verbatim from `state/events.jsonl`: `ExecutionCrashed(11-e2)`
  → `ExecutionSpawned(11-e3)` → `ExecutionFinished(11-e3, exit 0)` → `ValidationPassed(11-e3)` →
  `ReviewApproved(11-e3)` → `CommitIntent`/`CommitCreated(merge_commit=d663e32c)` →
  `IssueCompleted(11)` → `IssueActivated(12, base=d663e32c)` → `ExecutionSpawned(12-e1)` →
  `ExecutionFinished(12-e1, start==end==d663e32c)` → `ValidationPassed` → `ReviewRejected("diff is
  empty")` → `ExecutionSpawned(12-e2)` → `ExecutionFinished(12-e2, start==end==d663e32c)` →
  `ValidationPassed` → `ReviewRejected` → `IssueEscalated(12, reason=duplicate-feedback,
  needs-human)`.
- PASS: `refs/attempts/11/11-e2` (`00433c92e3...`) exists post-run and contains the loose
  `paths.py` diff (`log_level`/`basicConfig` both present via `git show ... -- src/common/paths.py
  | grep`).
- PASS: `refs/attempts/12/12-e1` and `refs/attempts/12/12-e2` both resolve to `d663e32c` itself
  (`git show --stat` on each shows the merge-11 commit, no additional tree delta) — confirms both
  attempts were truly empty diffs, not partial/lost work.
- PASS: `src/common/paths.py` at `d663e32c` (`git show d663e32c:src/common/paths.py`) already
  contains the `logging.basicConfig`/`log_level` fix — issue-12's described bug was already fixed
  at its own base commit.
- PASS: issue-11 and issue-12 `IssueCreated` payloads (events 86, 89) compared programmatically —
  `title` and `body` strings are exactly equal; only `acceptance_criteria` differs (issue-12 adds
  a pytest command unrelated to logging).
- PASS: post-run StockPhotoAgent state — `branch --show-current` → `agent-work`; `status --short`
  → clean (no output); `rev-parse agent-work issue/11 HEAD` → `agent-work`=`HEAD`=`d663e32c`,
  `issue/11`=`1d62e920...` (stale, unchanged by this run — no longer the checked-out branch).
  Cold-start blocker 2 from the prior handoff (wrong branch) is resolved as a side effect of this
  run completing cleanly through its `finally`-block branch restore.
- NOT TESTED: whether duplicate issues exist elsewhere in the backlog id-space beyond the
  witnessed 11/12 pair — no pool-wide audit performed this session.
- NOT TESTED: Group S gate (d) (production-shape pytest-leaf witness) — untouched this session,
  carried forward unchanged from the prior handoff.

## Outstanding Issues
- Issue-12 sits in `NEEDS_HUMAN` (event 109) as a diagnosed-but-structurally-unaddressed
  duplicate — correct resting state given this session's root cause, but the underlying gap (no
  ingest-side de-duplication) is not fixed, so the same pattern can recur for any other duplicate
  entry still in the backlog source.
- The `hold_pid` diff in `src/runtime/engine/claude_headless.py` remains applied, uncommitted, and
  unchanged this session — carried from session 26. Gate (d) (a real production-shape leaf witness
  under Group S) is still not achieved; no attempt was made against it this session.

## Risks
- Any future StockPhotoAgent `run`, once separately re-authorized, will ingest whatever
  `Issues.md`/event-log state exists at that time. Since ingest has no de-dup (see Decisions), if
  other duplicate bodies exist under distinct ids in the pool, the same wasted-attempt +
  escalation pattern witnessed on 11/12 will repeat unless the pool is audited first.

## Technical Debt
- Ingest de-duplication gap in `_ingest_issues` (`main.py:127-148`) — intentional-scope gap in the
  v1 design (id-only idempotency, no content-hash check), not introduced this session, but now
  empirically confirmed load-bearing since it produced one wasted escalation (issue-12) this
  session.

## User Constraints
- No commit without explicit per-commit authorization (standing).
- `claude_headless.py`'s `hold_pid` diff stays uncommitted until Group S passes (standing,
  restated this session; not touched).
- No StockPhotoAgent commit of any kind this session — scope was explicitly build-repo-only.
- Path A's `run` go-ahead was single-use and is now spent — no further StockPhotoAgent `run`
  without a fresh, separately explicit go-ahead (standing constraint, restated).

## Runtime & System State
- Commit at handoff (`issue-runtime`), prior to this handoff's own commit: `c0333d2`.
- Background processes: none running. The one background task this session (Path A's `run`,
  task id `biwjmfot1`) completed on its own with exit code 0; nothing left to kill.
- Dev servers / ports: none started or stopped. Ollama reviewer endpoint (`localhost:11434`,
  served by the Docker container `ollama`) confirmed reachable this session, not modified.
- Open branches / worktrees: StockPhotoAgent is on `agent-work` at `d663e32c`, worktree clean
  (verified this session, see Testing/Verification). `issue/11` branch still exists at its old
  tip `1d62e92056ea8c9823ca21368a1c54ab7fc05a7b`, now stale/unused.
- Memory files updated: `C:\Users\adity\.claude\projects\C--Projects-issue-runtime\memory\
  ollama_docker_not_native.md` (new) and its `MEMORY.md` index entry (new).

## Deferred Work
- Pool-wide audit for further duplicate issues beyond the witnessed 11/12 pair — deferred, not
  started this session.
- Group S gate (d) — deferred, untouched this session, carried unchanged from session 26.
- `config.yaml` `StockAgent`/`StockPhotoAgent` name-mismatch residual (lines 1-3) — deferred,
  low-blast-radius cleanup, not touched this session.

## Open Questions
**Needs User Input**
- ADR-19 accounting: does issue-11 (shipped on its 3rd attempt) count toward the "attempt-1
  success ≥30%" numerator, only toward the shipped denominator, or neither? Unresolved.
- Post-close direction: continue ADR-19 sampling with a fresh, pool-audited/de-duplicated issue
  (needs a new explicit `run` go-ahead), pursue Group S gate (d) next, or do the
  `config.yaml` name-mismatch cleanup first? None of these is authorized yet.
