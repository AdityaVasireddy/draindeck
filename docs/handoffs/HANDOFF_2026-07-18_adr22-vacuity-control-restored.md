# Session Handoff — ADR-22 vacuity-guard: synthetic positive control built, run, and reviewer-certified

## Objective
Item 0 (composed `ClaudeHeadlessEngine.run()` argv-survival witness) closed
its own narrow gap but its positive control failed to reproduce
`knowledge/` contamination — the third independent non-reproduction of the
original ADR-22 vacuity-guard control. Every green result in that family
was confounded: indistinguishable from "A-empty is suppressing an active
threat" vs. "nothing was ever going to contaminate this machine." This
session's job was to fix a blocking `config.yaml` corruption, then design
and (on approval) build a self-owned, reliably-arm-able positive control
that doesn't depend on the real ambient historian hook's drifting state —
and to survive an adversarial review that demanded raw witnessed output,
not agent-summarized results, for every pass/fail claim.

## Current Status
- Completed: `config.yaml` corruption fixed; Item 0 live run completed and
  documented (RUN/CLEAN-WITH-CAVEAT); synthetic positive control designed,
  approved, built, and run (Step B and Step C both PASS); `NEXT.md` and
  `docs/14-session6-phase2-gate.md` updated with the required dual framing;
  all raw evidence re-verified live, on disk, under reviewer pressure (see
  Testing / Verification Performed).
- In Progress: none.
- Blocked: Step 3 (live StockPhotoAgent smoke) — blocked on its own five
  preconditions (validation command, Ollama `qwen2.5-coder` pull,
  `Issues.md` authoring/location, baseline-green, `.gitignore` hygiene),
  none touched this session, last checked session 9 (2026-07-17). The
  reviewer separately noted the STANDING TICKLE's own two-leg probe
  (doc 14 §2.4 Probe 2/3) is only witnessed at CLI 2.1.212, while this
  session's runs happened at 2.1.214 — not a hard blocker for the
  ADR-22/vacuity design gate (which the reviewer certified discharged) but
  worth clearing before a live run leans on the STANDING TICKLE.

## Decisions & Rationale
- **`config.yaml` duplicate `child_env:` key fixed** by surgical
  single-line removal — diagnosed as an earlier Edit-tool replacement whose
  `old_string` anchored below the `child_env:` header instead of at it, so
  it appended a duplicate header instead of replacing in place. Evidenced
  via `git diff` against HEAD plus a `load_config()` call before (raised
  `ConfigError`) and after (clean) the fix. Not committed. —
  `C:\Projects\issue-runtime\config.yaml`
- **NEXT.md's parked Option (a)/(b) vacuity-guard decision resolved: Option
  (a) chosen.** Built a synthetic, zero-gate hook (NOT the real historian)
  registered via a scratch project-scope `.claude/settings.json`, proven to
  fire (Step B) before being trusted to judge A-empty (Step C) — the
  reviewer's explicit hard requirement ("a control you haven't watched fail
  is not a control"). Recorded explicitly, in both docs, that this does
  **not** retroactively verify the original historian bug was what A-empty
  stopped — that claim is **permanently INFERRED**, since no pre-patch
  artifact of `historian-sweep.sh` survives anywhere to diff against
  (`~/.claude/historian` is not a git repo, no backup exists). —
  `C:\Projects\issue-runtime\NEXT.md`,
  `C:\Projects\issue-runtime\docs\14-session6-phase2-gate.md`
- **Absolute paths used in the synthetic hook's `settings.json`**, not the
  relative path NEXT.md's original blueprint suggested — deliberately
  isolates "does a project-scope hook fire under a composed spawn at all"
  (what Step B exists to answer) from a separate, still-untested
  relative-path-resolution question.
