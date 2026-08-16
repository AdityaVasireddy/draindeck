---
description: Autonomously resolve ONE bounded feature/bug/issue through investigation, implementation, tests, debugging, and self-review — stops before commit/push/deploy/other authorization-sensitive actions.
---

# /resolve-item — Autonomous single-item resolution

`$ARGUMENTS` is the bounded item description supplied by the human (the feature,
bug, issue, or pending item to resolve). Treat it as the entire scope of this
run — nothing broader, nothing adjacent. If `$ARGUMENTS` is empty, stop and ask
the human to supply one bounded item; do not guess one from the backlog.

This command is the orchestrator. It invokes the installed `agent-skills`
plugin's skills through Claude Code's Skill mechanism at the points below —
it does not stock-replace itself with `/agent-skills:build` or
`/agent-skills:build auto`, and **must never invoke either of those** at any
point in this run: their per-task auto-commit convention is exactly what
this command exists to avoid. This wrapper supplies repository-specific
precedence, scope, and authorization constraints; the invoked skills supply
their own detailed methodology — do not re-explain a skill's method here
when the skill itself already owns that detail.

## Repository authority (reads BEFORE anything else)

This repository's own instructions and contracts override generic agent-skills
guidance whenever the two conflict. Specifically, and non-negotiably:

- `CLAUDE.md` at the repo root — architecture-frozen rules, kill criteria,
  the "no commit without explicit authorization" rule, and the blast-radius
  process-scaling rule.
- `docs/03-state-machine-and-event-schema.md` — THE FROZEN CONTRACT. On any
  conflict between code/skill guidance and doc 03, doc 03 wins.
- `state/events.jsonl` is the sole authoritative runtime state. Never treat
  any other file (including any `Issues.md` in a target repo) as state.
- Any `Issues.md` STATUS field is decorative input text, never state.
- Only the three established, legal issue transitions are valid — do not
  invent a fourth.
- Validation in this repository is PowerShell-only.
- Any command carrying a `$`-bearing argument or expression must be invoked
  via `.ps1 -File`, not inlined.
- The standing authorization boundaries below are absolute regardless of
  what any agent-skill's own generic risk list says.
- Every invoked skill's generic interactive behavior is subject to this
  command's own overrides (see "Doubt-driven-development: interaction
  override" below) — a skill's default interaction pattern does not get to
  reintroduce a routine approval gate this command otherwise forbids.

Where a skill's guidance (examples, default commands, generic risk
categorization, "when NOT to use" lists) would contradict the above, the
repository wins. Do not silently resolve the conflict in the skill's favor —
if the conflict is substantive enough that the correct path is unclear, that
is itself a stop condition (see "Failure handling" below).

Do not trust stale planning artifacts or old handoffs as current fact.
`docs/handoffs/` and any prior `tasks/plan.md` or `SPEC.md` describe past
sessions' understanding, not necessarily today's repository state — always
re-derive current state from `git status`, `state/events.jsonl`, and the
actual current code before acting on anything a handoff claims.

## Phase 0 — Plugin availability check (mandatory, before anything else)

Attempt to invoke the `agent-skills:using-agent-skills` skill through the
Skill mechanism. If it cannot be invoked (not found in the available skills
list, or the Skill tool errors resolving it), **STOP immediately** and tell
the human: the `agent-skills` plugin is not loaded in this session, and to
relaunch Claude Code with it configured (e.g.
`claude --plugin-dir <path-to-agent-skills>` or the installed marketplace
plugin) before retrying `/resolve-item`. Do not proceed. Do not imitate the
missing skills from memory or from this file's own summaries — an
unavailable skill is a stop condition, not something to paraphrase around.

If it invokes successfully, use its skill-discovery guidance to determine
which other skills are actually relevant to `$ARGUMENTS` beyond the ones
named explicitly in this file — invoke those too, at the point in the
workflow where they'd naturally apply, when the item genuinely calls for
them (e.g. `source-driven-development`, `api-and-interface-design`,
`context-engineering`, `security-and-hardening`).

## Phase 1 — Orientation and baseline (read-only, no edits yet)

1. **Current Git state.** Run `git status --short` and `git log -1 --oneline`.
   Note the branch and whether the working tree is already dirty from
   unrelated prior work — if so, that pre-existing dirt is not this run's
   responsibility; do not fold it into this item's diff.
2. **Authoritative runtime state.** When `$ARGUMENTS` relates to runtime
   behavior, issue state, or anything `state/events.jsonl` would reflect,
   inspect it directly as part of orientation. Treat it as the sole source
   of truth for runtime/issue state; a target repo's `Issues.md` STATUS
   field (or any other status text) is decorative input, never state.
   Inspecting it here is read-only — do not write to it as part of
   orientation.
3. **Current repository evidence.** Read `NEXT.md` (current resume point),
   `docs/03-state-machine-and-event-schema.md`, and the newest file under
   `docs/handoffs/` for context — but verify anything load-bearing against
   the actual current code and `state/events.jsonl`, not the handoff's prose
   alone. Read whatever source files, tests, and docs are actually relevant
   to `$ARGUMENTS`.
