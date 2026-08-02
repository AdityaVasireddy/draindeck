# Session Handoff — session 28: config.yaml/config.example.yaml project.name mismatch (Option C residual) closed

## Objective
Close the `project.name: StockAgent` vs. repo-path `StockPhotoAgent` mismatch flagged in the prior handoff as an open residual (Option C). This session's role was executor in a two-role relay (reviewer gates via Adi); goal was a read-only-first, evidence-gated rename of the config field plus removal of a stale divergence comment — explicitly scoped as low-blast-radius (doc/config only, no `src/` touched).

## Current Status
- Completed: `config.yaml` and `config.example.yaml` edited and committed as `4afdb4a81e7c53a863bc6510e672ee01c56f54fb`. Residual is CLOSED.
- In Progress: none.
- Blocked: none — session closed cleanly at Adi's authorization.

## Decisions & Rationale
- Renamed `project.name: StockAgent` → `project.name: StockPhotoAgent` and collapsed the stale 3-line "decision says StockAgent, path says StockPhotoAgent" divergence comment into one clean line, in both `config.yaml` and `config.example.yaml` — reason: a recursive grep across the repo found no code consumer of the literal string as a load-bearing value; the only code-adjacent hit, `tests/unit/test_foundation.py`'s `GOOD_YAML` fixture (around line 245), is never asserted against — that test asserts only on `cfg.engine.auth_mode` and `cfg.experiment.cost_per_shipped_issue_max_usd`. Verified cosmetic-only this session before editing. Lives in `C:\Projects\issue-runtime\config.yaml` and `C:\Projects\issue-runtime\config.example.yaml`, commit `4afdb4a`.
- Left `config.example.yaml` line 11's `<StockAgent test command — REQUIRED before first run>` placeholder untouched — reason: it sits inside the ADR-23 validation-command block, which the reviewer explicitly scoped out to keep the edit minimal. Flagged as optional follow-up, not forgotten.
- Commit was held pending Adi's literal authorization (not just the reviewer's gate) per the standing "no commit without explicit user authorization" rule — reviewer proposed the commit prompt, execution waited for Adi's separate "authorized" message before running it.

## Key Files
- `C:\Projects\issue-runtime\config.yaml` — live local config, edited this session; confirmed git-tracked (`git ls-files --error-unmatch` succeeded) and NOT gitignored (`git check-ignore -v` returned no match) — this was previously assumed possibly-ignored and is now settled.
- `C:\Projects\issue-runtime\config.example.yaml` — committed template, edited this session, same two changes as above.
- `C:\Projects\issue-runtime\tests\unit\test_foundation.py` — `GOOD_YAML` fixture near line 245 read this session to confirm no assertion depends on `project.name`'s value.
- `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-02_session27-gate-c-corrected-gate-d-witnessed-sd-verified.md` — predecessor handoff; still uncommitted (`??`) at close of this session. Carries the Group S / ADR-19 status this handoff repeats below without independent re-derivation.

## Next Action
Adi picks the session-29 direction from three open, unauthorized paths (see Deferred Work). Before any of them: next executor's opening action must be a read-only state re-verification (build HEAD, working tree, StockPhotoAgent branch/tip, baseline, attempt/recovery refs, event-log count, Ollama) run in PowerShell — not Git Bash — checked adversarially against this handoff as a dated snapshot, not standing fact.

## Knowledge Captured
- `config.yaml` is git-tracked, not gitignored — confirmed this session via `git check-ignore -v config.yaml` (no output, exit 1) and `git ls-files --error-unmatch config.yaml` (prints filename, exit 0). It IS captured by commits.
- This PowerShell console renders some UTF-8 characters as mojibake when printed via `Get-Content`/`echo` (e.g. `§` and em dash showed garbled) even though the underlying file bytes and `git diff` hunks are correct UTF-8 — a terminal-rendering artifact only, not file corruption. Confirmed by cross-checking `git diff`'s hunk output, which rendered `§6` correctly.
- Git Bash is inadmissible for validation on this project per Adi's explicit directive this session (backslash-path mangling, past false results). All git/file verification this session ran through `powershell.exe -NoProfile -File/-Command`, invoked from the Bash tool wrapper since no dedicated PowerShell tool is exposed — the commands themselves executed inside a PowerShell process, not Git Bash.

