# NEXT

> NEXT.md is a working queue and pointer index. It is NON-AUTHORITATIVE.
> On any conflict about evidence, event semantics, or state, the referenced doc or ADR
> wins over NEXT.md. Doc 03 continues to win on event/state semantics; doc 02 section 3
> wins on the advisory principle. NEXT.md never carries evidence labels.
>
> Exception: §3's precondition table (row 27) retains VERIFIED/INFERRED status labels by
> design — that is live gate status, not archived narrative. All OTHER evidence lives in
> the referenced docs; NEXT.md carries no evidence labels outside §3.

## 1. Current gate

Live smoke is **NOT authorized.** Gate (b)'s loop-composition variable is collapsed
(Dry-run A PASS); `main.py`'s end-to-end startup composition, the orphan-crash recovery
path, and real-tree behavior remain carried-forward as UNWITNESSED ahead of live smoke.
Gate (a), the vacuity-guard detectability question, is permanently unproven and carried as
a labeled limitation, not a blocker to resolve first.
Pointer: `docs/14-session6-phase2-gate.md` § "Carried-forward note (Session 16-17,
2026-07-26)" ["surfaces named UNWITNESSED ahead of live smoke"] (~L1072-1090).

## 2. Immediate next actions

1. Decide how to sequence live-smoke design against the 3 carried-forward-unwitnessed
   surfaces (witness one first vs. carry all three labeled) — precondition: none, a
   decision only. Pointer: `docs/handoffs/HANDOFF_2026-07-26_session17-dryrun-a-pass-correction-note.md`
   § "Next Action" ["decide how to handle the two items Dry-run A explicitly left
   unwitnessed"].
2. Resolve the ingest branch-check gap (Option A: add `checkout_branch` before ingest, vs.
   Option B: accept as scoped risk) — precondition: none, a decision only. Pointer: §5
   below, "Ingest branch-check gap" (this file).
3. Re-run doc 14 §2.4 Probe 2/3 at CLI 2.1.214 before leaning on the STANDING TICKLE again
   — precondition: the next `claude` CLI version bump. Pointer:
   `docs/handoffs/HANDOFF_2026-07-18_adr22-vacuity-control-restored.md` § "Deferred Work"
   ["Re-running doc 14 §2.4 Probe 2/3 at CLI 2.1.214"].
4. Build the env-witness script (docs/08 §5d spec) — precondition for the ADR-23
   end-to-end differential (all three of: script built, target collects >0 tests, a live
   "before" observed ahead of the next mechanism change). Pointer:
   `docs/08-session-0-closure-and-adr-amendments.md` § "5d. ADR-23" ["Env witness (required
   mechanism for any pre-Phase-2 live run)"].
5. Author/confirm a real StockAgent test command that both resolves the interpreter
   ambiguity (done) AND collects >0 real tests (not done) — precondition: StockPhotoAgent-side
   authoring, user input required. Pointer: §8 below, "NEEDS USER INPUT" (this file).
6. On the next `claude` CLI version bump, before anything else: re-run the ADR-22 probes
   (STANDING TICKLE) — precondition: a CLI version bump. Pointer: §4 below, "Standing
   tickles" (this file).
7. Then 5 real StockAgent issues, supervised; record cost + outcomes; expect to revise the
   context pack — precondition: live smoke authorized (see §1). `--allowedTools`/settings
   hardening is a non-goal (ADR-21 settled the fence); sanitized-env hardening is a
   pre-Phase-4 item, not this step. Pointer: `docs/05-architecture-decision-records.md`
   (ADR-21) / doc 08 §5b.

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
sunset-fulfilled. As of the last re-probe (CLI 2.1.215, Session 12): re-probe and hold B —
do NOT sunset (explicit user instruction); tickle re-armed for the next CLI bump. Pointer:
`docs/14-session6-phase2-gate.md` § "2.7 — Session 12 (2026-07-24): CLI re-pin re-probe at
2.1.215" ["Decision: re-probe and hold B"].

**CLI-2.1.214 Probe 2/3 two-leg re-probe — still owed.** The STANDING TICKLE above has
never actually been re-run at CLI 2.1.214 specifically (the version was skipped over,
2.1.212 → 2.1.215). Owed whenever the CLI version is next checked. Pointer:
`docs/handoffs/HANDOFF_2026-07-18_adr22-vacuity-control-restored.md` § "Deferred Work"
["Re-running doc 14 §2.4 Probe 2/3 at CLI 2.1.214"].

## 5. Parked decisions

**Ingest branch-check gap.** "Ingest does not verify/enforce checked-out branch before
reading `Issues.md`." `Issues.md` is currently read correctly only because ambient `HEAD`
happens to match `cfg.project.branch` — nothing in the runtime enforces or verifies this
match. Two options recorded, neither chosen: **Option A** — add an explicit
`checkout_branch(cfg.project.branch)` call before `_ingest_issues` in `main.py` (a `src/`
change, needs explicit sign-off + likely an ADR). **Option B** — accept as scoped risk;
rely on Step 3 preflight Item 0 to catch a branch mismatch before live smoke — but Item 0
in its current (scratch-workspace) form does NOT cover this, verified this session; it
would require widening Item 0's scope to the real StockPhotoAgent repo, or a separate
check. Status: OPEN, decision needed; do NOT fold into precondition #3; no `src/` change
made or proposed. Pointer: `docs/handoffs/next-md-archive-2026-07-26.md` is NOT this
item's home — full evidence for this specific item lives only here; see also
`docs/14-session6-phase2-gate.md` §2.6/§2.7 for Item 0's scoping evidence
["scratch workspace — explicitly 'never StockPhotoAgent'"].

**Vacuity-guard detectability — permanently unproven.** The positive control that would
prove the ADR-22 A-empty mechanism can detect contamination (not just fail to observe it)
has never fired across three independent, differently-constructed attempts. This is
carried into live smoke as a labeled limitation per standing ruling, not a blocker to
resolve first. Pointer: `docs/14-session6-phase2-gate.md` § "Session 11 (2026-07-18) —
ADR-22 vacuity-guard: synthetic positive control BUILT and RUN" ["three independent
non-reproductions"] (~L894-977); background: § "2.6 — Session 9" ["the vacuity guard no
longer fires"] (~L570-670).

## 6. Pointer index

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
- Unit: `python -m pytest tests\unit -q`  (expect 106)
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
> NEXT.md is 232 lines at this rewrite (cap is 120). The overage is §3's precondition
> table alone. This is the rotation trigger already firing: next session, §3 either shrinks
> as preconditions close, or it graduates to its own tracking doc. Do not trim the rest to
> hit 120 — the rest is already minimal.