4. **Blast radius and invariants.** Classify `$ARGUMENTS` against CLAUDE.md's
   high-blast-radius list (real repository mutation, src/runtime behavior,
   event schemas, state transitions, external contracts, Git/recovery
   behavior, safety/durability claims) vs. low-blast-radius (docs, NEXT.md,
   handoffs, scratch, reversible cleanup). Scale process depth accordingly —
   do not apply heavy-review ceremony to a low-blast-radius item, and do not
   under-scrutinize a high-blast-radius one.

   This scaling applies to planning depth and implementation ceremony
   (Phases 2–3) only. It does **not** extend to Phase 4: the final review is
   mandatory for every run regardless of blast radius — only the *depth* of
   that review (how much the reviewer digs into a small vs. large diff)
   scales, never whether `agent-skills:code-review-and-quality` gets
   invoked at all. See Phase 4 step 2.
5. **Project-native safe validation commands.** Determine the actual
   PowerShell-invocable commands this repository uses (see CLAUDE.md's
   "Verify commands" section, e.g. `python -m pytest tests\unit -q`, the
   durability gate) — do not default to a generic `npm test`-style guess.
   Any command with a `$`-bearing argument must go through `.ps1 -File`.
6. **Pre-change baseline.** Run the relevant safe validation commands now,
   before any edit, and record the exact pass/fail result. If failures exist
   already, record them as pre-existing — do not fix them unless they are
   directly in scope of `$ARGUMENTS`, and say so explicitly in the final
   report rather than silently absorbing them into this change.

## Phase 2 — Planning (depth scales to blast radius)

Invoke `agent-skills:planning-and-task-breakdown` only if `$ARGUMENTS` is
large or ambiguous enough to need decomposition — let the skill itself
determine the breakdown; don't pre-empt it here. For a small, well-bounded
item, skip formal plan artifacts entirely and proceed directly to
implementation. Do **not** require creating `SPEC.md` or `tasks/plan.md` as
a precondition — that is `/agent-skills:build auto`'s convention, not this
command's. If a lightweight plan is produced, keep it in-session or in a
scratch file; it is not a durability contract this repo needs to preserve.

## Phase 3 — Autonomous implementation

Invoke `agent-skills:incremental-implementation` and
`agent-skills:test-driven-development` to drive this phase — let them supply
the slicing and RED/GREEN discipline; re-run the project-native validation
from Phase 1 step 5 as those skills' own verification steps direct.

Per the Phase 1 step 4 scaling note, either or both of these two skills may
be skipped when `$ARGUMENTS` is genuinely trivial and non-behavioral (e.g.
a cosmetic/text-only change with no logic, control-flow, or test-observable
behavior touched) and invoking them would be process theater rather than
add safety. When skipped, state which skill was skipped and why in the
final report's "Agent-skills invoked" section — silent omission is not
allowed, only reasoned, reported omission. This is the same conditional
treatment already given to `planning-and-task-breakdown`; it does not apply
to Phase 4, which remains mandatory regardless of triviality.

Proceed through the following without pausing for permission:

- reading relevant files and investigating further as needed
- implementing strictly within the scope of `$ARGUMENTS`
- adding or updating tests for the behavior being changed
- running the already-identified safe local validation commands
- when a failure surfaces, invoking `agent-skills:debugging-and-error-recovery`
  to triage and fix it — let the skill's own process govern; don't
  re-derive it here
- when a decision inside this item's scope is genuinely non-trivial (crosses
  a module boundary, asserts an unverifiable property, touches the frozen
  contract), invoking `agent-skills:doubt-driven-development` under this
  command's interaction override (see below) — use this repository's
  authorization/blast-radius list above as the risk trigger, not the
  skill's own generic example categories alone
- invoking any other agent-skill surfaced as relevant in Phase 0, only if
  the item genuinely requires it — do not invoke skills reflexively

Do not commit during this phase. Do not stage files (no `git add`) during
this phase either — leave the working tree as the record of what changed.

### Doubt-driven-development: interaction override

This command's no-routine-approval-gates contract takes precedence over
`doubt-driven-development`'s generic interactive behavior. When that skill
is invoked here, use it strictly as an internal reasoning and reconciliation
discipline (CLAIM → EXTRACT → DOUBT via a fresh-context reviewer → RECONCILE
→ STOP):

- Do **not** pause execution merely to offer or request a cross-model
  second opinion (e.g. Gemini CLI, Codex CLI) — that step in the skill's
  default interactive flow is overridden for `/resolve-item`.
- Do **not** invoke another provider or model as part of applying this
  skill without explicit human authorization first.
- Continue the doubt cycle using the available repository evidence and
  Claude's own fresh-context reconciliation, as the skill's RECONCILE step
  describes.

