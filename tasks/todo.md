# Todo: Draindeck Intake v1

**Gate:** ACCEPTED 2026-08-29 — explicit approval of
`spec/draindeck-intake.md`, `tasks/plan.md`, ADR-28, and the bounded
nine-local-commit build-auto series. No push or merge.

Legend: `[ ]` pending · `[~]` in progress · `[x]` verified complete

- [x] Preparatory commit — archive prior task artifacts; commit approved spec,
      plan, and todo
- [x] Unit 0 — ADR-28 acceptance record and characterized baseline
- [x] Unit 1 — canonical model and deterministic safe compiler
- [x] Unit 2 — source protocol, bounded collector, local Issues.md adapter
- [x] Unit 3 — bounded HTTP JSON transport and GitHub adapter
- [x] Unit 4 — Jira Cloud adapter and ADF extraction
- [x] Unit 5 — Linear GraphQL adapter
- [x] Unit 6 — atomic managed output and CLI composition
- [x] Unit 7 — docs, fresh-context review, full verification, final handoff

## Final gates

- [x] All task acceptance criteria met
- [x] Intake suite green; combined core collection recorded as inherited baseline-blocked
- [x] Dashboard suite green
- [x] Durability seeds 42 and 1337 green
- [x] `compileall` and `git diff --check` green
- [x] No dependency added
- [x] `src/runtime` and Doc 03 unchanged
- [x] No secrets or raw provider payloads in code, tests, docs, or staged diffs
- [x] Every real review finding fixed test-first
- [x] Branch checkpointed and ready for user review
