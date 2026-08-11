# NEXT

> NEXT.md is a working queue and pointer index. It is NON-AUTHORITATIVE.
> On any conflict about evidence, event semantics, or state, the referenced doc or ADR
> wins over NEXT.md. Doc 03 continues to win on event/state semantics; doc 02 section 3
> wins on the advisory principle. NEXT.md never carries evidence labels.
>
> Exception: §3's precondition table retains VERIFIED/INFERRED status labels. The
> zero-evidence-label rule above was pre-committed as a hard target for this rewrite; it was
> NOT met for §3. On review, the rule was judged wrong for a live precondition table — a
> gate-status table is not useful without status — and is amended here to exempt §3
> specifically. This records a missed target and the reasoning for accepting the miss; it is
> not the original design intent, discovered after the fact and relabeled as if it were.
> All OTHER evidence lives in the referenced docs; NEXT.md carries no evidence labels
> outside §3.

## 1. Current gate

**Step-3 live smoke RAN, Session 22 (2026-07-27).** Core claim: **PASS** — 5/5 issues
attempt-1 (every `execution_id` is `{issue}-e1`; no `-e2`+, no `ExecutionAbandoned` event
anywhere in the log), event-log↔git-ref cross-check verified independently (every
`CommitCreated.merge_commit` hash confirmed reachable from `agent-work`'s own `git log`,
not taken from the engine's or reviewer's self-report), proxy cost **$0.3106/shipped
issue** ($1.5532177 total / 5) — mechanically below the ADR-19
`cost_per_shipped_issue_max_usd` ceiling ($3.00) and above `attempt1_success_min` (0.30).
**This is n=5, NOT an ADR-19 verdict** — ADR-19's own sample size is 20
(`experiment.sample_size`); this is a positive smoke signal consistent with the
kill-criteria thresholds, not a pass of the kill-criteria themselves. Full evidence:
`docs/14-session6-phase2-gate.md` §2.9.

**Surface witnesses (of the three carried-forward from Session 16-17, doc 14 L1129):**
- **Surface 1 (`main.py` end-to-end startup composition) — WITNESSED.** Ran clean:
  checkout → orphan-reap → recovery → reviewer health check → baseline-green → ingest →
  loop, all in one real process against the real `StockPhotoAgent` target, no crash.
- **Surface 2 (orphan-crash recovery path) — STILL UNWITNESSED.** Happy-path only;
  nothing crashed, so the reconciler's reap/no-double-commit behavior was never
  exercised. See §2 item 9.
- **Surface 3 (real-tree behavior) — WITNESSED, WITH DEFECT.** See §2 item 8 and doc 14
  §2.9 for the filed root cause.

**Gate (a), vacuity-guard detectability — untouched this session, stays permanently
unproven** (§5, unchanged).

## 2. Immediate next actions

1. ~~Decide how to sequence live-smoke design against the 3 carried-forward-unwitnessed
   surfaces~~ — **RESOLVED, Session 21 (2026-07-26), Option B.** Carry all three surfaces
   labeled into live-smoke design (none pre-witnessed); A-deferred escape hatch: a
   dedicated scratch probe reopens as a separately-gated item only if live-smoke design
   later surfaces a specific real-tree risk warranting pre-witness. Evidence basis: `grep`
   found zero `-m runtime` matches in `tests/crash/harness.py` — no existing scaffolding
   drives the real `cmd_run` entrypoint (the harness's `run_worker` drives a separate
   `WORKER` script via `Popen`), so a standalone witness probe for surfaces 1 & 2 would
   need new harness code plus the same live `claude`+reviewer/Ollama+baseline-green stack
   `cmd_run` hard-requires at steps 4/8 — strictly more costly than live smoke itself for
   those two surfaces. Surface 3 (real-tree behavior) is irreducible either way. This
   resolves the sequencing decision only; it witnesses nothing — §1 and all three surfaces
   remain UNWITNESSED / carried-forward exactly as worded. Pointer: this session's record
   for the full reasoning (no other doc holds it).
2. ~~Resolve the ingest branch-check gap~~ — **CLOSED, Session 20 (2026-07-26).** Option A
   adopted and implemented: `cmd_run` now enforces `adapter.checkout_branch(cfg.project.branch)`
   as step 5b, before recovery/baseline, fail-loud via `RepoError`. Durability harness re-run
   green, 60/60 both seed 42 and seed 1337. Gated by `docs/08-session-0-closure-and-adr-
   amendments.md` § "ADR-20 — Amendment 1 (2026-07-26)". Pointer: §5 below, "Ingest
   branch-check gap" (this file), for the resolution note.
3. ~~Close the CLI-2.1.214 Probe 2/3 coverage gap~~ — **CLOSED, Session 18 (2026-07-26).**
   The literal doc 14 §2.4 Probe 2/3 procedure was re-run and both legs PASSED at CLI
   2.1.220 (commit `ab99f55`) — the substantive identity gap (literal Probe 2/3 stale since
   2.1.211, only a substitute methodology re-run at 2.1.215) is closed. "Exactly 2.1.214"
   itself remains permanently unreachable (unchanged) — the closure is on the identity gap,
   not that literal version. Pointer: §4 below, "CLI-2.1.214 Probe 2/3 two-leg re-probe" /
   `docs/14-session6-phase2-gate.md` § "2.8 — Session 18 (2026-07-26)".
4. Build the env-witness script (docs/08 §5d spec) — precondition for the ADR-23
   end-to-end differential (all three of: script built, target collects >0 tests, a live
   "before" observed ahead of the next mechanism change). Pointer:
   `docs/08-session-0-closure-and-adr-amendments.md` § "5d. ADR-23" ["Env witness (required
   mechanism for any pre-Phase-2 live run)"].
5. Author/confirm a real StockAgent test command that both resolves the interpreter
   ambiguity (done) AND collects >0 real tests (not done) — precondition: StockPhotoAgent-side
   authoring, user input required. Pointer: §8 below, "NEEDS USER INPUT" (this file).
6. **Not owed now** — the ADR-22 STANDING TICKLE fired and PASSED this session at CLI
   2.1.220 (commit `ab99f55`); re-armed for the next `claude` CLI version bump past 2.1.220,
   before anything else, same as before. Pointer: §4 below, "Standing tickles" (this file).
7. ~~Then 5 real StockAgent issues, supervised; record cost + outcomes; expect to revise
   the context pack~~ — **RAN, Session 22 (2026-07-27).** Live smoke executed exactly
   this: 5 real StockAgent issues from `Issues.md`, supervised, cost recorded ($1.5532177
   total, $0.3106/issue, 5/5 attempt-1). Context-pack revision was NOT triggered — no
   execution needed a retry, escalation, or reviewer rejection to expose a context gap;
   this is a live possibility on future runs, not evidence the pack needs no revision.
   `--allowedTools`/settings hardening remains a non-goal (ADR-21 settled the fence),
   unchanged. Pointer: doc 14 §2.9 for full evidence.
