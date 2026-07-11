# 08 — Session 0 Closure & ADR Amendments

**Status:** ACCEPTED · **Date:** 2026-07-10
**Relationship to frozen docs:** This document extends the frozen design (docs 01–07). It adds ADR-18..20 and records the checklist-A1 verification result. It does not modify any frozen invariant, component, or schema. Where this document and doc 03 disagree, doc 03 wins.

---

## 1. Checklist A1 — Headless billing verification (RESOLVED)

**Finding (verified 2026-07-10 against Anthropic's Help Center):** The June 15, 2026 Agent SDK / `claude -p` billing split was **paused by Anthropic on its ship date**. As of today:

- `claude -p` (headless) draws from the normal Pro subscription usage limits — same pool as interactive use.
- No separate Agent SDK monthly credit is active or claimable.
- Anthropic has stated a revised plan will be announced before anything takes effect.

**Implications adopted:**
- There is no hard dollar-denominated ceiling specific to headless usage today; the constraint is the Pro plan's ordinary rate limits.
- The pause is explicitly temporary. ADR-09 budget protections are therefore **retained unchanged** (see §3).
- Re-verification is a standing gate item: re-check billing status **at the Phase 2 gate** and any time Anthropic announces a revised plan. Record each check in `config.yaml → billing.verified_on`.

Source of record: Anthropic Help Center article "Use the Claude Agent SDK with your Claude plan" (support.claude.com, article 15036540), June 15 update banner.

---

## 2. ADR-18 — Execution provider for v1: Claude Pro subscription, headless

**Decision.** v1 executes the Implementer role via `claude -p` authenticated against the user's Claude Pro subscription. No API key is configured in v1.

**Configurability.** Auth posture is a configuration value, not code:

```yaml
engine:
  provider: claude-headless      # only concrete engine in v1 (per ADR-08)
  auth_mode: subscription        # subscription | api_key
```

Switching to API mode later means setting `auth_mode: api_key` and supplying `ANTHROPIC_API_KEY` via environment — no orchestrator code changes. Note the mechanism: when `ANTHROPIC_API_KEY` is set in the subprocess environment, `claude` authenticates with it and bills pay-as-you-go; in subscription mode the orchestrator must ensure that variable is **absent** from the spawned environment to avoid silently billing the API. The engine wrapper owns this environment hygiene.

**Scope guard.** This does NOT introduce an engine abstraction seam. Per ADR-08, the engine seam remains un-abstracted until a second real harness exists. `auth_mode` is a parameter of the single concrete `claude-headless` engine, not a provider interface.

**Rejected alternatives.**
- *API key from day one:* more predictable metering, but incurs real per-token cost during the falsification run before the workflow has proven value; subscription cost is already sunk.
- *Max plan upgrade:* premature before the 20-issue verdict.

---

## 3. ADR-09 amendment note — Budget protections retained despite paused split

ADR-09 (budget manager) was motivated partly by the announced billing split. The split is paused (§1), but ADR-09 is **retained in full**, because: (a) Anthropic has committed to shipping a revised version with notice, and absorbing it must be a config change, not a redesign; (b) kill-criteria cost accounting (ADR-19) needs per-execution cost/turn/token metering regardless of who is billed; (c) runaway-loop protection is a correctness feature, not only a cost feature.

In subscription mode, where dollar cost is not directly metered, the budget manager tracks **proxy costs**: estimated tokens (from `claude -p` JSON output usage fields) priced at published API list rates. Cost-per-shipped-issue in ADR-19 is computed from this proxy. This is deliberately conservative: it prices the workflow as if the split were live, so the Phase 4 verdict remains valid under either billing regime.

---

## 4. ADR-19 — Pre-committed experiment kill criteria

**Decision.** The Phase 4 falsification run evaluates exactly these thresholds, committed now, before any code exists:

| Parameter | Value |
|---|---|
| Sample size | 20 completed issues |
| Continue if | Attempt-1 success rate ≥ 30% |
| Kill / redesign if | Attempt-1 success rate < 30% **OR** average proxy cost per shipped issue > **$3.00** |

**Definitions (binding):**
- *Attempt-1 success:* the first execution for an issue reaches COMMITTED (passes validation, passes review, pinning gate holds) with no retry.
- *Completed issue:* an issue that reached a terminal state (SHIPPED or FAILED). Abandoned/blocked issues do not count toward the 20 but are reported.
- *Proxy cost:* API-list-rate valuation of measured token usage per §3, summed over **all** attempts for the issue, divided by shipped issues only.

**Honesty clause (per User Constraints, doc 00 handoff):** thresholds may not be revised after the run begins. If the run fails a threshold, the verdict is Kill/Redesign — parameter tuning to re-run requires an explicit new ADR superseding this one, with the failed run's data attached.

---

## 5. ADR-20 — Initial target repository: StockAgent; repository is configuration only

**Decision.** The v1 target repository is **StockAgent** (local path `C:\Projects\StockPhotoAgent`, working branch `agent-work`).

> ⚠ Naming discrepancy to resolve in config: the decision names the project "StockAgent" but the path is `StockPhotoAgent`. The path below is used verbatim as provided; correct it in `config.yaml` if the directory name differs on disk.

**Repository-agnosticism (binding constraint):** no component may hardcode a repository path, branch name, language, test command, or project layout. All repository-specific knowledge enters through exactly two channels:

1. `config.yaml → project.*` — path, branch, validation commands.
2. The Repository Adapter interface (doc 09 §7) — all git and filesystem operations against the target repo go through it.

The baseline-green requirement (doc 06) applies to StockAgent: its test suite must pass on `agent-work` before the first supervised run.

**Rationale.** Real project, safe to experiment on, immediate business value, demoable; and choosing a real repo forces the repository-agnostic seam to be honest rather than theoretical.

---

## 6. Final v1 `config.yaml` (reference example)

```yaml
# config.yaml — v1 reference (Session 0 final)
project:
  name: StockAgent
  repository: 'C:\Projects\StockPhotoAgent'   # ⚠ confirm directory name on disk
  branch: agent-work
  issues_file: Issues.md
  validation:                    # deterministic gate — repo-specific, config-supplied
    commands:
      - <test command for StockAgent>          # fill in Session 1
    timeout_seconds: 600

engine:                          # ADR-02, ADR-08, ADR-18
  provider: claude-headless
  auth_mode: subscription        # subscription | api_key ; api_key requires ANTHROPIC_API_KEY
  model: default                 # let claude -p use plan default unless overridden
  max_turns: 30
  timeout_seconds: 1800

reviewer:                        # ADR-05 — provider-independent day one
  provider: qwen                 # qwen | claude
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
  claude:
    auth_mode: subscription

budget:                          # ADR-09, retained per ADR amendment §3
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  proxy_pricing: api_list_rates  # cost accounting basis for ADR-19
  hard_stop_proxy_cost_per_run_usd: 15.00

experiment:                      # ADR-19 — do not edit after run begins
  sample_size: 20
  attempt1_success_min: 0.30
  cost_per_shipped_issue_max_usd: 3.00

billing:                         # checklist A1 record
  posture: pro_subscription_headless
  headless_split_status: paused          # per Anthropic Help Center
  verified_on: '2026-07-10'
  reverify_at: phase-2-gate

event_log:                       # ADR-11
  path: state/events.jsonl

attempts:                        # ADR-15
  ref_namespace: refs/attempts
```

---

## 7. Session 0 status

All checklist items closed: A1 billing verified (§1), execution provider decided (ADR-18), kill criteria pre-committed (ADR-19), target repository decided (ADR-20). **The architecture is frozen.** Session 1 proceeds per doc 09.
