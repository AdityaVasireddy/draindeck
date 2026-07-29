# Session Handoff — item-9 start-state setup on StockPhotoAgent + a critical reconciler finding (design gate next, not a run)

## Objective
Bring StockPhotoAgent to a valid starting state for item 9's real-target fault-injection
run (orphan-crash recovery, previously unwitnessed against the real target) without
actually running it. Every step this session was reviewer-gated and held at a
setup-only boundary (no ingest, no `cmd_run`, no crash sequence) — StockPhotoAgent is a
high-blast-radius target per CLAUDE.md and requires Adi's explicit go-ahead before any
real run. Mid-session, tracing `recover()`'s code surfaced a mechanism (below) that must
be understood before the crash step can be safely authored.

## Current Status
- Completed: StockPhotoAgent landed on `agent-work`, clean, with `Issues.md` holding
  exactly the 3 issues (7/8/9) intended for the fault-injection run, all three verified
  unfixed on `agent-work` via `git show`. The session-24 handoff doc was committed in
  issue-runtime (commit `6421530`).
- In Progress: nothing mid-flight — this document is this turn's only action.
- Blocked: the actual item-9 fault-injection run is blocked on (a) tracing
  `recover()`'s dirty-workspace check against a real crashed execution (not yet done —
  see Risks) and (b) Adi's explicit authorization for the real-target run.

