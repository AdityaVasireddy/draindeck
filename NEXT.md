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

## 1. Current state (verified 2026-08-17)

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

## 3. Verify commands (updated 2026-08-17)

- Unit: `.venv\Scripts\python.exe -m pytest tests\unit -q` — **235 passed**,
  verified live this session (CLAUDE.md's "expect 117" is stale, see item 5
  above).
- Durability gate: `.venv\Scripts\python.exe tests\crash\harness.py %TEMP%\ch
  <seed>` for `<seed>` in `42`, `1337` — expect `ALL 60 SCENARIOS PASSED` on
  both. Last known-good per the `src/` commits that report it inline
  (`0ca147b`, `2bff89f`, `d100503`); not independently re-run to completion
  this session (see §1).
- Config sanity (no engine/reviewer call): `.venv\Scripts\python.exe -m
  runtime.main check-config config.local.yaml`.
- Read-only state inspection: `.venv\Scripts\python.exe -m runtime.main
  verify-log --log state\events.jsonl` / `show-state --log state\events.jsonl`.

## 4. Pointer index

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
