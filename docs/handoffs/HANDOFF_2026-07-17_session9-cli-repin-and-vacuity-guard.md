# Session Handoff — Session 9: CLI re-pin re-probe (2.1.212), Step-3 precondition sweep, vacuity-guard follow-up

## Objective
Re-verify ADR-18/21/22 against the now-installed `claude` CLI version (a bump from
2.1.211 to 2.1.212 was detected this session), re-check Step 3's five own
preconditions live against StockPhotoAgent (none carried forward from
Session 7/8 assumption), and design (but not run) the item-0 argv-survival
gate that must pass before Step 3's live smoke. A tight review follow-up
then required correcting one causal claim's evidence label and parking a
newly-discovered vacuity-guard gap as an explicit open decision.

## Current Status
- Completed: ADR-18 strip-var re-check; ADR-21/22 live re-probe at CLI
  2.1.212 (two spawns); Step-3's five preconditions re-checked live; item-0
  witness designed (not run); review-requested label correction and
  cause-3 rule-out; vacuity-guard gap recorded as its own NEXT.md item;
  doc 14 §2.6 + NEXT.md written; committed.
- Blocked: Step 3's live smoke — blocked on three user-side items (Ollama
  model pull, Issues.md relocation/reformat, validation command) plus item 0
  still not run. None of the three blockers are something this agent can
  resolve unilaterally.

## Decisions & Rationale
- **Skipped a full ADR-21 C1-C4 fence re-run**, did one fence-trip spot check
  instead (Probe B, denied `git init`) — the 2.1.211→2.1.212 bump is
  patch-level and §2.2 already re-derived the full matrix at the prior
  (2.1.207→2.1.211) bump; a full re-run was judged unnecessary. Recorded in
  `docs/14-session6-phase2-gate.md` §2.6.
- **Downgraded the "historian hook independently patched upstream" claim
  from VERIFIED to INFERRED** — done in response to explicit review
  pushback. Rationale: no line-anchored quote/diff of the hook's Session-7/8
  code state exists anywhere in this repo's records to compare against the
  current read of `historian-sweep.sh:293-304`; `~/.claude/historian` has no
  git history either. The VERIFIED facts (contamination then, no
  contamination now, hook ran to completion per `skips.log`) are now stated
  separately from the INFERRED causal/temporal attribution. See doc 14 §2.6
  ("Label correction" and "What IS verified" / "What is INFERRED"
  subsections).
- **Ruled out local-confound alternatives (cause 3)** rather than leaving the
  INFERRED label unqualified: checked `HISTORIAN_SWEEP_ACTIVE` was unset in
  the probe's env, confirmed `jq` present and functioning (via the
  well-formed `skips.log` entry, which requires successful JSON parsing),
  confirmed no disable/pause flag files, confirmed no other early-exit gate
  before the transcript check, confirmed hook registration unchanged in
  `~/.claude/settings.json`. One residual, un-ruled-out possibility (cause
  2: some other divergence in probe methodology from the original Session
  7/8 harness) is flagged, not resolved.
- **Did not build or run the vacuity-guard replacement (option a)** — judged
  as its own probe-design task, same class as item 0, deliberately left for
  a dedicated follow-up rather than squeezed into this session's tight
  review-response scope. Recorded as an open decision (a vs. b) in NEXT.md's
  new "VACUITY-GUARD GAP" section.