## Decisions & Rationale
- Discarded 2 of an originally-drafted 3 issues (a "submissions inserted with no
  review/fail guard" claim, and a "config.ini.example still says localhost" claim) —
  `git show agent-work:src/pipeline.py` and `git show agent-work:config.ini.example`
  both proved the underlying premises false (the guard already exists at
  `pipeline.py` ~404-409; the ollama section is already `127.0.0.1`/`qwen2.5vl:7b`).
  Re-cut to issues 7/8/9, each independently re-verified unfixed before being trusted.
- Landed the corrected `Issues.md` by discarding the `issue/5` working-tree copy,
  switching to `agent-work`, rewriting the file from known-good content, and
  committing there (`C:\Projects\StockPhotoAgent`, commit `45e545a`) — rather than
  committing it on `issue/5` where it was first drafted. Reason: see the reconciler
  finding below — `agent-work` is the branch `recover()`'s `_expected_commit` resolves
  to when no issue is active, so committing there makes `HEAD == expected`, defusing
  the auto-archive-and-reset path for the current start state.
- Held at a setup-only boundary on every turn this session (confirm → land → hold,
  repeated) rather than proceeding to ingest or `cmd_run` — per the reviewer's explicit
  scope on each turn and CLAUDE.md's high-blast-radius rule for real target-repo
  mutation.

## Key Files
- Plan file: `%USERPROFILE%\.claude\plans\reactive-crunching-ember.md` — an early-session
  verification plan (checkpoint + item-9 precondition re-check) written during a brief
  plan-mode turn; superseded by the direct read-only/setup work that followed, kept for
  reference only.
- `C:\Projects\issue-runtime\src\runtime\recovery\bindings.py` — `check_dirty_workspace`
  (~lines 78-104), the critical finding below. Next session's design trace centers here.
- `C:\Projects\issue-runtime\src\runtime\recovery\reconciler.py` — `recover()`'s
  ordering: check 1 (orphan detection via `proj.open_executions()`) runs before the
  injected checks 2/3, all within one `recover()` call.
- `C:\Projects\issue-runtime\src\runtime\main.py` (lines ~151-286, `cmd_run`) — full
  startup order: `reap_orphans` → `recover()` → `checkout_branch` → health checks →
  `_ingest_issues` → `Orchestrator.run()`. Read in full this session.
- `C:\Projects\issue-runtime\src\runtime\queue\issues_md.py` — ingest parser; confirmed
  no `STATUS` handling anywhere in the grammar.
- `C:\Projects\StockPhotoAgent\Issues.md` — the 3 live issues (7/8/9), committed at
  `45e545a`.
- `C:\Projects\issue-runtime\NEXT.md` — items 9/13/14 (orphan-recovery gating context),
  read at session start.
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-07-27_session24-orphan-recovery-fixes.md`
  — prior session's handoff; committed this session (`6421530`).

## Next Action
Trace `recover()`'s `check_dirty_workspace` (`bindings.py` ~78-104) against a real
crashed-execution scenario — mechanically, not by assumption — to resolve whether its
archive-to-attempt-ref-then-`reset_hard` behavior IS item 9's intended orphan-reap
mechanism, or instead fires first and pre-empts/interferes with the `EXECUTING → CRASHED`
+ `preserve_residue` path (check 1) that item 9 is actually trying to witness. Only after
that's resolved should the full item-9 outcome matrix be pre-committed in writing. No
execution spawn, `cmd_run` invocation, or crash step until the matrix is committed AND
Adi gives explicit authorization for the real-target run.

## Knowledge Captured
- Ingest is id-keyed and STATUS-blind: `issues_md.py` has no `STATUS` regex anywhere in
  its grammar (a `STATUS:` line falls through to inert body text); dedup is
  `spec.id in proj.issues` at `main.py:138`, keyed purely on the `## <id>:` heading.
  Reusing a previously-seen id silently no-ops on ingest regardless of body-text
  changes — ids 1-5 are permanently burned against the current event log.
- `recover()`'s `check_dirty_workspace` fires unconditionally on every startup, before
  `checkout_branch` and before ingest. With no `ACTIVE` issue in the projection,
  `_expected_commit` resolves to `adapter.head_of(cfg.project.branch)`. If the tree is
  dirty or `HEAD != expected`, it does `git add -A` + `git commit --no-verify` (labeled
  `"reconciler dirty-workspace"`), tags the commit under a new
  `refs/attempts/_recovery/reconciler-<event_id>` ref, then `git reset --hard` to the
  expected commit. It does not distinguish genuine crash residue from an operator's
  unrelated uncommitted edit sitting in the tree — discovered by reading the source
  before running an isolated ingest script, not by observing it fire.
- Two distinct Ollama daemons exist on this machine: Docker at `localhost:11434`
  (`qwen2.5-coder:14b` — the actual configured reviewer endpoint, `config.yaml`'s
  `reviewer.qwen.endpoint`) and a native/GPU instance at `127.0.0.1:11434`
  (`qwen2.5vl:7b` — StockPhotoAgent's own pipeline dependency, unrelated to the
  runtime's reviewer). Confirmed distinct via `curl` to both this session; easy to
  conflate.
- An unquoted Windows backslash path passed through git-bash silently loses its
  backslashes before ordinary letters (`tests\test_foo.py` → `testtest_foo.py`),
  producing a false "collected 0 items" validation result — every path argument must
  be individually quoted. Encountered and resolved this session; not a real
  regression in the validation command itself.

## Assumptions
- MED confidence: it is not yet known whether `check_dirty_workspace`'s behavior is
  the intended item-9 reap mechanism or an interference with it — explicitly unresolved,
  not assumed either way. Next session must trace it against a real crash, not infer
  from source reading alone.

## Testing / Verification Performed
- PASS — StockPhotoAgent's configured validation command
  (`C:\Python314\python.exe -m pytest` with the 5 pinned test files, each path
  individually quoted): 26 passed, RC 0.
- PASS — `git show agent-work:<path>` confirms issues 7/8/9 all unfixed: check `[04]`
  in `src/utils/validate_batch.py` (season-blind ban on "Snowcapped Mountain", no
  season gate); hardcoded `EXIFTOOL_PATH` in `src/agencies/alamy/iptc_embed.py:19`;
  no `-codedcharacterset`/`-charset iptc=UTF8` flags and `text=True` with no
  `encoding=` in that same file's `subprocess.run` calls.
- PASS — `git show agent-work:<path>` confirms the 2 discarded draft issues were
  already fixed (submissions guard present; ollama section already correct).
- PASS — `refs/attempts` empty on StockPhotoAgent (`for-each-ref`, exit 0, no output).
- PASS — reviewer endpoint `localhost:11434` confirmed serving `qwen2.5-coder:14b`
  via `curl`.
- NOT TESTED — the actual item-9 fault injection (real orchestrator kill against a
  live `claude -p` child on StockPhotoAgent) — not attempted this session, by design.
- NOT TESTED — `check_dirty_workspace`'s behavior against a real crashed execution —
  traced from source only this session, not exercised live.

## Risks
- `recover()`'s `check_dirty_workspace` does not distinguish genuine crash residue
  from an unrelated dirty tree, and its interaction with real orphan-crash residue
  during item-9 fault injection is untraced. It could either be the intended reap
  mechanism or could pre-empt/interfere with the orphan-recovery path item 9 is meant
  to witness — see Next Action.
- Issues 8 and 9 share one file (`src/agencies/alamy/iptc_embed.py`) — if both are
  processed in the same run, issue 9's base commit will chain from issue 8's
  completion commit (the same chaining shape issues 1-5 showed in a prior session's
  run). The item-9 outcome matrix must account for this if fault injection lands
  mid-chain on either issue.

## User Constraints
- No commit without explicit authorization (CLAUDE.md standing rule) — every commit
  this session (the issue-runtime handoff doc, StockPhotoAgent's `Issues.md`) was
  explicitly authorized turn-by-turn.
- No StockPhotoAgent action (ingest, `cmd_run`, crash sequence) without Adi's explicit
  go-ahead — held at every boundary this session.

## Runtime & System State
- Commit at handoff — issue-runtime: this document's own commit (SHA reported after
  this skill run completes; pre-commit `HEAD` was `6421530`). StockPhotoAgent:
  `45e545acb3ef15c9970b1668731ca710e3a50381`, branch `agent-work`, clean.
- Background processes: none started this session.
- Dev servers / ports: none started or stopped this session; the two Ollama endpoints
  (`localhost:11434`, `127.0.0.1:11434`) were queried read-only.
- Open branches / worktrees: StockPhotoAgent's `issue/1`..`issue/5` branches remain
  from a prior session's run, unchanged this session. `issue/5` was checked out at
  session start; this session switched the working tree to `agent-work` (the `issue/5`
  branch itself was not deleted).
- Memory files updated: none this session.

## Deferred Work
- The item-9 real fault-injection run — deliberately deferred pending the
  `check_dirty_workspace` design trace and Adi's authorization (see Next Action).

## Open Questions
**Needs User Input**
- Once the trace is done, whether `check_dirty_workspace`'s archive+reset behavior
  should be treated as item-9's reap mechanism as-is, or needs scoping/rework before
  the crash run — a design decision to make after the trace, not before.

**Model Uncertainty**
- Exact behavior of `check_dirty_workspace` against a real `EXECUTING`-state crashed
  execution has not been exercised or traced live this session — traced from source
  reading only, flagged rather than treated as verified.
