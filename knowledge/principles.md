# Principles

Vault-wide, cross-project. A principle requires 2+ cases across 2+ dates sharing a tipping factor, or 1 case with an explicit `promote-early` justification written by the human capturer at capture time.

## P-001: Enforce frozen/critical invariants by raising, never by silent degradation

status: active
scope: issue-runtime (durability/contract-enforcement code — reconciler, engine wrapper, anywhere a frozen ADR or doc-03/doc-02 contract is checked at runtime)
evidence: 2 cases, 2 dates
- issue-runtime/2026-07-11#tamper-detection-raises-not-forges — raised `ReconcilerTamperError` instead of forging a synthetic `merge_commit` event when tamper is detected, because ADR-11 join-key integrity forbids fabricating provenance.
- issue-runtime/2026-07-12#billing-guard-raise-not-assert — replaced `assert "ANTHROPIC_API_KEY" not in env` with an explicit `raise EngineEnvError`, because `assert` silently disappears under `python -O` and this guards a billing invariant (ADR-18) that must hold on every spawn.

**Statement:** When code enforces an invariant that a frozen contract (an ADR, doc 02, or doc 03) makes non-negotiable, enforce it with an explicit `raise` of a named exception — never with a mechanism that can silently no-op (a bare `assert`, which vanishes under `python -O`) or that papers over the violation with synthesized data (forging a plausible-looking event/value instead of refusing). Both cases the pipeline observed involve a hidden failure mode that could produce a state that "looks fine" while quietly violating a rule the architecture is not allowed to bend.

**Invalidation conditions:** if a future case shows a frozen invariant is deliberately enforced by a *softer* mechanism (a warning + fallback, an assert kept for a genuinely dev-only path with the flag never stripped in prod) *because the frozen contract itself sanctions graceful degradation there*, that's a direct counter-case and should challenge this principle's scope rather than be treated as an exception.

**Not standardizable (yet):** this doesn't binarize into a project-wide grep/lint check as stated — "which invariants are frozen/critical" requires judgment (an ADR reference nearby is a weak proxy, not a reliable signal, and plenty of legitimate asserts exist for non-frozen internal invariants). A narrower, mechanically checkable version (e.g., "no bare `assert` in `src/runtime/**` guarding a condition whose docstring/comment cites an ADR number") could be proposed as a future standard if the pattern recurs a third time with cases specific enough to pin the boundary.

## P-002: A pass/fail or VERIFIED claim must rest on the witnessed artifact itself, never on a narration of it

status: active
scope: issue-runtime (any session evaluating a test, probe, or verification step and reporting a PASS/FAIL/VERIFIED-style claim in a doc, handoff, or case record)
evidence: 4 cases, 4 dates
- issue-runtime/2026-07-16#isolated-fixture-proof-must-be-reproduced-live-not-summarized — a handoff's prose claim that a mutation spot-check was "verified in isolation" could not be distinguished from an inferred aggregate pass until the isolated run was reproduced live with its actual failing-assertion output shown.
- issue-runtime/2026-07-17#argv-verified-label-required-popen-boundary-witness — a VERIFIED label for argv-survival rested on a test that only checked `_command()`'s return value, not the actual Popen spawn boundary; the label was corrected only once a live spawn test crossed that boundary.
- issue-runtime/2026-07-18#raw-artifact-paste-over-self-report-for-step-b — a reviewer downgraded a "went red" claim from VERIFIED to INFERRED because it was executor narration of a witnessed event, not the witnessed artifact itself; only pasting the raw marker file, pid, and wording restored VERIFIED.
- issue-runtime/2026-07-25#prose-description-of-diff-not-accepted-as-evidence — twice, a prose description of a diff's shape and line numbers was offered in place of the literal `@@`/`-`/`+` text and rejected both times; only the literal diff text in a fenced block was accepted.

**Statement:** When reporting the outcome of a test, probe, or verification step as PASS/FAIL/VERIFIED, the claim must be backed by the actual witnessed artifact — the literal output, the raw file contents, the specific compared values, pasted or shown directly — never by a narrated description or summary of what was observed, however accurate that narration feels to the person writing it. A description of a diff's shape, a claim that something "went red," or an inferred equivalence between a hand-built probe and the real code path all carry the identical trust problem: they cannot be checked against what actually happened. Self-report of a witnessed event is exactly the class of evidence this discipline forbids; only the raw projection counts.

**Invalidation conditions:** a future case where the project deliberately and reviewedly accepts a narrated/summarized claim as sufficient evidence for a load-bearing verification (an explicit, named exception for a specific low-stakes or fully reversible check) would directly counter this and should challenge the principle's scope, rather than be treated as an ad hoc exception.

**Not standardizable (yet):** distinguishing "the actual witnessed artifact" from "an accurate-sounding narration of it" requires semantic judgment a grep can't apply — both can look like prose. A narrower, mechanically checkable version (e.g., "every case tagged `evidence-discipline` or `verification` must include a fenced code/output block, not prose only") could be proposed if a future case sharpens the boundary between the two forms.

## P-003: Session commits exclude ambient/tool-generated file changes, scoped to the session's actual deliverable

status: active
scope: issue-runtime (git commit hygiene at session close, where ambient historian-hook or tooling output may be present in the working tree alongside real deliverables)
evidence: 3 cases, 2 dates
- issue-runtime/2026-07-16#knowledge-vault-writes-left-uncommitted-per-gitignore-convention — left the day's vault capture unstaged rather than force-adding it past an explicit prior `.gitignore` decision.
- issue-runtime/2026-07-16#unexpected-working-tree-paths-halt-commit-for-explicit-scoping — stopped before committing on finding two ambient `.sweep/*` changes and a pre-existing untracked handoff file, none matching the session's described deliverable set, and committed only the intended files once the user confirmed scope.
- issue-runtime/2026-07-17#ambient-sweep-log-excluded-from-commit-per-precedent — excluded a modified `knowledge/.sweep/sweep.log` from the session's commit, confirming it as ambient historian-hook output rather than session work product.

**Statement:** At session close, a commit must be scoped to the session's actual, intended deliverable. Ambient files that change as a side effect of tooling (the engineering-historian's own hook logs, auto-generated vault state) must be identified and excluded rather than swept into the commit just because they happen to be present and modified in the working tree, even when a prior repo decision (like a `.gitignore` entry) would make including them easy to justify. When unexpected paths appear in the working tree at commit time, stop and confirm scope explicitly rather than assuming everything present belongs to the session.

**Invalidation conditions:** a future case where the project deliberately decides ambient historian/tooling state *should* be committed alongside session deliverables (e.g., a policy change to track `.sweep/` for audit purposes) would directly counter this and should challenge the principle's scope.

**Not standardizable (yet):** "ambient/tool-generated" vs. "part of the session's deliverable" requires knowing what the session was actually scoped to do, which isn't mechanically derivable from the diff alone. A narrower standard (e.g., "never `git add` any path under `knowledge/.sweep/` in a project commit") could be written if the ambient-file set stays confined to that one directory across future cases.

## Declined promotions

- **Empirical-probe-before-building-dependent-code** (candidates: issue-runtime/2026-07-12#max-turns-cli-flag-removed-reactive-enforcement, issue-runtime/2026-07-12#allowedtools-falsified-denylist-is-the-real-fence, issue-runtime/2026-07-12#pid-in-log-is-writer-not-engine-child) — all three share a "verify against the real system before committing the design" tipping factor, but all three land on the same calendar date (2026-07-12), so the 2-cases/2-dates bar isn't met. Revisit if a case with this tipping factor shows up on a different date.
