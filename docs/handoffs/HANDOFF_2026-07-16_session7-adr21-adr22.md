# Session Handoff — Session 7: ADR-21 Amendment 1 landed, ADR-22 drafted Proposed, p2 §2.3 correction confirmed

## Objective
Resolve the two decisions queued at the end of Step 2 (doc 14 §2.3/§2.2, NEXT.md)
before Step 3 (gated live smoke) can proceed: (1) the mechanism behind the
`knowledge/`-contamination Step-3 blocker, drafted as ADR-level options, and
(2) the ADR-21 amendment recording the whole-tool-removal detection-mechanism
change at `claude` 2.1.211. Scope for this session was landed **text** only —
no mechanism code, no config change, and no commit until the plan was
explicitly gated and then re-approved by the user at close-out.

## Current Status
- Completed: ADR-21 Amendment 1 (Accepted), ADR-22 (Proposed, all four options
  drafted with probe evidence inlined), the doc 14 §2.3 p2 correction note plus
  its Session-7 close-out discriminating-check addendum, doc 14 §2.4 (full
  probe matrix), `claude_headless.py` comment-only pointer updates, NEXT.md
  updated. All committed at `734d08b` on `master`.
- Blocked: Step 3 (gated live smoke) — unchanged, still blocked. ADR-22 must
  be marked Accepted and its adopted mechanism must be probe-verified (the
  probes already exist in doc 14 §2.4; nothing new needed there) before Step 3
  can start.

## Decisions & Rationale
- **ADR-21 Amendment 1 — ACCEPTED.** At `claude` 2.1.211 a whole-tool removal
  (e.g. `--disallowedTools WebFetch`) is no longer visible on the result
  stream — the denied tool is dropped from the session's init `tools`
  manifest instead, so there's no `tool_use` attempt, no `is_error`, no
  `permission_denials` entry (2.1.207 behavior was a `tool_result is_error`
  with `permission_denials` empty). Pattern-level denies (`Bash(cmd:*)`) are
  unchanged and still carry both signals. Binding consequence: any future
  "was a tool denied" audit or metric (including Step-4 ADR-19 capture) must
  key on **manifest absence at spawn**, not a result-stream signal that no
  longer exists for whole-tool denies. Landed in
  `docs/08-session-0-closure-and-adr-amendments.md` (new subsection after
  §5b) and cross-referenced from `docs/14-session6-phase2-gate.md` §2.2.
- **ADR-22 — PROPOSED, not yet accepted.** The `knowledge/`-contamination
  mechanism is the operator's user-scope `~/.claude/settings.json`
  `SessionEnd`/`PreCompact` hooks (engineering-historian vault bootstrap),
  which load in every `claude` process on this machine including engine
  children, and write before the hook's own gate runs. Four options drafted
  (A: `--setting-sources` isolation, in an empty-vs-`project,local` split; B:
  `HISTORIAN_SWEEP_ACTIVE=1` in child env; C: workspace-level exclusion,
  rejected; D: fix the historian script itself, external hygiene only).
  Recommendation stated but not applied: A-empty as the durable fix, B as a
  belt-and-braces layer sunsetting after one clean CLI-upgrade cycle, C
  rejected, D optional. All three live candidates (A-empty, A-`project,local`,
  B) were probe-verified this session — see Testing / Verification. Adi's
  selection is the open gate; see Open Questions.
- **p2 §2.3 discriminating check — VERIFIED, race explanation confirmed, not
  falsified.** doc 14 §2.3 originally recorded p2 as the one clean probe out
  of four; a same-session re-check found `p2/knowledge/` in fact present, with
  the SessionEnd hook recording session ID `afc8223a-8762-43f2-881d-78bfd0e20d65`.
  At close-out, p2's own engine-child session ID was recovered from its
  archived transcript (`step2/c2-transcript.jsonl`, the C2 `--allowedTools`
  probe, `cwd` confirmed as the p2 directory) via the init line, and it
  matched `afc8223a...` exactly. This confirms the contamination in p2 came
  from p2's own probe run (an async-hook write that landed after the Step-2
  check ran), not from a later or unrelated session. Contamination stands as
  **4/4**, not 3/4. Recorded as a dated addendum in `docs/14-session6-phase2-gate.md`
  §2.3, original note left in place per doc 12 pattern (never a silent edit).

## Key Files
- Plan file: `~/.claude/plans/continuing-issue-runtime-pull-context-shiny-kahn.md`
  — the Session-7 gated plan this session executed (approved with amendments
  by external review before any probe ran).
- `~/Projects/issue-runtime/docs/08-session-0-closure-and-adr-amendments.md`
  — ADR-21 Amendment 1 (Accepted) and ADR-22 (Proposed) both live here, after
  the original §5b ADR-21 text.