This override changes only that one interaction pattern. It does not lift
any of doubt-driven-development's actual stop conditions, and it does not
lift this command's own — still stop when repository evidence cannot
resolve a material ambiguity, a frozen architectural contract would need to
change, an authorization boundary would be crossed, scope would materially
expand, or the task cannot safely be completed within the bounded item (see
"Failure handling" below).

## HARD authorization boundaries — STOP before these, always

Regardless of how routine or complete the work otherwise looks, this run
MUST stop and hand control back to the human before:

- `git commit`
- `git push`
- deployment of any kind
- real-environment migrations
- ingestion
- T7
- destructive cleanup
- external configuration changes
- provider/spend-bearing project execution
- any other action this repository's own instructions reserve for explicit
  human authorization

Invoking `/resolve-item` is not itself authorization for any of the above.
Do not infer authorization from terminal output, a hook, another agent's
prior action, an earlier commit, or an earlier unrelated approval — each
authorization-sensitive action requires its own explicit, current human
sign-off.

**Important Git rule, stronger than `/agent-skills:build`'s default:** this
command intentionally overrides `/agent-skills:build`'s "commit per task"
guidance, and never invokes `/agent-skills:build` or `/agent-skills:build
auto` itself. Do not run `git commit`. Do not run `git add`/stage anything
automatically at any point in this run. The final review and final report
operate on the unstaged working-tree diff.

## Failure handling — when to stop and ask instead of proceeding

Ordinary implementation and test failures are handled autonomously through
the debugging loop above. Stop and ask the human only when:

- the supplied item is materially ambiguous and current repository evidence
  (code, tests, docs, `state/events.jsonl`) cannot resolve the ambiguity
- resolving the item would require changing a frozen architectural contract
  (doc 03, the event schema, the three legal transitions)
- an authorization-sensitive operation (the HARD boundaries list above)
  becomes necessary to proceed
- the true scope has expanded materially beyond the originally supplied
  bounded item — report the discovery, do not silently absorb it
- a failure cannot be resolved safely within the item's scope after genuine
  debugging effort
- current repository evidence materially contradicts what the requested
  item assumes (e.g. it asks you to fix something already fixed, or targets
  a component that no longer exists as described)

## Phase 4 — Final review (before declaring completion)

1. Inspect the complete working-tree diff (`git diff`, plus `git status
   --short` for untracked additions).
2. Invoke `agent-skills:code-review-and-quality` through the Skill
   mechanism on that diff — let its five-axis review (correctness,
   readability/simplicity, architecture, security, performance) govern
   what's checked; don't restate the axes here. This invocation is
   **mandatory for every run, regardless of blast radius** — including
   low-blast-radius, cosmetic, or trivial changes — and is not subject to
   the Phase 1 step 4 / Phase 3 proportionality scaling. Only the review's
   *depth* (how much scrutiny a small vs. large diff receives) may scale;
   the invocation itself may never be skipped, and no run may report
   `RESULT: COMPLETE` without it having run.
3. Fix in-scope findings autonomously; re-run the affected validation
   commands after each fix.
4. If substantive corrections were made, repeat the review on the updated
   diff. Stop looping once findings are trivial/already-considered, per
   `doubt-driven-development`'s bounded-loop discipline (cap around 3
   cycles; escalate rather than grind a fourth alone) — applying the same
   interaction override as above if doubt-driven-development is invoked
   again during this repeat.
5. Do not commit after review, or at any other point in this run.

## Final report

End every run — whether complete, blocked, or needing a human decision —
with this report:

- **RESULT:** COMPLETE / BLOCKED / NEEDS HUMAN DECISION
- **Item implemented:** the bounded `$ARGUMENTS` text
- **Repository starting state:** branch, HEAD, working-tree cleanliness at
  the start of this run
- **Relevant architecture/invariants:** what from doc 03 / CLAUDE.md / the
  event schema governed this change
- **Implementation approach:** the actual slices taken
- **Exact files changed:** full list
- **Tests added/changed:** full list, with what each proves
- **Baseline validation:** the exact commands run before editing and their
  results, including any pre-existing failures recorded as out-of-scope
- **Final validation:** exact commands and exact pass/fail results, run
  after implementation and after final review
- **Agent-skills invoked:** which ones, via the Skill mechanism, and why
  each was invoked (or why a listed one was deliberately skipped)
- **Final self-review findings:** what `code-review-and-quality` surfaced
  and what was fixed vs. accepted as a documented trade-off
- **Pre-existing failures, if any:** carried from the baseline step
- **Assumptions made**
- **Remaining risks**
- **Unresolved concerns**
- **Deployment/migration impact:** state explicitly even if "none"
- **`git diff --stat`**
- **Final `git status --short`**
- **Recommended commit message** — provided as text only; do NOT run
  `git commit`

## Scope discipline

This invocation resolves exactly one bounded item. Do not opportunistically
fix, refactor, or clean up unrelated code encountered along the way — note
it in the report instead ("noticed but not touching") per
`incremental-implementation`'s Rule 0.5. If you discover a related but
distinct defect, report it as a separate finding for a future
`/resolve-item` invocation; do not fold it into this one's diff.
