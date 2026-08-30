# NEXT

> NEXT.md is a working queue and pointer index. It is NON-AUTHORITATIVE.
> On any conflict about evidence, event semantics, or state, the referenced doc or ADR
> wins over NEXT.md. Doc 03 wins on event/state semantics; `state/events.jsonl` is the
> sole authoritative runtime state. A target repo's `Issues.md` STATUS field is
> decorative input text, never state.
>
> Rotation: at session close, completed items move out to the session handoff; new
> items come in. Evidence produced this session goes to a handoff or the relevant ADR,
> never here. If this file exceeds ~120 lines, that is the signal to rotate.

## 1. Current state (verified 2026-08-30)

- **Dashboard-controlled target configuration (ADR-29): BUILD COMPLETE
  (Units 0-6), committed directly to `master`, pending user review before
  merge (no push/merge occurred — commits are already on `master` since the
  work started there). `runtime.init.service` is the sole policy/mutation
  gate for creating/editing a target's `config.local.yaml`; CLI `cmd_init`
  and a new Dashboard REST + UI surface (`/repositories/new-target`,
  `/repositories/{id}/configuration`) both delegate to it. Found and fixed
  8 real defects during the build (3 pre-existing service bugs, a CLI
  architecture violation where `cmd_init` mutated Git directly bypassing
  the service, a rendering-ownership gap, a preview branch-prediction gap,
  and 2 live-browser-found frontend bugs including a genuine `[hidden]`-
  vs-CSS-cascade defect now fixed at the base stylesheet level). **1104
  combined `tests/unit tests/dashboard` passed**, durability harness **ALL
  60 SCENARIOS PASSED** on both seed 42 and seed 1337, `git diff --check`
  clean at every commit, golden paths live-browser-verified against a real
  Git repository. Responsive-breakpoint/keyboard-only verification and a
  separate fresh-context review were NOT completed — see evidence for why.
  Full evidence: `docs/reviews/TARGET_CONFIGURATION_BUILD_EVIDENCE.md`;
  handoff: `docs/handoffs/HANDOFF_2026-08-30_target-configuration-complete.md`.
  **Next action is a user decision:** review the evidence, then approve
  merge or request more verification.

- **Draindeck Intake v1: BUILD COMPLETE, on branch
  `codex/draindeck-intake`, baseline `4357b4a`; awaiting user merge
  decision.** Optional one-way intake compiles local `Issues.md`, GitHub,
  Jira Cloud, or Linear into a deterministic managed `Issues.md` without
  touching `src/runtime` or Doc 03. Final Intake suite: 77 passed, 1
  Windows symlink test skipped; standalone Dashboard: 496 passed; compile and
  CLI checks passed; durability harness passed all 60 scenarios for seeds 42
  and 1337. Fresh-context review fixes include Unicode structural-injection
  defense, bounded PR-only GitHub pagination, Jira completion validation,
  Linear label-truncation detection, and coordinated managed-output
  publication. Evidence and known inherited clean-worktree core-test limit:
  `docs/reviews/DRAINDECK_INTAKE_BUILD_EVIDENCE.md`; handoff:
  `docs/handoffs/HANDOFF_2026-08-29_draindeck-intake-complete.md`.