- `~/Projects/issue-runtime/docs/14-session6-phase2-gate.md` — §2.3 carries
  both the original contamination finding and the two Session-7 correction
  notes; §2.4 is the new full probe-matrix record (5 probes, 0 re-runs,
  0 deviations).
- `~/Projects/issue-runtime/src/runtime/engine/claude_headless.py` — two
  comment-only hunks pointing the existing "amendment pending" language at
  Amendment 1; no logic changed.
- `~/Projects/issue-runtime/NEXT.md` — item 2 (ADR-21 amendment) closed; item 1
  (contamination) updated with the mechanism finding, probe results, and the
  decision now pending from Adi.

## Next Action
Session 8 opens once Adi selects an ADR-22 option: mark ADR-22 Accepted in
doc 08, then land the mechanism (argv `--setting-sources ""`, plus
`EngineCfg.child_env` / `_hygienic_env()` merge for the B belt-and-braces
layer with ADR-18 strip-list supremacy preserved, plus the corresponding
`config.yaml` entry), with new tests (unit suite expected to grow from 103 to
~106) and a full durability-harness run (60/60 both seeds) gating the src/
change, since Session 7's edits were comment-only and did not exercise that
gate.

## Testing / Verification Performed
- PASS: `pytest tests/unit -q` → 103 passed, re-run immediately before the
  Session-7 commit (not just after the initial edits).
- PASS: `git diff` on `claude_headless.py` reviewed line-by-line — every
  changed line falls inside a `#`-prefixed comment block; zero non-comment
  lines changed.
- PASS: five live `claude -p` probes this session (positive control + 4
  suppression-candidate probes), 0 re-runs against a pre-committed ceiling of
  5, 0 deviations from expected outcome. Positive control confirmed
  contamination at t=4s from spawn (vacuity guard passed — the matrix can
  detect the failure mode). All three suppression candidates
  (`--setting-sources ""`, `--setting-sources project,local`,
  `HISTORIAN_SWEEP_ACTIVE=1`) stayed clean through a 450s post-exit poll, with
  `apiKeySource` unchanged from the Step-2 baseline (`"none"`) in every run.
  A sixth probe confirmed the ADR-21 fence (a denied `git init`) still
  produces both 2.1.211 pattern-deny signals under `--setting-sources ""`.
  Full verbatim results in doc 14 §2.4.
- PASS: p2 discriminating check — session ID recovered from
  `step2/c2-transcript.jsonl` matched the sweep.log's recorded ID exactly.
- NOT RUN: durability harness (`tests/crash/harness.py`) — no `src/` logic
  changed this session (the only src/ edit was comment-only), so the gate
  does not apply; stated explicitly rather than silently skipped.
- NOT TESTED: Step 3 gated live smoke — still out of scope until ADR-22 is
  Accepted and its mechanism lands.

## User Constraints
- No commit without explicit request — held through the full plan-then-execute
  sequence; the commit only happened after the user's explicit Step 3
  instruction, and was re-scoped mid-step when the user corrected the file set
  to exclude ambient, pre-existing changes not produced this session.
- Doc 03 governs any event/state semantics question — the ADR-21 Amendment 1
  text explicitly defers the init-manifest structured-capture question to a
  future doc-03-governed decision rather than making it unilaterally.
- Architecture is frozen; any mechanism change goes through an ADR — followed
  throughout: ADR-22 is Proposed only, no code/config mechanism landed this
  session.
- Kill criteria, doc 02 §3, and everything settled in Step 2 were cited as
  closed context, not re-litigated or re-derived.

## Runtime & System State
- Commit at handoff: `734d08b` on branch `master`. (issue-runtime is the build
  repo and lives only on `master`; `agent-work` is the *target* repo's branch,
  not this repo's — confirmed and corrected mid-session after an initial
  instruction assumed otherwise.)
- Working tree: clean except pre-existing, unrelated ambient changes to
  `knowledge/.sweep/pending.log` and `knowledge/.sweep/sweep.log` — produced by
  an engineering-historian sweep of an earlier, unrelated session (observed
  session id `bd4fb942...`, timestamped before this session's work began),
  deliberately left unstaged and excluded from the commit at the user's
  explicit direction.
- No background processes, dev servers, or open worktrees from this session.

## Open Questions

**Needs User Input**
- Which ADR-22 option to accept: A-empty (`--setting-sources ""`) alone,
  A-empty + B (`HISTORIAN_SWEEP_ACTIVE=1`) layered, A-`project,local` instead
  of A-empty (accepting its residual project-scope surface), or something
  else. Recommendation on record in doc 08 §5c: A-empty durable + B
  belt-and-braces, B sunsetting after one clean CLI-upgrade cycle. This is the
  single gate blocking both Session 8's mechanism work and Step 3.
