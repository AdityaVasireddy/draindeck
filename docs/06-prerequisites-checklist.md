# Prerequisites Checklist (Phase 0)
**Status:** FROZEN — v1.0, 2026-07-05
**Rule:** every box checked before Phase 1 begins. Items marked ⚠ are known unknowns that can invalidate the plan — resolve those first.

---

## A. Economics — resolve before anything else

- [ ] ⚠ **Verify headless billing status on your account.** The June 15, 2026 split (headless `claude -p` / Agent SDK onto a separate ~$20/mo credit pool at API rates on Pro) was announced; at least one report says it was paused on ship day. Check the Anthropic help center + your account usage page. Record the answer in the ADR log.
- [ ] Decide the billing posture and write it down: (a) Pro plan + headless credit with Qwen carrying review load, (b) API key with hard budget caps, or (c) Max plan if volume justifies. Re-decide after Phase 2's measured cost-per-issue.
- [ ] Set the caps: per-execution dollar cap (suggested start: $2), per-run daily cap, execution cap per issue (default 3). These are config values in the orchestrator core (I7/I8).
- [ ] ⚠ **Pre-commit the Phase 4 decision criteria** (falsification, decided *now*, not after): e.g., "if attempt-1 success rate < 30% OR cost per shipped issue > $X after 20 issues, the loop is not economical — stop and rethink, don't tune indefinitely." Fill in X from your budget.

## B. Toolchain

- [ ] Claude Code CLI installed at a **pinned version**, authenticated; record the version in config.
- [ ] Headless smoke test passes: `claude -p "create hello.txt containing 'hi'" --output-format json` in a scratch repo — confirm JSON parses, usage fields present, file created.
- [ ] Scoped-permission profile defined and tested for headless runs (no blanket skip-permissions on your real machine; no push credentials in the engine's environment; consider containerizing engine execution only, loop on host).
- [ ] Ollama running; Qwen Coder model pulled; a single-shot structured-output smoke test passes (prompt in → parseable JSON verdict out, with one parse-retry).
- [ ] Python ≥3.11, git ≥2.40 on PATH.

## C. Repository hygiene (the target repo)

- [ ] Baseline is green: build, lint, typecheck, unit tests all pass on a clean checkout. **The validator is meaningless against a red baseline.**
- [ ] Test suite determinism audit: run the suite 3× — any test that flips is quarantined or fixed before the runtime blames engine code for it.
- [ ] Playwright/E2E: runs headlessly on this machine; rough path→suite mapping drafted (which source paths trigger E2E).
- [ ] All validation invocable as single non-interactive commands with meaningful exit codes (`npm run lint`, `npm test`, etc.). Record them in config.
- [ ] Lean CLAude.md exists: conventions, build/test commands, architecture pointers; **< ~2k tokens** (bloat measurably hurts).
- [ ] Repo is fully committed and pushed; a `main`-protection habit or rule exists (the runtime works on branches; nothing force-pushes main).
- [ ] Disk headroom for attempt refs + transcripts (transcripts dominate; budget ~1–5 MB/execution).

## D. Issue queue

- [ ] Issues.md issues meet the spec bar: each has a clear title, expected behavior, and **verifiable acceptance criteria**. Vague issues are the #1 cause of non-converging loops — fix the specs, not the prompts.
- [ ] Issues are sized for one context window (rule of thumb: describable change touching ≲ a handful of files). Oversized ones pre-split or tagged for the decomposition path.
- [ ] First 5 issues hand-picked to be well-defined, test-covered, low-risk — the supervised Phase 2 batch.
- [ ] One-shot preprocessing of Issues.md → canonical queue reviewed by you (IDs, deps, acceptance criteria intact).

## E. Runtime environment

- [ ] Dedicated working directory layout created: `log/events.jsonl`, `artifacts/`, `projections/`, `config.yaml`.
- [ ] Machine sleep/power settings: laptop won't suspend mid-run (or you accept reconciler exercise — it's designed for this, but don't make it routine).
- [ ] Crash drill planned: you will deliberately `kill -9` the orchestrator during Phase 1's stub-engine test at each transition. (Listed here so it isn't skipped when it feels unnecessary — it will feel unnecessary.)

## F. Human-in-the-loop plan

- [ ] You have blocked time to **watch the first supervised runs end-to-end** — autonomy is earned incrementally, not configured.
- [ ] NEEDS_HUMAN handling defined: where escalations land (a projection query), and your cadence for clearing them.
- [ ] Weekly 15-minute slot for the learning loop: feedback-recurrence query → guideline promotion.

---

*When every box is checked: Phase 1, step 1 — the event log. Nothing expensive runs until the durable core survives kill -9.*