- **Committed only `NEXT.md` and `docs/14-session6-phase2-gate.md`** —
  excluded `knowledge/.sweep/sweep.log` (ambient historian tool activity,
  unrelated to this repo's work) from the commit.

## Key Files
- `~/Projects/issue-runtime/docs/14-session6-phase2-gate.md` §2.6 — full
  probe evidence (Probe A/B), the label-correction writeup, cause-3
  rule-out detail, and the item-0 witness design. This is the primary
  record for this session; NEXT.md summarizes it.
- `~/Projects/issue-runtime/NEXT.md` — top of file: STANDING TICKLE (ADR-22
  B-layer sunset, now with the Session-9 partial-re-run note), new
  VACUITY-GUARD GAP section, updated Resume point, and the rewritten Step-3
  preconditions table (0-5) with live re-check status.
- `~/.claude/historian/historian-sweep.sh` (outside this repo, operator's
  own tool) — lines ~293-304 (transcript-existence gate) and ~691-706 (hook
  entry / `jq` check) are what this session's root-cause investigation
  read directly. Not version-controlled (`git status` there: "not a git
  repository") — any future re-investigation starts from the same
  no-history limitation.

## Next Action
Whoever next touches ADR-22 re-pinning should read NEXT.md's VACUITY-GUARD
GAP section first and pick option (a) or (b) before relying on a Probe-A-style
control again — the control currently gives a false "all clear" regardless
of whether A-empty is doing anything, since it no longer discriminates.
Separately and independently, the three Step-3 user-side blockers (Ollama
`qwen2.5-coder` pull, Issues.md move-to-root + reformat, validation command)
remain outstanding and are not this agent's to resolve.

## Assumptions
- INFERRED (not HIGH confidence): the historian hook's write-before-check
  bug was fixed upstream between Session 8 and Session 9. Best-supported
  explanation after ruling out local confounds, but not confirmed by any
  before/after comparison — see Decisions & Rationale above.
- MED confidence: the 2.1.211→2.1.212 bump is patch-level with no fence
  semantics change, based on the absence of any surprising signal in Probe
  B's single fence-trip check — not confirmed by a full C1-C4 re-run.

## Testing / Verification Performed
- PASS: ADR-18 six-var strip-list check (`printenv` on each, unset) —
  VERIFIED live this session.
- PASS: Probe B (production `_command()` argv mirror: `--setting-sources
  ""` + full `_DENY_TOOLS`, live `claude` spawn) — rc=0, `apiKeySource:
  "none"`, clean at the full 450s poll, `git init` denied with both
  2.1.211+ signals, `.git` absent, no `skips.log` entry for that cwd.
  VERIFIED live at CLI 2.1.212.
- NOT REPRODUCIBLE: Probe A (control, no suppression) — expected
  contamination per Session 7/8's methodology, did not occur (checked at
  t≈30s, t≈90s, and re-checked ~3 hours later). See Decisions & Rationale
  for the label-corrected interpretation.
- NOT TESTED: item 0 (real `ClaudeHeadlessEngine.run()` against real
  `claude`) — designed only, explicitly out of scope to run this session.
- NOT TESTED: StockPhotoAgent's actual test suite (`baseline-green`
  precondition) — no test-runner config exists to invoke; running bare
  `pytest` was judged unsafe given the `tests/` directory contains files
  that look auth/network-probe-shaped, not obviously the project's own
  suite.

## Risks
- The vacuity-guard gap itself: until resolved (option a/b), a future
  CLI-bump re-pin cycle could pass its `--setting-sources ""` clean-check
  while A-empty is silently doing nothing, with no control able to catch
  that condition.
- Cause 2 (unruled-out probe-methodology divergence) — if some difference
  between this session's hand-built probe harness and the original
  `~/.claude/plans/floating-napping-pelican.md` harness is the real reason
  Probe A didn't reproduce, the "historian hook was fixed" inference would
  be wrong, and the vacuity-guard gap's root cause would need re-diagnosis.

## User Constraints
- No `src/` change this session (honored — diff is `NEXT.md` +
  `docs/14-session6-phase2-gate.md` only).
- No commit without explicit request (honored — committed only after this
  session's explicit "commit" instruction).
- Do not touch `schema.py` or `transitions.py` this session (not touched).
- Do not expand scope into Step 3 execution or item 0's live run (honored).

## Runtime & System State
- Commit at handoff: `eed1760`
- Working tree: clean except `knowledge/.sweep/sweep.log` (ambient historian
  tool activity, not part of this repo's tracked work) and an untracked
  prior handoff file (`docs/handoffs/HANDOFF_2026-07-17_session8-adr22-mechanism-landed.md`)
  from a previous session.
- No background processes started this session.
- No dev servers running.
- `claude` CLI version witnessed this session: **2.1.212**.

## Open Questions
**Needs User Input**
- Ollama: pull `qwen2.5-coder` (currently only `qwen2.5vl:7b` is present).
- Issues.md: move to StockPhotoAgent's repo root and convert to the
  `## <id>: <title>` heading format (currently `docs/Issues.md`, a numbered
  list — parsing it as-is raises `IssuesParseError`).
- Validation command: `config.yaml → project.validation.commands` still has
  the placeholder; no test-runner config exists anywhere in
  StockPhotoAgent to infer one from — needs to come from the user.
- Vacuity-guard gap: option (a) build a synthetic discriminating control, or
  option (b) retire the control and rely on structural/unit evidence instead
  — no position taken this session, needs a decision before the next
  re-pin cycle.
