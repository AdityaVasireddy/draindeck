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

---

## 5. ADR-20 — Initial target repository: StockAgent; repository is configuration only

**Decision.** The v1 target repository is **StockAgent** (local path `C:\Projects\StockPhotoAgent`, working branch `agent-work`).

> ⚠ Naming discrepancy to resolve in config: the decision names the project "StockAgent" but the path is `StockPhotoAgent`. The path below is used verbatim as provided; correct it in `config.yaml` if the directory name differs on disk.

**Repository-agnosticism (binding constraint):** no component may hardcode a repository path, branch name, language, test command, or project layout. All repository-specific knowledge enters through exactly two channels:

1. `config.yaml → project.*` — path, branch, validation commands.
2. The Repository Adapter interface (doc 09 §7) — all git and filesystem operations against the target repo go through it.

The baseline-green requirement (doc 06) applies to StockAgent: its test suite must pass on `agent-work` before the first supervised run.

**Rationale.** Real project, safe to experiment on, immediate business value, demoable; and choosing a real repo forces the repository-agnostic seam to be honest rather than theoretical.

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
