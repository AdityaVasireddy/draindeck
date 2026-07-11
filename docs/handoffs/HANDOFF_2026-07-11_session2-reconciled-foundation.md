# Session Handoff — Runtime foundation built and reconciled against doc 03; ready for Session 3 (RepositoryAdapter)

## Objective
Continue the autonomous issue-resolution runtime per the frozen design (docs 01–07 from the design phase). This chat session closed Session 0 (three architectural decisions + billing verification), produced the Session 1 implementation blueprint, implemented the Session 2 durability foundation (event log, replay, recovery, kill-9 harness, config loader), and — once doc 03 was finally uploaded — reconciled the entire codebase against the frozen contract. Durability is the first production feature; everything else builds on this layer.

## Current Status
- Completed: Session 0 closure (doc 08: ADR-18/19/20 + verified billing finding); Session 1 blueprint (doc 09; its §4–§5 now superseded by doc 03 + doc 10); Session 2 foundation implemented AND reconciled verbatim against doc 03; reconciliation report written (doc 10). Verified: 19/19 unit tests, 46/46 kill-9 harness scenarios × 2 seeds, mutation-tested harness — all on Linux, this session.
- Blocked: nothing hard-blocked. Session 3 can start immediately; the Windows verification and config gaps below are pre-Phase-1-gate items, not blockers for writing the RepositoryAdapter.

## Decisions & Rationale
- Doc 03 wins every conflict; code rewritten to it verbatim rather than adapted — the architecture is frozen and the draft blueprint had diverged in 14 places (full table in doc 10). Two were semantic, not naming: recovery must NEVER witness an orphaned execution as finished (always ExecutionCrashed + residue ref — an unwitnessed exit is indistinguishable from a partial run), and CommitIntent exists as a required intent event before the merge (the draft had a single commit fact).
- Envelope per doc 03: `event_id` IS the monotonic integer (no separate seq/uuid); `schema_version` serialized; `kind` (intent/fact) is code-side schema knowledge, not a wire field; type strings CamelCase.
- Projection enforces I5/I6 structurally — `CommitCreated` without prior `CommitIntent` is a replay error, not a warning. Lives in `src/runtime/events/projections.py`.
- Reconciler checks 2 (unwitnessed commit) and 3 (dirty workspace) are injectable seams that default to None and are reported as SKIPPED — recovery never silently claims a check it didn't run. Binding them to the RepositoryAdapter is the core of Session 3. `src/runtime/recovery/reconciler.py`.
- New harness invariant I-h: each execution's ExecutionFinished pid must equal its ExecutionSpawned pid — makes "abandonable, never replayed" observable from the log. Chosen because a mutation test showed the stub workload could otherwise silently resume an orphan.
- SPAWNED is unobservable from a log replay (no event marks the subprocess spawn), so the projection maps ExecutionSpawned → EXECUTING; SPAWNED stays in the enum for in-process bookkeeping only. Flagged in doc 10 §1 as an interpretation, documented in `state/model.py`.
- Doc 03's "12 event types" = 12 table rows but 15 distinct type strings (pass/fail pairs are separate types). All 15 implemented.
- Session 0 decisions (doc 08): ADR-18 execution provider = Claude Pro subscription via `claude -p`, `auth_mode` as config on the single concrete engine (no engine seam, ADR-08 intact); ADR-19 kill criteria = 20 issues, attempt-1 success ≥30%, proxy cost/shipped ≤ $3.00, tamper-guarded; ADR-20 target repo = StockAgent, repository-agnostic, path in config only.
- Billing (checklist A1, verified 2026-07-10 against Anthropic Help Center): the June 2026 headless billing split is PAUSED; `claude -p` draws from normal Pro limits. ADR-09 budget protections retained with proxy-cost accounting (API list rates) so the ADR-19 verdict holds under either billing regime. Re-verify at the Phase 2 gate.

## Key Files
Upload the zip (or the extracted tree) plus docs to the new session; the container filesystem does not persist across chats.
- `issue-runtime-session2-reconciled.zip` (chat outputs) — the complete reconciled project tree. Extract and commit as-is.
- `03-state-machine-and-event-schema.md` — the frozen implementation contract. Re-upload to Session 3; the RepositoryAdapter's residue/backfill behavior must match its §2 and §5.
- Inside the zip: `src/runtime/recovery/reconciler.py` — read first for Session 3; the seam signatures (`preserve_residue`, `check_unwitnessed_commit`, `check_dirty_workspace`) are documented at the top and are what Session 3 implements against.
- Inside the zip: `tests/crash/harness.py` and `tests/crash/worker.py` — the Phase 1 gate instrument and its invariants I-a..I-h; Session 3 extends the world from stub files to a temp git repo.
- Inside the zip: `NEXT.md` — resume pointer matching this handoff.
- `10-reconciliation-report.md` (chat outputs) — full divergence table; commit alongside docs 01–09.
- `08-session-0-closure-and-adr-amendments.md`, `09-implementation-blueprint.md` (chat outputs) — doc 08 includes the final `config.yaml` reference in §6.

## Next Action
Session 3: implement the RepositoryAdapter (`repo/adapter.py` interface + `repo/git_adapter.py` git-CLI implementation per doc 09 §7) and bind the three reconciler seams to it — residue-to-attempt-ref for real, check 2 emitting `CommitCreated(backfilled=true)`, check 3 archiving dirty workspaces — then extend the crash harness to use a temp git repo as the world. Before or alongside: run both suites on Windows (item 1 in NEXT.md).

