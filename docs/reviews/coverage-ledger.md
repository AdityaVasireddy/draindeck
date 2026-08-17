# Coverage ledger — Draindeck full codebase review

**Coverage is NOT 1/1.** 71 of 108 tracked files were reviewed this pass. The remaining 37
are historical narrative documents (`docs/14`, 34 of 39 `docs/handoffs/*.md` files, and both
`docs/scratch/*.md` files) declared SKIPPED with a stated reason, per the task's explicit
allowance for declared partial coverage on a review of this size. **All 44 tracked `.py`
files (100% of `src/` and `tests/`) and all 5 config/hygiene files were reviewed in full** —
the partial fraction is confined entirely to the historical-documentation corpus, not to any
code.

Columns: file path | lines | REVIEWED / SKIPPED / NOT RUN | reason if not REVIEWED.

## src/ (27 files — 27/27 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| src/runtime/__init__.py | 0 | REVIEWED | — |
| src/runtime/budget/__init__.py | 7 | REVIEWED | — |
| src/runtime/budget/manager.py | 71 | REVIEWED | — |
| src/runtime/config.py | 180 | REVIEWED | — |
| src/runtime/context/__init__.py | 7 | REVIEWED | — |
| src/runtime/context/pack.py | 87 | REVIEWED | — |
| src/runtime/engine/__init__.py | 19 | REVIEWED | — |
| src/runtime/engine/claude_headless.py | 767 | REVIEWED | — |
| src/runtime/events/__init__.py | 0 | REVIEWED | — |
| src/runtime/events/log.py | 150 | REVIEWED | — |
| src/runtime/events/projections.py | 268 | REVIEWED | — |
| src/runtime/events/schema.py | 130 | REVIEWED | — |
| src/runtime/loop.py | 357 | REVIEWED | — |
| src/runtime/main.py | 311 | REVIEWED | — |
| src/runtime/queue/__init__.py | 6 | REVIEWED | — |
| src/runtime/queue/issues_md.py | 98 | REVIEWED | — |
| src/runtime/recovery/__init__.py | 0 | REVIEWED | — |
| src/runtime/recovery/bindings.py | 156 | REVIEWED | — |
| src/runtime/recovery/reconciler.py | 130 | REVIEWED | — |
| src/runtime/repo/__init__.py | 18 | REVIEWED | — |
| src/runtime/repo/adapter.py | 159 | REVIEWED | — |
| src/runtime/repo/git_adapter.py | 262 | REVIEWED | — |
| src/runtime/reviewer/__init__.py | 21 | REVIEWED | — |
| src/runtime/reviewer/base.py | 88 | REVIEWED | — |
| src/runtime/reviewer/qwen_ollama.py | 170 | REVIEWED | — |
| src/runtime/validation/__init__.py | 6 | REVIEWED | — |
| src/runtime/validation/runner.py | 138 | REVIEWED | — |

## tests/ (17 files — 17/17 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| tests/__init__.py | 0 | REVIEWED | — |
| tests/crash/__init__.py | 0 | REVIEWED | — |
| tests/crash/harness.py | 620 | REVIEWED | — |
| tests/crash/item9_orphan_harness.py | 834 | REVIEWED | — |
| tests/crash/worker.py | 278 | REVIEWED | — |
| tests/unit/__init__.py | 0 | REVIEWED | — |
| tests/unit/test_bindings.py | 246 | REVIEWED | — |
| tests/unit/test_engine.py | 342 | REVIEWED | — |
| tests/unit/test_engine_adr22.py | 84 | REVIEWED | — |
| tests/unit/test_foundation.py | 312 | REVIEWED | — |
| tests/unit/test_git_adapter.py | 261 | REVIEWED | — |
| tests/unit/test_loop.py | 309 | REVIEWED | — |
| tests/unit/test_loop_real_git.py | 130 | REVIEWED | — |
| tests/unit/test_main.py | 63 | REVIEWED | — |
| tests/unit/test_main_exit_paths.py | 117 | REVIEWED | — |
| tests/unit/test_seams.py | 150 | REVIEWED | — |
| tests/unit/test_validation_env_adr23.py | 96 | REVIEWED | — |

## Config / hygiene (5 files — 5/5 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| config.example.yaml | 41 | REVIEWED | — |
| config.yaml | 71 | REVIEWED | — |
| pyproject.toml | 15 | REVIEWED | — |
| .gitattributes | 3 | REVIEWED | — |
| .gitignore | 10 | REVIEWED | — |

