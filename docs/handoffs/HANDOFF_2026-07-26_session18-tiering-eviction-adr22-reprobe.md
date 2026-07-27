# Session Handoff — Process fixes (tiering rule, historian eviction) + ADR-22 literal Probe 2/3 re-probe PASS at CLI 2.1.220

## Objective
This was a process-fix + probe session, not a build session. Three threads: (1) codify a
blast-radius tiering rule in CLAUDE.md so review overhead scales to what a change actually risks,
not to how long the session runs; (2) stop tracking the historian experiment vault (`knowledge/`)
in this repo and gitignore it; (3) close a specific, previously-flagged coverage gap — the literal
doc 14 §2.4 ADR-22 Probe 2/3 procedure had not been re-witnessed since CLI 2.1.211, while the
2.1.215 "re-probe" (doc 14 §2.7) had substituted a different (synthetic-marker) methodology
without actually re-running Probe 2/3 itself. NEXT.md §4 named this identity gap explicitly; this
session closed it by re-running the actual Probe 2/3 procedure at the CLI version now installed
(2.1.220).

## Current Status
- Completed: blast-radius tiering rule added to CLAUDE.md (commit `e049aa3`).
- Completed: historian experiment vault (`knowledge/`) untracked and gitignored (commit `70cd4c9`).
- Completed: ADR-22 literal Probe 2/3 re-run at CLI 2.1.220, both legs PASS, recorded in
  `docs/14-session6-phase2-gate.md` §2.8 (commit `ab99f55`).
- Completed: NEXT.md §2 synced to reflect the §4 closure — items 3 and 6 marked closed instead of
  owed (commit `aa75231`).
- Blocked (unchanged from Session 17): live smoke still NOT authorized. Gate (a) (vacuity-guard
  detectability) remains permanently unproven; gate (b)'s three carried-forward-unwitnessed
  surfaces (main.py startup composition, orphan-crash recovery path, real-tree behavior) are
  untouched this session.

## Decisions & Rationale
- **Blast-radius tiering rule adopted, not the uniform five-gate process.** Prior sessions
  (~17 of them) applied the full five-gate + heavy-review apparatus even to reversible
  documentation work. The rule makes explicit that process depth should scale to blast radius
  (real repo mutation, src/runtime behavior, event schemas, state transitions, external
  contracts, Git/recovery behavior, safety/durability claims = high; docs, NEXT.md, handoffs,
  scratch work, reversible cleanup = low). Lives in `CLAUDE.md` at the project root (commit
  `e049aa3`).
- **`knowledge/` evicted from git tracking and added to `.gitignore`**, rather than kept tracked.
  It is an experiment vault for a separate historian tool, not project state; tracking it was
  incidental. Commit `70cd4c9`.
- **ADR-22 re-probe used the actual §2.4 Probe 2/3 procedure, not the Session-11 synthetic-marker
  substitute used at 2.1.215.** The user explicitly required this — a re-probe using a different
  methodology than the one it's meant to re-witness doesn't close the gap it claims to close.
  Ran via a standalone scratch script (`probe_23.py`, scratchpad-only, not committed) that
  hand-mirrors `ClaudeHeadlessEngine._command()`/`_hygienic_env()` from
  `src/runtime/engine/claude_headless.py` (read for fidelity, never imported/modified). Both legs
  PASS: Probe 2 (empty `--setting-sources`, clean at 450s across all 16 poll ticks) and Probe 3
  (fence sanity — `git init` attempted-and-denied with both deny signals, `.git` absent, verified
  by direct `ls`). Recorded in `docs/14-session6-phase2-gate.md` §2.8 (commit `ab99f55`).
- **B-layer (`HISTORIAN_SWEEP_ACTIVE`) held, not sunset, despite an all-PASS matrix.** NEXT.md §4
  already carried a standing explicit-user instruction from Session 12 to hold B even on green;
  this session's PASS result does not change that — sunset stays a deliberate per-instance
  decision, never an automatic consequence of a passing probe. No `config.yaml` change made.
- **NEXT.md §2 items 3 and 6 updated to reflect closure**, so a handoff snapshot taken now doesn't
  read as if the ADR-22 tickle/coverage gap were still owed — a fresh session reading only §2
  would otherwise re-derive work already committed done. §1 and items 1, 2, 4, 5, 7 intentionally
  left untouched (still accurate). Commit `aa75231`.
