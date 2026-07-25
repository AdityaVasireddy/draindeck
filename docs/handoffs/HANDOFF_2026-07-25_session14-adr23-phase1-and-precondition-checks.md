# Session Handoff — Session 14: precondition #3 verification, ADR-23 accepted (Phase 1 landed, Phase 2 pending)

## Objective
Pick up from the 2026-07-24 handoff: verify Step 3's remaining preconditions (#1 validation command, #3 Issues.md, #4 baseline green) with raw, re-verified evidence rather than carried-forward assessments — several of which turned out to be stale or wrong when actually re-checked. Along the way, a structural gap was found (the validation subprocess has no environment hygiene, unlike the engine subprocess under ADR-18) serious enough to need its own ADR before precondition #1 can be honestly resolved.

## Current Status
- **Completed:** Precondition #3 (Issues.md) independently re-verified and CLOSED, with a corrected error along the way. ADR-23 drafted, reviewed, and ACCEPTED. ADR-23 Phase 1 (docs + one config line + NEXT.md) landed and committed.
- **In Progress:** none — both authorized commits (`6a19d59`, `9bd2a7a`) are settled; nothing mid-edit.
- **Blocked:** Step 3 preconditions #1 and #4 remain UNMET (see Current Checkpoint below — this isn't a stall, it's the session's actual finding). ADR-23 Phase 2 not started. The checkout-before-ingest tracked item (opened this session) has no decision yet.