## Knowledge Captured
- Anthropic Help Center (article 15036540, June 15 banner, verified 2026-07-10): Agent SDK / headless billing changes paused; subscription limits apply to `claude -p`; many blog posts claiming the split shipped are wrong. Also: SDK renamed `@anthropic-ai/claude-code` → `@anthropic-ai/claude-agent-sdk` (Python `claude-code-sdk` → `claude-agent-sdk`); the `claude -p` CLI name is unchanged, so subprocess spawning is unaffected.
- ADR-18 env hygiene mechanism: if `ANTHROPIC_API_KEY` is present in the spawned environment, `claude` bills the API pay-as-you-go; in subscription mode the engine wrapper must strip it. `validate_environment()` in `src/runtime/config.py` flags the leak; enforcement belongs to the future engine wrapper.
- Torn-tail policy that survived testing: a malformed final line without trailing newline = crash during append; since append() hadn't returned, the event was never acted on — quarantine bytes to a `.torn.<ts>` sidecar and truncate. Any malformed line before the tail = refuse to load (CorruptionError). Repairing the middle would forge history.
- kill -9 proves process-crash durability only; the OS page cache survives a killed process, so fsync correctness (power-loss durability) is untestable in this harness — correct by construction, not by observation.
- The six original frozen docs were NOT recoverable from past-chat search in this project; only what the user uploads exists. Docs 01, 02, 04–07 have still never been seen in this chat — knowledge of them comes solely from the 2026-07-10 handoff summary.

## Assumptions
- Windows compatibility (HIGH): `os.fsync`, `os.replace`, pathlib are cross-platform by contract; directory-fsync is guarded POSIX-only. Verified on Linux (Python 3.12.3) only.
- Doc 07's session ordering puts the RepositoryAdapter next (MED): doc 07 never seen this chat; ordering inferred from the original handoff and doc 09 §9. If doc 07 says otherwise, doc 07 wins.
- Language choice Python 3.12 + pyyaml + pydantic (MED): blueprint assumption flagged ⟦reconcile⟧ against doc 07 in doc 09; user accepted Session 1 and Session 2 without objection, so treated as ratified.
- ExecutionFinished routing (MED): payload `outcome=REJECTED` → REJECTED, otherwise → VALIDATING regardless of exit_status; doc 03 §5 only specifies the timeout/budget row explicitly. Selector lives in `state/transitions.py`.

## Testing / Verification Performed
- PASS: 19/19 unit tests (`tests/unit/test_foundation.py`) — durability semantics (round trip, reopen, torn tail, mid-file corruption, event_id gap, schema_version rejection), doc 03 transition tables including CommitIntent ordering and recovery-never-witnesses, config structural + environment validation.
- PASS: kill-9 harness 46/46 scenarios on seeds 42 and 1337 — genuine SIGKILL at all 15 named transition points × 2 occurrences + 15 random-timing rounds (self-verifying ≥10 landed kills) + control; invariants I-a..I-h.
- PASS: mutation tests — (pre-reconciliation) archive-before-retry removal caught; (post-reconciliation) recovery-skip caught by I-h ("finished by a different process than spawned it").
- NOT TESTED: anything on Windows; power-loss durability (see Knowledge Captured); reconciler checks 2 and 3 (seams intentionally unbound — reported SKIPPED); the real `claude -p` engine, reviewer, budget manager, queue, context pack (not in scope through Session 2).

## Technical Debt
- Worker rebuilds the full projection from replay after every step (`tests/crash/worker.py`, comment "deliberately expensive-honest") — intentional for the harness; the real orchestrator will apply incrementally.
- `HumanIntervention` / `GuidelinePromoted` events are counted but drive no state machine — intentional; orchestration-layer semantics arrive with escalation handling.
- `budget/`, `engine/`, `reviewer/`, `queue/`, `context/`, `validation/` folders from the doc 09 skeleton are empty or absent in the reconciled tree — intentional, per "foundation only" scope.

## User Constraints
- Frozen architecture is authoritative; doc 03 is the implementation contract; changes only via ADRs.
- Honesty discipline: every session report must separate verified from assumed; kill criteria (ADR-19) may not be tuned after the run begins.
- Repository path is configuration only; orchestrator stays repository-agnostic (ADR-20).
- Solo builder, ~3 hrs/week, single sittings: every session ends at a runnable, committed checkpoint with NEXT.md updated.
- No plugin framework, no Temporal/LangGraph, no parallelism, no external state store in v1.
- Target: StockAgent at `C:\Projects\StockPhotoAgent`, branch `agent-work` (Windows dev environment).

## Runtime & System State
- No git repo initialized in the working tree this session; no commit SHA exists. The zip is the artifact of record — extract and make it the initial commit.
- No background processes, servers, or worktrees.

## Open Questions
**Needs User Input**
- StockAgent vs StockPhotoAgent: decision text says "StockAgent", path says `C:\Projects\StockPhotoAgent`. Confirm the on-disk directory name and fix `config.yaml`.
- StockAgent's actual test command for `project.validation.commands` in config.yaml — required before baseline-green can be checked, currently a placeholder.
- Windows suite run (NEXT.md item 1): will you run it, or should Session 3 treat Windows as unverified and add CI later?

**Model Uncertainty**
- Docs 01, 02, 04–07 have never been visible in this chat; anything attributed to them here traces to the 2026-07-10 handoff summary, unconfirmed against the originals. Upload doc 07 to Session 3 if its session plan should drive scope.
- Doc 09 (in chat outputs) still contains the superseded §4–§5 draft with ⟦reconcile⟧ markers; doc 10 declares them superseded rather than editing doc 09 in place. If you prefer doc 09 rewritten to match doc 03, say so in Session 3.
