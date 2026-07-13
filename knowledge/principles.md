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

## Declined promotions

- **Empirical-probe-before-building-dependent-code** (candidates: issue-runtime/2026-07-12#max-turns-cli-flag-removed-reactive-enforcement, issue-runtime/2026-07-12#allowedtools-falsified-denylist-is-the-real-fence, issue-runtime/2026-07-12#pid-in-log-is-writer-not-engine-child) — all three share a "verify against the real system before committing the design" tipping factor, but all three land on the same calendar date (2026-07-12), so the 2-cases/2-dates bar isn't met. Revisit if a case with this tipping factor shows up on a different date.
