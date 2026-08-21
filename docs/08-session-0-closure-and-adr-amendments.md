# 08 — Session 0 Closure & ADR Amendments

**Status:** ACCEPTED · **Date:** 2026-07-10
**Relationship to frozen docs:** This document extends the frozen design (docs 01–07). It adds ADR-18..20 and records the checklist-A1 verification result. It does not modify any frozen invariant, component, or schema. Where this document and doc 03 disagree, doc 03 wins.

---

## 1. Checklist A1 — Headless billing verification (RESOLVED)

**Finding (verified 2026-07-10 against Anthropic's Help Center):** The June 15, 2026 Agent SDK / `claude -p` billing split was **paused by Anthropic on its ship date**. As of today:

- `claude -p` (headless) draws from the normal Pro subscription usage limits — same pool as interactive use.
- No separate Agent SDK monthly credit is active or claimable.
- Anthropic has stated a revised plan will be announced before anything takes effect.

**Implications adopted:**
- There is no hard dollar-denominated ceiling specific to headless usage today; the constraint is the Pro plan's ordinary rate limits.
- The pause is explicitly temporary. ADR-09 budget protections are therefore **retained unchanged** (see §3).
- Re-verification is a standing gate item: re-check billing status **at the Phase 2 gate** and any time Anthropic announces a revised plan. Record each check in `config.yaml → billing.verified_on`.

Source of record: Anthropic Help Center article "Use the Claude Agent SDK with your Claude plan" (support.claude.com, article 15036540), June 15 update banner.

---

## 2. ADR-18 — Execution provider for v1: Claude Pro subscription, headless

**Decision.** v1 executes the Implementer role via `claude -p` authenticated against the user's Claude Pro subscription. No API key is configured in v1.

**Configurability.** Auth posture is a configuration value, not code:

```yaml
engine:
  provider: claude-headless      # only concrete engine in v1 (per ADR-08)
  auth_mode: subscription        # subscription | api_key
```

Switching to API mode later means setting `auth_mode: api_key` and supplying `ANTHROPIC_API_KEY` via environment — no orchestrator code changes. Note the mechanism: when `ANTHROPIC_API_KEY` is set in the subprocess environment, `claude` authenticates with it and bills pay-as-you-go; in subscription mode the orchestrator must ensure that variable is **absent** from the spawned environment to avoid silently billing the API. The engine wrapper owns this environment hygiene.

**Scope guard.** This does NOT introduce an engine abstraction seam. Per ADR-08, the engine seam remains un-abstracted until a second real harness exists. `auth_mode` is a parameter of the single concrete `claude-headless` engine, not a provider interface.

**Rejected alternatives.**
- *API key from day one:* more predictable metering, but incurs real per-token cost during the falsification run before the workflow has proven value; subscription cost is already sunk.
- *Max plan upgrade:* premature before the 20-issue verdict.

---

## 3. ADR-09 amendment note — Budget protections retained despite paused split

ADR-09 (budget manager) was motivated partly by the announced billing split. The split is paused (§1), but ADR-09 is **retained in full**, because: (a) Anthropic has committed to shipping a revised version with notice, and absorbing it must be a config change, not a redesign; (b) kill-criteria cost accounting (ADR-19) needs per-execution cost/turn/token metering regardless of who is billed; (c) runaway-loop protection is a correctness feature, not only a cost feature.

In subscription mode, where dollar cost is not directly metered, the budget manager tracks **proxy costs**: estimated tokens (from `claude -p` JSON output usage fields) priced at published API list rates. Cost-per-shipped-issue in ADR-19 is computed from this proxy. This is deliberately conservative: it prices the workflow as if the split were live, so the Phase 4 verdict remains valid under either billing regime.

---

## 4. ADR-19 — Pre-committed experiment kill criteria

**Decision.** The Phase 4 falsification run evaluates exactly these thresholds, committed now, before any code exists:

| Parameter | Value |
|---|---|
| Sample size | 20 completed issues |
| Continue if | Attempt-1 success rate ≥ 30% |
| Kill / redesign if | Attempt-1 success rate < 30% **OR** average proxy cost per shipped issue > **$3.00** |

**Definitions (binding):**
- *Attempt-1 success:* the first execution for an issue reaches COMMITTED (passes validation, passes review, pinning gate holds) with no retry.
- *Completed issue:* an issue that reached a terminal state (SHIPPED or FAILED). Abandoned/blocked issues do not count toward the 20 but are reported.
- *Proxy cost:* API-list-rate valuation of measured token usage per §3, summed over **all** attempts for the issue, divided by shipped issues only.

**Honesty clause (per User Constraints, doc 00 handoff):** thresholds may not be revised after the run begins. If the run fails a threshold, the verdict is Kill/Redesign — parameter tuning to re-run requires an explicit new ADR superseding this one, with the failed run's data attached.

### ADR-19 — CLOSED PASS (2026-08-11)

**Verdict:** kill-criteria met across two independent samples.

- **Sample 1** (n=20, issues 13–22 + prior 10, `run-20260803T050931Z`): attempt-1 17/20 = 85%; cost ~$0.36/shipped; no double-commit. Ref: handoff `HANDOFF_2026-08-03_session29-adr19-pass-holdpid-blocked.md`.
- **Sample 2** (n=19, issues 29–47): attempt-1 16/19 = 84%; cost $9.8269/16 = $0.61/shipped incl. wasted escalation spend; no double-commit; all shipped -e1 (Rule B strict). Escalations 36 (needs-human), 39/43 (needs-decomposition) are turn-budget/decomposition, not review rejections. Refs: `events.jsonl` 322–461; run_ids `run-20260810T002149Z`, `run-20260810T193401Z`, `run-20260810T201428Z`, `run-20260811T235441Z`.

Both bars: attempt-1 ≥30% PASS; cost/shipped ≤$3 PASS; $15 hard stop never breached.

Carried non-blocking: reviewer raw-response not persisted; reviewer model-string INFERRED.

Backlog: decompose 39, 43, 36.

**Clarification (2026-08-15) — relationship to the later full-backlog drain.**
Sessions 43–44 (2026-08-14, per `docs/handoffs/HANDOFF_2026-08-14_session43-first-live-drain.md` and `HANDOFF_2026-08-14_session44-backlog-drained.md`) subsequently ran the StockPhotoAgent backlog
to full terminal state — 0 PENDING, 0 ACTIVE, 74 DONE, 7 NEEDS_HUMAN, 21
NEEDS_DECOMPOSITION (`state/events.jsonl` last_event_id 843; see
`docs/handoffs/HANDOFF_2026-08-14_session44-backlog-drained.md`). That drain
is **not** additional ADR-19 sampling and does not itself need to satisfy
this ADR's sample-size/attempt-1/cost thresholds.

**Evidence hierarchy (binding, for any future reader of this section).**
**Sample 1 (n=20) alone already satisfies ADR-19's binding validation
requirement and both thresholds** — 20 completed issues (the ADR's exact
sample-size requirement), 85% attempt-1 (≥30% bar), ~$0.36/shipped (≤$3.00
bar) — with no dependency on Sample 2 to reach n=20 or to clear either
threshold. **Sample 2 (n=19) is additional corroborating evidence, not a
second required leg of the PASS verdict**: it independently reproduces the
same result on a different, later issue population, which strengthens
confidence in the verdict, but ADR-19's own text requires exactly one
20-issue sample, and Sample 1 is that sample on its own. Both samples were
closed and committed (`e9f5d5b`) before the session 43–44 drain began.
**Because Sample 1 alone already satisfies ADR-19, dedicated ADR-19 sampling
is not still owed** — the 74-DONE drain is not needed to, and does not,
independently satisfy this ADR; it is not evidence this ADR still needs.

The 74-DONE count is cumulative production history (it
necessarily includes the same issues counted in Sample 1 and Sample 2, plus
issues completed afterward); it was never run under a fresh pre-committed
experiment frame, and no attempt-1-success-rate or cost-per-shipped-issue
figures have been computed for that population in any committed document —
only terminal-state issue counts are recorded. **The 74-DONE drain does not
itself satisfy ADR-19** — it is not a substitute for, or additional leg of,
the sample-based verdict above. Recorded here so a future
session does not conflate "74 DONE" with a third ADR-19 sample or treat the
drain as evidence this ADR still needs to satisfy; it does not, and the
verdict above stands on its own two-sample evidence.

---

## 5. ADR-20 — Initial target repository: StockAgent; repository is configuration only

**Decision.** The v1 target repository is **StockAgent** (local path `C:\Projects\StockPhotoAgent`, working branch `agent-work`).

> ⚠ Naming discrepancy to resolve in config: the decision names the project "StockAgent" but the path is `StockPhotoAgent`. The path below is used verbatim as provided; correct it in `config.yaml` if the directory name differs on disk.

**Repository-agnosticism (binding constraint):** no component may hardcode a repository path, branch name, language, test command, or project layout. All repository-specific knowledge enters through exactly two channels:

1. `config.yaml → project.*` — path, branch, validation commands.
2. The Repository Adapter interface (doc 09 §7) — all git and filesystem operations against the target repo go through it.

The baseline-green requirement (doc 06) applies to StockAgent: its test suite must pass on `agent-work` before the first supervised run.

**Rationale.** Real project, safe to experiment on, immediate business value, demoable; and choosing a real repo forces the repository-agnostic seam to be honest rather than theoretical.

### ADR-20 — Amendment 1 (2026-07-26): enforce `cfg.project.branch` checkout before ingest

**Status:** Accepted. Amends ADR-20's binding constraint above (`config.yaml → project.*` carries the branch);
this closes a gap in enforcing that decision, not a new architectural mechanism.

**Gap.** `cmd_run` (`src/runtime/main.py`) read `cfg.project.branch` throughout startup —
`bind_reconciler(adapter, cfg.project.branch)` (recovery), `adapter.head_of(cfg.project.branch)`
(baseline health check) — but never enforced or verified that branch was actually checked out
on the target repo's working tree. Correctness depended entirely on ambient `HEAD` happening to
match `cfg.project.branch`; nothing in the runtime detected or corrected a mismatch. Recorded as
an open parked decision (`NEXT.md` §5, "Ingest branch-check gap") with two options: Option A
(explicit checkout) vs. Option B (accept as scoped risk). Option A is adopted here.

**Insertion point.** The checkout is enforced as a new step "5b" in `cmd_run`, immediately after
the adapter is constructed and **before** orphan reap / recovery / the baseline health check —
not immediately before ingest as a naive reading of the gap might suggest. Reasoning: recovery's
`bind_reconciler` binds its three seams (`preserve_residue`, `check_unwitnessed_commit`,
`check_dirty_workspace`) against `cfg.project.branch`, and the baseline health check's
`Validator.validate` runs validation commands against the physical working tree at
`cfg.project.repository`. Both are meaningless — recovery reconciling the wrong branch's state,
baseline-green asserting nothing about the configured branch — if enforcement happens only at
the ingest call site, after both have already run against whatever was on disk.

**Mechanism.** No adapter change. Reuses the existing `RepositoryAdapter.checkout_branch`
(`src/runtime/repo/adapter.py:100`, implemented at `src/runtime/repo/git_adapter.py:165-174`,
already called once in production for per-issue branches at `src/runtime/loop.py:204`) —
called as `adapter.checkout_branch(cfg.project.branch)`, deliberately **without** `create_from`:
`create_from` force-creates/resets a branch at a pinned commit (`git checkout -B`), correct for
disposable per-issue branches but wrong for the target repo's long-lived branch, which must only
be switched to, never force-reset.

**Failure-mode contract (fail-loud, no silent no-op).** `checkout_branch` already raises
`RepoError` for a dirty working tree (`git_adapter.py:166-170`); with no `create_from`, a
missing local branch surfaces as a nonzero `git checkout` exit, which `_git`'s `check=True`
(`git_adapter.py:52-75`) re-raises as the same `RepoError` — one `except RepoError` arm in
`cmd_run` covers both cases, printing to stderr and returning 1, matching the existing
`except ConfigError` / `except EngineError` arms. Detached HEAD is not a distinct case: plain
`git checkout <branch>` corrects it identically to switching from another named branch. Already
being on the target branch is an idempotent no-op by construction (`git checkout` exits 0); the
same `[startup] checked out {branch}` log line fires truthfully in both cases, so nothing is
silently skipped.

**Blast radius.** Confined to `src/runtime/main.py`; no event-schema or state-transition change
(confirmed: `grep -rn "checkout" src/runtime/events/ src/runtime/state/` — zero matches).

### ADR-20 — Amendment 2 (2026-07-27): recovery runs BEFORE checkout, not after

**Status:** Accepted. Re-sequences Amendment 1's placement of the branch-checkout step; does
not touch the checkout mechanism, the checkout guard, or the decision that a checkout must
happen before baseline/ingest — only WHEN relative to recovery.

**Gap.** Amendment 1 placed `checkout_branch(cfg.project.branch)` as step 5b, immediately
after adapter construction and **before** `reap_orphans`/`recover()`. Its stated rationale was
that recovery's `bind_reconciler` seams and the baseline health check "are meaningless" if the
wrong branch is on disk. Live fault-injection this session (Session 24, real `cmd_run`, real
`claude -p` child, orchestrator killed mid-execution against a disposable scratch repo —
evidence under `orphan-report/`, `NEXT.md` item 13) falsified that rationale for the recovery
half: a genuine crash leaves the tree checked out on a per-issue attempt branch
(`issue/N`, `loop.py:204`) with real uncommitted residue. `checkout_branch`'s own dirty-tree
guard (`git_adapter.py:166-170`) then refuses — by design, it does not force-reset — and because
the guard runs BEFORE recovery, recovery never gets a chance to clean the residue that would
have satisfied it. This is a standing deadlock, not a transient race: every subsequent
orchestrator start on that repo hits the identical refusal and exits 1 until a human
intervenes outside the runtime, because nothing in the startup path can reach the code that
would fix it.

**Why recovery never needed the branch pre-switched (verified from source, not assumed).**
`bind_reconciler`'s seams (`src/runtime/recovery/bindings.py`) operate two ways, neither of
which requires `cfg.project.branch` to be the current checkout:
- Read/compare operations (`check_unwitnessed_commit`'s `is_ancestor`/`find_merge_commit`,
  `check_dirty_workspace`'s `_expected_commit` fallback `adapter.head_of(target_branch)`) all
  resolve by explicit ref name (`refs/heads/<branch>`) via git plumbing (`rev-parse`,
  `merge-base`, `for-each-ref`) — independent of what HEAD currently points at.
- Mutating operations (`preserve_residue`'s `snapshot_commit`, `check_dirty_workspace`'s
  `reset_hard`) act on whatever is CURRENTLY checked out — which, in the crash case, is
  exactly the per-issue attempt branch the crash left behind, the correct target for residue
  capture, not `cfg.project.branch`.
- `snapshot_commit` (`git_adapter.py:176-184`) does `git add -A` (stages tracked, modified,
  AND untracked) then `git commit --no-verify`, leaving the tree clean (`is_dirty()` false)
  whenever it had something to commit. `check_dirty_workspace`'s `reset_hard`
  (`git_adapter.py:203-205`, `git reset --hard` + `git clean -fd`) independently guarantees a
  clean tree even if `preserve_residue` didn't run or didn't apply — it fires on
  `dirty OR head != expected`, not gated on branch identity.
- Net effect, confirmed by re-running the witnessed crash shape source-side line by line
  (not merely asserted): by the time `recover()` returns, the physical tree is unconditionally
  clean, on whichever branch it happens to be sitting on. `checkout_branch`, called
  immediately after, therefore always finds `is_dirty() == False` and succeeds.

**Doc 03 wins.** `src/runtime/recovery/reconciler.py`'s own module docstring states doc 03's
ordering law plainly: "a crash may only leave a missing FACT, which the reconciler
backfills... residue is preserved to an attempt ref, then `ExecutionCrashed` is emitted, then
the workspace is reset." Amendment 1's checkout-before-recovery placement inverted this for
the branch-checkout step specifically; per `CLAUDE.md` ("On any conflict between code and doc
03, doc 03 wins"), doc 03's ordering law governs, and Amendment 1's placement is corrected
here rather than left standing.

**New insertion point.** `checkout_branch(cfg.project.branch)` moves to a new step "7b" in
`cmd_run`, immediately after `recover()` returns and immediately before the reviewer
health/baseline checks (step 8) and ingest (step 9) — both of which still run strictly after
checkout, unchanged from Amendment 1's intent. Only the position relative to
`reap_orphans`/`recover()` (steps 6/7) moves; nothing else in Amendment 1's mechanism,
failure-mode contract, or blast-radius statement changes. The dirty-tree guard itself is
NOT weakened or made conditional — it is reached later, at a point recovery has already
guaranteed is clean, not bypassed.

**Evidence.** Session 24 (2026-07-27) scratch-repo fault injection, preserved on disk under
`orphan-report/` (`run2_stdout.log`: the pre-fix `CHECKOUT FAILED` exit, reproduced live) and
`orphan-scratch-repo/` (left dirty exactly as the crash produced it, for comparison). Full
mechanical trace of all three viability claims above (source line numbers,
`snapshot_commit`/`preserve_residue`/`check_dirty_workspace` behavior on the witnessed shape)
recorded in this session's transcript and `NEXT.md` item 13. Post-fix re-test (durability
harness both seeds + the same scratch injection re-run) is the gate for calling this item
done — see `NEXT.md` item 13 for the pass/fail criteria.

**Blast radius.** Confined to `src/runtime/main.py` (pure reorder of two existing step
groups, no new code paths); no adapter, event-schema, or state-transition change. Classed as
a `main.py` startup-composition change (same class as `NEXT.md` item 8), so it carries item
8's gates: full durability-harness re-run, 60/60, both seed 42 and seed 1337, required before
landing.

---

## 5b. ADR-21 — Engine fence is a denylist; strict "no credential access" is accepted as unclosable while Bash exists

**Status:** Accepted (Session 5, 2026-07-12). Supersedes the Session-4 forward-pointer that assumed `--allowedTools` would fence the engine.

**Context — the probe that forced this.** doc 02 §3 requires the engine get "read/write on the worktree only, no network push, no credential access." The Session-4 plan intended to enforce that with a `--allowedTools` allowlist, deferring the exact list to Session 5. A probe of `claude` 2.1.207 (Windows, subscription — the live runtime) falsified that mechanism:

- **`--allowedTools` does NOT restrict.** In `-p` mode a tool matching neither an allow nor a deny rule *runs*. `--allowedTools Read` still let Bash run `whoami`; `--allowedTools "Bash(echo:*)"` still let `whoami` run. True under `--permission-mode default` and `acceptEdits` alike. (Session 4's docstring claim that a non-allowlisted tool records a `permission_denial` is likewise false — corrected in `claude_headless.py` and doc 12.)
- **The denylist is the only working fence.** `--disallowedTools` is enforced, is *selective* at the `Bash(cmd:*)` pattern level (`Bash(curl:*)` denies curl while `echo hello` still runs), and is *chaining-resistant* (`echo ok && curl …` is denied by `Bash(curl:*)`; `echo START && git push` is denied by the `git push` rule even though `git push` is not the leading token).
- **Explicit flags compose with, and are not masked by, ambient `~/.claude/settings.json`; deny always wins.** The fence is therefore passed **entirely as explicit `--disallowedTools` flags** so it is self-contained and does not depend on any operator's settings.
- **Detection nuance:** a pattern deny populates `result.permission_denials` *and* yields a tool-result `is_error`; a whole-tool removal (`--disallowedTools Bash`) yields only the tool-result error with `permission_denials` empty. Transcript-based fence auditing must key on **both** signals. (The transcript is advisory only, ADR-07 — none of this gates a transition.)

**Decision.** The engine is fenced by an explicit denylist (`_DENY_TOOLS` in `engine/claude_headless.py`): whole tools `WebFetch`, `WebSearch`, `Task` (the sub-agent escape hatch), and `Bash(cmd:*)` patterns for network egress (curl/wget/ssh/scp/nc/telnet/powershell/pwsh/Invoke-WebRequest and `.exe` variants), the entire `git` CLI (`Bash(git:*)` — also enforcing ADR-07: the engine never touches git, the orchestrator owns it, which incidentally closes the push path), destruction/privilege (`rm`/`sudo`/`chmod`), and recursive engine spawns (`claude`/`npx`). All entries use the probe-proven one-word `Bash(cmd:*)` colon form.

**Accepted deviation.** doc 02 §3's strict "no credential access" is **structurally unclosable while Bash is available** — a shell can read a local file and egress via curl/python, and denylist whack-a-mole cannot reliably prevent it. Rather than cripple the engine (removing Bash entirely tanks the falsification metric by preventing build/test/explore), ADR-21 fences **egress + destruction + push + recursive-spawn** and accepts the residual local-read exposure. Compensating controls: no push path, egress tools denied, the engine never touches git, reconciler check 3, the *supervised* Phase-2 gate, and ADR-20's deliberately safe-to-experiment target (StockAgent). A **sanitized-env** hardening (spawn the engine under a credential-free HOME) is recorded as a pre-Phase-4 item, not built in v1.

**Rejected alternatives.** *Allowlist fence* — falsified above. *Remove Bash entirely* — closes egress but limits the engine to file edits, making attempt-1 success reflect the fence rather than the workflow. *Settings-file deny* — Session 4 proved `--settings` keys are silently dropped in print mode, so nothing settings-based is trusted; explicit flags were probe-verified instead.

### ADR-21 — Amendment 1 (2026-07-16, Session 7): whole-tool-removal detection signal changed at `claude` 2.1.211

**Status:** Accepted. Amends the "Detection nuance" bullet of ADR-21 above.
Enforcement is unchanged; this is a documentation/auditing amendment, not a fence change.

**What changed.** At `claude` 2.1.207, a whole-tool removal (`--disallowedTools WebFetch`) produced a tool-result `is_error` with `permission_denials` empty. At 2.1.211 (re-probed live, doc 14 §2.2 C3) the denied tool is instead **dropped from the session's init `tools` manifest entirely** — the model never attempts it: no `tool_use`, no `is_error`, no `permission_denials` entry. Controlled cross-check: C1's manifest (denying Task/WebFetch/WebSearch) lacked exactly those three; C3's (denying WebFetch only) retained the other two. Pattern-level denies (`Bash(cmd:*)`) are UNCHANGED and still produce **both** signals — a `permission_denials` entry AND a tool-result `is_error` (re-confirmed 2026-07-16, doc 14 §2.4 Probe 3: a denied `git init` populated `permission_denials` and yielded `is_error:true`, `.git` absent).

**Consequence for all future audit/metric logic (binding).** After 2.1.211 a whole-tool denial is NOT observable from the result stream — there is no attempt, no error, no denial record. The only evidence is the init `tools` manifest captured at spawn. Any "was a tool denied this run" logic — including Step 4's ADR-19 metric capture and any transcript audit — MUST key on **manifest ABSENCE in the init line**, never on a result-stream signal that no longer exists. Pattern denies keep both result-stream signals; audits must therefore branch on deny *kind* (whole-tool vs. pattern).

**QUEUED PREREQUISITE (init-manifest capture is not yet persisted structurally).** As of this session the init `tools` manifest is parsed only for `apiKeySource` (`src/runtime/engine/claude_headless.py:461-462`); the manifest itself is never extracted into `EngineResult` or the event log, surviving only as raw lines inside the archived transcript (`EngineResult.transcript_path`, written in `run()`). Therefore, **before any Step-4 ADR-19 "was a tool denied" metric can be built, a structured init-manifest capture must be added.** Mechanism is TBD — an engine-side artifact (parse the init `tools` list in `_parse_result` and expose it on `EngineResult`, advisory-only per ADR-07) versus an event-schema addition — and **doc 03 governs any event/state change**. Not built this session; no event-schema change made. Carried into `NEXT.md`.

**Assessment.** Enforcement is structurally stronger (the tool is invisible, not merely refused); the fence design (explicit `--disallowedTools` denylist) is unaffected and remains as accepted in ADR-21. Version-scoping discipline: the 2.1.207 behavior stays recorded in `claude_headless.py` as an explicitly version-tagged historical note (`[2.1.207 ONLY — …]`); re-pin on upgrade continues.

### ADR-21 — Amendment 2 (2026-08-07, Session 35): permission mode changed to bypassPermissions; Write-tool cwd-escape residual documented

**Status:** Accepted, landing with the Gap 1 fix commit.

**Change.** `_DEFAULT_PERMISSION_MODE` changes from `"acceptEdits"` to `"bypassPermissions"` (`claude_headless.py`). Driver: under `acceptEdits`/`default`, the CLI's own interactive Bash-approval heuristic denies every Bash `tool_use` in headless `-p` mode — including a single, non-chained, single-file pytest command — with no human present to approve it (`tool_result_meta.non_execution_kind="user-rejected"`), making self-verification structurally impossible for a headless child. VERIFIED across issue-26 (4/4 denied) and four controlled probes this session (single-command, a 4-mode matrix, a blast-radius probe, and an acceptEdits comparison probe). `bypassPermissions` is the only tested mode where a non-denied Bash command actually executes (`is_error:false`, real pytest stdout observed) while the denylist (`_DENY_TOOLS` / `--disallowedTools`) continues to deny curl, rm, AND git identically (`tool_result_meta.non_execution_kind="permission-rule"`) — confirmed mechanism-independent of the permission-mode value across every mode tested (default, acceptEdits, bypassPermissions).

**Accepted residual.** The `Write` tool has no cwd confinement under any tested permission mode. Host-verified (not self-report, via `Test-Path` on the real filesystem, not the child's narration): under `bypassPermissions`, a child wrote a file to an absolute path outside its assigned working directory with no prompt and no denial. This is a property of the fence's tool-scoping design (the denylist only covers specific `Bash(cmd:*)` patterns and a few whole tools — `WebFetch`/`WebSearch`/`Task` — never `Write`/`Edit`), not something introduced by this mode change. Whether the same escape is reachable under `acceptEdits` without a mechanism-level block remains **unconfirmed**: a same-prompt probe under `acceptEdits` produced a model self-refusal (the child recognized the prompt as a likely containment test and declined to attempt the write) rather than a fence-level denial or approval, so that comparison is inconclusive, not negative. Accepted as unchanged-risk for this fix — same class as ADR-21's original "Bash can read a local file" unclosable residual — and left open for a future session; not blocking this change.

**Re-pin.** This session's probes ran under installed CLI `2.1.224` (see the `VERIFIED CLI contract` header, `claude_headless.py:12-14`, updated accordingly).

**Assessment.** Fence design (explicit `--disallowedTools` denylist) unaffected; the mode value governs only the CLI's own approval-prompt behavior, which was never part of the fence's threat model (ADR-21 already names the denylist as the *sole* working restriction). The distinction between the two denial kinds observed this session — `non_execution_kind="user-rejected"` (the CLI's interactive-approval heuristic, gone under `bypassPermissions`) vs. `non_execution_kind="permission-rule"` (the denylist, present under every mode) — is the load-bearing evidence behind this amendment and should be the vocabulary used in any future audit of this fence.

### ADR-21 — Amendment 3 (2026-08-08, Session 36): Write/Edit cwd-escape structurally live (A, C permitted; B self-refused) — residual remains open

**Status:** Accepted, documentation only. No src/, config, or fence change. The residual named in Amendment 2 is NOT closed by this amendment.

**Context.** Amendment 2 recorded the `Write`-tool cwd-escape as an accepted residual but left the `acceptEdits` comparison inconclusive (a single self-refusal, not a fence signal) and never ran the destructive-overwrite case. This session ran three probe vectors under `bypassPermissions`, using the real `engine._command()` argv (`self._claude_exe` resolved via `shutil.which`, the full `_DENY_TOOLS` fence, `--setting-sources ""`) via `engine.run()` unmodified — no src/ edits — against a disposable sandbox outside both repos.

**Vector A — relative traversal, new file.** Write to `..\outside\newfile.txt` (relative to cwd) → **PERMITTED**. `permission_denials: []`, no `non_execution_kind`, file created at the resolved path outside the workspace. Session `2d479723`.

**Vector B — relative traversal, destructive overwrite of an existing file.** Write to `..\outside\victim.txt`, which already held content flagging itself as not to be overwritten → **SELF-REFUSED by model judgment, NOT a fence.** No `Write` tool_use was ever emitted; the model reconnoitered (`Bash ls`, then `Read`), read the target's warning content, and declined. `permission_denials: []` — there is no denial record because there was no attempt to deny. The file was unchanged (host-verified via `Get-Content` post-run: `ORIGINAL-CONTENT-DO-NOT-CLOBBER`). **Nothing in the argv would have stopped the Write had the model attempted it — this vector is UNWITNESSED as contained, and destructive overwrite remains structurally possible.** Session `fef9aceb`.

**Vector C — absolute path, new file.** Write to the literal absolute path `C:\...\outside\abs.txt` → **PERMITTED**. `permission_denials: []`, file created, confirmed via `Test-Path` (`True`). Session `050d79a2`.

**Assessment.** `Write`/`Edit` have no cwd confinement under any permission mode tested to date (`default`, `acceptEdits`, `bypassPermissions`) — pre-existing, not introduced by Amendment 2's `acceptEdits` → `bypassPermissions` change. Vectors A and C show the escape is mechanically live, not merely theoretical; Vector B shows the one guardrail observed so far is model self-restraint, which is not a structural fence and cannot be relied on (a differently-phrased prompt, a different model, or a future model version could attempt the same write with no argv-level obstacle). A structural fence (e.g., a pre-write path-confinement check, or a `--disallowedTools` pattern if one becomes expressible for `Write`/`Edit`) was considered this session and **deliberately deferred — this is a documentation-only session, no src/ change**. The residual named in Amendment 2 stays **open, not closed**, now with host-verified evidence for both the new-file and absolute-path cases and one (non-dispositive) self-refusal on the destructive case.

**Evidence base.** Raw stream-json transcripts for all three probes: `$env:TEMP\wtprobe\artifacts\probe-A\transcript.jsonl`, `...\probe-B\transcript.jsonl`, `...\probe-C\transcript.jsonl` (sandbox is disposable/local, not committed to either repo).

---

## 5c. ADR-22 — Engine-child ambient-hook isolation (contamination of the engine cwd)

**Status: ACCEPTED (2026-07-16, Session 8).** Decision gated by external review; endorsed selection: **Option A-empty + Option B (config-driven), B under a sunset condition** — recorded precisely in "Accepted decision" below. Originally PROPOSED Session 7, 2026-07-16. Step 3 unblocks on this acceptance plus the landed mechanism.

**Context — the finding.** Every `claude -p` child the engine spawns writes an unrequested `knowledge/` tree (`.gitignore` 8 B, `capture-rules.md` 684 B, `.sweep/`, an empty project dir) into its cwd. The cause is the operator's **user-scope** `~/.claude/settings.json`, which registers `SessionEnd`/`PreCompact` hooks running `~/.claude/historian/historian-sweep.sh` (the engineering-historian vault bootstrap). User-scope settings load in every `claude` process on this machine, including engine children — this is global config, not a skill auto-load and not parent-session inheritance (VERIFIED, doc 14 §2.3 + §2.4). The hook's `run_pipeline()` does the `mkdir`/seed writes **before** its own triviality gate, so the write happens even though the engine passes `--no-session-persistence` (no transcript ⇒ the sweep then stops at "SKIP no transcript"; the model call and its `history(auto):` auto-commit never fire *on the engine path today* — but would if `--no-session-persistence` were ever dropped, which is strictly worse: an unwitnessed commit into the target repo).

**Why it blocks Step 3.** `GitAdapter.is_dirty()` is `git status --porcelain` non-empty (`src/runtime/repo/git_adapter.py:108`); the two un-ignored files under `knowledge/` show as `?? knowledge/` ⇒ dirty on every run ⇒ reconciler check 3 trips ⇒ the smoke is a guaranteed false failure, and at worst masks a *real* dirty-tree signal. The hook is **async and can land after `run()` returns** — even after a `reset_hard`/`clean -fd` — so any observe-around or clean-up-after approach races; only prevention-at-source is deterministic (doc 14 §2.3 correction note). Contamination is **4/4** across the Step-2 probes, not 3/4.

**Probe evidence (doc 14 §2.4, VERIFIED live at 2.1.211, 2026-07-16).** Positive control (no suppression) contaminated at t=4 s; `apiKeySource=none`. All suppression forms below stayed clean for a full 450 s poll with `apiKeySource` unchanged from the `"none"` baseline.

### Options

**Option A — settings-source isolation: add `--setting-sources` to the engine argv.**
User-scope settings (and their hooks) never load in the child. Two forms probed, both clean, both auth-unaffected:
- **A-empty (`--setting-sources ""`) — PREFERRED.** Loads no settings scope at all. VERIFIED clean (§2.4 Probe 2), CLI accepts the empty value (`rc=0`). Fence intact under it (§2.4 Probe 3: denied `git init` still produced `permission_denials` + `is_error`, `.git` absent).
- **A-projlocal (`--setting-sources project,local`).** VERIFIED clean (§2.4 Probe 1) — but still loads *project/local* scope **from the child cwd, which on the production path is the target repo**; a `.claude/settings.json` planted in a target repo would then be a cross-run config-injection/persistence vector. Adopt only with that residual project-scope surface recorded as an explicit open limitation.
- *For:* general — suppresses *any* operator's ambient hooks on any machine, not just this historian; aligns with ADR-21's self-containment principle ("the fence does not rely on ambient settings"); a concrete first slice of the pre-Phase-4 sanitized-env hardening already on the roadmap; no coupling to a third-party tool's internals.
- *Against:* a settings-machinery mechanism under a load-bearing invariant (the exact class ADR-21 warns about, and `--settings` keys once surprised us by being silently dropped in `-p` mode) — mitigated here by the direct probes above, which must be re-run on CLI upgrade.

**Option B — targeted hook suppression: set `HISTORIAN_SWEEP_ACTIVE=1` in the child env.**
The hook still fires but hits its own recursion guard (`historian-sweep.sh:51`) and exits before any write. VERIFIED clean (§2.4 Probe 4). To honor "config only, never hardcode machine specifics in src/", implement generically as `config.yaml → engine.child_env: {…}` merged in `_hygienic_env()` (the ADR-18 strip still wins); the machine-specific var name lives in config, src/ stays generic.
- *For:* surgical, near-zero risk to CLI semantics (no new flags, no settings machinery); cheapest to verify; uses the tool's own documented guard.
- *Against:* couples config to one ambient tool's private variable name (a historian rename/upgrade silently reintroduces contamination with no runtime signal); protects against exactly this hook, not ambient hooks as a class.

**Option C — workspace-level exclusion: tolerate contamination, blind check 3 to `knowledge/`. REJECTED.**
A config-driven ignore glob in `is_dirty()`, or `knowledge/` in the target repo's `.gitignore`/`.git/info/exclude`. *Rejected because* it **masks real signals** — any future engine write under `knowledge/` becomes invisible to check 3, weakening the I1 clean-base guarantee the whole durability layer leans on; it ships operator artifacts permanently into a real target repo; it does nothing about the auto-commit hazard if `--no-session-persistence` is dropped; and a `.gitignore`-based exclusion makes the residue *survive* `reset_hard`'s `clean -fd` (`-x` omitted), accumulating in the target. Largest conceptual change for the least integrity.

**Option D — fix the historian's own bug (complementary, outside this repo).**
The sweep writes the vault bootstrap *before* checking a transcript exists; moving that check above the `mkdir`/seed writes would stop it writing vaults into `-p` children's cwds while leaving real sessions intact. Fixes the root cause for every consumer on this machine — but it is ambient operator tooling the runtime **cannot depend on** (any machine/upgrade may differ), so D alone is not an acceptable fence. Recommend only as hygiene alongside A or B.

### Recommendation
**A-empty as the durable fix; B (config-driven) as an immediate belt-and-braces layer; D as optional operator hygiene; C rejected.** The two mechanisms compose (deny-in-depth). **B is removable once A has survived one CLI upgrade cycle with the §2.4 probes re-run green — recorded as a sunset condition, not a permanent layer.** If a future upgrade shows `--setting-sources` unreliable in `-p` mode, fall back to B alone and record A's falsification here (mirroring the ADR-21 allowlist precedent).

### Accepted decision (2026-07-16, Session 8 — gated by external review)

The endorsed selection is **Option A-empty + Option B (config-driven), B under a sunset condition**:

- **A-empty — `--setting-sources ""` appended to the engine argv.** Preferred over A-projlocal because the empty value loads **NO settings scopes at all**, whereas `project,local` would still load project/local scope **from the child cwd — i.e. the target repo** — leaving a cross-run config-injection/persistence vector (a `.claude/settings.json` planted in a target repo would load on the next run). Witnessed in doc 14 §2.4 Probe 2: CLI accepts the empty value (rc=0), clean through the full 450 s poll, `apiKeySource` unchanged from the `"none"` baseline; fence intact under it (Probe 3).
- **B — `HISTORIAN_SWEEP_ACTIVE=1` merged into the child env via config (`engine.child_env`).** The machine-specific variable name lives in **config only**; `src/` stays generic (a `child_env` dict merged in `_hygienic_env()`, with the ADR-18 strip list applied last and always winning). **Sunset condition:** B is removable after one clean CLI-upgrade cycle in which the A-empty re-pin probes (below) pass.
- **C — rejected** (as drafted above: masks real signals, weakens the I1 clean-base guarantee).
- **D — optional operator hygiene** (separate repo, handled independently; as drafted above — never a fence the runtime depends on).

**Upgrade re-pin discipline (binding).** `--setting-sources ""` joins the existing upgrade re-pin discipline. On any `claude` CLI version bump, **before the engine runs against a real repo**, re-witness in scratch:
1. a Probe-0-style **control** (no suppression) still shows contamination — the vacuity guard proving the probe can detect the failure mode;
2. a Probe-2-style run with `--setting-sources ""` is still **accepted (rc=0)**, still **CLEAN at WAIT=450 s**, and `apiKeySource` still matches the baseline.

The witnessed procedure is doc 14 §2.4; re-run it as written.

### Gate chain before any mechanism lands (none of this happens while Status = Proposed)
Probes passed (done, §2.4) → **Adi selects an option** → ADR-22 marked Accepted → mechanism lands in `src/`/`config.yaml` (with new tests if `engine.child_env` is added) → Step 3 unblocks. `src/` changes are legitimate only as the implementation of an Accepted ADR. *(Gate satisfied Session 8: acceptance recorded above; mechanism landing recorded in doc 14 §2.5.)*

---

## 5d. ADR-23 — Validation-command toolchain resolution and child-env hygiene

**Status:** ACCEPTED · **Date:** 2026-07-25 (Session 14). Options selected by Adi this session (both forks below signed off explicitly). Rule 1 + rule 2 land immediately; rule 3's mechanism (Phase 2) is decided but NOT yet built — it lands under its own gate chain, recorded at the end of this section.

**Problem.** `Validator._run_once` (`src/runtime/validation/runner.py:90-94`) spawns `project.validation.commands` via `subprocess.run(cmd, cwd=workspace, shell=True, …)` with **no `env=`** — the child inherits the orchestrator's entire environment. The engine path does the opposite (`claude_headless.py:294` passes `env=self._hygienic_env()`, ADR-18 strip applied last). **ADR-18 governs the engine child only; nothing governs the validator child.** Consequence: a validation verdict is currently a function of `(tree, operator shell state)`, not of `(tree)` alone — which is inconsistent with doc 03 / ADR-11 `validated_commit` pinning (the gate is meant to be a fact about a tree hash) and with ADR-15's consequent claim that verdicts approve a tree and are therefore cacheable.

**Evidence (VERIFIED live 2026-07-25; full probe set in the Session-14 record).**
- The configured command, run through the Validator's exact spawn shape, failed `ModuleNotFoundError: No module named 'PIL'` (exit 2). Bare `python` resolved to `C:\Projects\issue-runtime\.venv\Scripts\python.exe` — this repo's own venv, not the target's.
- With `VIRTUAL_ENV` unset and `.venv` off PATH, the *same* command on the *same* commit resolved to `C:\Python314\python.exe` and behaved differently. **The verdict flips on operator shell state alone.**
- An **absolute** interpreter path does NOT protect the child: with `PYTHONPATH` inherited, an injected `sitecustomize.py` **executed automatically** inside the validation subprocess before the target code. Absolute paths pin *which interpreter runs*, not *what it inherits*.
- `VIRTUAL_ENV=""` is still `in os.environ` (True) whereas unset is False — **empty ≠ absent**, mechanically. Any overlay that can only *set* cannot neutralize a variable that tools test by membership.
- A near-empty env (`env -i`) did **not** break Windows stdlib (`import ssl, socket, tempfile` → ok, exit 0) — recorded because it disproves the assumed blocker against option F below.

**Decision — two normative rules plus one mechanism.**
1. **Commands are self-contained.** `project.validation.commands` MUST name an absolute interpreter/toolchain path. The runtime resolves nothing: it does not detect venvs, inspect target-repo layout, or infer a language. Preserves the CONFIG-ONLY rule; requires no `src/` change.
2. **Commands name explicit targets.** Commands MUST name specific test targets — never a bare runner, directory, or glob relying on discovery. *Evidence:* StockPhotoAgent's only two pytest-collectible files (`test_button_selector_only.py`, `test_login_only.py`) are live credentialed browser automation (keyring credentials, non-headless Chromium, hardcoded batch UUIDs against a third-party site). A discovery-based command would execute them as part of a gate.
3. **Mechanism — `project.validation.env` (Phase 2).** A config-supplied dict merged into the validation child env where **a null value means unset**. `src/` stays language-agnostic: merge non-null keys, pop null keys; it never learns what `VIRTUAL_ENV` means. Mirrors ADR-22's `engine.child_env` precedent — machine-specific names live in config, `src/` stays generic.

**What this claims, and what it does not.** Phase 2 **closes the enumerated ambient vectors** (`PATH`, `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME`), including the absent-vs-empty distinction additive-only merging cannot express. It does **NOT** eliminate the unenumerated tail: any inherited variable not named in config still reaches the child. The supportable claim is *"known vectors closed; unenumerated tail documented, not closed"* — **not** "the verdict is restored to a pure function of the tree." An earlier draft of this decision asserted that stronger claim and it was **withdrawn under review as unsupportable**; it is recorded here as withdrawn rather than quietly dropped.

**Options considered.**
- **A — self-contained commands.** ADOPTED as rule 1. *For:* zero `src/` change; honors CONFIG-ONLY; works today; the config author already owns the command string. *Against:* necessary but NOT sufficient — pins the interpreter, not the inherited env.
- **B — target-repo venv auto-detection in `src/`. REJECTED.** Hardcodes language and layout convention into `src/`, which the project's hard rules forbid; and would not have worked anyway — StockPhotoAgent has no venv directory.
- **C — target repo declares its interpreter by convention. REJECTED.** Invents a cross-repo contract every future target must adopt, and makes the runtime depend on target-repo cooperation — the class ADR-22 Option D already rejected as "ambient tooling the runtime cannot depend on."
- **D — additive-only `validation.env`, exactly mirroring `engine.child_env`. REJECTED.** Tightest precedent match and smallest delta, but it cannot unset; `VIRTUAL_ENV` — the vector behind this session's bug — would remain leaked *by construction*, for no meaningful saving over E.
- **E — additive + null-unset. ADOPTED as rule 3.** Closes the identified live vectors at near-minimal `src/` cost, keeps `src/` language-agnostic, and states a claim defensible under audit.
- **F — allowlist base (env built from empty + only listed vars). DEFERRED — explicitly not rejected on feasibility.** The only shape that closes the unenumerated tail, and the assumed blocker was disproved (see evidence). Deferred because its failure mode — a missing enumerated var surfacing as a false-red baseline — refuses startup under ADR-20 and would spend ADR-19 budget on environment debugging rather than the experiment it is meant to fund. Adopt on the trigger below, not on a date.

**Escalation trigger (Phase 2 → option F).** Escalate if **any one** is observed. Each is detectable from signal that already exists — this is a condition, not a "revisit someday":
- **T1.** Two validation runs at the same `validated_commit`, same config, same overlay produce different verdicts. *Detector:* the existing `ValidationResult.flake_retries` counter — a pass-on-retry is already recorded as flaky, so a nonzero flake rate on a suite with no known nondeterminism is the signal; no new instrument required.
- **T2.** A post-Phase-2 failure log shows a module-resolution/toolchain error not attributable to the target repo's own code — i.e. this session's failure shape recurring after the enumerated vectors are closed.
- **T3.** The env witness (below) shows a variable *outside* the enumerated set differing between two runs whose verdicts differed.

**Sequencing (binding).**
- Rules 1 + 2 and the `config.yaml` fix land immediately (Phase 1) and unblock precondition #1's *interpreter* defect.
- The **watched, single-issue diagnostic smoke MAY proceed** on the rule-only fix, provided the env witness below is captured for that run. A contaminated result in a supervised probe is informative, not corrupting.
- The **ADR-19 20-issue measured sample MUST NOT start until Phase 2 has landed and been verified.** Those verdicts are consumed once as kill-criteria evidence under a hard budget; contamination there is permanent and undetectable after the fact.

**Env witness (required mechanism for any pre-Phase-2 live run).** Scratchpad-only witness script, same pattern as the ADR-22 witnesses (`witness_synth_control.py`, `witness_repin_2_1_215.py` — uncommitted, never in `src/`), run in the *same shell that launches `main.py run`*, writing a JSON record alongside that run's validation artifacts under `state/artifacts/<execution_id>/validation/`. It must capture **from inside a child spawned with the Validator's exact `subprocess.run(shell=True, cwd=repo)` shape** — parent-side capture alone is not a witness of what the child saw:
- `PATH`, `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME` — each as present/absent **plus** value, so absent-vs-empty stays distinguishable;
- `sys.executable`, `sys.prefix`, `sys.version`;
- the `validated_commit` and a UTC timestamp.

Without this, "the smoke is watched, not silently recorded" is a promise with no mechanism — a shape this project does not accept elsewhere.

**Non-vacuity requirement for baseline green (Step-3 precondition #4).** A zero exit code alone does not establish a baseline. Before precondition #4 may be marked MET, the configured gate must be witnessed **non-vacuous once**: collected count > 0, AND a deliberate mutation to the code under test turns it red. Same discipline already applied to the crash harness (mutation-tested; R1 / fixture `f5`), and the direct analogue of ADR-22's vacuity guard — a green gate that collects nothing is the same class of error as a probe that cannot detect its own failure mode. Concrete instance: with the correct interpreter, the currently-configured target returns pytest exit 5 (`collected 0 items`), so the command as configured can never produce a meaningful pass.

### Gate chain before Phase 2's mechanism lands (rule 3)
ADR-23 Accepted (done, above) → Phase 1 (docs + `config.yaml` command line + NEXT.md) committed → **separate session** for `src/`: `ValidationCfg.env` added to the schema (note `extra="forbid"`, `src/runtime/config.py:28` — the key does not exist until then, so `validation.env:` MUST NOT appear in `config.yaml` before it) + `runner.py` env construction + new unit tests asserting on the built env dict (result-shape, not call-order) → unit suite green → **durability harness 60/60 on BOTH seeds 42 and 1337** (gating because `src/` logic changes) → Phase 2 complete. `src/` changes are legitimate only as the implementation of an Accepted ADR.

### Phase 2 status note (Session 15, 2026-07-25) — mechanism LANDED + VERIFIED; end-to-end differential DEFERRED
The Phase 2 `src/` mechanism landed and passed its full gate chain this session: `ValidationCfg.env` schema (declared field, `extra="forbid"` verified still live), `Validator._child_env()` (pop-from-**base** single-pass merge, `None` = unset; passed as `env=` to the validation `subprocess.run` which previously passed none), both `main.py` `Validator(...)` call sites wired identically, 6 new result-shape unit tests (the load-bearing membership-absence test verified RED under a pop-from-overlay mutant, then restored). Unit suite **112/112** (identity-confirmed: 6 new + 106 baseline unmoved). Durability harness **60/60 seed 42, 60/60 seed 1337** (separately). A scratchpad-only live-child witness confirmed `VIRTUAL_ENV` genuinely ABSENT in a real child spawned through the Validator's exact `subprocess.run(shell=True)` shape (absent-vs-empty / probe 7 held at the OS boundary), with the unenumerated tail confirmed still open.

**The end-to-end differential specified above ("Env witness" + the red-before/green-after divergence check) was NOT performed. It is DEFERRED behind a THREE-PART AND — each condition independently sufficient to block, and fixing any ONE alone does NOT unblock the differential; ALL THREE must hold before it can run as a genuine verification (not a tautology):**
- **(a) Env-witness script not built** — correctly out of scope this session (a separate, uncommitted, scratchpad-only build per the "Env witness" spec above).
- **(b) Precondition #4 non-vacuity fails** — the currently-configured target (`tests\qc\test_qc_rules.py`) collects **0 items** (pytest exit 5) regardless of interpreter; a StockPhotoAgent-side gap. A differential against a target that collects nothing compares two vacuous runs, so the delta is vacuous — the same class of error the non-vacuity requirement above names. **Note explicitly: fixing #4 alone does NOT unblock the differential** — (a) and (c) still stand.
- **(c) The "before" half is unwitnessable for this change** — Phase 2 code now exists; ADR-23 requires the check go red-before / green-after to be a verification rather than a tautology, and a prior session's probes are not this session's live observation. **A `git stash` reconstruction does NOT satisfy this** — a stashed pre-mechanism state is *simulated*, not witnessed; that is a semantic defect in the evidence, not a sequencing inconvenience to engineer around. The deferred session must either observe "before" live AHEAD of the next mechanism change, or record the honest claim as *"mechanism verified at unit + live-child level; end-to-end differential not performed"* and label it exactly that. A stashed before must never be quietly upgraded to a witnessed one.

**Supportable claim as of Session 15:** *the Phase 2 mechanism is verified at the unit + live-child level* (genuine — the `VIRTUAL_ENV`-absent-in-child witness is real evidence the merge reaches the OS boundary). The stronger claim — that the StockPhotoAgent verdict is now shell-state-independent end-to-end — is **NOT** made this session; it remains gated on the three-part AND above.

---

## 5e. ADR-15 — Amendment 1 (2026-07-27): GC scope corrected to the completing execution, not the whole issue

**Status:** Accepted. Corrects ADR-15's original decision text (doc 05: "Namespaced
attempt refs (`refs/attempts/<issue>/<execution>`) for every execution including
failures/crash residue, committed before any reset; diffs always `git diff
start..end`; GC refs on completion.") — the phrase "GC refs on completion" was
ambiguous on scope (issue vs. execution) and the shipped implementation resolved
that ambiguity the wrong way, contradicting the decision's own stated purpose.

**Gap.** `loop.py`'s `_commit_sequence` GC'd attempt refs on `IssueCompleted` by
calling `delete_attempt_refs(issue_id)` — issue-scoped, deleting every ref under
`refs/attempts/<issue_id>/*`, not just the completing execution's own ref. Real
fault-injection this session (NEXT.md item 14, surfaced by item 13's GATE-3
re-test) witnessed the consequence: a crashed execution's residue ref
(`refs/attempts/1/1-e1`), durably written by recovery's `preserve_residue`
moments after the crash, was silently deleted the instant a *different*
execution of the same issue (`1-e2`, the retry) completed — leaving the residue
commit dangling, one `git gc` from permanent loss, while the `ExecutionCrashed`
event's `residue_ref` field kept asserting it was preserved. This directly
contradicts ADR-15's own stated purpose: attempt refs are named as existing
specifically "including failures/crash residue" — evidence worth preserving,
not disposable the moment the issue as a whole happens to resolve via a
different attempt.

**Correction.** GC on `IssueCompleted` is scoped to the **completing
execution's own ref only** (`refs/attempts/<issue>/<completing_execution_id>`).
This is safe and non-leaking for the one ref in scope: by the time
`IssueCompleted` fires, that execution's `end_commit` is already a parent of
the merge commit just landed on the target branch (`loop.py`'s
`_commit_sequence` is a strict three-step ladder — `CommitIntent` →
`merge_to`/`CommitCreated` → `IssueCompleted`+delete — each step returning
immediately after emitting its fact, so the delete step is only ever reached
on a later invocation than the merge step; witnessed directly against the
Session-24 scratch run: `git merge-base --is-ancestor <1-e2 end_commit>
agent-work` → exit 0), so its content stays permanently reachable through
real branch history regardless of whether the attempt ref itself survives.
Deleting it is genuine GC, not evidence loss.

**Residue lifecycle (does a crashed execution's ref ever get GC'd?).** Not by
this mechanism, and not automatically at all under this amendment: a crashed
execution's residue ref is retained **indefinitely** once written. No event in
doc 03's frozen vocabulary marks "this crash's evidence is no longer needed,"
and `ExecutionCrashed` is itself doc 03's terminal state for that execution
("EXECUTING is abandonable, never resumed") — there is no later event to hang
a reap on. Cost is bounded: one extra ref + one extra (typically small) commit
object **per crashed execution**, not per execution overall; crashes are the
exception path (Session 22's live smoke: 5/5 attempt-1, zero crashes), so this
is "keep abandoned/crashed attempts forever," not "keep everything forever" —
the same cost class as a CI system retaining failed-build artifacts longer
than successful ones. If accumulated crash-residue growth ever becomes a real
concern in practice, a dedicated periodic reap mechanism — decoupled from
`IssueCompleted`, using `is_ancestor` against the target branch as its "safe
to discard" predicate — is a candidate **future, separate** ADR. It is
deliberately not folded into `IssueCompleted`'s GC path now, because that
exact conflation (issue-done implies all-this-issue's-evidence-is-disposable)
is item 14's root cause.

**Mechanism.** `RepositoryAdapter.delete_attempt_refs(issue_id) -> int`
(issue-scoped) is replaced by `delete_attempt_ref(issue_id, execution_id) ->
bool` (single-ref-scoped), mirroring `set_attempt_ref`'s per-execution
signature. `loop.py:339` (the sole production caller) now passes
`ex.execution_id` alongside `issue`. The old issue-scoped method is removed
entirely, not left dormant beside the new one — `git_adapter.py`'s
`delete_attempt_refs` had exactly one caller in `src/`, so retaining the
issue-scoped bulk-delete unused would leave a foot-gun a future call site
could reintroduce this same defect through.

**Blast radius.** `src/runtime/repo/adapter.py` (interface),
`src/runtime/repo/git_adapter.py` (implementation), `src/runtime/loop.py`
(call site) — no event-schema or state-transition change (`IssueCompleted`'s
shape is unchanged; this is evidence housekeeping, not state-machine
behavior), no change to `bindings.py`'s crash-residue *write* path
(`preserve_residue` was already correct — the bug was purely on the delete
side). Classed as a `src/runtime` Git/recovery-behavior change, same class as
ADR-20 Amendment 2: gated on the full durability harness re-run (60/60, both
seed 42 and seed 1337) plus a targeted scratch re-test asserting the inverse
of item 14's finding — the crashed execution's residue ref survives issue
completion, the completing execution's own ref is correctly gone, and the
residue commit is not dangling in `git fsck`.

---

## 5f. ADR-24 — Explicit no-validation contract: `acknowledged_no_gate`

**Status:** ACCEPTED · **Date:** 2026-08-17. Drafted from `docs/17-issue-
b-no-validation-contract-spec.md` (approved) and `tasks/plan.md`'s Phase 1
evidence package, per the workflow CLAUDE.md and doc 17 require: ADR
review precedes any Issue B `src/` change, not the reverse. This ADR
authorizes the *architecture*; it does not itself authorize `/build` —
implementation still proceeds through Issue B's own five-gate +
60/60-both-seeds floor (doc 17 §5, `tasks/plan.md` Phase 7), and a second,
later compliance check against the *landed* diff is required before Issue
B may be called done (`tasks/plan.md` Unit 7).

**Problem.** `ValidationCfg.commands` (`config.py:32`) currently requires
`Field(min_length=1)`, and `Validator.__init__` (`validation/
runner.py:69-70`) independently raises on an empty command list — two
enforcement points, no escape hatch. Some target repositories (or some
phases of onboarding a repository, before a real check exists) have no
meaningful automated validation command to configure. Today this means
`draindeck init` refuses to write a config at all for such a repository
(doc 16 §2 "Issue A" subsection), and no config can ever represent "this
repository is intentionally running without a validation gate" — only
"validation configuration is incomplete." The gap is real: an operator
who wants to run Draindeck against such a repository has no path other
than inventing a fake command that either always passes (worse than no
gate — it fabricates false assurance) or always fails (blocks every
issue). This ADR decides whether, and how, to add a genuine no-gate path
without ever letting an empty command list mean "no gate" *by accident*.

**Evidence (VERIFIED this session, against HEAD `ba447e1`, before any
Issue B `src/` change exists).**

*Evidence 1 — state-transition consumers depend on event TYPE and
`validated_commit`, never on `gate_results` length.*
- `state/transitions.py:58-59`: `(ExecutionState.VALIDATING,
  EventType.VALIDATION_PASSED): lambda p: ExecutionState.REVIEWING` — the
  transition function is a constant lambda; it receives the event payload
  (`p`) and **ignores it entirely**. The state reached depends only on
  which event type fired, never on the payload's contents.
- `events/projections.py:421-422`
  (`_execution_transition`'s `EventType.VALIDATION_PASSED` branch):
  `view.validated_commit = ev.payload.get("validated_commit")` — the only
  field read off this event anywhere in the projection layer.
  `gate_results` is never accessed by `_execution_transition`
  (`events/projections.py:403-429`, read in full this session) or by
  `StateProjection.digest()` (`events/projections.py:141-168`) — the
  digest's execution tuple (lines 144-149) includes `validated_commit`
  but not `gate_results`.
- `ValidationReport`'s documented shape (doc 03:104,
  `{schema_version, execution_id, validated_commit, gates:[...],
  flake_retries, passed}`) places no minimum length on `gates`; `doc
  03:41-43` states `REVIEWING`'s precondition as
  "`ValidationReport(passed)` for same hash" — a boolean plus a hash, not
  a claim about how many gates ran.

*Evidence 2 — recovery/reconciliation does not inspect validation-result
content.* `src/runtime/recovery/` (all three files —
`bindings.py`, `containment.py`, `reconciler.py`) grepped this session for
`gate_results`, `ValidationPassed`, `ValidationFailed`, and
`validated_commit`: **zero matches in any file.** No reconciler seam
(`preserve_residue`, `check_unwitnessed_commit`, `check_dirty_workspace`)
branches on, counts, or otherwise depends on the length or content of a
`ValidationPassed` event's `gate_results`.

*Evidence 3 — replay experiment (pre-implementation architectural
evidence; no `src/`/`tests/` change persisted).* Using a scratchpad-only
script (`adr24_replay_probe.py`, uncommitted — same convention as ADR-23's
`witness_synth_control.py`/`witness_repin_2_1_215.py` witnesses, doc 08
§5d), a legal event sequence was hand-built with TODAY's unmodified
`events/schema.py`/`events/projections.py` (`IssueCreated` →
`IssueActivated` → `ExecutionSpawned` → `ExecutionFinished(outcome="OK")`
→ `ValidationPassed(validated_commit=..., gate_results=[],
flake_retries=0)`) and replayed through `StateProjection().rebuild(...)`.
**Observed result:** no exception raised; the execution reached
`ExecutionState.REVIEWING` (matching the transition table's
`VALIDATING`→`REVIEWING` edge exactly); `validated_commit` was set
correctly on the resulting `ExecutionView`; `StateProjection.digest()`
computed successfully. A contrasting run with the same sequence but a
**non-empty** `gate_results` list produced the **identical** downstream
execution state (`REVIEWING`) — direct, observed confirmation that
today's state machine does not distinguish an empty from a populated
`gate_results` list in any way. This is evidence the premise holds against
the codebase *as it exists right now*, independent of whether `Validator`/
`Config` can yet produce such an event (they cannot, until Units 1-2 of
`tasks/plan.md` land) — the consumption path already exists; only the
production path is new.

*Evidence 4 — no config-fingerprint/identity mechanism exists.* All
`hashlib`/`sha256` usage in `src/` (three sites) was inspected this
session: `workspace_lease.py:72,153` hashes a workspace *path string* into
a mutex name; `engine/claude_headless.py:1054-1067`
(`capture_work_liveness`) hashes a work-target *file's bytes* for
containment-kill liveness witnessing; `events/projections.py:141-168`
(`StateProjection.digest`) hashes the event-log-derived state projection,
explicitly excluding even static issue metadata as "not state identity."
`Config`/`load_config` (`config.py:165-179`) returns a fresh object on
every call; nothing pins, hashes, or compares configs across runs
anywhere in `src/`. No reconciliation is required with any existing
fingerprint mechanism, because none exists.

**Decision — the architecture in doc 17 is ACCEPTED, on this evidence,
with no changes to its central premise.**

1. **Explicit no-gate authorization.** A configuration MAY contain
   `validation: {commands: [], acknowledged_no_gate: true}`. An empty
   `commands` list without `acknowledged_no_gate: true` remains invalid
   configuration, rejected at structural load (`ConfigError`), before any
   workspace/log/engine involvement — this is unchanged from doc 17 §2a/
   §2g and is not weakened by this ADR.
2. **Defense in depth is intentional, not a smell.** Two independent
   enforcement sites remain: `ValidationCfg`'s cross-field model
   validator (schema layer) and `Validator.__init__`'s own guard
   (construction layer). A directly constructed `Validator` — outside any
   `Config` object, e.g. from a test or a future caller — still requires
   `acknowledged_no_gate=True` explicitly; the config layer alone is not
   trusted to be the only gate a hand-built `Validator` passes through.
   This mirrors this repo's own existing precedent
   (`_powershell_safe_commands`'s `$`-check duplicated independently in
   both `config.py:66-67` and `runner.py:71-72`) and is not collapsed
   into a single check.
3. **Vacuous validation is a real, first-class outcome.** An
   acknowledged-empty `Validator` runs zero configured commands, returns
   `passed=True`, and `gate_results() == []`. Gap-2 `extra_commands`
   (doc 08 Amendment, Session 35) remain fully active and can still fail
   validation — the no-gate acknowledgement covers only the
   config-sourced baseline, never the per-execution new-test-file
   mechanism.
4. **`ValidationPassed(gate_results=[])` is judged a semantically valid,
   frozen-contract-compatible `ValidationPassed` for the same
   `validated_commit`/tree hash, and satisfies `REVIEWING`'s doc-03 entry
   precondition identically to a populated result.** This is the central
   decision (see "Frozen-contract conclusion," restated in the report
   below) and it is grounded in Evidence 1-3 above, not asserted by
   analogy: the transition table's own lambda ignores payload content:
   there is no `len(gate_results)` branch anywhere in `src/` for this ADR
   to be inconsistent with.
5. **No event-schema expansion.** No new event type (e.g. no
   `ValidationWaived`), no new event field, and no new state-machine
   branch are introduced solely to represent acknowledged no-gate
   execution. `ValidationPassed` now legitimately represents two distinct
   real-world situations — a real configured check ran and passed, or an
   explicitly acknowledged configured-check-free pass — and downstream
   consumers are decided, by this ADR, to intentionally NOT distinguish
   them by event shape. The distinguishing fact (whether a gate was
   configured at all) lives in the *config* that produced the run, and in
   the human-readable `gate_results` length within the event itself — not
   in a second event type.
6. **Baseline-green behavior is unchanged in structure.** The ADR-20
   baseline-green check (`main.py:323-335`) continues to construct and
   invoke `Validator` exactly as today; an acknowledged-empty baseline is
   vacuously green (zero subprocess spawned, nothing to time out) but
   MUST remain operator-visible — the startup log line is required to say
   so explicitly (doc 17 §2d), not simply print the unqualified
   `"baseline green"` a real pass would.
7. **CLI trust boundary.** `--yes` alone MUST NOT authorize the
   no-validation decision under any flag combination. The only paths to
   an acknowledged-empty generated config are: `--no-validation` plus
   interactive confirmation of a dedicated, separate prompt, or
   `--no-validation --yes-no-validation` as the explicit non-interactive
   acknowledgement (doc 17 §2h — locked flag names, not placeholders).
   `--force` retains only its existing Issue A config-overwrite meaning
   and is not reused or overloaded for this purpose.

**Future architectural invariant (binding on later work, not just this
feature).** `ValidationPassed.gate_results` MUST NOT be assumed non-empty
by any future consumer. Any later code that reads `gate_results` — a new
reviewer heuristic, a reporting tool, a future reconciler seam — must
treat `[]` as a valid, meaningful value (a real, acknowledged no-gate
pass), not as a malformed or unexpected shape. This is a direct consequence
of decision 5 above, recorded explicitly so it is not silently violated by
a future change that assumes otherwise.

**What this ADR claims, and what it does not.** This ADR establishes that
the no-gate architecture is compatible with the frozen contracts *as
those contracts and their actual consumers exist today*, evidenced by
direct inspection and a live replay experiment. It does **not** claim
that the *landed Issue B implementation* will conform to this decision
without its own verification — `tasks/plan.md`'s Unit 6 (post-
implementation integration evidence) and the final acceptance gate's ADR-24
compliance re-check exist specifically because an approved architecture
and a correctly shipped implementation are two different claims, verified
at two different times, against two different kinds of evidence (a
hand-built event today vs. the actual `Config`→`Validator`→
`Orchestrator._validate`→emitted-event chain once it exists).

**Options considered.**
- **A — the doc-17 architecture (explicit `acknowledged_no_gate` flag,
  vacuous `ValidationPassed`, no schema change). ADOPTED.** Evidence 1-3
  show the existing consumers are indifferent to `gate_results` content;
  this is the smallest change that closes the gap without touching a
  frozen contract, and it keeps the auditability property (the
  acknowledgement is explicit, config-visible, and operator-reported at
  every surface: check-config, baseline, `_print_report`).
- **B — skip `Validator` construction entirely when no gate is
  configured, replacing it with a distinct no-op code path in the
  orchestrator/baseline check. REJECTED.** Doc 17 §2c/§2d already reasoned
  through this: it requires a second control-flow branch whose only job
  is "don't call this," for zero behavioral difference once `Validator`
  itself vacuously passes on an empty acknowledged list — unnecessary
  complexity for an outcome the simpler option already produces
  correctly, and it would mean the baseline-check code path is no longer
  uniform across configs, doubling the surface a future bug could hide
  in.
- **C — add a new event type (`ValidationWaived` or similar) to
  distinguish a real pass from an acknowledged vacuous one. REJECTED.**
  This is the one alternative that would have required touching THE
  FROZEN CONTRACT (doc 03's event vocabulary) for a distinction Evidence
  1-2 show no current consumer needs. It would also require every future
  consumer of validation results to learn a second event type
  permanently, in exchange for a distinction already fully recoverable
  from `gate_results`'s length within the existing `ValidationPassed`
  event — strictly worse: more surface, no consumer benefits from it
  today, and it is exactly the kind of ad hoc frozen-contract change
  CLAUDE.md requires an ADR to justify, which this ADR does not find
  justification for.
- **D — treat an empty `commands` list as implicitly valid (no
  acknowledgement field at all; empty just means "no gate," silently).
  REJECTED.** This is precisely the failure mode the whole feature exists
  to prevent — an operator (or a config generated by a future tool, or a
  typo that drops the last list entry) could end up running unattended
  with zero validation and no visible signal anywhere that this was
  intentional. Rejected outright, not seriously weighed against the
  adopted option.
- **E — enforce the acknowledgement only in `Config` (schema layer),
  drop the `Validator`-level guard. REJECTED.** A directly constructed
  `Validator` (bypassing `Config` entirely — tests do this today, and any
  future caller could) would then silently vacuous-pass on an empty list
  with no acknowledgement anywhere in that call. This is the same class
  of gap ADR-23's own `_powershell_safe_commands`/`Validator` `$`-check
  duplication already exists to close; collapsing to one layer reopens
  it for this feature specifically.
- **F — enforce the acknowledgement only in `Validator` (construction
  layer), drop the `Config`-level guard. REJECTED.** Would let an
  unacknowledged `commands: []` config load successfully and only fail
  much later, deep inside orchestrator startup, instead of failing at the
  earliest possible point (`load_config`, before workspace/log/engine
  ownership — doc 17 §2g). Later failure is strictly worse operator
  experience for an error that is knowable at parse time, and it
  contradicts this repo's own established preference for the earliest
  possible refusal point (the recovery-before-checkout ordering rationale
  in ADR-20 Amendment 2 is the same instinct applied here).
- **G — let `--yes` alone authorize no-validation, no second flag.
  REJECTED.** `--yes` today means "accept the detected configuration
  default" — there is no detected default to accept in the no-gate case,
  so overloading it would silently expand what an existing, already-
  understood flag means. This is exactly the class of decision the
  existing dependency-install trust boundary (`confirm_and_run_install`,
  doc 16 §4 step 4) already established needs its own explicit gate
  independent of `--yes` — the no-validation decision is at least as
  consequential and gets the same treatment, not a lesser one.
- **H — overload `--force` for the no-validation acknowledgement instead
  of a new flag. REJECTED.** `--force` has one existing, well-understood
  meaning (config-overwrite authorization, Issue A). Reusing it for an
  unrelated authorization (running without a validation gate) would make
  a single flag's presence ambiguous between two different consequences,
  which is strictly worse for an operator reading a command line than two
  named flags each doing one thing.
- **I — reject `acknowledged_no_gate: true` when `commands` is non-empty
  (mutual exclusion). REJECTED, in favor of accepting it.** Doc 17 §2a's
  reasoning stands: forcing mutual exclusivity would require an operator
  who adds a real check later to remember to flip the flag back off, and
  a stale `true` alongside real commands is harmless — the commands still
  run, the flag is simply unused. Rejecting it would add a rejection path
  that protects against nothing (no unsafe state results from the
  combination) at the cost of a config that could otherwise be written
  once and edited incrementally.

**Consequences.**
- **Less automated execution assurance for acknowledged-no-gate drains.**
  This is the accepted, load-bearing tradeoff, not a side effect —
  auditability is provided entirely by the explicit config
  acknowledgement and its visibility at every operator-facing surface
  (check-config's NOTE line, the baseline-check log line, `init`'s
  `_print_report`), not by any automated check.
- **`ValidationPassed` now represents two distinct real-world
  situations** — a real configured validation pass, and an explicitly
  acknowledged configured-validation-free pass — **without distinguishing
  them by event type.** This is decision 5 above, and it is the specific
  fact the "future architectural invariant" note exists to keep visible
  to later engineers.
- **Gap-2 `extra_commands` remain fully meaningful** even under
  `acknowledged_no_gate=True` — a repository with no baseline check
  configured can still have child-authored new test files gated, which is
  strictly better than "no gate at all, ever" for that repository.
- **Old configs are unaffected.** `acknowledged_no_gate` defaults to
  `False`; any config that loaded successfully before this ADR's
  implementation lands continues to load with identical parsed values and
  identical downstream behavior (doc 17 §2i).
- **Defense-in-depth duplication (`Config` + `Validator`) is deliberate
  and is not to be "simplified" into one check later** without a new ADR
  revisiting this decision specifically.
- **This ADR does not authorize implementation.** Issue B's `src/`
  implementation (`tasks/plan.md` Units 1-6) proceeds only after this ADR
  is independently reviewed and approved by the external reviewer this
  ADR is now handed to, exactly as doc 17/`tasks/plan.md` specify.

**Gate chain before Issue B's `src/` mechanism lands.** ADR-24 drafted
(done, above, this session) → **external review and approval** (not yet
done — this ADR is Proposed-then-Accepted only in the sense that it
records the drafting session's own conclusion; it is held for the same
external-review step doc 17 itself went through before this session began
drafting it) → Issue B `tasks/plan.md` Units 1-6 (`ValidationCfg`
schema, `Validator` guard, `main.py` wiring, `init` flags, generated YAML,
integration evidence) → unit suite green → durability harness 60/60 on
BOTH seed 42 and seed 1337 → a SECOND, later ADR-24 compliance check
against the landed diff (not this drafting session's prediction of it) →
Issue B complete. `src/` changes are legitimate only as the implementation
of an Accepted-and-reviewed ADR, per this repo's standing rule.

---

## 5g. ADR-25 — Read-only external observer contract (additive, non-mutating)

**Status:** ACCEPTED · **Date:** 2026-08-19. Lightweight ADR per CLAUDE.md's
blast-radius rule: this is a low-blast-radius additive read surface (no
runtime behavior, event schema, state transition, or Git/recovery change),
so it uses doc 05's original context → decision → alternatives rejected →
consequences format rather than ADR-24's heavy evidence apparatus.

**Context:** `SPEC.md` ("Read-only observer contract") asks for a stable
local read boundary for the Draindeck Dashboard — event evidence and
observational status without changing workflow behavior, event schema,
filesystem state, locks, or Git state. No external read surface exists
today; the only readers of `state/events.jsonl` are `EventLog`/
`ReadOnlyEventLog`, both internal and lock-aware.

**Decision:** Add a separate, bytes-direct reader (`src/runtime/
observe.py`) that frames the log on `\n` itself and never instantiates
`EventLog`/`ReadOnlyEventLog`, acquires the writer/workspace mutex,
repairs/truncates the log, or invokes Git. Expose it through a new
`draindeck` console entry point (`observe events`, `observe status`),
versioned JSON responses only, with raw evidence preserved for unknown/
malformed/torn records (exact bytes + SHA-256 hash + opaque adapter-owned
cursor). `status.writerState` returns `UNKNOWN` whenever answering it
precisely would require the mutex — it never guesses. No new event type,
schema version, or state transition is introduced; doc 03 stays frozen
(see its added consumer note, same commit).

**Rejected:**
- *Route through `EventLog`/`ReadOnlyEventLog`* — couples an external,
  best-effort read surface to the writer's lock/repair semantics; a slow
  or misbehaving dashboard consumer could then contend with or block the
  orchestrator.
- *Relax `Event.from_line()` to tolerate unknown/malformed input* — would
  weaken the strict parser the live writer/replay path depends on. The
  observer needs a different failure posture (preserve evidence, never
  raise) than the writer (strict, fail fast); one function cannot honestly
  serve both.
- *Acquire the mutex to report a precise `writerState`* — the SPEC
  explicitly trades precision for the read-only guarantee. `UNKNOWN` is
  honest; a wrong `ACTIVE`/`IDLE` guess is not.

**Consequences:** A second, independent reader of the same physical file
now exists permanently; any future change to on-disk record framing must
be evaluated against both readers, not just `EventLog`. The observer is
additive-only — removing or narrowing it is a consumer-facing break and
needs its own ADR-governed deprecation, not a silent edit.

### ADR-25 — Amendment 1 (2026-08-20): identity, cursor safety, strict
### pagination, and bounded reads

**Status:** ACCEPTED. Filed via `/resolve-item` as a remediation against
the shipped implementation, which review found short of this ADR's own
"additive, non-mutating, read-only" bar in four ways. Handled as an
amendment to this ADR, not a new one, per the remediation item's explicit
authorization ("stop and ask ... if [it] requires a new ADR beyond
amending ADR-25" — none of the four gaps below require changing doc 03 or
a frozen contract; they correct this ADR's own external surface).

**Gap 1 — no log-identity signal, so a cursor could silently continue
across a replaced or truncated log.** The original cursor encoded only a
byte offset; if the log at that path were ever replaced (a corrupted log
recovered from backup, an operator swapping in a different log) or
truncated, a stale cursor would resume reading the new file at the old
numeric offset and misinterpret unrelated bytes as continuation records —
exactly the "silently continue after log replacement" failure this ADR's
own read-only-observer premise exists to avoid. **Fix:** every `events`
response now reports `contentLineage` (SHA-256 of the first complete
record) and `fileGeneration` (device + file index — the same pair Python
surfaces on Windows via `os.stat().st_dev`/`st_ino` as the NTFS volume
serial number and file index, no platform-specific API needed). Cursors
embed both; `read_events_page` recomputes current identity on every call
and rejects a mismatch — or an embedded offset past the current file's
end — as `CURSOR_LOG_REPLACED`, never silently continuing.

**Honest scope of this fix (corrected same-day, before this diff's first
commit):** the first draft of this Gap 1 fix described itself as
detecting "the log being replaced or truncated," full stop — that
overclaimed. What `(contentLineage, fileGeneration)` actually catches is
four concrete, realistic cases: the log going missing, `fileGeneration`
(the file's on-disk identity) changing, `contentLineage` (the first
record's bytes) changing, or the cursor's offset landing past the
current file's end. An in-place truncate-and-rewrite that preserves both
the file's identity and the exact first-record bytes while changing only
the bytes between the first record and the cursor's position is
**not** detected — it is indistinguishable from ordinary append-only
growth to a reader that only fingerprints the first record. Closing that
would need hashing the full prefix up to the cursor's offset on every
call (which breaks Gap 4's own boundedness fix below), persistent
cross-invocation state (this CLI has none), or writer cooperation (out
of scope). This is a documented boundary of a stat + first-record
fingerprint, not a bug — see SPEC.md's Identity section for the same
wording kept in sync.

**Gap 2 — `offsetBytes` leaked the internal position abstraction into
public output**, in tension with the ADR's own "cursors are adapter-owned
and opaque to consumers" clause. **Fix:** removed from record output;
resumability is carried only by the opaque cursor. No external consumer
existed yet (the dashboard integration this ADR supports had not started
consuming the field), so this is recorded as a pre-GA correction rather
than a breaking-change deprecation under the "additive-only" consequence
above.

**Gap 3 — pagination could exceed the requested `limit`.** The original
loop appended a torn tail record unconditionally before checking the
limit, so a page could return `limit + 1` records whenever the record
immediately after the limit boundary happened to be torn. **Fix:** the
limit check now runs before any record (complete, torn, or oversized) is
added to the page; an unread item beyond the limit is reported via
`hasMore=true` and a cursor pointing at it instead of being force-included.

**Gap 4 — `Path.read_bytes()` loaded the entire log into memory
regardless of `limit`,** undermining the ADR's own boundedness intent for
a diagnostic tool meant to run against a potentially long-lived,
ever-growing log. **Fix:** replaced with a streaming reader over an open
file handle, bounded to `CHUNK_SIZE` (64 KiB) per read and never reading
past `limit + 1` records. A single record's scan for its terminator is
separately capped at `MAX_RECORD_BYTES` (8 MiB); a record that never
terminates within that cap is reported as `integrity: "OVERSIZED"` with a
hash of only the scanned prefix — explicitly labeled as partial evidence,
never silently truncated and presented as if it were the complete record.

**Bug fixed same-day, before this diff's first commit:** the first draft
searched for a record's terminating `\n` across the *entire* accumulated
read buffer, not just its first `MAX_RECORD_BYTES` bytes. Because a
single `read()` can pull in up to one `CHUNK_SIZE` more than the cap in
one call, a `\n` sitting just past the cap could still be found and wrongly
accepted as a valid terminator — the cap was enforced only when no `\n`
was present anywhere in the (possibly already-overshot) buffer, not when
one existed beyond byte `MAX_RECORD_BYTES`. Fixed by bounding the search
itself (`buf.find(b"\n", 0, MAX_RECORD_BYTES)`) in both the record
streamer and the `contentLineage` discovery reader — a `\n` only counts
as a terminator when it falls within the cap; the same rule now applies
consistently to both.

**Consequences:** the cursor's internal encoding changed (now a
self-describing token carrying resume position + log identity, still
opaque outside this module) and record shape gained
`truncatedPrefixHash`/`truncatedPrefixBytes` alongside the identity
fields in `metadata`. Both are backward-incompatible with the initial
shipment's shape; accepted because no consumer existed yet. Any future
change to this surface still needs its own ADR-governed deprecation per
this ADR's original consequences clause — this amendment does not relax
that going forward.


---

## 5h. ADR-26 — Dashboard architecture and run-lifecycle evidence

**Status:** ACCEPTED · **Date:** 2026-08-20 (accepted 2026-08-20). This is a
high-blast-radius decision. Acceptance authorizes Phase 1-6 implementation
(docs/19, dashboard foundation, registration/indexing, API/SSE, UI/artifacts)
per the gate chain in "Consequences and acceptance gate" below. It is NOT
authorization to alter the frozen Doc 03 schema or emit a new event type
(`RunStarted`/`RunFinished`, decision items 5-8) — that Phase 7 work requires
the separate Doc 03 amendment, its own review, explicit acceptance, and the
normal per-commit user authorization, per "Required Doc 03 amendment before
implementation" below.

**Context.** ADR-25 provides a read-only Dashboard boundary but intentionally
excludes run lifecycle, provider/model, configuration, and cost metadata.
The Dashboard also needs a durable local index, concurrent read behavior, a
safe registration rule, and a single SSE resume sequence. Existing strict
replay rejects unknown event types, so adding run events is not a harmless
additive change: opening such a log with an older binary is unsafe.

**Decision.**

1. Dashboard is a local FastAPI/Uvicorn process with a static vanilla UI and
   Dashboard-owned SQLite database in a separate `draindeck_dashboard`
   package. This is an explicit framework carve-out for that package only;
   core `src/runtime` stays framework-free. It consumes only ADR-25's observer
   CLI. The complete public and operational contract is docs/19.
   The package path is `src/draindeck_dashboard`; FastAPI/Uvicorn are a
   `dashboard` optional-dependency extra, so core-only installs do not pull the
   web stack.
   Because Part 2 has no authentication, it binds only to loopback and rejects
   non-loopback Host/Origin access; remote exposure requires a future
   authentication/TLS ADR. Browser output is self-only CSP-protected and all
   observed evidence is rendered as text, never executable markup.
2. SQLite uses WAL and a 5-second busy timeout. One Dashboard-owned lease
   elects exactly one indexer writer per database; other processes serve
   reads/SSE only. The lease uses a 2-second heartbeat, 10-second TTL, and
   atomic expired-owner takeover. The one monotonic SSE cursor is
   `change_sequence`.
3. Registration requires an operator-supplied absolute `logPath`; Dashboard
   never discovers it by loading target config. Polling, not watching, uses
   a configured absolute observer executable, `shell=False`, a minimal
   credential-free child environment, global concurrency four, documented
   OFFLINE/NOT_INITIALIZED backoff, and bounded pages per tick. Hot polling
   uses only `observe events --format json`; availability comes from its
   metadata and status is registration diagnostics only.
4. ADR-25's current pagination is binding: `nextCursor` is exclusive and null
   at caught-up EOF only for limit pagination; on a delivered TORN/OVERSIZED
   tail it is pinned inclusively. Record cursors are inclusive. Dashboard durably
   checkpoints the last record cursor/hash and identity generation, accepts
   intentional boundary re-delivery idempotently, and never loops without a
   per-tick page cap. OVERSIZED is a visible terminal halt because the public
   contract cannot advance past it. CORRUPT requires two OK records sharing
   the same non-null integer eventId but different recordHash values, scoped
   to one contentLineage/fileGeneration generation. CURSOR_LOG_REPLACED is
   confirmed with a successful after=None identity probe before generation
   rollover; transient/unavailable probes retain the checkpoint and back off.
5. After Doc 03 is amended, two new schema-version-1 types exist:
   `RunStarted` and `RunFinished`. A run ID is
   `run-<UTC-second>-<uuid4>`; timestamp readability is retained but UUID4
   prevents new same-second collisions. Existing timestamp-only IDs remain
   valid but may be ambiguous and carry no fabricated lifecycle metadata.
6. `RunStarted` is appended and fsync'd immediately after entering normal run
   work, before checkout, reviewer health, baseline validation, and
   `_ingest_issues`. Its payload includes engine `{provider, model}`, reviewer
   `{provider, model}` when configured, safe budget limits, and
   `config_digest`. Reviewer model is resolved from the selected
   provider-specific subsection (`qwen.model` today), null only when that
   provider has no model field. The digest is SHA-256 over UTF-8 canonical JSON
   with sorted keys and separators `(',', ':')` of exactly this allowlist: engine
   provider/model/max_turns/timeout_seconds; reviewer provider/model; and
   budget max_attempts_per_issue/max_executions_per_run/
   hard_stop_proxy_cost_per_run_usd/proxy_pricing. Missing reviewer model is
   encoded as null. The projection excludes every other config field,
   particularly `ANTHROPIC_API_KEY`, auth tokens, passwords, environment
   mappings, validation commands/env, repository paths, and all endpoints.
   It never serializes raw configuration into an event.
7. Once RunStarted exists, every controlled terminal exit appends
   exactly one `RunFinished` with one of `COMPLETED`, `CHECKOUT_FAILED`,
   `REVIEWER_UNREACHABLE`, `BASELINE_FAILED`, `INGEST_FAILED`, `HALTED`, or
   `INTERRUPTED`; safe reason/detail fields are defined by the Doc 03
   amendment. Failures before normal-run entry have no RunStarted and hence
   no RunFinished. RunFinished is never synthesized after abrupt process
   death; recovery may describe crash facts only through existing recovery
   mechanisms.
8. No-downgrade policy: a log containing either run type requires a Draindeck
   version that recognizes both. Operators must not replay or write it with an
   older binary; release documentation and runtime compatibility checks make
   this a refusal, not an implied compatibility promise.

**Required Doc 03 amendment before implementation.** It must define the two
event rows, their envelope fields, payload schemas, controlled outcomes,
the exact config-digest projection, ordering relative to issue ingestion,
replay/projection treatment, and the no-downgrade operational policy. It
must state that pre-normal-run failures carry neither lifecycle event. It
must not silently reinterpret historical
events or change existing issue/execution transitions.

**Alternatives rejected.**

- Direct Dashboard log parsing: bypasses ADR-25's torn-tail and
  forward-compatible evidence boundary.
- File watching and every-process indexing: nondeterministic across Windows
  filesystems and conflicts with SQLite's single-writer reality.
- Automatic target-config discovery: duplicates core path-resolution logic and
  makes registration unexpectedly read arbitrary repository configuration.
- Timestamp-only run IDs: known same-second collision.
- Blacklisting secrets in a digest: new secret-shaped fields could leak;
  allowlisting safe fields is the safer boundary.
- Treating new run types as backward compatible: existing strict schema replay
  rejects them, so that claim would cause operator data loss or failed runs.

**Consequences and acceptance gate.** Before any source change, this ADR,
docs/19, and the Doc 03 amendment require review and explicit acceptance.
Implementation then proceeds in small verified commits: Dashboard foundation,
registration/indexing, API/SSE, UI/artifacts, then separately the core
run-event change. The core change must add focused ordering/digest/collision/
controlled-exit/abrupt-death/no-downgrade tests, the full unit suite, and
crash harness seeds 42 and 1337. Existing logs without run events remain
valid and receive no fabricated lifecycle history.

## 6. Final v1 `config.yaml` (reference example)

```yaml
# config.yaml — v1 reference (Session 0 final)
project:
  name: StockAgent
  repository: 'C:\Projects\StockPhotoAgent'   # ⚠ confirm directory name on disk
  branch: agent-work
  issues_file: Issues.md
  validation:                    # deterministic gate — repo-specific, config-supplied
    commands:
      - <test command for StockAgent>          # fill in Session 1
    timeout_seconds: 600

engine:                          # ADR-02, ADR-08, ADR-18
  provider: claude-headless
  auth_mode: subscription        # subscription | api_key ; api_key requires ANTHROPIC_API_KEY
  model: default                 # let claude -p use plan default unless overridden
  max_turns: 30
  timeout_seconds: 1800

reviewer:                        # ADR-05 — provider-independent day one
  provider: qwen                 # qwen | claude
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
  claude:
    auth_mode: subscription

budget:                          # ADR-09, retained per ADR amendment §3
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  proxy_pricing: api_list_rates  # cost accounting basis for ADR-19
  hard_stop_proxy_cost_per_run_usd: 15.00

experiment:                      # ADR-19 — do not edit after run begins
  sample_size: 20
  attempt1_success_min: 0.30
  cost_per_shipped_issue_max_usd: 3.00

billing:                         # checklist A1 record
  posture: pro_subscription_headless
  headless_split_status: paused          # per Anthropic Help Center
  verified_on: '2026-07-10'
  reverify_at: phase-2-gate

event_log:                       # ADR-11
  path: state/events.jsonl

attempts:                        # ADR-15
  ref_namespace: refs/attempts
```

---

## 7. Session 0 status

All checklist items closed: A1 billing verified (§1), execution provider decided (ADR-18), kill criteria pre-committed (ADR-19), target repository decided (ADR-20). **The architecture is frozen.** Session 1 proceeds per doc 09.