## Root docs (3 files — 3/3 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| CLAUDE.md | 71 | REVIEWED | — |
| NEXT.md | 711 | REVIEWED | — |
| README.md | 14 | REVIEWED | — |

## docs/ numbered design docs (15 files — 14/15 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| docs/01-theory-of-operation.md | 60 | REVIEWED | — |
| docs/02-architecture-specification.md | 120 | REVIEWED | — |
| docs/03-state-machine-and-event-schema.md | 123 | REVIEWED | — |
| docs/04-implementation-roadmap.md | 52 | REVIEWED | — |
| docs/05-architecture-decision-records.md | 83 | REVIEWED | — |
| docs/06-prerequisites-checklist.md | 53 | REVIEWED | — |
| docs/07-implementation-guide-solo.md | 100 | REVIEWED | — |
| docs/08-session-0-closure-and-adr-amendments.md | 497 | REVIEWED | — |
| docs/09-implementation-blueprint.md | 271 | REVIEWED | — |
| docs/10-reconciliation-report.md | 40 | REVIEWED | — |
| docs/11-session3-repository-adapter-design.md | 198 | REVIEWED | — |
| docs/12-session4-engine-wrapper.md | 266 | REVIEWED | — |
| docs/13-session5-orchestrator-loop.md | 168 | REVIEWED | — |
| docs/14-session6-phase2-gate.md | 1351 | SKIPPED | Largest remaining doc (1351 lines); time-boxed out of this pass. Its findings (ADR-22 probe history, CLI re-pin log, vacuity-guard non-reproduction) are re-surfaced and cross-checked via docs/08, docs/12, and NEXT.md, all read in full and more current. Low blast radius (historical probe log, not live code). |
| docs/15-item9-outcome-matrix.md | 482 | REVIEWED | — |