- **Coding-engine proxy cost: BUILD COMPLETE (Units 0-8), on branch
  `dashboard-engine-proxy-cost`, baseline clean `master` `0bb1629`.
  Awaiting user merge decision.** Exposes engine-reported API-list-rate
  proxy cost (`ExecutionFinished.payload.usage`) across the Dashboard:
  SQLite `SCHEMA_VERSION` 2→3 ordered migration chain adds nullable
  cost/token columns to `execution_views` and flips READY read models to
  REBUILDING for the existing async backfill (no startup evidence scan); a
  `proxyCost` object + average-per-completed-issue + top-cost issues are
  attached additively to execution/issue/run/repository/global responses
  (Evidence/Search/Attention deliberately excluded); Home/Repository
  Overview/Issues/Runs/Executions/About UI render cost with a
  proxy-not-invoice framing. **Units 7-8 completed 2026-08-28:** real-browser
  security/accessibility verification of every placement × all four states
  (COMPLETE/PARTIAL/UNAVAILABLE/metered-$0.00), exclusions, both themes,
  keyboard/focus, reduced motion, reflow, and cost-sort injection probes
  (→422); a fresh-context six-axis review that found and fixed **two real UI
  findings test-first** — Home top-cost chart labels showed raw micro-USD
  (now formatted USD), and Run Detail lacked the visible Partial chip (now
  present) — each re-verified live. **Combined `tests\unit tests\dashboard`
  1056 passed** (560 unit unchanged — no `src/runtime` touched — + 496
  dashboard); scale re-run all cost aggregates ≤6.8 ms at 10k executions /
  100k evidence; durability harness re-confirmed on seed 42 and seed 1337.
  Spec: `spec/coding-engine-proxy-cost.md`; design: `docs/28-proxy-cost.md`;
  evidence: `docs/reviews/PROXY_COST_BUILD_EVIDENCE.md`; handoff:
  `docs/handoffs/HANDOFF_2026-08-28_proxy-cost-complete.md`; plan/todo:
  `tasks/plan.md` / `tasks/todo.md`. **No merge or push.** Next action is a
  **user decision**: review evidence, then approve merge (or request changes).

### Prior state (verified 2026-08-23)

