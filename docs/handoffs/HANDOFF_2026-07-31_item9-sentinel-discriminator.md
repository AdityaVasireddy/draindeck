# Session Handoff — item-9 sentinel: pause-point fix + layered orphan discriminator (Group R/S not yet run)

## Objective
Witness item-9 orphan-crash recovery against real StockPhotoAgent via the sentinel
fault-injection harness (`docs/15-item9-outcome-matrix.md`'s pre-committed Rows A-E). Not
yet reached this session — historically blocked on a real-time race (losing the crash
window to real wall-clock execution speed) and, this session, on two deeper bugs found
only by actually running the sentinel for the first time: a pause point that starved the
child of stdin, and an orphan discriminator (`child_pid`) that was structurally
unfalsifiable. Both are now fixed and re-gated; the actual Group R/S injection run is the
next session's job, gated on Adi's explicit go-ahead (high-blast-radius: real repository
mutation, real crash injection).

## Current Status
- Completed: sentinel built and its pause-point bug fixed (three-step split: off-thread
  stdin write, pause, wait); layered orphan discriminator built (Layer 1 leaf resolution,
  Layer 2 mtime+hash helper); durability harness 60/60 both seeds re-run three times across
  this session's iterations (each rebuild), unit suite 117/117 each time; a real,
  non-degenerate crash fixture (`10-e2`) is frozen and ready for the next session.
- In Progress: nothing mid-flight — every phase this session reached its own stop point
  and was gated before proceeding.
- Blocked: the actual Group R (startup recovery) then Group S (live orphan witness,
  layered discriminator exercised for real) run — blocked on Adi's explicit go-ahead, and
  on `claude_headless.py` staying uncommitted until Group S passes (by design, stated
  standing instruction this session).

## Decisions & Rationale
- Sentinel pause point moved to land AFTER the prompt is delivered to the child's stdin,
  never before — the original placement (pause before `communicate()`) starved the child of
  stdin; it hit its own 3-second stdin grace period and self-killed with `Error: Input must
  be provided either through stdin or as a prompt argument when using --print` (observed
  directly in `state/artifacts/10-e1/stderr.log` earlier this session). Lives in
  `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py`, `ClaudeHeadlessEngine.run()`.
- stdin delivery moved onto a background thread with `writer.join(timeout=cfg.timeout_seconds)`,
  not a plain synchronous `proc.stdin.write()` — a synchronous write would hang forever
  against a child that never reads stdin at all (the stdin PIPE has a small, fixed OS
  buffer). Caught before shipping by running the pre-existing regression test
  `tests/unit/test_engine.py::test_timeout_arms_when_child_never_reads_stdin` against the
  first draft; it would have hung. The threaded version preserves that test's guarantee.
- stdout/stderr were already real files (`out_f`/`err_f`), never `subprocess.PIPE`, before
  this session's changes — confirmed both structurally (only stdin is a PIPE) and
  empirically (a scratch child wrote 10MB while paused, transcript file grew the whole
  time, no hang) that no reader-thread is needed for output; only stdin needed thread
  protection.
- The wait-timeout (`proc.wait(timeout=cfg.timeout_seconds)`) is armed only after
  `_sentinel_pause()` returns, never from spawn — so an arbitrarily long pause never trips
  the child's own execution timeout. Proven empirically: `cfg.timeout_seconds=3`, held
  paused `8s`, `timed_out` still came back `False`.
- Orphan discriminator moved off `child_pid` (the `claude.CMD` shim / `cmd.exe`) onto a
  resolved `leaf_worker_pid` — the shim was witnessed exiting shortly after handing off to
  the real worker, on three separate real runs this session (issue 8's `8-e1`, the first
  real-run session's issues 7/8/9, and `10-e2` itself), while real work visibly continued
  on disk each time. "Is `child_pid` alive" was proven unfalsifiable as an orphan witness.
- Layer 1 (`_resolve_leaf_worker`) walks the process tree via PowerShell
  `Get-CimInstance Win32_Process` (pid/ppid pairs, one query per poll) rather than psutil —
  deps are frozen to pyyaml/pydantic/pytest project-wide, and `tasklist` alone doesn't
  expose parent-pid. Tuning: 20 polls / 10s cap / 3 consecutive identical "deepest pid"
  observations before trusting a leaf as stable — stated as chosen, sane values, not
  independently load-bearing beyond that framing.
- Layer 1 never falls back to the shim on failure — an unresolved leaf records
  `leaf_worker_pid: null` plus an explicit `reason` string, proven via two scratch cases: a
  real shim→child→grandchild chain resolving to the true grandchild, and a real standalone
  childless process producing `descendant_pids: []` on every one of 10 polls before
  capping out.
- Filler issue 10 (`config.ini.example` missing `debug_logs_dir`) was committed to
  StockPhotoAgent's `Issues.md` with Adi's explicit per-commit authorization (`4c58b31`) —
  required because `checkout_branch` (`git_adapter.py`) unconditionally refuses to run on
  any dirty tree, so the filler issue had to be committed before the orchestrator could
  start at all.

## Key Files
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — all sentinel +
  discriminator work this session. Currently **uncommitted** (`M` against HEAD `d1d5525`).
  This is the file Group S will exercise; do not commit it until Group S passes.
- `C:\Projects\issue-runtime\docs\15-item9-outcome-matrix.md` — the pre-committed 5-row
  outcome matrix (Rows A-E) this whole effort verifies. Not modified this session, but is
  the reference the Group R/S witnessing plan (see Knowledge Captured) traces back to.
- `C:\Projects\issue-runtime\NEXT.md` — item 9's tracking entry. Not updated this session;
  should be updated once Group R/S actually completes, not before.
- `C:\Projects\StockPhotoAgent\Issues.md` — issue 10 (filler, `debug_logs_dir` doc gap)
  added and committed at `4c58b31`.
- `C:\Projects\StockPhotoAgent\config.ini.example` — holds the frozen, uncommitted mid-edit
  (issue 10's real one-line fix) that is the next session's fixture.
- `C:\Projects\issue-runtime\state\events.jsonl` — 77 lines at session end, ends at
  `ExecutionSpawned(10-e2)` (event_id 77), no terminal event for `10-e2`.
- `C:\Projects\issue-runtime\state\artifacts\10-e2\` — residue: `prompt.md`, `pid` (now
  stale, names a killed orchestrator's shim), `sentinel_ready`, `transcript.jsonl` (~32KB,
  real stream-json output, not empty).

## Next Action
Run Group R (startup recovery on the `10-e2` fixture) then Group S (live orphan witness
using the layered discriminator) against real StockPhotoAgent — gated on Adi's explicit
go-ahead. See Knowledge Captured below for the full witnessing plan (S-A through S-E) as
designed this session; it lives only in this handoff, not yet in any tracked doc.

## Knowledge Captured
- The recorded `child_pid` (the `claude.CMD` shim, image `cmd.exe`) reliably exits shortly
  after handing off to the real worker while work continues on disk — witnessed three
  separate times this session and the prior one. Group S must use `leaf_worker_pid` (Layer
  1) plus work-liveness via `capture_work_liveness` (Layer 2) as the orphan discriminator;
  `child_pid` alone is not a valid witness.
- Group S's planned witness sequence, as designed this session via conversation (not yet
  written into any doc):
  - **S-A** (pre-kill): both layers alive/advancing — `leaf_worker_pid` present in
    `tasklist`, and `capture_work_liveness` on the live edit target shows movement.
  - **S-B**: crash witnessed post-kill (the kill target is the **orchestrator** pid, `/F`,
    explicitly **no** `/T` — the opposite of the reset-kill's tree-kill — so the leaf worker
    is orphaned, not killed directly).
  - **S-C**: reap + residue preserved on resume.
  - **S-D**: no work repeated (no duplicate execution spawned for the same attempt).
  - **S-E**: no double-commit (merge commit's second-parent content check, same technique
    used in the earlier real-run session's fixture verification).
  - An ambiguous result on only one layer (e.g., leaf process gone but the work file still
    shows fresh activity, or vice versa) is a **STOP**, not an orphan claim — both layers
    must agree.
- `10-e1`'s crash produced `residue_ref: null` in its `ExecutionCrashed` event — not a bug.
  Confirmed via source read this session: `bindings.py`'s `preserve_residue` hits its own
  documented "b1: nothing happened" branch when `snapshot_commit` finds a clean tree, which
  is exactly what happened — `10-e1` died from stdin starvation (the pre-fix bug) before it
  ever touched the workspace. `10-e2` is different in kind: it holds a real, verified
  uncommitted edit (`config.ini.example`, +1 line), so the next recovery pass should
  produce a non-null residue ref for the first time this project has witnessed live.
- Git Bash (MSYS) mangles bare single-slash Windows flags (`/PID`, `/FI`, `/c`) passed as
  separate argv tokens — confirmed repeatedly this session. The reliable workaround used
  throughout: `cmd.exe //c '<full command string as one quoted argument>'` (the doubled
  leading slash stops MSYS's path-translation heuristic from firing on it).
- `C:\Projects\issue-runtime\.venv\Scripts\python.exe` is a redirector-stub interpreter
  that spawns a second internal process per invocation (re-confirmed this session during
  the Layer-1 scratch proof, which had to switch to `C:\Python314\python.exe` to get a
  clean, expected 2-level test chain instead of 4 levels).

## Assumptions
- MED confidence: the `10-e2` fixture state described above (StockPhotoAgent on
  `4c58b31`/clean HEAD, branch `issue/10`, `config.ini.example` dirty with the real edit;
  `state/artifacts/10-e2/` residue intact) was last directly verified two turns before this
  handoff was written, not re-checked in this final turn — this session's own instructions
  said not to touch StockPhotoAgent again while writing this handoff, so it was
  deliberately not re-read here.
- HIGH confidence: `src/runtime/engine/claude_headless.py` is the only uncommitted file in
  issue-runtime — verified immediately before writing this handoff (`git status --porcelain=v1`).

## Testing / Verification Performed
- PASS — durability harness, both seeds (42, 1337), `ITEM9_SENTINEL` confirmed unset
  (echoed empty + `-u`-stripped from the subprocess env each time): 60/60 both seeds, run
  three times across this session (once per sentinel rebuild — initial pause-point fix,
  then the layered-discriminator build).
- PASS — unit suite, same three points: 117/117 each time, including
  `test_timeout_arms_when_child_never_reads_stdin` (the specific regression the threaded
  stdin-write change protects).
- PASS — scratch stdout-drainage proof: a dummy child wrote 10MB while paused; transcript
  grew from 500,004 to 6,750,054 bytes during the pause alone, finished clean
  (`exit_status=0`, `timed_out=False`).
- PASS — scratch timeout-exclusion proof: `cfg.timeout_seconds=3`, paused `8s`,
  `timed_out=False`.
- PASS — Layer 1 positive case: real shim→child→grandchild chain (`C:\Python314\python.exe`
  based, to avoid the venv-stub confound), `leaf_worker_pid` resolved to the true
  grandchild, confirmed two independent ways (the chain's own self-report and an
  independent parent-chain query).
- PASS — Layer 1 negative case (clean re-witness): a real standalone childless process,
  10 consecutive polls all showing `descendant_pids: []`, capped out to `leaf_worker_pid:
  null` + explicit reason, no shim fallback.
- PASS — Layer 2 (`capture_work_liveness`) scratch unit tests: missing file, stable file
  (identical mtime+hash across two reads), and a real edit (mtime strictly advanced, hash
  changed).
- NOT TESTED — Group R or Group S themselves. No recovery has been run against the `10-e2`
  fixture yet; no orphan has been created or witnessed with the new discriminator against a
  real StockPhotoAgent execution.

## Technical Debt
- Layer 1's PowerShell-per-poll approach spawns a real `powershell.exe` process for every
  poll (up to 20 per pause) — functionally correct and proven, but each poll costs real
  wall-clock time (session observed ~0.4-1s per poll including subprocess overhead, not
  just the 0.5s sleep). Intentional: no lighter-weight Windows process-tree API is available
  without adding a dependency (psutil is explicitly excluded project-wide).
- `_sentinel_pause`'s resume mechanism is a bare `while not resume.exists(): time.sleep(0.5)`
  poll loop with no upper bound — by design (a fault-injection harness is expected to
  resume or kill it deliberately, not time out on its own), but means a forgotten paused
  orchestrator will sit indefinitely until someone kills it or drops the resume file.

## User Constraints
- No StockPhotoAgent `cmd_run` (or any real orchestrator run against it) without Adi's
  explicit, per-run go-ahead — held throughout this session.
- `src/` changes require the durability harness green on both seeds before being treated as
  usable — held for every rebuild this session.
- `claude_headless.py`'s sentinel/discriminator work stays **uncommitted** until Group S
  passes — explicit standing instruction this session, deliberately not committed here.
- No commit without explicit, per-commit authorization — held for the filler-issue commit
  (`4c58b31`, StockPhotoAgent) and for this handoff commit (issue-runtime).

## Runtime & System State
- Commit at handoff: `d1d5525` (issue-runtime) — this handoff will add one commit on top,
  reported after saving. StockPhotoAgent at `4c58b31` (Issues.md, issue 10 filler),
  dirty on branch `issue/10` with the real uncommitted fix (last directly verified two
  turns before this handoff, see Assumptions).
- Background processes: none left running. Every orchestrator process started this session
  (`ITEM9_SENTINEL=1` runs, PIDs 25400, 39992, and the earlier non-sentinel real run) was
  either killed explicitly (`taskkill`) or exited on its own; none are alive at handoff.
- Dev servers / ports: none started or stopped this session. Ollama reviewer endpoint
  (`http://localhost:11434`) used read-only by orchestrator health checks, as in prior
  sessions.
- Open branches / worktrees: StockPhotoAgent is checked out on `issue/10` (not `agent-work`)
  — this is expected/intentional, it's the frozen fixture's own branch, left exactly where
  the reset-kill produced it. Do not check it back to `agent-work` before Group R runs (that
  would be recovery's own job).
- Memory files updated: none this session.

## Deferred Work
- Group R and Group S themselves — deferred pending Adi's go-ahead, per standing user
  constraints, not a technical blocker.
- Updating `NEXT.md`'s item 9 entry and `docs/15-item9-outcome-matrix.md` with this
  session's findings (pause-point fix, layered discriminator) — deferred until Group R/S
  actually completes, so the doc update reflects real results rather than
  design-time-only work.
- ADR-19's kill-criteria verdict remains out of scope regardless of item 9's outcome — still
  needs a 20-issue sample; the project's only real-issue run to date is n=5 (an earlier
  session's live smoke), unrelated to this session's work.

## Open Questions
**Needs User Input**
- Go/no-go on the actual Group R then Group S run against the `10-e2` fixture — Adi's call,
  not inferable from this session's clean scratch/unit results (which only prove the
  mechanism works in isolation, not against the real target).

**Model Uncertainty**
- Whether `10-e2`'s residue and StockPhotoAgent's frozen dirty tree are still exactly as
  left — not re-verified in the turn this handoff was written (see Assumptions).