## docs/handoffs/ (39 files — 5/39 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| docs/handoffs/HANDOFF_2026-07-11_session2-reconciled-foundation.md | 78 | SKIPPED | Historical, superseded per NEXT.md's own pointer index ("Session-by-session narrative & evidence... superseded/closed items"). Low blast radius (docs/handoffs). Declared partial coverage, time-boxed. |
| docs/handoffs/HANDOFF_2026-07-11_session3-repository-adapter.md | 188 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-12_session4-engine-wrapper.md | 291 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-12_session5-orchestrator-loop.md | 262 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-13_session6-step1-harness-crash-points.md | 131 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-15_session6-r1-reset-proof.md | 127 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-16_session6-step2-preflight.md | 141 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-16_session7-adr21-adr22.md | 150 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-17_session8-adr22-mechanism-landed.md | 163 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-17_session9-cli-repin-and-vacuity-guard.md | 152 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-18_adr22-vacuity-control-restored.md | 229 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-24_adr22-repin-settings-fix-model-reinstate.md | 251 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-25_session14-adr23-phase1-and-precondition-checks.md | 106 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-25_session15-adr23-phase2-mechanism-landed.md | 67 | SKIPPED | Same reason as above; content substantially re-covered by docs/08 §5d (read in full). |
| docs/handoffs/HANDOFF_2026-07-25_step3-precondition1-validation-command.md | 55 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-26_session17-dryrun-a-pass-correction-note.md | 63 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-26_session18-tiering-eviction-adr22-reprobe.md | 147 | SKIPPED | Same reason as above; content substantially re-covered by NEXT.md §4 (read in full). |
| docs/handoffs/HANDOFF_2026-07-26_session19-pointer-fix-and-no-commit-rule.md | 80 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-26_session20-branch-checkout-adr20-amendment1.md | 145 | SKIPPED | Same reason as above; content substantially re-covered by docs/08 ADR-20 Amendment 1 (read in full). |
| docs/handoffs/HANDOFF_2026-07-26_session21-branch-check-item1-option-b.md | 116 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-26_step3-precondition4-mutation-leg-closure.md | 66 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-27_session22-live-smoke.md | 155 | SKIPPED | Same reason as above; content substantially re-covered by NEXT.md §1-2 (read in full). |
| docs/handoffs/HANDOFF_2026-07-27_session23-branch-restore-fix.md | 139 | SKIPPED | Same reason as above; content substantially re-covered by NEXT.md item 8 (read in full). |
| docs/handoffs/HANDOFF_2026-07-27_session24-orphan-recovery-fixes.md | 198 | SKIPPED | Same reason as above; content substantially re-covered by docs/08 ADR-20 Amendment 2 and NEXT.md item 13 (both read in full). |
| docs/handoffs/HANDOFF_2026-07-29_item9-crash-harness.md | 220 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-29_item9-startstate-and-reconciler-finding.md | 170 | SKIPPED | Same reason as above. |
| docs/handoffs/HANDOFF_2026-07-31_item9-sentinel-discriminator.md | 226 | SKIPPED | Same reason as above; content substantially re-covered by docs/15 §6 (read in full). |
| docs/handoffs/HANDOFF_2026-07-31_session25-group-r-overrun.md | 131 | REVIEWED | — |
| docs/handoffs/HANDOFF_2026-08-01_session26-group-s-holdpid-queue-block.md | 255 | REVIEWED | — |
| docs/handoffs/HANDOFF_2026-08-02_session26to27-close-issue11-shipped-issue12-duplicate-escalated.md | 206 | SKIPPED | Declared partial coverage, time-boxed; adjacent sessions 26 and 28 were read in full and bracket this one's material. |
| docs/handoffs/HANDOFF_2026-08-02_session27-gate-c-corrected-gate-d-witnessed-sd-verified.md | 198 | SKIPPED | Same reason as above; its correction note is quoted verbatim inside session26's handoff, which was read in full. |
| docs/handoffs/HANDOFF_2026-08-02_session28-config-name-mismatch-closed.md | 73 | REVIEWED | — |
| docs/handoffs/HANDOFF_2026-08-03_session29-adr19-pass-holdpid-blocked.md | 86 | REVIEWED | — |
| docs/handoffs/HANDOFF_2026-08-03_session30-adr19-close-holdpid-committed.md | 71 | REVIEWED | — |
| docs/handoffs/HANDOFF_2026-08-03_session31-item9-scratch-fault-injection.md | 93 | SKIPPED | Declared partial coverage; its full content is summarized in NEXT.md item 9's "Session 31 follow-up" (read in full) and in the commit message quoted in git log Step 0. |
| docs/handoffs/HANDOFF_2026-08-04_session32-issue19-decomposed-stockphotoagent-hygiene.md | 87 | SKIPPED | Declared partial coverage; superseded content — session 34's correction (read in full via NEXT.md's dated 2026-08-05 correction section) revises this session's own premise. |
| docs/handoffs/HANDOFF_2026-08-05_session33-issue23-24-shipped-issue25-hand-landed.md | 83 | SKIPPED | Declared partial coverage; its material is quoted at length in NEXT.md's two dated Session-33 NOTE blocks (read in full). |
| docs/handoffs/HANDOFF_2026-08-05_session34-gap4-shipped-gap1-confirmed-live.md | 72 | SKIPPED | Declared partial coverage; its material (Gap 4 num_turns persistence) is independently verified directly against current loop.py source in this review's own Tier-A reading, and summarized in NEXT.md's dated 2026-08-05 correction section (read in full). |
| docs/handoffs/next-md-archive-2026-07-26.md | 773 | SKIPPED | Explicitly an archival dump of superseded Session 5-17 material, per NEXT.md's own description ("Session-by-session narrative & evidence... superseded/closed items"). Largest handoff file; time-boxed out. |

## docs/scratch/ (2 files — 0/2 REVIEWED)

| File | Lines | Status | Reason |
|---|---|---|---|
| docs/scratch/next-md-audit-verify.md | 878 | SKIPPED | Declared partial coverage; this is the audit trail for a prior NEXT.md rewrite (per NEXT.md §6, "This rotation's audit trail"), not a description of current runtime behavior. Low blast radius, largest scratch file, time-boxed out. |
| docs/scratch/next-md-audit.md | 115 | SKIPPED | Same reason as above. |

---

## Totals

- **src/: 27/27 (100%)**
- **tests/: 17/17 (100%)**
- **config/hygiene: 5/5 (100%)**
- **root docs: 3/3 (100%)**
- **docs/ numbered: 14/15 (93.3%)**
- **docs/handoffs/: 5/39 (12.8%)**
- **docs/scratch/: 0/2 (0%)**

**Overall: 71 / 108 files reviewed = 65.7%.**

All non-code files marked SKIPPED are low-blast-radius per `CLAUDE.md`'s own effort-sizing
rule (documentation, handoffs, scratch work) — no `src/`, `tests/`, or config file was
skipped. Every SKIPPED handoff's material content that bears on this review's Tier A-D
findings was independently cross-checked against a REVIEWED, more-current source
(`NEXT.md`, `docs/08`, `docs/10`, `docs/15`, or direct source reading) — none of the SKIPPED
files introduced a claim this review relied on without a REVIEWED corroborating source.