- **Reviewer (separate review window) rejected agent-summarized pass/fail
  claims outright** and required raw witnessed output for every claim in
  this family. Re-verified Step B/Step C results this session via direct
  `cat`/`find`/`ls` against the actual marker files on disk (not the
  witness script's JSON characterization of them), and confirmed the live
  CLI version (`2.1.214`, up from session 10's `2.1.212`) via each
  transcript's own `claude_code_version` field in the `system`/`init`
  line — a stronger witness than a bracketing `claude --version` call,
  which neither witness script had captured.

## Key Files
- Plan file: `C:\Users\adity\.claude\plans\async-shimmying-whistle.md` —
  the approved synthetic-control-restoration plan; fully executed this
  session, kept for the record (includes the reviewer-mandated Step
  B-before-Step-C ordering, wrong-cwd-vs-didn't-fire disambiguation, and
  the escalate-don't-retry framing for a Step C failure).
- `C:\Projects\issue-runtime\NEXT.md` — STANDING TICKLE note, VACUITY-GUARD
  GAP section (Session 9/10/11 entries, decision recorded), Resume point,
  Item 0 line in the Step 3 preconditions table. All updated this session.
- `C:\Projects\issue-runtime\docs\14-session6-phase2-gate.md` — Item 0
  §2.6 "RUN this session" subsection, new Session 11 section documenting
  the synthetic-control build/run. Read this for the full probe-family
  history before touching ADR-22 again.
- `C:\Projects\issue-runtime\config.yaml` — corruption fixed, uncommitted.
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — read
  and referenced only (`_command()`, `.run()`, `_hygienic_env()`,
  `_parse_result()`); not modified.
- Scratch artifacts (uncommitted, outside the repo — matches every prior
  ADR-22 probe convention):
  - `~\AppData\Local\Temp\claude\C--Projects-issue-runtime\44f1eb81-468b-4aed-9b98-edf6d94ac86e\scratchpad\item0_witness.py`
    (Item 0 witness script)
  - `~\AppData\Local\Temp\claude\C--Projects-issue-runtime\44f1eb81-468b-4aed-9b98-edf6d94ac86e\scratchpad\adr22-synth-control\`
    (`synth-hook-marker.sh`, `witness_synth_control.py`,
    `probe_cwd_trigger/`, `probe_cwd_empty/`, `result.json` — holds the raw
    marker files and transcripts the reviewer's certification depended on)

## Next Action
Re-run doc 14 §2.4's Probe 2/3 (ADR-22 A-empty two-leg check) at the
now-current CLI 2.1.214 before any future session leans on the STANDING
TICKLE, which is still recorded at 2.1.212. Not a hard blocker — the
reviewer certified the ADR-22/vacuity design gate fully discharged as-is —
but it's the cleanest next unit of work. Independently, Step 3's own five
preconditions remain untouched and are a separate gate.

## Knowledge Captured
- `ClaudeHeadlessEngine._parse_result()` does NOT expose
  `permission_denials` or `tool_result` — only `apiKeySource`, `usage`,
  `num_turns`. Any future probe needing denial signals must parse the
  transcript JSONL manually (the `result` line's `permission_denials`
  array; `is_error` inside `tool_result` blocks nested in `user`-role
  message content).
- The transcript's `system`/`init` line carries a literal
  `claude_code_version` field — a better live CLI-version witness than a
  separate bracketing `claude --version` call, since it's embedded in the
  same artifact already used for `apiKeySource`. Worth building into any
  future witness script from the start (neither this session's synth-control
  script nor session 10's Item 0 script captured version separately; both
  gaps were only caught/patched around under reviewer pressure this
  session).
- `~/.claude/historian` is not a git repo and has no backup or versioned
  copy anywhere. The "original historian bug" root cause is **permanently**
  unrecoverable to VERIFIED status — a structural fact, not a temporary
  evidence gap that a future session could close with more digging.
- Current `historian-sweep.sh` is check-then-write with a recursion guard
  (`HISTORIAN_SWEEP_ACTIVE=1` short-circuit) and four early-return gates
  before its `mkdir` write. A code comment in the script itself ("the vault
  used to get created anyway") is first-person confirmation the old
  behavior was write-before-check, though undated/unversioned.
- Real ambient hook registration shape (`~/.claude/settings.json`, user
  scope): `SessionEnd` + `PreCompact`, `type:command`, `async:true`,
  `timeout:400`. This session's synthetic control deliberately used
  `async:false` to remove one timing variable while validating the assay
  itself — a defensible deviation for validation, but note it if anyone
  wants to reconcile timing behavior with the real hook later.

## Assumptions
- HIGH confidence: the synthetic control's Step B/C results generalize to
  "A-empty suppresses project-scope settings-loaded hooks" — directly
  observed via file-existence checks re-verified live, not inferred.
- Permanently LOW / explicitly non-upgradable: "A-empty stopped the
  original historian contamination bug specifically" — stays INFERRED
  forever per this session's own findings (see Knowledge Captured above).
  No future session should be able to upgrade this without a pre-patch
  artifact that does not exist.
- MED confidence: using absolute paths (not the originally-blueprinted
  relative path) in the synthetic hook's `settings.json` didn't compromise
  the control's validity — reasoned, not tested against the relative-path
  variant, which remains untested if anyone specifically needs it later.

## Testing / Verification Performed
- PASS: `config.yaml` — `load_config()` succeeded after the fix (previously
  raised `ConfigError: engine.child_env.child_env — Input should be a
  valid string`).
- PASS: Item 0 Pass 1 (real `engine.run()`) — `exit_status=0`,
  `apiKeySource=none`, `permission_denials` + `is_error:true` for a denied
  `git init`, `.git` absent, `knowledge/` absent across 450s/16 polls, zero
  new `skips.log` lines for that run's cwd.
- NOT REPRODUCED (a genuine finding, not a script failure): Item 0 Pass 2
  positive control — `knowledge/` never appeared even with
  `--setting-sources ""` stripped from the argv.
- PASS: synthetic control Step B — marker fired at t=0s under
  `--setting-sources project`; event/pid/cwd fields re-verified this
  session via direct `cat` of the marker file on disk and a literal pid
  comparison (hook `229655` vs. witness script `22956`), not just the
  script's own JSON output.
- PASS: synthetic control Step C — marker absent across all 16 polls/450s
  under the real, unmutated `--setting-sources ""`; re-verified via direct
  `ls` (confirmed nonexistent at the expected path) and a scratch-root-wide
  `find` (only Step B's marker found, nowhere else).
- NOT TESTED: Step 3's five preconditions — untouched this session, last
  real check was session 9 (2026-07-17) per `NEXT.md`.
- NOT TESTED: doc 14 §2.4 Probe 2/3 (ADR-22 two-leg re-verify) at CLI
  2.1.214 — only witnessed at 2.1.212 on record; the version bump was
  discovered incidentally (via the synth-control transcripts), not
  proactively re-probed this session.

## Risks
- CLI version drift: `2.1.212` → `2.1.214` happened between sessions with
  no corresponding re-probe of ADR-22's Probe 2/3 two-leg check. If a
  future session runs Step 3's live smoke while relying on the STANDING
  TICKLE's stale 2.1.212 record, that is exactly the kind of silent
  surface drift ADR-21 was written to guard against. Not yet manifested as
  a failure — flagged as a risk only.

## User Constraints
- Standing rule: no commit without explicit user request — nothing was
  committed this session despite substantial file changes.
- No `src/`, `schema.py`, or `transitions.py` changes this session (frozen
  contract; doc 03 governs). No Step 4 event-schema work, no Step 3 live
  smoke, no 5-issue supervised run — all explicitly out of scope.
- Reviewer's evidence discipline: every pass/fail claim must be a
  mechanical projection (event log, git ref, or witnessed output) — never
  engine/reviewer self-report. Enforced hard this session; should carry
  forward to any future session touching this probe family.
- `ANTHROPIC_API_KEY` must stay unset (subscription billing) — confirmed
  unset throughout this session's live spawns.

## Runtime & System State
- Commit at handoff: `62e67de` (unchanged this session — nothing
  committed).
- Working tree: `config.yaml`, `NEXT.md`,
  `docs/14-session6-phase2-gate.md` modified (uncommitted);
  `knowledge/.sweep/sweep.log` also shows modified (pre-existing
  auto-generated file, not intentionally touched); two untracked handoff
  files from prior sessions (session 8, session 9) present, not created
  this session.
- Background processes: none currently running — all `run_in_background`
  Bash tasks from this session completed and were read via their output
  files; nothing left to track or kill.
- Dev servers / ports: none.
- Open branches / worktrees: none opened this session (on `master`
  throughout).
- Memory files updated: none this session.

## Deferred Work
- Re-running doc 14 §2.4 Probe 2/3 at CLI 2.1.214 — deferred per the
  reviewer's own framing ("if you want the tickle itself clean before a
  live run leans on it"), not a hard requirement to close this session's
  work.

## Open Questions
**Needs User Input**
- Commit `config.yaml` / `NEXT.md` / `docs/14` changes now, or hold until
  Step 3's own preconditions are also resolved so everything lands in one
  commit?
- Do the CLI 2.1.214 re-probe before or independent of picking up Step 3's
  own five preconditions?

**Model Uncertainty**
- None beyond what's already flagged under Assumptions (the relative-path
  hook-resolution question was deliberately routed around, not resolved).