## CURRENT CHECKPOINT (read this first)
- **HEAD is `9bd2a7a`.** Two commits landed this session, in order: `6a19d59` (precondition #3 CLOSED + checkout-before-ingest item opened) then `9bd2a7a` (ADR-23 Phase 1). A third commit, `69bbbef`, landed **between** those two — see Open Observation below; it is an automated historian-sweep commit, not something done this session, and touches only `knowledge/.sweep/` log files (confirmed no overlap with `NEXT.md`/`docs/`/`config.yaml`).
- **ADR-23 is ACCEPTED** — `docs/08-session-0-closure-and-adr-amendments.md` §5d, landed in `9bd2a7a`.
- **Phase 1 is LANDED:** the ADR-23 §5d text itself, `config.yaml`'s `validation.commands` line (bare `python` → absolute `C:\Python314\python.exe`), and the corresponding `NEXT.md` entries.
- **Phase 2 has NOT been started.** No `src/` file was touched this session. Phase 2 is explicitly the next session's work, and per the user's own gating instruction this session, it should run as its **own session, on Opus** — not folded into whatever picks up next.

## THE `extra="forbid"` TRAP (read before touching `config.yaml` again)
`src/runtime/config.py:28` — the `ValidationCfg`-adjacent frozen model — currently sets `extra="forbid"`. **Do not add a `validation.env:` key to `config.yaml` until `ValidationCfg` in `src/runtime/config.py` actually declares that field.** Adding the config key first will raise at `load_config()` time, not silently ignore it. Schema change (Phase 2 step a) must land before the config key is ever written anywhere, including scratch/test configs.

## PHASE 2 GATE CHAIN — IN ORDER, do not reorder or skip
This is what the next (Opus) session needs to execute, per ADR-23 §5d's own gate-chain text:
1. **(a)** Add `ValidationCfg.env: dict[str, str | None]` to `src/runtime/config.py` — `None` value means "unset this key in the child," not "leave it inherited."
2. **(b)** In `src/runtime/validation/runner.py` (`Validator._run_once`, currently lines ~90-94), build the child env explicitly: start from `dict(os.environ)`, merge non-null keys from `validation.env`, pop keys whose value is null, then pass that dict as `env=` to `subprocess.run` (which currently passes no `env=` at all — this is the actual defect ADR-23 addresses).
3. **(c)** New unit tests under `tests/unit/`: assert on the **built env dict's shape** (null → absent from the dict, non-null → present with that value, unrelated keys untouched) — not on call order or mock-call arguments.
4. **(d)** Full unit suite green. Baseline going in: **106/106** (verified this session, unrelated to Phase 2, as a sanity check after the config.yaml edit — not yet re-run against Phase 2 code, which doesn't exist yet).
5. **(e)** Durability harness **60/60 on BOTH seed 42 and seed 1337** — required because this is a `src/` logic change, per this project's own standing rule.
6. **(f)** Only after (a)–(e) all pass does Phase 2 count as complete/mergeable.

**Also required, per ADR-23, not optional polish:** a differential verification distinct from the unit tests above — run validation twice against the *same* commit, once from a shell with `.venv` activated and once from a clean shell, and confirm the env witness (see below) shows identical child-side enumerated vars and identical verdicts. Under **pre-Phase-2** code this diverges — this session's own probes (bare `python` resolving to two different interpreters depending on shell state, same commit) demonstrated the divergence live. The check should go **red before Phase 2 lands and green after** — that transition is what makes it a real verification rather than a tautology.

## ENV-WITNESS SCRIPT — NOT YET BUILT
`docs/08-session-0-closure-and-adr-amendments.md` §5d specifies a scratchpad-only witness script (same pattern as the existing ADR-22 witnesses — uncommitted, never in `src/`) that does not exist yet. It must:
- Run in the *same shell* that would launch `main.py run`.
- Capture, from **inside a child spawned with the Validator's exact `subprocess.run(shell=True, cwd=repo)` shape** (parent-side capture doesn't witness what the child actually saw): `PATH`, `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME` — each as present/absent **plus** value (absent-vs-empty must stay distinguishable) — plus `sys.executable`, `sys.prefix`, `sys.version`, the `validated_commit`, and a UTC timestamp.
- Write that record alongside the run's own validation artifacts.

**This is a prerequisite for ANY live smoke against StockPhotoAgent — pre-Phase-2 or post-Phase-2 — per ADR-23's binding sequencing rule.** Building this witness script is separate work from Phase 2 itself: landing Phase 2's `src/` mechanism does **not**, by itself, unblock a live smoke. Both the witness script and Phase 2 need to exist before any live run against the real target repo.

## EXPLICITLY OUT OF SCOPE for the next (Phase 2) session
- **The checkout-before-ingest tracked item** (opened earlier in this same session, `6a19d59`): `main.py`'s `_ingest_issues` runs before any `checkout_branch` call, and the only `checkout_branch` call site in `src/` (`loop.py:204`) fires downstream of ingest for per-issue branches — nothing verifies `cfg.project.branch` is what's actually checked out when `Issues.md` is read. Two options (A: add an explicit checkout before ingest; B: rely on Step 3 preflight Item 0) were recorded with neither chosen. **Still pending a decision from Adi — do not fold into Phase 2, do not resolve unilaterally.**
- **StockPhotoAgent test authoring/repair.** `tests/qc/test_qc_rules.py` (the currently-configured validation target) has **zero** pytest-collectible `test_*` functions — verified live this session (`pytest` exit 5, `collected 0 items`, even with the correct interpreter). This is a target-repo-side gap, out of scope for `issue-runtime`.
- **Step 3 preconditions #1 and #4 do not get resolved by Phase 2.** Phase 2 fixes the *env-hygiene mechanism* (the interpreter/environment ambiguity). It does **not** fix the *non-vacuity* problem — the configured test file collecting zero tests. Both preconditions remain UNMET after Phase 2 lands, pending separate StockPhotoAgent-side work.

## Decisions & Rationale
- **ADR-23 ACCEPTED** (`docs/08-session-0-closure-and-adr-amendments.md` §5d) — `Validator._run_once` passes no `env=` to its subprocess, unlike the engine child (`_hygienic_env()` per ADR-18); verified live that the same command/repo/commit produces different validation outcomes depending on operator shell state (activated `.venv` vs. clean shell), which is inconsistent with `validated_commit` being a pure function of the tree. Two normative rules (self-contained absolute-path commands; explicit named targets, no discovery/glob) plus one deferred mechanism (`validation.env`, additive + null-unset) were adopted; an allowlist-base alternative was considered and explicitly deferred (not rejected) behind a named escalation trigger, not left open-ended.
- **Additive-only env overlay was rejected in favor of additive + null-unset** — verified live that `VIRTUAL_ENV=""` is still `True` under `in os.environ` while an unset var is `False`; an overlay that can only *set* values can never reproduce "absent," so it can't fully neutralize the exact variable that caused this session's bug.
- **Phase 2 is deferred to a separate session, explicitly, at the user's direction** — a `src/` change to child-process environment construction under a frozen architecture is treated with the same weight as ADR-18's own engine hygiene: its own session, Opus, full gate chain, not squeezed into the same pass as the docs-only Phase 1 work.
- **Precondition #3 (Issues.md) closed**, after correcting an error found under review: an earlier claim in this same investigation said the file's controlling commit was dated 2026-07-17 — that was the file's **filesystem mtime**, not its commit date, read without ever running `git log`/`git show` on the actual hash. The real commit (`58bc162`) is dated 2026-07-19 13:53:45. Corrected explicitly, not silently, matching this project's existing doc-12 correction-note convention. `Issues.md` parses cleanly (5 valid issues) against the grammar in `src/runtime/queue/issues_md.py`.
- **A new tracked item was opened, not resolved:** ingest has no checkout-before-read guarantee for `Issues.md`'s branch (see Out of Scope above) — recorded with both options, no decision made.
- **`config.yaml`'s `validation.commands` line was fixed to an absolute interpreter path only** — `C:\Projects\issue-runtime\config.yaml`. This resolves the interpreter-ambiguity half of precondition #1's failure but deliberately does not touch `tests/qc/test_qc_rules.py` (a target-repo file), so the command still returns pytest exit 5 today. The non-vacuity gap is stated in the config file's own comment, not left implicit.

## Key Files
- Plan file: `~/.claude/plans/adaptive-orbiting-brook.md` — drove the ADR-23 design (full evidence table, options A–F, escalation trigger, Phase 1/Phase 2 execution gating). Worth reading if the next session wants the reasoning behind rejected options, not just the accepted ADR text.
- `C:\Projects\issue-runtime\docs\08-session-0-closure-and-adr-amendments.md` — new §5d is the canonical ADR-23 text; read this before writing any Phase 2 code, it specifies the exact schema shape, the gate chain, and the escalation trigger.
- `C:\Projects\issue-runtime\config.yaml` — the `validation.commands` line and its inline comment record exactly what was and wasn't fixed this session.
- `C:\Projects\issue-runtime\NEXT.md` — Resume Point section has two new dated Session-14 blocks (one for precondition #3 / the checkout item, one for ADR-23) plus append-only status updates on items #1 and #4 in the itemized precondition list, and a second dated blockquote after the six-preflight-items summary. All original text left intact per this project's append-only convention.
- `C:\Projects\issue-runtime\src\runtime\validation\runner.py` — `Validator._run_once` (~lines 90-94) is exactly what Phase 2 needs to modify; read alongside `src\runtime\engine\claude_headless.py`'s `_hygienic_env()` as the pattern to mirror.
- `C:\Projects\issue-runtime\src\runtime\config.py` — line 28's `extra="forbid"` is the trap noted above.

## Next Action
Start ADR-23 Phase 2 as its own session (Opus, per the user's explicit gating instruction) — begin with step (a) of the gate chain (`ValidationCfg.env` schema field), and do not add anything to `config.yaml` until that schema change exists. Alternatively, if Phase 2 isn't next, the env-witness script (separate, smaller, unblocks smoke testing independently) or the checkout-before-ingest decision are the other two open threads — but Phase 2 is what this session's evidence points at as highest-value.

## Knowledge Captured
- `Validator._run_once`'s `subprocess.run(cmd, cwd=workspace, shell=True, ...)` passes no `env=` — confirmed by reading `src/runtime/validation/runner.py` directly this session. This is a structural asymmetry with the engine path, not a new regression.
- On this machine, bare `python` resolves differently depending on shell state: `C:\Projects\issue-runtime\.venv\Scripts\python.exe` when `.venv` is activated, `C:\Python314\python.exe` in a clean shell — and only the latter has StockPhotoAgent's `requirements.txt` dependencies (`pillow==12.2.0` confirmed present there) installed. Verified live this session via `sys.executable` probes inside the exact `subprocess.run(shell=True)` context the Validator uses.
- An absolute interpreter path alone does not isolate a subprocess's environment — verified live: with `PYTHONPATH` inherited, an injected `sitecustomize.py` executed automatically inside a subprocess spawned with an absolute interpreter path, before any target code ran.
- `VIRTUAL_ENV=""` is still `True` under `"VIRTUAL_ENV" in os.environ`, while an unset `VIRTUAL_ENV` is `False` — verified live. An additive-only env overlay (set specific keys) cannot express "absent," only "present with some value," which is why ADR-23 requires null-unset semantics rather than mirroring ADR-22's `engine.child_env` exactly.
- A near-empty subprocess environment (`env -i`) did not break Python's stdlib on this Windows machine (`ssl`, `socket`, `tempfile` all imported fine) — verified live, recorded because it disproves an assumption used to argue against the allowlist-base alternative (that alternative was still deferred, but not on grounds of Windows stdlib breakage).
- `tests/qc/test_qc_rules.py` and `tests/qc/test_sharpness_rule.py` in StockPhotoAgent are standalone scripts with module-level side effects, not pytest test suites — zero `def test_*` functions in either, confirmed by grep and by reading both files.
- Only two files anywhere in StockPhotoAgent's `tests/` tree are pytest-collectible: `test_button_selector_only.py` and `test_login_only.py`. Both are live, credentialed Playwright browser-automation scripts (real `keyring` credential lookups, non-headless Chromium, hardcoded batch UUIDs against a real third-party URL) — confirmed by reading them, deliberately not executed.
- The commit that last touched StockPhotoAgent's `Issues.md` (`58bc162`) is dated 2026-07-19 13:53:45, not 2026-07-17 — the 07-17 date was the file's filesystem mtime, mistaken for its commit date in an earlier pass of this same investigation before `git log`/`git show` were actually run against the hash.

## Assumptions
- **MED confidence:** the hypothesis that a `/model` switch triggers a session boundary in the CLI harness (see Open Observation below) — plausible from timing alone, not verified against actual harness internals.
- **HIGH confidence, but not independently re-verified against `src/`:** ADR-23's claim that Phase 2 (null-unset env merge) closes the specific vectors identified (`PATH`, `VIRTUAL_ENV`, `PYTHONPATH`, `PYTHONHOME`) — this rests on the live probes done this session, not on Phase 2 code, since Phase 2 doesn't exist yet.

## Outstanding Issues
- **Twice this session**, a tool-result diff (`git diff NEXT.md`, once for the precondition-#3 work and once for the ADR-23 Phase-1 work) did not actually render to the user despite my own message claiming it had been pasted — caught both times by the user, not by me. Resolved by literally pasting the diff text as a markdown code block directly in the chat response rather than relying on a Bash/Read tool result to carry it. Worth the next session being deliberately careful that "I ran `git diff` and it's above" is only true if the diff text is visibly present in the actual message body, not just referenced.
- Step-3 preconditions #1 and #4 are confirmed UNMET this session with concrete evidence (pytest exit 5, "collected 0 items" for #1's target; #4 blocked on #1 plus a new non-vacuity requirement from ADR-23). This isn't new relative to the prior handoff's general uncertainty, but it's now a specific, verified UNMET rather than an unconfirmed placeholder.

## User Constraints
- No `src/`, `config.yaml` beyond the one authorized line, or commit without explicit request, all held throughout — every commit this session (`6a19d59`, `9bd2a7a`) was made only after the user explicitly said to go ahead.
- Explicit gating instruction for Phase 2: separate session, Opus, manual edit approval (not auto mode), harness 60/60 both seeds as a hard merge precondition — stated directly by the user when the plan was reviewed, not inferred by me.
- `validation.env:` must not appear in `config.yaml` before the Phase 2 schema change lands (`extra="forbid"` trap above) — stated explicitly in the ADR text itself as a sequencing rule, not just a note.

## Runtime & System State
- Commit at handoff: `9bd2a7a` (short SHA, from `git rev-parse --short HEAD` this session).
- Working tree: `knowledge/.sweep/sweep.log` modified (auto-generated historian-hook log, consistent with every prior session's handoff — left uncommitted by established convention) and one untracked prior handoff file (`HANDOFF_2026-07-24_...md`, not from this session, not touched).
- Background processes: none running.
- Dev servers / ports: none.
- Open branches / worktrees: none opened this session (stayed on `master`).
- Memory files updated: none.

## Deferred Work
- ADR-23 Phase 2 (`src/` mechanism) — deferred to its own session by explicit user instruction, not because of any blocker; see gate chain above.
- Env-witness script — deferred; not built this session; required before Phase 2 (and before Phase 1-only) live smoke testing.
- Checkout-before-ingest decision (Option A vs. B) — deferred; recorded, not decided.

## Open Questions

**Needs User Input**
- Checkout-before-ingest: Option A (explicit `checkout_branch(cfg.project.branch)` before `_ingest_issues`) vs. Option B (accept as scoped risk, rely on Step 3 preflight Item 0) — still open, no lean stated by the user this session.
- Whether the env-witness script should be built before or alongside the start of Phase 2, given both are independently required before any live smoke.

**Model Uncertainty**
- Commit `69bbbef` (automated historian-sweep, landed 2026-07-25 14:24:23, between this session's two manual commits) — confirmed to be log-only (`knowledge/.sweep/sessions.log`, `knowledge/.sweep/sweep.log`) with no overlap against `NEXT.md`/`docs/`/`config.yaml`. The working hypothesis — that an earlier `/model` switch in this same session (Sonnet → Opus for the ADR-23 plan-mode work, then back to Sonnet) triggered a session-boundary SessionEnd sweep independent of the ongoing conversation — is **INFERRED from timing alone, not verified** against the CLI harness's actual session-boundary logic. Worth checking later whether the same pattern repeats around the earlier `/model` switch's own timestamp in `sweep.log`. Low priority, not blocking, but flagged as a candidate addition to this project's existing "silent surface changes" tracking pattern (same category as the standing CLI-version re-probe tickle already in `NEXT.md`) if the pattern holds up under a second observation.
