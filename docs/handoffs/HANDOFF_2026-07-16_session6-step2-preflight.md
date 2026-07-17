# Session Handoff — Session 6 Step 2 preflight (2a billing + 2b fence re-probe), committed

## Objective
Re-verify, by live observation rather than carried-forward assumption, the two
Phase-2-gate preflight items doc 07/doc 14 require before any gated live smoke:
**2a** billing posture (ADR-18, contractually due at `billing.reverify_at:
phase-2-gate`) and **2b** the engine tool-fence behavior (ADR-21, pinned to
`claude` 2.1.207). The session ran under a user-gated plan with two rounds of
external review (six amendments pre-execution, four more before the final
probes) — every claim in the resulting record carries an explicit
VERIFIED / INFERRED / NOT-OBSERVABLE label per the project's honesty
discipline. A new blocker surfaced mid-session (ambient hook contamination of
the engine's working directory) and is carried forward, unresolved, as the
reason Step 3 cannot start yet.

## Current Status
- Completed: Step 2 preflight (2a + 2b), fully re-derived by live observation,
  committed at `2877733`. Both the doc 14 §2 as-built diff and the
  `claude_headless.py` comment-only diff were shown to the user verbatim and
  externally cleared before commit.
- Blocked: **Step 3 (gated live smoke) cannot start.** Two decisions are
  queued for the user, both detailed in `NEXT.md` (resume point + numbered
  list) and `docs/14-session6-phase2-gate.md` §2.2–2.3 — see Next Action.

## Next Action
**Step 3 is blocked, not merely next in sequence — do not attempt the gated
live smoke without first resolving this:** every engine run through the
production `ClaudeHeadlessEngine.run()` path writes an unrequested
`knowledge/` tree (an ambient engineering-historian hook/skill vault
bootstrap) into the run's working directory. Against a real target repo this
dirties the tree on every single run, which trips `is_dirty()` / reconciler
check 3 and turns the Step-3 smoke into a guaranteed false failure (or worse,
masks a genuine dirty-tree signal behind expected noise). This needs an
ADR-level decision — sanitized settings, hook suppression, or another
mechanism — made explicitly with the user before any engine run touches a
real repo. Full detail, including which probe runs showed the contamination
and which didn't, is in `docs/14-session6-phase2-gate.md` §2.3 and
`NEXT.md`'s Resume-point blocker list; read those rather than re-deriving.

A second, non-blocking item should be resolved in the same pass: an ADR-21
amendment note is queued (also in `NEXT.md` and doc 14 §2.2) because at
`claude` 2.1.211 a whole-tool denial is no longer observable from the result
stream — no tool attempt, no `is_error`, no `permission_denials` entry. The
only signal is the init `tools` manifest at spawn. This doesn't block Step 3
itself, but any future audit or ADR-19 metric-capture logic must be designed
against the manifest-absence signal, not the old result-stream signal.

## Decisions & Rationale
- **2a billing re-verified as still PAUSED, not carried forward from
  2026-07-10** — re-fetched the Anthropic Help Center source of record this
  session and found the same "nothing has changed" banner; `config.yaml →
  billing.verified_on` was bumped to `'2026-07-16'`. Rationale: the project's
  honesty discipline requires re-derivation at the phase-2 gate, not reuse of
  a stale finding — `docs/14-session6-phase2-gate.md` §2.1.
- **2b fence re-probed at `claude` 2.1.211 (the installed CLI had moved off
  the 2.1.207 pin) rather than assumed unchanged** — four live `claude -p`
  probes (one against the actual production `ClaudeHeadlessEngine.run()`
  path) confirmed deny enforcement, selectivity, chaining-resistance, and
  `--allowedTools` non-restriction are all unchanged from ADR-21. Landed as a
  **comment-only** docstring/comment update in
  `src/runtime/engine/claude_headless.py` (no logic touched) — gated on the
  103-unit suite plus a diff review confirming zero non-comment lines
  changed, per a pre-committed rule for exactly this kind of edit.
- **Whole-tool-denial detection is recorded as changed, not silently
  patched over** — 2.1.211 drops a denied whole tool from the init `tools`
  manifest instead of producing a result-stream error, so the old detection
  note in the code comments would have gone stale. It was rewritten to be
  version-scoped rather than corrected in place as if always true — see the
  inline `[2.1.207 ONLY — ...]` tag in `claude_headless.py`.
- **The `knowledge/`-contamination finding was recorded and left unfixed on
  purpose** — this session's scope was preflight verification, not incident
  response, and the fix is squarely ADR territory (which mechanism —
  sanitized settings vs. hook suppression — is a design choice, not a bug
  fix). Fixing it ad hoc would have violated the project's "architecture is
  frozen, changes go through an ADR" rule.
- **`knowledge/.sweep/sweep.log` was deliberately left unstaged** — it's a
  pre-existing ambient-tooling change unrelated to Step 2's scope; committing
  it would have muddied a commit meant to be scoped to preflight only.

## Key Files
- Plan file: `~/.claude/plans/floating-napping-pelican.md` — the full
  probe-by-probe plan this session executed, including all ten user
  amendments (six before execution, four before the final three probes); read
  this for the exact pass/fail criteria each probe was held to.
- `~/Projects/issue-runtime/docs/14-session6-phase2-gate.md` §2 (as of commit
  `2877733`) — the as-built record: the full VERIFIED/INFERRED/NOT-OBSERVABLE
  table for 2a, the per-probe fence findings for 2b, and the §2.3
  `knowledge/`-contamination finding with its consequences spelled out.
- `~/Projects/issue-runtime/NEXT.md` — resume point and the two queued
  decisions, written for the next session to act on directly.
- `~/Projects/issue-runtime/src/runtime/engine/claude_headless.py` — the
  three comment-only hunks (module docstring, ADR-21 block header, and the
  version-scoped detection-signal note).

## Testing / Verification Performed
- PASS: `pytest tests/unit -q` → 103 passed, run at the actual pre-commit
  state (not just after the initial edit).
- PASS: `git diff --cached src/runtime/engine/claude_headless.py` reviewed
  line-by-line against the staged bytes — confirmed every changed line falls
  inside the module docstring or a `#`-prefixed comment; zero non-comment
  lines staged.
- PASS: four live `claude -p` probes (one hand-built fence mirror, one
  `--allowedTools`-only recheck, one whole-tool-removal recheck, one through
  the actual production `ClaudeHeadlessEngine.run()`), zero re-runs needed
  against a pre-committed budget ceiling of seven.
- NOT TESTED: the gated live smoke itself (Step 3) — explicitly out of scope
  until the `knowledge/`-contamination decision is made.

## Outstanding Issues
- The `knowledge/`-contamination finding (§2.3) has already manifested three
  times across the session's own probe runs, including once through the
  actual production code path — this is not a hypothetical, it is observed
  behavior that will recur on every future engine run until addressed.

## User Constraints
- No `src/` behavior changes without an ADR — enforced this session by
  keeping the version re-pin comment-only and explicitly gating it on a
  zero-non-comment-line diff review.
- Kill criteria and other frozen contracts were not touched or discussed this
  session; not re-litigated.
- Every summary must separate VERIFIED from ASSUMED — this handoff followed
  that discipline throughout doc 14 §2, and the same distinction is preserved
  above (e.g., 2a's "which pool is billed" is explicitly INFERRED, not
  VERIFIED, in the underlying record).

## Runtime & System State
- Commit at handoff: `2877733`
- Working tree: clean except `knowledge/.sweep/sweep.log` (pre-existing,
  ambient, deliberately unstaged)
- No background processes, dev servers, or open worktrees from this session.

## Open Questions

**Needs User Input**
- Which mechanism resolves the `knowledge/`-contamination finding — sanitized
  settings for the engine's spawned environment, suppressing the
  engineering-historian hook/skill for engine-child sessions, or something
  else? This is an ADR-level decision and blocks Step 3 outright.
- How to word the ADR-21 amendment for the whole-tool-denial detection change
  at 2.1.211 — non-blocking for Step 3, but should be resolved in the same
  pass per the user's own framing this session.