8. **NEW, Session 22 (2026-07-27) — fix BEFORE Phase-2. RESOLVED, Session 23
   (2026-07-27), commit `86e2476`.** Working tree left on the last
   `issue/N` attempt branch after a clean drain, not on `cfg.project.branch` —
   deterministic, not incidental. Root cause: `loop.py:204`
   (`self.adapter.checkout_branch(f"issue/{issue}", create_from=base)`, inside
   `_commit_sequence`) has no matching restore call anywhere; `main.py:189`'s step-5b
   checkout runs only at STARTUP and masks the *previous* run's dirty end-state on the
   *next* invocation — it does not fix the end-state itself. Classification: fix-BEFORE
   Phase-2. Rationale: Phase-2 is a supervised metric-capture run; a deterministic
   dirty-tree-at-rest breaks the "work lives on `agent-work`, tree is on `agent-work`"
   assumption any observer or crash-recovery makes — this is the harness-masking pattern
   (a startup reset hiding an uncleaned end-state), the same shape of gap ADR-20
   Amendment 1 already closed for ingest. Fix shape: restore `cfg.project.branch` in the
   normal-exit path (`Orchestrator.run()`'s return in `loop.py`, or `cmd_run`'s teardown
   after `orch.run()` returns, `main.py:250-262`). This is src/ exit-path logic —
   REQUIRES a full durability harness re-run, 60/60 both seed 42 AND seed 1337, in the
   session that implements it; not a sneak-in one-liner. Pointer: doc 14 §2.9 for the
   full mechanical trace (both `checkout_branch` call sites, `run()`'s exit, `cmd_run`'s
   exit, and the live `issue/5`-at-rest evidence, left dirty on purpose for this filing).

   **Resolution (Session 23, 2026-07-27, commit `86e2476`):** Fix landed in `cmd_run`
   (`src/runtime/main.py`) only — `loop.py`/schema/transitions untouched. The early
   `return 2`/`return 0` inside the `orch.run()` try/except were replaced with an
   `exit_code` variable, and a `finally` attached to that same `try` now calls
   `adapter.checkout_branch(cfg.project.branch)` unconditionally on every exit path:
   clean drain, budget hard stop, `OrchestratorHalt`/`ReviewerError`, `KeyboardInterrupt`,
   and uncaught-exception fall-through. The restore is self-guarded (`except RepoError`
   inside the `finally`, logs a `[shutdown] WARNING` and does not re-raise) so a failed
   shutdown checkout cannot supersede an in-flight halt's `exit_code`. Verified, not
   assumed: `tests/unit/test_main_exit_paths.py`, 5/5 (four exit paths + the
   restore-failure-survives-halt guard, each asserting `checkout_branch` was actually
   called, not asserted from the shape alone); durability harness 60/60 at both seed 42
   and seed 1337, re-run post-change per the fix-BEFORE-Phase-2 gating requirement above.

   **Defect reclassification — correct the record, don't silently re-derive it next
   session:** the original filing above (and this session's opening brief) described the
   defect as the workspace being left with a "dirty tree" / uncommitted changes. Live
   re-verification this session (`git status` on `StockPhotoAgent`, full form, not just
   `--porcelain`) showed the opposite: `On branch issue/5` / `nothing to commit, working
   tree clean`. The actual defect was narrower and purely branch-identity: the tree is
   checked out on the wrong branch (`issue/5` instead of `agent-work`) with no
   uncommitted changes at all. Same fix class (restore `cfg.project.branch` on exit),
   same root cause (`loop.py:204`'s per-issue checkout, no matching restore) — the fix
   above resolves the actual (wrong-branch) defect, not the originally-misdescribed
   (dirty-tree) one. Recorded here so the next session does not re-derive this
   correction from scratch.
9. **NEW, Session 22 (2026-07-27) — named, not blocking Phase-2. NOW GATED BY item 13
   (Session 24).** Orphan-crash recovery path has never been positively witnessed —
   every run to date, including this session's live smoke, is happy-path only. The
   reconciler's reap/no-double-commit behavior needs a deliberate fault-injection
   witness (kill `claude -p` mid-execution, then resume) before the system can be
   trusted unsupervised. Not gated on Phase-2, but must not be carried silently as
   "works" — this line is that explicit carry. Pointer: doc 14 §2.9.

   **Session 24 (2026-07-27) follow-up — real injection attempted, BLOCKED, and a
   second finding logged.** A real fault-injection run (disposable scratch repo, real
   `cmd_run`, real `claude -p` child, orchestrator killed via `taskkill /PID <pid> /F`
   with no `/T`) confirmed the kill mechanism works — GAP-1 live-child witness clean,
   the real child was confirmed alive via `tasklist` immediately after the orchestrator
   was terminated — but resume could not reach `recover()` at all; see item 13, which
   this item is now gated on. Independent of item 13, the run surfaced a second finding
   that must survive into whatever run finally exercises this item: the orphaned child
   ran to completion fully unsupervised and left a real edit on the target repo's
   per-issue attempt branch (uncommitted, in `calc.py`) with ZERO event-log trace — no
   `ExecutionFinished`, no `ExecutionCrashed`, no residue ref, because recovery never
   ran. Implication: real residue can exist on disk/in git with no corresponding
   event-log record at all, so a future no-double-commit proof that keys only off
   `CommitCreated`/event cardinality is insufficient by construction — it cannot detect
   residue that was never witnessed as an event in the first place. The merge-commit
   second-parent / attempt-ref provenance check already specified in this item's
   approved outcome matrix (Session 24, design gate) is therefore load-bearing, not
   redundant, and must not be dropped as a simplification when this item is re-attempted.
   Evidence preserved on disk under `<scratchpad>/orphan-report/` and
   `<scratchpad>/orphan-scratch-repo/` (untouched, not cleaned up — it is the
   reproduction for item 13's fix re-test).

   **Session 31 (2026-08-03) follow-up — GAP-1 witnessed on a disposable scratch
   target, not on live StockPhotoAgent.** With item 13 resolved, a real
   fault-injection run was attempted; the live StockPhotoAgent backlog was found
   already fully drained (`run-20260803T050931Z`), so a disposable scratch target
   was built and used instead — live StockPhotoAgent was deliberately untouched
   this session. Results, precisely scoped:
   - GAP-1 live-child witness: **PASS, witnessed twice** on the scratch target
     (issues 902 and 903), via marker-file-polling detection (polling the
     `sentinel_ready` marker file's existence, not text-scanning the live log —
     the detection method that made the witness reliable). **NOT witnessed
     against live StockPhotoAgent.**
   - Recovery mechanics (crash detect / exactly one retry / content-based
     no-double-commit / residue durability): **PASS**, on issue 902's completed
     cycle, scratch target only.
   - Escalation path (reviewer-reject → cap-hit → `IssueEscalated`, residue refs
     persist, no merge): **PASS**, on issue 903, scratch target only.
   - Layer-2 `capture_work_liveness` movement-across-kill: **still OPEN** — the
     snapshot mechanism itself works (correctly-formed snapshots on every call),
     but no pre/post-kill content delta was ever observed across three attempts;
     the agent collapsed even an explicitly staged multi-step task into a single
     atomic write each time.
   Dated 2026-08-03, session 31. Full evidence: handoff commit `3040c25`
   (`docs/handoffs/HANDOFF_2026-08-03_session31-item9-scratch-fault-injection.md`).
10. **NEW, Session 22 (2026-07-27) — cosmetic, file-and-defer.** `Issues.md` STATUS text
    never written back after issues complete — cosmetic, not a correctness bug. The
    user hand-verified after the live smoke that all 5 issues in `Issues.md` still read
    `STATUS: OPEN — not started.` despite all 5 being `DONE` in the event log.
    **Confirmed idempotent, statically, not by a second run** (which would have created
    real duplicate commits had the answer been bad): `issues_md.py`'s `IssueSpec` has no
    `status` field and its parser has no STATUS-handling regex anywhere — the text folds
    into the issue body and is never actioned. Dedup keys off `spec.id in proj.issues`
    (`main.py:138`), and `proj.issues` membership is set once, permanently, by
    `_issue_created` (`projections.py:134-138`) on replay of the persistent event log's
    `IssueCreated` events — never off `Issues.md`'s text. A second invocation with the
    event log intact would read `[ingest] 0 new issue(s)` and drain immediately, $0
    spent, 0 duplicate commits. Optional future nicety: write `DONE` back to `Issues.md`
    for human legibility — nothing in the runtime depends on it. Pointer: doc 14 §2.9.
11. **NEW, Session 22 (2026-07-27) — named latent-dependency, not a fix, a tracked
    invariant.** Ingest idempotency (item 10) depends on `state/events.jsonl`
    (issue-runtime-side, i.e. `C:\Projects\issue-runtime\state\events.jsonl`, not the
    target repo) surviving between runs. If that event log is ever deleted, moved, or
    repointed while `Issues.md` still lists issues as available text, ingest loses all
    memory of what already ran and re-emits every issue as new — real duplicate
    executions and real duplicate commits on `agent-work`. This is the precondition
    idempotency rests on, not a contradiction of it. Relevant because the recovery model
    treats the event log as source of truth; this makes "event log durable and correctly
    located" an invariant to protect, and it shares a trust surface with item 9
    (unwitnessed crash-recovery) — both ultimately trust the event log's integrity and
    availability. Not blocking Phase-2; tracked so it is not carried as an unstated
    assumption. Pointer: doc 14 §2.9.
12. **NEW, Session 23 (2026-07-27) — housekeeping, not blocking.** A stray `--help/`
    directory exists at the issue-runtime repo root — leftover harness-fixture scratch
    from an accidental `python tests\crash\harness.py --help` invocation this session
    (the harness has no `argparse`/`--help` handling; `sys.argv[1]` is taken literally
    as the run root, so `--help` was treated as a directory name). It is untracked
    (`git status` shows `?? --help/`), contains only empty harness-fixture
    subdirectories, and was deliberately left in place this session (not force-deleted)
    per reviewer instruction. Next session: delete manually or add a `.gitignore` line —
    a separate housekeeping decision, not part of item 8's fix commit.
13. **NEW, Session 24 (2026-07-27) — fix BEFORE Phase-2. GATES item 9. RESOLVED,
    same session.** Real
    fault-injection (kill the orchestrator mid-execution against a disposable scratch
    repo; real `claude -p` child confirmed alive post-parent-kill, GAP-1 witness clean)
    surfaced a standing startup deadlock, not a transient race.
    **Symptom:** on resume after a real mid-execution crash, `cmd_run` exits 1 at
    `checkout_branch` (`src/runtime/repo/git_adapter.py:165-170`) with `refuse to
    checkout <branch>: worktree dirty (upstream sequencing bug — residue must be
    preserved first)`, BEFORE `reap_orphans` (`main.py` step 6) or `recover()` (step 7)
    ever run.
    **Root cause:** `main.py` step ordering — step 5b (`checkout_branch`, added by ADR-20
    Amendment 1, dated 2026-07-26, §5 "Ingest branch-check gap") runs BEFORE reap/recover.
    That amendment's stated rationale ("recovery's `bind_reconciler` and the baseline
    health check... both act against `cfg.project.branch`/the physical tree and would
    otherwise run pre-checkout") is now live-falsified: recovery's seams (`bindings.py`)
    operate via explicit-ref git plumbing (`rev-parse`, `merge-base`, `for-each-ref`) and
    mutate whatever branch is CURRENTLY checked out, not `cfg.project.branch`
    specifically — they never needed the branch pre-switched. `checkout_branch`'s own
    dirty-tree guard message ("upstream sequencing bug — residue must be preserved
    first") already anticipated this conflict; the amendment was never reconciled
    against it.
    **Blast radius: STANDING DEADLOCK, not transient.** Once a real crash leaves the
    tree dirty (the normal shape of a mid-execution crash — the engine works on a
    per-issue `issue/N` attempt branch per `loop.py:204`, and a kill mid-edit leaves
    uncommitted changes there), every subsequent orchestrator start on that repo hits
    the identical refusal and exits 1 until a human manually intervenes outside the
    runtime. This is on the mainline recovery path, not an edge case — it is item 9's
    exact scenario.
    **Evidence:** scratch-repo fault injection this session, preserved on disk under
    `<scratchpad>/orphan-report/` (`run1_stdout.log` empty — confirms an uncatchable
    hard kill, no graceful flush; `run2_stdout.log` is exactly the two-line
    `CHECKOUT FAILED` message and nothing else) and `<scratchpad>/orphan-scratch-repo/`
    (left exactly as the crash produced it: `git status` shows `## issue/1` /
    ` M calc.py`, an uncommitted real edit from the killed `claude -p` child). Scratch
    `events.jsonl` frozen at 5 events post-resume — no `ExecutionCrashed`, no second
    `ExecutionSpawned`. See item 9's Session-24 follow-up for the orphaned child's fate.
    **Cross-link:** GATES item 9 — orphan-reap / no-double-commit cannot be witnessed
    until recovery can actually start on a genuinely dirty post-crash tree.
    **Fix design (written up for gate, NOT implemented):** reorder `reap_orphans` +
    `recover()` ahead of `checkout_branch` in `main.py`. Confirmed viable, not assumed:
    `preserve_residue`'s `snapshot_commit` (`git_adapter.py:176-184`) does `git add -A`
    + `git commit --no-verify` on whatever branch is currently checked out, which
    leaves `is_dirty()` False afterward; check 3 (`check_dirty_workspace`) additionally
    `reset_hard`s if still off-target. Both are branch-agnostic — neither needs
    `cfg.project.branch` checked out first. `checkout_branch`, moved to run
    immediately after `recover()` returns, therefore always finds a clean tree. Ingest
    (step 9) and baseline (step 8) still run strictly after checkout, unchanged — only
    recovery moves ahead of it, not ingest/baseline. Requires a new ADR entry (doc 08,
    "ADR-20 — Amendment 2") since this reorders an already-ADR'd sequencing decision —
    not an ad hoc change — plus a full durability harness re-run (60/60, both seed 42
    and seed 1337) before landing, same class as item 8's `main.py` startup-composition
    change. Pre-committed re-test: re-run the same scratch fault injection; PASS
    condition is resume reaching `recover()` (an `ExecutionCrashed` event appended, not
    a `CHECKOUT FAILED` exit) and the full item-9 outcome matrix becoming evaluable.

    **Resolution (Session 24, 2026-07-27, NOT YET COMMITTED — implemented and gated,
    commit pending explicit authorization).** `ADR-20 — Amendment 2` written in doc 08
    (§5, after Amendment 1). `main.py` reordered exactly as designed: `reap_orphans`
    (step 6) and `recover()` (step 7) now run before `checkout_branch` (moved to step
    7b); ingest and baseline untouched, still strictly after checkout. All three gates
    green: (1) durability harness 60/60 both seed 42 AND seed 1337 (raw: `ALL 60
    SCENARIOS PASSED` both runs); (2) fresh scratch-repo v2 re-test — resume stdout
    `[startup] reaped orphan engine 1-e1 (pid 48208)` / `[recovery] crashed orphans:
    ['1-e1']` / `[startup] checked out agent-work`, no `CHECKOUT FAILED`, a real
    `ExecutionCrashed` event appended (event_id 6); (3) item-9 outcome matrix now
    evaluable for the first time and PASSES all three checks — orphan reaped (child pid
    gone from `tasklist` after resume), no work repeated (exactly one retry
    `ExecutionSpawned`, one terminal `IssueCompleted` for the crashed issue), no
    double-commit (`rev-list --count` delta = 6 = 3 completed issues × 2 commits/issue,
    no extras; `CommitCreated` count for the crashed issue = exactly 1; the merge's
    second parent is the retry's own commit, verifiably distinct from the abandoned
    residue commit). Evidence preserved under `<scratchpad>/orphan-report-v2/` and
    `<scratchpad>/orphan-scratch-repo-v2/`, alongside the original pre-fix
    `orphan-report/`/`orphan-scratch-repo/` left untouched for comparison. **The GATE-3
    re-test also surfaced item 14 (evidence-integrity defect in attempt-ref
    preservation) — independently confirmed NOT caused by this reorder (see item 14's
    root cause); does not block calling this item's own fix verified.**
14. **NEW, Session 24 (2026-07-27) — fix BEFORE Phase-2, EVIDENCE-INTEGRITY severity.**
    Surfaced by item 13's GATE-3 re-test (the first real crash-residue scenario
    recovery has ever been able to reach). **Symptom:** the `ExecutionCrashed` event for
    execution `1-e1` asserts `residue_ref: "refs/attempts/1/1-e1"` as preserved, but
    `git rev-parse refs/attempts/1/1-e1` fails ("unknown revision"), `git for-each-ref
    refs/attempts` returns nothing, and `git fsck --unreachable` shows the residue
    commit (`3297589670ae...`, message "crash residue 1-e1", confirmed present in the
    `issue/1` reflog at `@{2}`) as dangling/unreachable — one `git gc` from permanent
    loss. The event log asserts a durability guarantee the repository does not actually
    keep.
    **Root cause, confirmed from source (not hypothesized):** `loop.py:339` —
    `self.adapter.delete_attempt_refs(issue)`, fired unconditionally on every
    `IssueCompleted` ("both done -> close the issue, then GC attempt refs (ADR-15)") —
    calls `delete_attempt_refs(issue_id)` (`git_adapter.py:240-244`), which internally
    calls `list_attempt_refs(issue_id)` (`git_adapter.py:133-134`) using the glob
    pattern `refs/attempts/<issue_id>` — **scoped to the ISSUE, not the execution** —
    and deletes every ref that matches via `git update-ref -d`. On this run: `1-e1`
    (crashed, residue preserved by recovery's `preserve_residue`,
    `bindings.py:39`) and `1-e2` (the retry that actually succeeded, its own attempt
    ref written normally at `loop.py:217`) both live under `refs/attempts/1/*`. When
    `1-e2` completed and `IssueCompleted` fired, `delete_attempt_refs("1")` deleted
    BOTH — the retry's own now-superseded-by-the-merge-commit ref (harmless, matches
    the "idempotent; harmless if crashed pre-GC" comment's intent) AND the crashed
    sibling execution `1-e1`'s residue ref (NOT harmless — that ref was the only
    anchor for evidence of a DIFFERENT execution's abandoned work, unrelated to
    whether the issue as a whole eventually succeeded). Confirmed as the actual
    mechanism, not a race or environment quirk: the reflog timeline (`3297589`
    committed -> `4c6365b` reset by check 3 -> `68dd430` committed by the retry) is
    fully explained by existing code paths with no unexplained gap, and a manual
    `git update-ref refs/attempts/1/1-e1 3297589...` in the same repo persists
    immediately, ruling out a git/Windows write-persistence bug.
    **Does NOT implicate item 13's reorder.** `delete_attempt_refs` fires from
    `loop.py`'s normal issue-completion path, entirely independent of `main.py`'s
    startup step order — it would delete the same refs regardless of whether
    `checkout_branch` runs before or after `recover()`. Item 13's fix only made this
    scenario reachable for the first time (previously, no real crash-residue run ever
    got far enough for an issue to both crash AND later complete); it did not create
    the bug.
    **Why it matters:** confirms, in production, the exact risk item 9's Session-24
    follow-up predicted — residue can exist with no reliable durable trace. GATE 3's
    no-double-commit PASS this session survived only because that check compared
    commit CONTENT (the merge's second parent vs. the residue commit's own sha, both
    independently resolvable via the reflog) rather than trusting the `residue_ref`
    itself; any future check or audit that trusts `residue_ref` as durable would be
    reading a false guarantee.
    **Cross-link:** related to item 9's second finding (Session 24) — this run is that
    finding's production confirmation, not a new independent risk class. Does not gate
    or block item 13's reorder fix, which is independently verified working.
    ~~**Fix:** NOT designed or implemented this session — root-cause trace only, per
    explicit instruction.~~ Evidence (console log, `events.jsonl`, reflog, fsck output)
    preserved under `<scratchpad>/orphan-report-v2/`.

    **CORRECTION (dated 2026-07-29, added the session after next — the line above went
    stale within Session 24 itself and was never updated).** The struck sentence is
    WRONG as a description of the current repo: the fix WAS designed and implemented,
    later the same session, at commit `9c071ed` ("fix(repo): scope attempt-ref GC to
    the completing execution (ADR-15 Amendment 1)", 2026-07-27 20:29:01 — after this
    item's filing but still within Session 24). `loop.py:339`'s issue-scoped
    `delete_attempt_refs(issue)` was replaced with execution-scoped
    `delete_attempt_ref(issue_id, execution_id)` (`loop.py:342`,
    `git_adapter.py:240-245`); the issue-scoped method no longer exists anywhere in
    `src/` (`grep -rn "delete_attempt_refs" src/` → zero matches, re-confirmed live
    2026-07-29). Full correction record: `docs/08-session-0-closure-and-adr-amendments.md`
    §5e. Per the commit message: gated by 117/117 unit, 60/60 durability harness (both
    seeds), and a scratch re-test showing the crashed sibling's residue ref survives —
    those are the fix commit's own self-reported gates, not independently re-run by the
    session that added this correction note. This item (14) should be treated as
    RESOLVED, not open, in any future read of this file; left in place under its
    original number rather than renumbered, per the append-only correction pattern —
    do not silently rewrite history, annotate it.

## 3. Open preconditions (Step 3's own five, plus its gating item 0)

**Step 3's OWN separate preconditions — checked LIVE Session 9 (2026-07-17,
`claude` 2.1.212) — see doc 14 §2.6 for full evidence. NONE satisfied yet;
none carried forward from Session 7/8 assumption:**
0. **GATE, not a checklist line — live end-to-end re-witness of the ADR-22
   argv, through `ClaudeHeadlessEngine.run()` against the real `claude`
   binary, is a hard precondition on Step 3's live smoke, not an optional
   preflight nicety.** **RUN Session 10 (2026-07-17, doc 14 §2.6 "RUN this
   session") — CLEAN, WITH A CAVEAT, not an unqualified pass.** The composed
   real-`_command()`→`Popen`→real-`claude` path (never exercised together
   before) came back clean: `exit_status=0`, `apiKeySource="none"`, `git
   init` denied with both detection signals, `.git` absent, `knowledge/`
   absent across the full 450s poll, zero new `skips.log` lines for this
   run's cwd. That specific "never composed" gap IS closed. The caveat: this
   session's positive control (mutated argv, isolation stripped) also came
   back clean, so the run does NOT independently prove the mechanism is
   doing detectable work — see `docs/handoffs/next-md-archive-2026-07-26.md`
   § "VACUITY-GUARD GAP" ["that control no longer discriminates"] (now a
   third non-reproduction). Do not treat this line as "ADR-22 proven"; treat
   it as "the specific composition gap is closed, the vacuity question is
   separately still open."
1. `project.validation.commands` in `config.yaml` still has the placeholder
   `'<StockAgent test command — REQUIRED before first run>'`. **RE-CHECKED
   LIVE, STILL UNCONFIRMED — genuinely no answer available without user
   input.** No `pytest.ini`/`pyproject.toml`/`setup.cfg`/`conftest.py`/
   `Makefile`/CI workflow exists anywhere in `C:\Projects\StockPhotoAgent`;
   `CLAUDE.md` documents many `python -m src....` operational commands but no
   test runner. This is not a probing gap — there is nothing left to probe;
   someone must author or supply the command. **RE-CHECKED LIVE Session 14
   (2026-07-25) — STILL UNMET, two independent problems found and only ONE
   fixed.** (a) Bare `python` in the configured command resolved
   ambiguously — VERIFIED to different interpreters depending on operator
   shell state (this repo's own `.venv`, lacking StockPhotoAgent's Pillow
   dependency, vs. `C:\Python314\python.exe`, which has it) — **FIXED this
   session**: `config.yaml` now pins the absolute path (ADR-23 rule 1, see
   `docs/handoffs/next-md-archive-2026-07-26.md` § "Session 14, continued
   (2026-07-25): ADR-23 ACCEPTED" and `docs/08-session-0-closure-and-adr-amendments.md`
   § 5d). (b) Even with
   the correct interpreter, `tests\qc\test_qc_rules.py` has ZERO
   pytest-collectible `test_*` functions — VERIFIED exit 5, `collected 0
   items` — **NOT FIXED**, out of scope (StockPhotoAgent-side authoring).
   Precondition #1 stays UNMET on (b) alone.
2. Ollama running with the configured reviewer model pulled. **RE-CHECKED
   LIVE Session 9 — UNMET at the time** (`ollama list` showed only
   `qwen2.5vl:7b`; `config.yaml → reviewer.qwen.model` named the un-pulled
   `qwen2.5-coder`). **CLOSED Session 13 (2026-07-24)** — that Session-9
   check queried the wrong Ollama instance. `config.yaml →
   reviewer.qwen.endpoint` (`http://localhost:11434`) is served by a
   separate Docker Ollama instance; `localhost:11434/api/tags` queried
   directly confirms `qwen2.5-coder:14b` present (14.8B, Q4_K_M, pulled
   2026-04-17). `config.yaml` now points at `qwen2.5-coder:14b`, matching
   the endpoint that will actually serve the reviewer at runtime.
3. `Issues.md` authored in StockAgent in the `## <id>: <title>` format.
   **RE-CHECKED LIVE — UNMET, two independent problems.** (a) Wrong
   location: an untracked `docs/Issues.md` exists, but `main.py` resolves the
   issues file at repo-ROOT (`Path(project.repository) / project.issues_file`
   = `C:\Projects\StockPhotoAgent\Issues.md`), which does not exist. (b)
   Wrong format: `docs/Issues.md` is a numbered list with inline
   `**STATUS:**` markers, not `## <id>: <title>` headings — parsing it as-is
   would raise `IssuesParseError` (no `## ` heading matches the grammar at
   all). **CLOSED Session 14 (2026-07-25)** — see
   `docs/handoffs/next-md-archive-2026-07-26.md` § "Entry 1 — PRECONDITION #3
   CLOSED (2026-07-25)" for full evidence. The file now exists
   at the correct repo-root path, is committed on `agent-work` (`58bc162`),
   and parses cleanly (5 valid `IssueSpec`s, no errors).
4. Baseline green on StockAgent's `agent-work` branch. **BLOCKED on #1, not
   independently re-verifiable this session** — no known test command to
   run; guessing one (e.g. bare `pytest`) was judged unsafe given the
   `tests/` dir contains files that look auth/network-probe-shaped
   (`test_401_response_body.py`, `test_csrf_cookie_match.py`,
   `test_login_only.py`, ...), not obviously StockAgent's own suite. `git
   status` on `agent-work` itself is otherwise clean (only the untracked
   `docs/Issues.md` from #3). **RE-CHECKED LIVE Session 14 (2026-07-25) —
   STILL BLOCKED on #1, plus a NEW requirement added (ADR-23): a zero exit
   code alone no longer counts as baseline green.** The gate must be
   witnessed non-vacuous (collected count > 0, and a deliberate mutation to
   the code under test turns it red) before #4 can be marked MET — same
   discipline as the crash harness's own mutation-testing. VERIFIED this
   session: the auth/network-probe suspicion (immediately above) is confirmed, not just
   suspected — grepped the full `tests/` tree for `^def test_|^class Test`;
   only `test_button_selector_only.py` and `test_login_only.py` match, and
   both are live credentialed Playwright browser automation against a real
   third-party site (`keyring` credentials, non-headless Chromium,
   hardcoded batch UUIDs) — confirmed by reading them, not run. No safe,
   appropriate, currently-passing baseline exists anywhere in this repo's
   `tests/` tree today; see `docs/08-session-0-closure-and-adr-amendments.md`
   § 5d for the full non-vacuity requirement text.
5. StockAgent `.gitignore` hygiene (covers build/test byproducts).
   **RE-CHECKED LIVE — MET.** Covers `input/output/done/failed/review/`,
   `database/`, `logs/`/`*.log`/`debug_logs/`, `__pycache__/`, venv
   variants, IDE/OS cruft, and `config.ini` (credentials).

## 4. Standing tickles

**ADR-22 B-layer sunset — check on every `claude` CLI version bump.** B is removable once
A-empty (`--setting-sources ""`) has survived one clean CLI-upgrade cycle with the doc 14
§2.4 probes re-run green (control still contaminates; `--setting-sources ""` still `rc=0`,
still clean at 450s, `apiKeySource` unchanged). On the next `claude` version bump, before
anything else: re-run those probes, and if they pass, remove `HISTORIAN_SWEEP_ACTIVE` from
`config.yaml → engine.child_env` and strike the B layer from doc 08 §5c as
sunset-fulfilled. **Re-witnessed at CLI 2.1.220, Session 18 (2026-07-26) — literal §2.4
Probe 2/3 re-run, both PASS.** Sunset was NOT evaluated or acted on — **re-probe and hold B
remains the standing instruction, unchanged: a green re-probe does not, by itself, license
the B-layer sunset**; that decision stays explicitly the user's to make, each time, not an
automatic consequence of a passing matrix. Tickle re-armed for the next CLI bump past
2.1.220. Pointer: `docs/14-session6-phase2-gate.md` § "2.8 — Session 18 (2026-07-26): ADR-22
Probe 2/3 literal re-probe at CLI 2.1.220 (STANDING TICKLE — fired, PASS)" ["Decision:
re-probe and hold B"].

**CLI-2.1.214 Probe 2/3 two-leg re-probe — CLOSED (identity gap, not the literal version).**
Previously: the literal doc 14 §2.4 Probe 2/3 procedure had not been re-run since CLI 2.1.211
— the 2.1.215 re-probe (doc 14 §2.7) substituted the Session-11 synthetic-marker methodology
(Leg B / Synth Step B / Synth Step C) instead of re-running Probe 2/3 itself, and re-probing
literally at 2.1.214 specifically was no longer possible once the CLI moved past it. **Session
18 (2026-07-26, CLI 2.1.220) closed the underlying identity gap** by re-running the actual
§2.4 Probe 2/3 procedure (not a substitute) and getting both PASS — see doc 14 §2.8. The
specific "at exactly 2.1.214" version is still permanently unreachable (unchanged, cannot be
rolled back to as a matter of routine), but the substantive gap it stood for — literal Probe
2/3 going stale across multiple CLI bumps with only a substitute methodology re-run in its
place — is closed as of 2.1.220. Pointer: `docs/14-session6-phase2-gate.md` § "2.8 — Session
18 (2026-07-26)" (this file, above) supersedes
`docs/handoffs/HANDOFF_2026-07-18_adr22-vacuity-control-restored.md` § "Deferred Work"
["Re-running doc 14 §2.4 Probe 2/3 at CLI 2.1.214"] as this item's live pointer.

## 5. Parked decisions

**Ingest branch-check gap — RESOLVED, Session 20 (2026-07-26).** Originally: "Ingest does
not verify/enforce checked-out branch before reading `Issues.md`." `Issues.md` was read
correctly only because ambient `HEAD` happened to match `cfg.project.branch` — nothing in
the runtime enforced or verified this match. Two options were recorded, neither chosen at
the time: **Option A** — add an explicit `checkout_branch(cfg.project.branch)` call before
`_ingest_issues` in `main.py`. **Option B** — accept as scoped risk, rely on Step 3
preflight Item 0 (which did NOT cover this in its scratch-workspace form, verified that
session).

**Resolution (2026-07-26):** Option A implemented. `cmd_run` (`src/runtime/main.py`) now
calls `adapter.checkout_branch(cfg.project.branch)` as a new step 5b, placed after the
adapter is constructed and *before* orphan reap / recovery / the baseline health check —
not immediately before ingest — because recovery's `bind_reconciler` and the baseline
health check's `Validator.validate` both act against `cfg.project.branch`/the physical
tree and would otherwise run pre-checkout. No adapter signature change: reuses the
existing `checkout_branch(branch, *, create_from=None)`, called with no `create_from` so
the target repo's long-lived branch is only switched to, never force-reset. Failure modes
(dirty tree, missing local branch) both raise `RepoError`, caught by one new
`except RepoError` arm that prints to stderr and returns 1 — fail-loud, no silent no-op;
detached HEAD and already-on-branch are not special-cased (plain `checkout` handles both
correctly, idempotently). Durability harness re-run in full post-change: 60/60 on seed 42
AND 60/60 on seed 1337 (`tests/crash/harness.py`). Gated by, and full rationale recorded
in, `docs/08-session-0-closure-and-adr-amendments.md` § "ADR-20 — Amendment 1
(2026-07-26): enforce `cfg.project.branch` checkout before ingest". Pointer:
`docs/handoffs/next-md-archive-2026-07-26.md` is NOT this item's home — full prior
evidence for the original gap lives only here; see also `docs/14-session6-phase2-gate.md`
§2.6/§2.7 for Item 0's scoping evidence ["scratch workspace — explicitly 'never
StockPhotoAgent'"], preserved for history, not superseded by this resolution.

**Vacuity-guard detectability — permanently unproven.** The positive control that would
prove the ADR-22 A-empty mechanism can detect contamination (not just fail to observe it)
has never fired across three independent, differently-constructed attempts. This is
carried into live smoke as a labeled limitation per standing ruling, not a blocker to
resolve first. Pointer: `docs/14-session6-phase2-gate.md` § "Session 11 (2026-07-18) —
ADR-22 vacuity-guard: synthetic positive control BUILT and RUN" ["three independent
non-reproductions"] (L894-977); background: § "2.6 — Session 9" ["the vacuity guard no
longer fires"] (L542-890).

## 6. Pointer index

- **Session 22 (2026-07-27) — Step-3 live smoke (first real run), event-log↔git-ref
  cross-check, attempt-1/cost table, surface-3 defect root cause, orphan-recovery gap:**
  `docs/14-session6-phase2-gate.md` §2.9.
- **Session-by-session narrative & evidence (Sessions 5-17, superseded/closed items):**
  `docs/handoffs/next-md-archive-2026-07-26.md`.
- **ADR-22 mechanism, vacuity-guard probe evidence, CLI re-pin probes:**
  `docs/14-session6-phase2-gate.md` §2.1-2.7, plus the Session 16-17 carried-forward note
  at end-of-file.
- **ADR-21 (engine fence), ADR-22 (ambient-hook isolation), ADR-23 (validation-env
  hygiene):** `docs/08-session-0-closure-and-adr-amendments.md` §5b / §5c / §5d.
- **Per-session handoffs (full conversational record, one per session):**
  `docs/handoffs/HANDOFF_*.md`, dated.
- **This rotation's audit trail:** `docs/scratch/next-md-audit.md`,
  `docs/scratch/next-md-audit-verify.md`.
- **Doc 03** governs event/state semantics; **doc 02 §3** governs the advisory principle;
  neither is superseded by anything in this file.

## 7. Verify commands (updated)
- Unit: `python -m pytest tests\unit -q`  (expect 117)
- Durability gate: `python tests\crash\harness.py %TEMP%\ch`  (expect 60;
  minutes. `... %TEMP%\ch 1337` also 60. `... %TEMP%\ch 42 <point>` filters to
  one crash point.) Use the `.venv` python — the system Python on this
  machine lacks `pyyaml`/`pydantic`.
- Orchestrator (needs config + live services): `python -m runtime.main run
  --config config.yaml` (see §8, NEEDS USER INPUT, before first run).

## 8. NEEDS USER INPUT before the first real StockAgent run (doc 13 §6)
1. `project.validation.commands` — StockAgent's real test command (config.yaml
   still has the `<REQUIRED>` placeholder).
2. Directory name (StockAgent vs `C:\Projects\StockPhotoAgent`) + `agent-work`
   branch exists.
3. Issues.md in StockAgent in the `## <id>: <title>` format (or author it).
4. Ollama up + reviewer model pulled — gates the reviewer health check and
   the live smoke. **CLOSED Session 13 (2026-07-24)** — see
   `docs/handoffs/next-md-archive-2026-07-26.md` § "Session 13 (2026-07-24):
   Step-3 precondition #2 CLOSED" and §3 item 2 above; `config.yaml` now
   points at `qwen2.5-coder:14b`, verified present at the actual serving
   endpoint (`localhost:11434`, Docker Ollama instance).
5. Baseline green on `agent-work` (startup health check enforces it).
6. StockAgent `.gitignore` covers build/test byproducts.
7. ADR-19 tamper guard has no doc-03 event home — defer to Phase-4 prep.

---

> Rotation: at session close, completed items move out to the session handoff; new items
> come in. Evidence produced this session goes to doc 14 or the relevant ADR, never here.
> If NEXT.md exceeds 120 lines, that is the signal to rotate, not to keep appending.
>
> The ≤120-line cap above was a pre-committed PASS target for this rewrite and was NOT met:
> this file is 254 lines, longer than that at every point since the rewrite landed. The cap is retained
> as the correct default target for future rewrites, not redefined — the miss is recorded
> honestly here, not reframed as a pass. The overage is §3's precondition table alone; this
> is the rotation trigger already firing: next session, §3 either shrinks as preconditions
> close, or it graduates to its own tracking doc. Do not trim the rest to hit 120 — the rest
> is already minimal, and trimming it would not address why the cap was missed.

> **NOTE (Session 33, 2026-08-05) — two observability/ergonomics gaps found during the
> issue-23 live run (`run-20260805T132808Z`).** Neither fixed; neither authorized for
> fixing this session; recorded here so neither is silently re-derived later.
>
> 1. **Reviewer verdict rationale not persisted.** The `ReviewApproved` event (schema as
>    seen live, event_id 203 this run) persists only `reviewed_commit`, `reviewer_provider`,
>    and `verdict`. The Qwen reviewer's raw JSON response (`severity`, `feedback[]`) is
>    parsed in-memory by `_parse()` in `src/runtime/reviewer/qwen_ollama.py` and never
>    written to disk or the event log. Consequence: after a run, there is no retrievable
>    artifact explaining why the reviewer approved or rejected — the approval rationale is
>    structurally unwitnessable. Candidate fix (NOT authorized now, just noted): persist
>    `severity` and `feedback` into the `ReviewApproved`/`ReviewRejected` payload, or write
>    the raw reviewer response to `state/artifacts/<exec-id>/review.json`. Flag: any
>    schema/event-payload change is a five-gate `src/` change requiring 60/60 both seeds.
> 2. **`run` subcommand has no per-issue scope flag.** `run` exposes only `--config` and
>    `--skip-baseline`. Scoping a live run to a single issue currently requires temporarily
>    editing `budget.max_executions_per_run` (done 10→1→10 for the issue-23 run,
>    working-tree only, reverted to an empty `git diff`, no commit). Candidate fix (NOT
>    authorized now, just noted): a real `--issue <id>` or `--max-executions <n>` flag so
>    single-issue scoping doesn't require a config maneuver.

> **NOTE (Session 33, 2026-08-05) — issue 25 hand-merged onto StockPhotoAgent `agent-work`,
> bypassing the orchestrator pipeline, by explicit Adi authorization.** Merge commit
> `f1e816e` (second parent `2978c486`, the escalated execution's own attempt-ref commit),
> touching only `tests/test_country_derivation.py` (+79 lines, one new file). Not an
> orchestrator-driven commit — no `CommitCreated`/`IssueCompleted` event exists for issue 25
> in `state/events.jsonl`; the event log's last word on issue 25 remains `IssueEscalated`
> (event 218). This note is the durable record of the out-of-band land.
>
> **Reason for bypass.** The execution (`25-e1`) exhausted its 30-turn budget
> (`num_turns` 33 ≥ `engine.max_turns` 30, confirmed live: `grep -o
> "\"num_turns\":[0-9]*" state/artifacts/25-e1/transcript.jsonl` → `"num_turns":33`;
> `config.yaml`'s `engine.max_turns: 30`) retrying `pytest` calls that were auto-rejected
> under the headless engine's `--permission-mode acceptEdits` + `--setting-sources ""`
> posture — every Bash invocation the child attempted came back `"This command requires
> approval"` / `non_execution_kind: user-rejected`, including a trivial `python -c
> "print(1+1)"` sanity check and one call marked `dangerouslyDisableSandbox: true`; 15
> distinct denied `Bash` calls total, zero successful pytest runs anywhere in the
> transcript. The turn-budget guard in `loop.py:231-243` then emitted
> `ExecutionFinished(outcome=REJECTED, taxonomy_category=needs-decomposition)` and
> `IssueEscalated` inline, in the same branch, with no call to `_validate()` anywhere in
> that code path — validation was not skipped by a decision, it was structurally
> unreachable for this execution. Traced from source this session, not inferred: `loop.py`'s
> post-execution branch reads only `result.timed_out` / `result.num_turns` /
> `result.exit_status` (the engine's own advisory signals), never anything the child
> self-reports — this is verdict (A) from the session's source trace.
>
> **Consequence / provenance asymmetry — record this precisely, do not let it blur into
> "issue 25 shipped like 23/24 did."** Issue 25 has **no `ReviewApproved` event** and
> **never passed the orchestrator's own validation gate** — unlike issues 23 and 24, both
> of which have a full `ValidationPassed`→`ReviewApproved`→`CommitCreated`→`IssueCompleted`
> chain in the event log. The 5 tests in `tests/test_country_derivation.py` were instead
> manually verified green by checking the file out of the unmerged commit into the
> then-current `agent-work` tree (both before the merge, against `db504eb`, and after,
> against the merge commit `f1e816e`): `C:\Python314\python.exe -m pytest
> tests\test_country_derivation.py -v` → `5 passed`, returncode 0, both times. That manual
> verification is real evidence the tests pass, but it is a human/session-level check, not
> a pipeline gate — the distinction matters for any future audit of what "shipped through
> the runtime" means for this repo.
>
> **Three distinct gaps this exposes. Gaps 1 and 2 were investigated and documented earlier
> this same session (Session 33) but are recorded here for the first time as NEXT.md items —
> the entry directly above this one covers two DIFFERENT Session-33 gaps (reviewer-rationale
> persistence, `run`'s missing per-issue scope flag) and is not their source. Gap 3 is new:**
> 1. Headless child cannot self-verify via Bash under the current permission posture — see
>    this note's own "Reason for bypass" paragraph above for the full mechanism
>    (`--permission-mode acceptEdits` + `--setting-sources ""`, confirmed from
>    `src/runtime/engine/claude_headless.py`'s `_command()`).
> 2. `config.yaml`'s validation command list (`project.validation.commands`) is a fixed,
>    hardcoded file set that excludes `tests/test_country_derivation.py` — so even if issue
>    25 HAD reached the orchestrator's validation gate, the new tests would not have been
>    exercised by it. Any future issue that adds a new test file has this same exposure
>    until the validation command list is made to discover new test modules rather than
>    naming them individually.
> 3. **New, distinct from 1 and 2: the turn-budget escalation itself is a third gap, not a
>    restatement of the permission gap.** A child that cannot self-verify (gap 1) will
>    predictably burn its turn budget retrying and escalate as `needs-decomposition` (gap
>    3) BEFORE the pipeline ever reaches validation (where gap 2 would additionally have
>    bitten it) — three independent failure modes chained into one observed outcome. Fixing
>    only one of the three would not have been sufficient to land issue 25 through the
>    normal pipeline; all three would need addressing (or the permission gap specifically,
>    since it is the root trigger of the chain) before trusting unsupervised runs not to
>    repeat this pattern on a future issue that also needs child-side self-verification.
>    None of the three is fixed or authorized for fixing this session — decomposition,
>    permission-posture change, and validation-command-list change are all still open,
>    tracked here only.

## 2026-08-05 — CORRECTION: issue-19 decomposition premise (session 34)

Correcting the session-32 and session-33 record. Does not invalidate any shipped work.

WHAT WAS RECORDED: issue 19 escalated as needs-decomposition and was read as genuinely too complex, prompting decomposition into 23/24/25.

WHAT IS ACTUALLY TRUE (VERIFIED, session 34):
- "needs-decomposition" / "decompose" is written at exactly one place in the codebase: loop.py:236 and loop.py:239-240, inside the branch guarded by `result.num_turns >= self.cfg.engine.max_turns` (loop.py:231-232).
- The code never inspects why the turn budget was exhausted. Genuine complexity and permission-denial turn-burn produce byte-identical payloads.
- Issue 19's ExecutionFinished (event_id 170) carries taxonomy needs-decomposition with exit_status 0, so it entered that branch and no other. Issue 19 hit the turn cap. It was never assessed for complexity by anything.
- The "too complex" reading was an inference from a label that does not carry that meaning.

WHAT THIS DOES NOT CHANGE: issues 23 and 24 shipped through the full pipeline with ValidationPassed + ReviewApproved (merges ec888d1, db504eb). Their work stands on its own gates. No retroactive rework required.

WHAT IT DOES CHANGE — decomposition is not the remedy for turn-budget escalation:
- Issue 25 was the smallest possible unit (one test module) and hit the same cap.
- Decomposing did not address the cause. It made 2 of 3 units small enough to finish under the cap; the third still failed.
- This is Gap 3 chaining off Gap 1 (headless child cannot self-verify via Bash under --permission-mode acceptEdits + --setting-sources ""), exactly as logged in session 33.

GAP 4 (NEW, session 34): num_turns is the deciding value in the escalation branch and is never persisted to any event. Issue 19's ExecutionSpawned records budget max_turns 30; no event records the turn count actually reached. The discriminating value is unobservable after the fact. Persisting it would make Gap 1's severity measurable rather than inferred.

COST/WASTE NOTE: 19-e1 produced end_commit 199db62b9dbd67e8c504be2396bfab1b9e60ce4f, then reset_hard(base) discarded it (loop.py:243). Turn-budget escalation throws away real work before validation ever runs. 19-e1 cost $0.9706 / 13,692 output tokens for a discarded result.

STATUS: diagnosis only. Gaps 1, 3, 4 remain UNAUTHORIZED for fixing — Adi's call.

ALSO STALE (unrelated, noted in passing): Issues.md STATUS: fields read "OPEN — not started" for issues 13-25, all of which are terminal in the event log (15 CommitCreated, 19 and 25 escalated). Issues.md is a static input file the runtime never writes back to. Do not use its STATUS field as state; the event log is authoritative.

## SCOPING GAP — single-issue live scope is not reliable

`max_executions_per_run` caps TOTAL executions per run, not the targeted issue.
If the target issue escalates early (e.g. duplicate-feedback guard trips before the
cap), the budget slot falls through to the NEXT queued issue and it ships
unplanned (session 40: issue 36 escalated → issue 37 shipped on the freed slot).

Mitigation until fixed: when running a single issue live, confirm the queue tail —
no unintended next-issue should be eligible to consume a freed slot. If manual
reject-injects are needed, VARY taxonomy_category so the dup-guard doesn't escalate
early.

Ref: events 381 (36 escalated), 389 (37 completed).