## Assumptions
- MED confidence: the Group S gate statuses (S-A through S-E, gate d) and the ADR-19 n=6 sample composition/flags stated below are carried forward from the reviewer's session-close summary and the session-27 handoff. Not independently re-derived or re-verified by me this session, beyond the raw event-log tail (events 107–109) read during this session's opening state check.

## Testing / Verification Performed
- PASS: `git check-ignore -v config.yaml` (no match) + `git ls-files --error-unmatch config.yaml` (tracked) → config.yaml is tracked, not ignored.
- PASS: recursive grep (`Get-ChildItem -Recurse -Include *.py,*.yaml,*.yml,*.ini,*.toml | Select-String -Pattern "StockAgent"`) across the build repo found only `config.yaml`, `config.example.yaml`, and `tests\unit\test_foundation.py:245`.
- PASS: `git diff -- config.example.yaml config.yaml` before commit showed exactly the intended comment + name-line hunks in each file; validation block, `repository`, and `branch` lines unchanged.
- PASS: post-commit `git log -1`, `git show --stat HEAD`, `git status --porcelain=v1` confirmed commit `4afdb4a` touched exactly `config.example.yaml` and `config.yaml` (2 files changed, 4 insertions(+), 6 deletions(-)), and that `.gitignore`, both handoff files, `claude_headless.py`, and `scratch/` remained uncommitted.
- NOT TESTED: no `src/` code changed this session, so the 60/60-both-seeds durability harness was not run — per CLAUDE.md this is only required for `src/` changes; this was a doc/config-only edit.

## Outstanding Issues
- Issue 12 remains escalated `needs-human` / `duplicate-feedback` (event log events 107–109, witnessed this session's opening read-only check: `ValidationPassed` → `ReviewRejected` (REJECT, empty diff) → `IssueEscalated`, execution `12-e2`). No action taken on it this session; carried forward from session 27.

## Technical Debt
- `config.example.yaml` line 11 still contains the stale `<StockAgent test command — REQUIRED before first run>` placeholder text — intentional, deliberately scoped out this session to keep the edit minimal. Low-blast-radius follow-up.

## User Constraints
- No commit without Adi's explicit authorization of that specific commit — enforced this session (held the commit prompt until Adi's literal "authorized").
- `src/` changes require 60/60 on both seeds (42, 1337) — not triggered this session.
- NO StockPhotoAgent `cmd_run` without Adi's explicit fresh go-ahead — not exercised this session.
- Git Bash is inadmissible for validation on this project — use PowerShell (or cmd) going forward.
- Commit → handoff → exit ordering is fixed.

## Runtime & System State
- Commit at handoff: `4afdb4a` (verified via `git rev-parse --short HEAD` this session).
- Background processes: none started this session.
- Dev servers / ports: none.
- Open branches / worktrees: build repo (`C:\Projects\issue-runtime`) on `master`. StockPhotoAgent (`C:\Projects\StockPhotoAgent`) on branch `agent-work`, tip `d663e32c...` — confirmed earlier this session, not re-checked at the exact moment of this handoff.
- Memory files updated: none this session.

## Deferred Work
- (A) Continue ADR-19 sampling with a new distinct issue — needs a fresh run go-ahead from Adi and the pool de-dup question resolved first.
- (B) Witness S-E / 11-e2 frontier-churn via a real StockPhotoAgent run — needs Adi's explicit fresh go-ahead, high blast radius; only path that clears the `hold_pid` commit gate.
- (C) `config.example.yaml` line-11 placeholder cleanup — low blast radius, optional, not done this session.
None of the three is authorized; Adi decides fresh next session.

## Open Questions
**Needs User Input**
- Which of (A) / (B) / (C) above should session 29 pursue first?
- ADR-19 attempt-1 numerator definition: does issue-11's 3rd-attempt success count toward the attempt-1 success rate? Unresolved, carried forward from session 27.
- ADR-19 pool de-dup: issue-11/issue-12 appear to be a byte-identical duplicate — does the id-space overcount the sample pool? Unresolved, carried forward from session 27; issue-12's this-session escalation (events 107–109) is a live instance of the same problem.

**Model Uncertainty**
- The Group S gate statuses (S-A/S-B/S-C/S-D VERIFIED, S-E NOT-OBSERVABLE, gate (d) 11-e2 frontier-churn out of scope) and the ADR-19 n=6 sample composition are stated above as carried forward from the reviewer's relay and the session-27 handoff — not independently re-derived by me this session.