- **Dashboard redesign: BUILD-AUTO COMPLETE (Units 0-16 plus two
  merge-blocker `/build-auto` continuations), pending user review before
  merge/push.** Branch `dashboard-redesign`, baseline
  `4052fef97dbb90b52ae91fc01832557bc348cab8`: implementation/security
  fixes completed at commit `ed09179`; documentation closeout at commit
  `c991be5` (33 commits after baseline); a further documentation-only
  cleanup commit (bookkeeping corrections, no behavior/test change) is
  HEAD. **970/970 combined `tests/unit tests/dashboard` suite
  green** (560 unit, 410 dashboard); every docs/27 route implemented and
  live-verified, including a 100,000-row scale fixture, a dedicated
  event-loop-responsiveness/lease-starvation measurement (100k-row
  rebuild and max 2,000-record tick, both well within budget, no
  starvation, re-run twice), and six independent fresh-context review
  rounds across the full history (0 security findings survived to final;
  every real defect found was fixed test-first and live-verified). The
  old Part 2 static UI is fully retired. **No merge or push has
  occurred.**

  Both merge-blocker continuations closed real, previously-shipped gaps
  a fresh-context review or the user caught: (1) `INDEX_PREPARING`/
  `REBUILDING`/`READY`/`ERROR` read-model status wired end-to-end
  (a pre-existing bug had every incremental write fabricating READY);
  (2) `rebuild_read_models` now has a real lease-owned production caller
  with a decisive, linearizable ownership re-check immediately before
  publication -- it never publishes READY or replaces view rows once the
  lease is lost, proven by regression tests that replaced a prior test
  weak enough to pass even if publication-after-loss were silently
  permitted; (3) generation-rollover pruning now happens atomically WITH,
  and only upon, the new generation's successful publish, not immediately
  on rollover (which used to destroy the old generation's complete
  snapshot before the new one was ready); (4) the undocumented status
  value `FAILED` renamed to the spec-accepted `ERROR` everywhere,
  including an idempotent data-migration correcting any already-written
  legacy row and flipping the readiness gate from fail-open (denylist) to
  fail-closed (allowlist); (5) focus/scroll now survive SSE-triggered
  list refreshes on every list page, including a reorder-churn bug a
  review caught in the fix itself; (6) 320/768/1024/1440px and 200% text
  resize are now live-verified via a working alternate mechanism (a local
  CSP-relaxing reverse-proxy + iframe harness), not just code-reviewed.

  **One item remains genuinely open, by explicit user waiver, not by
  omission:** `forced-colors: active` true browser/OS-level rendering was
  attempted with the user's active cooperation across three escalating
  mechanisms (DevTools access, an OS-level High Contrast toggle + reload,
  then an authorized full Chrome restart) and never observed by the
  automated browser surface despite being genuinely active on the user's
  own desktop throughout -- a session/profile boundary no available tool
  could bridge. The user chose to waive this one sub-check rather than
  continue searching; `.chart-bar`'s System Colors override remains
  verified by code review only. See `tasks/todo.md`'s WCAG checkbox
  (left intentionally OPEN) for the full attempt log.

  Full outcome, files changed, migration/compatibility statement, test/
  browser/security results, and independent-review dispositions for
  every round are recorded in `docs/reviews/DASHBOARD_REDESIGN_BUILD_
  EVIDENCE.md` (status header now reflects completion, not "IN
  PROGRESS") and `tasks/todo.md`'s dated evidence-log entries -- read
  those before deciding what (if anything) still needs doing before
  merge. **Next action is a user decision**, not an autonomous next
  step: review the evidence, then either request the forced-colors gate
  be revisited with a different mechanism, or approve merge.

- **Dashboard Part 2 (ADR-26): Phase 7 (run lifecycle events) complete on
  branch `dashboard`** (2026-08-21, commits `fd2b9eb`..`7ff1033`, on top of
  Phases 1-6 below): the frozen Doc 03 amendment (`RunStarted`/`RunFinished`,
  commits `a8cfdbb`, `9113ec5`, `ecca3cf`) is now implemented. Core:
  `EventType.RUN_STARTED`/`RUN_FINISHED` added (`RunStarted` is
  `Kind.INTENT`, deliberately excluded from `RESOLUTION_OF` so recovery
  never fabricates a `RunFinished` for an orphaned `RunStarted`);
  validation-only `StateProjection` handlers enforce the exact closed
  payload/envelope schemas (canonical lowercase UUID4 run IDs, valid UTC
  timestamps, 64-hex config digest, finite non-bool budget values, the
  seven-outcome enum, null `detail`); `main.py` generates
  `run-<UTC-second>-<uuid4>` IDs, emits exactly one `RunStarted` (fsync'd
  before checkout/reviewer-health/baseline/ingestion) and exactly one
  `RunFinished` per controlled exit (`CHECKOUT_FAILED`,
  `REVIEWER_UNREACHABLE`, `BASELINE_FAILED`, `INGEST_FAILED`, `COMPLETED`,
  `HALTED`, `INTERRUPTED`), with `COMPLETED`/`INTERRUPTED` decided by
  control-flow path rather than exit code; `config.py` gained field
  validators rejecting empty engine/reviewer models and booleans/non-finite
  values in budget fields, so a config that cannot produce a Doc-03-valid
  `RunStarted` is rejected before any lifecycle event is even constructed,
  and `main.py` additionally re-validates every constructed event through
  the same canonical `StateProjection` handlers immediately before
  `log.append` (defense in depth, not a second implementation). Dashboard:
  a new paginated `/api/repositories/{id}/runs` endpoint and UI section
  render every observed run — including a `RunStarted` followed by an
  early failure with zero executions — showing provider/model/budget/
  config digest/outcome, or the literal `"no controlled finish observed"`
  for an unresolved run (never "Running", since ADR-25 gives Dashboard no
  liveness signal); the existing per-execution `runMetadata` fallback
  (`"run metadata unavailable (legacy/ambiguous)"`) is preserved unchanged.
  Two independent adversarial reviews found and fixed three real issues
  (Dashboard's tolerant reducer under-validating malformed/duplicate
  RunStarted/RunFinished payloads twice, and a "first-observed-wins"
  duplicate-handling bug that could permanently hide a later valid record
  behind an earlier malformed one) — all with regression tests. Verified:
  **757 unit+dashboard tests passed** (560 unit, 197 dashboard), **crash
  harness `ALL 60 SCENARIOS PASSED` on both seed 42 and seed 1337**
  (re-run against the final code), a dedicated abrupt-death fixture
  (`tests/crash/run_lifecycle_harness.py`, real git + real `EventLog` +
  real `recover()`, two successive recovery passes) confirming `recover()`
  never fabricates a `RunFinished` for an orphaned `RunStarted`,
  `git diff --check` clean, and live browser smoke tests for both a normal
  COMPLETED run and an early-failure (`CHECKOUT_FAILED`) run with zero
  executions. Working tree clean after both commits (confirmed via
  `git status --short --branch`). No-downgrade policy (README "Version
  compatibility"): `EventLog`/`ReadOnlyEventLog` refuse an unrecognized
  event type on the strict writer/replay path; `draindeck observe` (ADR-25)
  is intentionally exempt, being bytes-direct and read-only. Full detail:
  `docs/handoffs/HANDOFF_2026-08-21_dashboard-part-2-complete.md`.
- **Dashboard Part 2 (ADR-26): Phases 1-6 built on branch `dashboard`**
  (2026-08-21, commits `e989b3b`..`15ed193`): ADR-26 accepted (docs/08
  §5h, PROPOSED→ACCEPTED) and docs/19 filed as its contract; then the
  `draindeck_dashboard` package (FastAPI/Uvicorn, `dashboard` extra) —
  registration API + single-writer lease + bounded observer polling with
  automatic scheduling (one asyncio task per repo, independent 2s-normal
  / 2-60s-backoff cadence, gated on holding the indexer lease) +
  evidence/identity/checkpoint store with CORRUPT detection + a tolerant
  issue/execution projection (deliberately NOT `runtime.events.projections`,
  which raises on illegal transitions) + paginated REST views + a bounded
  SSE change feed + a vanilla-JS UI covering every UI state in docs/19 +
  artifact containment (transcript serving, resolved-final-path
  containment verified against real symlinks/junctions/8.3 aliases) and a
  hardened derived-diff endpoint (`--no-ext-diff`/`--no-textconv`
  verified against a real configured driver with a vacuity check). Five
  real bugs were found and fixed during this build, three via an
  independent adversarial review and two via live scheduler smoke
  testing (a stale-checkpoint generation race, an unbounded SSE queue, a
  checkpoint-cursor perpetual-restart bug, an SSE-feed churn bug on no-op
  record re-delivery) — see the handoff for details. `pytest
  tests\dashboard -q` 150/150, `pytest tests\unit -q` 445/445 (unchanged
  — no `src/runtime` file touched, confirmed by a dedicated dependency-
  carveout test), `git diff --check` clean at every commit, plus three
  live manual browser/DB smoke tests. Phase 7 (RunStarted/RunFinished) was
  separately gated at the time this entry was written; it is now also
  complete — see the entry immediately below. Full detail, decisions, and
  open questions for Phases 1-6:
  `docs/handoffs/HANDOFF_2026-08-21_dashboard-part-2-phases-1-5.md`.
- **Read-only external observer CLI shipped, then remediated**
  (`draindeck observe events`/`observe status`, SPEC.md / ADR-25 +
  Amendment 1, `docs/08` §5g): a bytes-direct, streaming reader
  (`src/runtime/observe.py`) that never instantiates `EventLog`/
  `ReadOnlyEventLog`, never touches the writer/workspace mutex, and never
  invokes Git — see docs/03's consumer note. The 2026-08-19 shipment's
  "lineage/file-generation" gap (noted below as unimplemented) was closed
  via a 2026-08-20 `/resolve-item` remediation: every `events` response
  now reports `contentLineage`/`fileGeneration`, cursors are rejected
  (`CURSOR_LOG_REPLACED`) once the log they were issued against no longer
  matches, `records.length` never exceeds `limit` (even into a torn
  tail), `Path.read_bytes()` is gone in favor of bounded chunked reads,
  and an oversized record is capped and honestly flagged
  (`integrity: "OVERSIZED"`) rather than silently truncated. `offsetBytes`
  was removed from public record output as part of the same amendment
  (pre-GA correction — no external consumer existed yet). A same-day
  second `/resolve-item` pass fixed a real bug the first pass introduced
  (a `\n` found past `MAX_RECORD_BYTES` in one oversized `read()` gulp
  could still validate a record as complete, in both record streaming
  and `contentLineage` discovery — fixed by bounding the search itself,
  `buf.find(b"\n", 0, MAX_RECORD_BYTES)`) and narrowed an overclaim: the
  cursor/identity check detects the log going missing, its on-disk
  identity changing, its first record's bytes changing, or the cursor
  landing past current EOF — it does **not** detect an in-place
  truncate-and-rewrite that preserves both fingerprints while changing
  only later bytes; that's a documented, accepted bounded-reader
  limitation now, not a claimed guarantee. Full detail: `docs/08` §5g
  Amendment 1. **Uncommitted as of this NEXT.md edit** — the remediation
  diff is sitting in the working tree pending the human's explicit commit
  authorization (`/resolve-item` never commits); unit suite 445/445,
  harness `ALL 60 SCENARIOS PASSED` both seed 42 and seed 1337, all
  verified live against the uncommitted diff.
- **Event-log cross-repo isolation + untracked-file preservation fixed**
  (resolve-item, 2026-08-19): a real LUVZ smoke test hit two runtime
  data-safety bugs — (1) `event_log.path`'s default resolved against
  Draindeck's own CWD, not the target repo, so every target shared one
  physical log; (2) startup reconciler check 3 treated ANY untracked file
  as crash residue and deleted legitimate ones (`Issues.md` + backup) via
  `clean -fd`. Both fixed together, gated: unit suite 393/393 (up from 235;
  58 new tests), durability harness `ALL 60 SCENARIOS PASSED` both seed 42
  and seed 1337, no ADR required (both determinations documented). Full
  design rationale, worked example, and compatibility notes:
  `docs/18-resolve-item-event-log-isolation-and-untracked-preservation.md`.
- **Architecture frozen**, per CLAUDE.md / doc 03.
- **ADR-19 (kill criteria) CLOSED PASS**, 2026-08-11, two corroborating samples
  (n=20 and n=19; both clear the attempt-1 and cost-per-shipped-issue bars).
  Record: `docs/08-session-0-closure-and-adr-amendments.md` §4, "ADR-19 — CLOSED
  PASS (2026-08-11)". The doc explicitly rules that later drain volume (below)
  does **not** constitute a further ADR-19 sample — don't re-litigate this.
- **StockPhotoAgent backlog drained to terminal state**, session 44 (2026-08-14):
  102 issues total — 74 DONE, 21 NEEDS_DECOMPOSITION, 7 NEEDS_HUMAN, 0
  PENDING/ACTIVE. `state/events.jsonl` last_event_id 843 (unchanged since —
  confirmed live this session). Full detail:
  `docs/handoffs/HANDOFF_2026-08-14_session44-backlog-drained.md`.
- **Durability gate green**: unit suite 235/235 (verified live this session via
  `.venv\Scripts\python.exe -m pytest tests\unit -q`); harness 60/60 both seed 42
  and seed 1337 per the last several `src/` commits' own self-reported gates
  (not independently re-run this session — the harness run started but did not
  finish within a 2-minute window; trust the commits' reported evidence, not an
  untested assumption of "still green").
- **Open-source cutover complete**: renamed `issue-runtime` → **Draindeck**
  (commit `f808cb9`), MIT license added, portable config (`config.example.yaml`
  tracked template + `config.local.yaml` gitignored local operational config —
  no more hardcoded `config.yaml` target-repo path), README rewritten with
  install/config/workflow/authorization sections and an Architecture diagram.
  See `README.md`.
- **Reviewer-parser hard-halt fixed** (commit `98c3002`, "prove malformed verdict
  does not halt run"): `loop.py:326`'s `except ReviewParseError` now escalates
  the single issue (`reviewer-protocol-violation` → NEEDS_HUMAN) instead of
  halting the whole run. The 2026-08-14 drain's Outstanding Issue #1 is
  resolved.
- **Reviewer rejection rationale now persisted**: `ReviewRejected` events carry
  `severity`, `taxonomy_category`, and `feedback` (`loop.py:342-347`) — the
  earlier "rationale is structurally unwitnessable" gap (Session 33) is closed
  for the REJECT path, which is the case that matters (APPROVE has no feedback
  to lose). `ReviewApproved` still persists only `reviewed_commit`,
  `reviewer_provider`, `verdict` — unchanged, not a live gap.
- **Windows-only coupling reduced, not eliminated** (commit `2bff89f`): the
  validation runner and PID-resolution paths now dispatch by platform.
  `windows_job.py` / `workspace_lease.py` remain **intentionally** Windows-only
  — Job Object containment has no POSIX equivalent; porting it is a new
  safety-critical mechanism requiring its own ADR, not a portability patch.
  See README "Platform constraint (intentional, not incidental)".
- **Reviewer provider hardcoding replaced with a registry** (commit `d100503`):
  `config.py`'s `KNOWN_REVIEWER_PROVIDERS` and `main.py`'s `_REVIEWER_FACTORIES`
  make adding a provider a registration, not a control-flow edit. **`qwen` is
  still the only registered provider** — the registry exists but has not yet
  been exercised with a second provider.
- **CORRECTION to a prior claim.** The session-34 NEXT.md entry ("GAP 4:
  `num_turns` is the deciding value in the turn-budget escalation branch and
  is never persisted to any event") is **false as verified live this
  session** — `loop.py:244` includes `num_turns` in the `common` payload
  dict shared by every `ExecutionFinished` event, confirmed against the real
  event log (event 814: `"num_turns":12`). Do not resurrect this claim.

## 2. Open items (carried forward, none blocking)

1. **21 issues in NEEDS_DECOMPOSITION** on the StockPhotoAgent backlog (includes
   19, 25, 39, 43, 51-53, 56-58, 60, 62, 65, 72, 74, 86, 87, 91-93, 96 — confirm
   full list against `show-state` before acting; not re-verified this session).
   Each needs sub-issue breakdown with fresh IDs above the current ceiling (104)
   before it can re-enter the queue.
2. **7 issues in NEEDS_HUMAN** (12, 36, 48, 54, 82, 88, 94) need manual
   disposition. Issue 88 is unblocked now that the reviewer-parser fix (§1)
   has landed — its diff already passed validation (`ValidationPassed`,
   event 732); recommend re-issuing under a fresh ID rather than resuming
   `88-e1` directly.
3. **SCOPING GAP, still open.** `budget.max_executions_per_run` caps TOTAL
   executions per run, not the targeted issue. If a targeted issue escalates
   early, the freed slot falls through to the next queued issue and it ships
   unplanned (session 40: issue 36 escalated → issue 37 shipped unplanned).
   `main.py`'s argparse has no `--issue`/per-issue scope flag (confirmed live
   this session — only `--config`, `--skip-baseline`, `--log` exist across
   subcommands). Mitigation: confirm the queue tail before any single-issue
   live run. Not fixed in `src/` — would need its own five-gate change.
4. **ADR cleanup / concurrency audit not done.** The parallel Codex work
   (`docs/handoffs/HANDOFF_2026-08-15-CODEX.md`) tracked a "B7: ADR
   race/concurrency audit" item (remove multi-writer race defenses that don't
   apply to a sequential engine) as INVESTIGATE/NOT_STARTED. No audit report
   was found anywhere under `docs/` this session — status unchanged, still
   open.
5. **CLAUDE.md is stale** (noticed, not touched — out of scope for this
   docs-only pass): its "Current task" section still describes Session 3
   (RepositoryAdapter implementation) and its "Verify commands" unit-test count
   (117) is far below the current 235. Flagging for a future CLAUDE.md-scoped
   pass, not fixed here.

## 3. Verify commands (updated 2026-08-21)

- Unit: `.venv\Scripts\python.exe -m pytest tests\unit -q` — **560 passed**,
  verified live this session (Dashboard Part 2 Phase 7; see §1 above).
  CLAUDE.md's "expect 235" is stale, see §2 item 5 above.
- Durability gate: `.venv\Scripts\python.exe tests\crash\harness.py %TEMP%\ch
  <seed>` for `<seed>` in `42`, `1337` — expect `ALL 60 SCENARIOS PASSED` on
  both. Verified live this session against the Phase 7 code — both seeds
  independently re-run to completion.
- Lifecycle abrupt-death harness: `.venv\Scripts\python.exe
  tests\crash\run_lifecycle_harness.py %TEMP%\rlh` — expect `PASS` (proves
  `recover()` never fabricates a `RunFinished` for an orphaned
  `RunStarted`, across two successive recovery passes). Verified live this
  session.
- Config sanity (no engine/reviewer call): `.venv\Scripts\python.exe -m
  runtime.main check-config config.local.yaml`.
- Read-only state inspection: `.venv\Scripts\python.exe -m runtime.main
  verify-log --log state\events.jsonl` / `show-state --log state\events.jsonl`.
- Dashboard suite: `.venv\Scripts\python.exe -m pytest tests\dashboard -q` —
  **197 passed**, verified live 2026-08-21 (Phase 7; see §1 above).

## 4. Pointer index

- **Dashboard Part 2, complete (Phases 1-7, run lifecycle events shipped):**
  `docs/handoffs/HANDOFF_2026-08-21_dashboard-part-2-complete.md`. Governing
  contracts: `docs/19-dashboard-part-2-spec.md` (Dashboard) and the Doc 03
  amendment (`docs/03-state-machine-and-event-schema.md`, "Amendment — run
  lifecycle events") for the core runtime; decision record: `docs/08` §5h.
- **Dashboard Part 2, Phases 1-5 (ADR-26 acceptance through API/SSE/UI):**
  `docs/handoffs/HANDOFF_2026-08-21_dashboard-part-2-phases-1-5.md` —
  superseded by the complete handoff above for anything it conflicts with.
- **ADR-19 closure, both samples:** `docs/08-session-0-closure-and-adr-amendments.md` §4.
- **Backlog drain to terminal state, reviewer-parser bug discovery:**
  `docs/handoffs/HANDOFF_2026-08-14_session44-backlog-drained.md`.
- **Durability gate closure (f4 fixture fix):**
  `docs/handoffs/HANDOFF_2026-08-15_durability-gate-closed-stuck-resolving-reap.md`
  (preceded by `..._durability-gate-f4-blocked.md`, the decision fork it resolved).
- **Open-source cutover / B1-B7 backlog / Windows containment / T7:**
  `docs/handoffs/HANDOFF_2026-08-15-CODEX.md` (a parallel Codex CLI work
  session — different tool, same repo; its `agent/backlog-resolution` branch
  work IS merged into `master`, confirmed live this session via
  `git merge-base --is-ancestor`).
- **Doc 03** governs event/state semantics; **doc 02 §3** governs the advisory
  principle; neither is superseded by anything in this file.
- **All session narrative prior to 2026-08-11** (sessions 5-40, the original
  StockPhotoAgent live-smoke gate this file used to track in detail): superseded
  by §1 above. Full evidence trail, if needed, is still in
  `docs/handoffs/next-md-archive-2026-07-26.md` and the dated `HANDOFF_*.md`
  files — not repeated here.