- **Both-halves discipline maintained explicitly in the doc 14 §2.8 write-up**: the PASS closes
  the literal Probe 2/3 re-witness gap only; it does not resolve the separate, permanently-open
  vacuity-guard question (a clean Probe 2 can't discriminate "still suppressing" from "no-op
  because upstream is inert"); and it does not license the B-layer sunset.

## Key Files
- `~/Projects/issue-runtime/CLAUDE.md` — blast-radius tiering rule (commit `e049aa3`).
- `~/Projects/issue-runtime/NEXT.md` — §4 updated with the 2.1.220 re-probe result (commit
  `ab99f55`); §2 items 3/6 synced to that closure (commit `aa75231`).
- `~/Projects/issue-runtime/docs/14-session6-phase2-gate.md` §2.8 — the full Probe 2/3 re-probe
  write-up: method, both legs' raw results, both-halves discipline (commit `ab99f55`).
- `~/Projects/issue-runtime/src/runtime/engine/claude_headless.py` — read this session (not
  modified) to hand-mirror `_command()`/`_hygienic_env()` for the probe script; still the
  authoritative source for the real production argv/env-hygiene logic.
- `.gitignore` — now excludes `knowledge/` (commit `70cd4c9`).

## Next Action
Decide the live-smoke sequencing question at NEXT.md §2 item 1: whether to witness one of the
three carried-forward-unwitnessed surfaces (`main.py` end-to-end startup composition, the
orphan-crash recovery path, real-tree behavior) before designing live smoke, or carry all three
forward labeled into live smoke itself. This is a decision only — no precondition, no code
required to answer it. (§2 item 2, the ingest branch-check gap decision — Option A `checkout_branch`
before ingest vs. Option B accept-as-scoped-risk — is the other open decision-only item at the
same priority tier; either can be taken first.) Gate (a), the vacuity-guard detectability question,
stays carried forward as a permanently unproven, labeled limitation per standing ruling — it is
not a blocker to resolve before this decision. Live smoke remains NOT authorized until both this
sequencing decision and its consequences are worked through.

## Knowledge Captured
- The CLI is at **2.1.220** as of this session (`claude --version`, live check) — the ADR-22
  standing tickle is NOT owed again until the next bump past 2.1.220.
- The gap between "doc 14 §2.7's re-probe" and "the literal §2.4 Probe 2/3 procedure" was real,
  not a naming quibble: §2.7 ran a different control design (Session-11's synthetic marker hook)
  and the difference matters because a substitute methodology re-run doesn't mechanically prove
  the same thing the original probe was built to prove.
- A gap exists between CLAUDE.md's written hard rules and an operative norm this project actually
  follows: "no commit without explicit authorization." The Session-17 handoff describes departing
  from "the default no-commit-without-authorization reflex" as a deliberate exception, implying
  the reflex is the norm — but CLAUDE.md's current hard-rules list (read this session) does not
  contain this as a verbatim bullet. It is currently enforced through session-to-session practice
  and user instruction only, not a written CLAUDE.md rule. Flagged here per this session's own
  orientation-read finding; not fixed this session — worth adding as an explicit hard rule next
  session if the user confirms that's the intent.

## Testing / Verification Performed
- PASS: `claude --version` → `2.1.220 (Claude Code)`, captured live at probe time.
- PASS: Probe 2 (empty `--setting-sources`) — `rc=0`, `apiKeySource="none"`, `num_turns=1`,
  `claude_code_version="2.1.220"` parsed from transcript; `knowledge/` absent at all 16 poll
  ticks (t=0..450s, 30s interval) via direct directory listing at each tick.
- PASS: Probe 3 (fence sanity) — `rc=0`, `apiKeySource="none"`; `git init` `tool_use` attempted
  (not self-censored); denied with both signals (`permission_denials` entry + `tool_result
  is_error:true`), same `tool_use_id` on both; `.git` absent verified by direct `ls`.
- PASS: post-commit `git status --short` / `git show --stat HEAD` confirmed each commit (`e049aa3`
  pre-existing at session start per orientation read, `70cd4c9` pre-existing, `ab99f55`,
  `aa75231`) touched only the intended file(s) — no `src/`, schema, transitions, or `config.yaml`
  file in any diff this session.
- NOT TESTED: unit test suite / crash harness were not re-run this session (no `src/` change
  occurred, so re-running was not required per the verify-commands guidance, but this means their
  current pass/fail state is not re-confirmed here, only carried forward from whenever they last
  ran).

## User Constraints
- No `src/`, schema, `transitions.py`, or `config.yaml` change this session under any
  circumstance — explicitly scoped to docs/process work throughout, enforced by diff review
  before every commit this session.
- B-layer (`HISTORIAN_SWEEP_ACTIVE`) sunset explicitly forbidden this session even on a clean
  probe result — standing instruction, re-confirmed, not re-litigated.
- Every commit this session was preceded by an explicit raw-diff review and explicit user
  authorization before `git commit` ran.

## Runtime & System State
- Commit at handoff: `aa75231` (short SHA, from this session's own `git show --stat HEAD` output).
- Background processes: none left running — the probe script (`probe_23.py`) ran to completion
  synchronously (foreground) for both legs; no orphaned process.
- Open branches / worktrees: none opened this session.
- Scratch artifacts (uncommitted, outside the repo's tracked tree, disposable): `probe_23.py`,
  `probe2_cwd/`, `probe3_cwd/` under this session's scratchpad directory — not cleaned up, not
  required to be (never inside the repo).

## Deferred Work
- The "no-commit-without-explicit-authorization" hard-rule gap (see Knowledge Captured) — flagged,
  not added to CLAUDE.md this session; deferred pending user confirmation of intent.
- Live-smoke sequencing decision and the ingest branch-check gap decision (NEXT.md §2 items 1-2)
  — both open, decision-only, deferred to the user/next session per this handoff's Next Action.
- The env-witness script (doc 08 §5d spec, NEXT.md §2 item 4) and the StockAgent test-command
  authoring gap (§2 item 5) — untouched this session, still open from prior sessions.

## Open Questions
**Needs User Input**
- Whether to add "no commit without explicit authorization" as a verbatim CLAUDE.md hard rule
  next session, given it is already the operative practice but currently unwritten there.
- Which of NEXT.md §2 items 1 or 2 (live-smoke sequencing vs. ingest branch-check gap) to decide
  first — both are decision-only with no precondition, so the ordering is a preference, not a
  dependency.
