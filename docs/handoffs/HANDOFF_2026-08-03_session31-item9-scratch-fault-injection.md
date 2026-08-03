# Session Handoff — item-9 fault injection: GAP-1 witnessed on a scratch target, Layer-2 movement still open
Continues from: `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-03_session30-adr19-close-holdpid-committed.md` — no conflicts (this session builds directly on that one's hold_pid commit `7d2f4eb`, without touching durability-gate/commit content)

## Objective
Run the first real fault-injection exercise of `cmd_run` + Layer-2 `capture_work_liveness` (item 9, orphan-crash recovery witness) since hold_pid landed. Six-item precondition check (repo state, StockPhotoAgent branch/tree, Ollama, Issues.md freshness, config validation, `.gitignore`/event-log state) found the real StockPhotoAgent backlog already fully drained by a same-day prior run (`run-20260803T050931Z`) — 9 of 10 "OPEN" issues in `Issues.md` were already fixed in code, confirmed by grep. With no real backlog left to interrupt, a disposable scratch target was built instead, per the item-9/13/14 precedent of not fault-injecting against the live target when nothing is safely in flight. Live StockPhotoAgent was never touched this session.

## Current Status
- Completed:
  - Six-item precondition check, all raw-verified (see prior turns this session; not re-summarized here as it precedes the handoff-worthy work).
  - Scratch target built at `C:\Users\adity\AppData\Local\Temp\ch-scratch-item9` (git repo) + `...\ch-scratch-item9-state` (event log/artifacts, kept outside the repo tree).
  - Three scratch `cmd_run` cycles executed to a terminal state: issues 900/901 (both completed), issue 902 (completed on retry after a witnessed live kill), issue 903 (escalated after 3 attempts).
  - GAP-1 live-child witness: **PASS, witnessed twice.** Issue 902 — `claude.exe` PID 49724 alive and growing (391MB→405MB) in `tasklist` immediately before a parent-only `taskkill /PID 12556 /F` (no `/T`); leaf, shim, and hold companion all survived, orchestrator confirmed gone. Issue 903 — re-witnessed, `claude.exe` PID 41436, same pattern, orchestrator `69356` killed, leaf/shim/hold survived.
  - Detection-mechanism fix that made GAP-1 possible: switched from text-scanning the live UTF-16 PowerShell `Tee-Object` log (`grep`/`Select-String`, both missed the pause line for minutes) to polling for the `sentinel_ready` marker file's existence directly. Two earlier misses this session were this latency/encoding bug, confirmed via the marker's own `paused_at` timestamp showing a multi-minute gap versus when I actually checked — not the child's task being too fast.
  - Recovery mechanics (issue 902, completed cycle): all PASS — `ExecutionCrashed(902-e1)` with non-null `residue_ref` before the retry spawn; exactly one retry (`902-e2`); merge commit `23266a8`'s second parent (`95af1d8c...`) equals `902-e2`'s `end_commit` exactly (content-based no-double-commit); residue SHA `fad2714...` distinct from that; `refs/attempts/902/902-e1` resolves post-`IssueCompleted`; `refs/attempts/902/902-e2` correctly GC'd (execution-scoped).
  - Escalation path (issue 903): PASS — all three attempts (one killed, two run to full natural completion) implemented only `power()` despite explicit staged instructions; reviewer `REJECT`ed the two completed attempts for that reason; `IssueEscalated(reason=cap-hit)` after the 3-attempt budget; all three `refs/attempts/903/903-e{1,2,3}` persist (no GC on escalation, only on `IssueCompleted`); `scratch-work`'s tip (`bb9fbafa04c9717a401fe113b8a623e1ddfd1cff`) unchanged before/after — no merge landed.
- In Progress: none.
- Blocked: none.
- Not yet built: Layer-2 movement (pre/post-kill content delta) has never been observed — see Risks.

## Decisions & Rationale
- Moved the scratch event log/artifacts path outside the scratch git repo's own working tree (`ch-scratch-item9\state\...` → sibling `ch-scratch-item9-state\...`) — the first launch attempt crashed inside the reconciler's `git clean -fd` trying to delete an open event-log file, because `event_log.path` had been pointed inside the repo tree. Matches production's real topology, where `state/` lives outside the target repo. Fixed in `C:\Projects\issue-runtime\config.scratch-item9.yaml`.
- Added a `.gitignore` (`__pycache__/`, `*.pyc`, `.pytest_cache/`) to the scratch repo — the baseline `pytest` validation step left an untracked `__pycache__/`, which then tripped `checkout_branch`'s dirty-tree guard for the first real issue. Same hygiene precondition StockPhotoAgent's real `.gitignore` already covers (confirmed earlier in this session's precondition check).
- Killed six leftover scratch/hold-companion `python.exe` processes across two cleanup rounds, each identified individually by `Get-CimInstance ... CommandLine` before killing — never a blanket kill. VSCode's autopep8 LSP processes (PIDs 37052, 40224) were left untouched both times.

## Key Files
- `C:\Projects\issue-runtime\config.scratch-item9.yaml` — the disposable scratch config used for every run this session. **Untracked, left in place**, not part of this handoff's commit.
- `C:\Users\adity\AppData\Local\Temp\ch-scratch-item9` — the disposable scratch git repo (target), branch `scratch-work`, tree clean, tip `bb9fbafa04c9717a401fe113b8a623e1ddfd1cff`. Left in place.
- `C:\Users\adity\AppData\Local\Temp\ch-scratch-item9-state\events.jsonl` — the scratch run's own event log, 13 events, terminal state = issue 903's escalation. Left in place.
- `C:\Projects\issue-runtime\src\runtime\engine\claude_headless.py` — engine source; `ITEM9_SENTINEL` gate, `_sentinel_pause`, `_resolve_leaf_worker` (Layer 1), `capture_work_liveness` (Layer 2) all read this session, none modified.
- `C:\Projects\issue-runtime\docs\15-item9-outcome-matrix.md` — pre-existing outcome-matrix design (scoped to the live target in an earlier session); its mechanics (kill method, GAP-1 discriminator, Layer-1/Layer-2 dual witness) were adapted to the scratch target this session, not re-derived from scratch.
- `C:\Projects\issue-runtime\NEXT.md` — item 9's entry (§2, item 9) still reads "STILL UNWITNESSED" as of session 24's text; not updated this session (see Next Action).

## Next Action
Update `NEXT.md` item 9 to record GAP-1 as witnessed (twice, on a scratch target) and Layer-2 movement as a documented, likely-structural open sub-item — do not touch any other section of `NEXT.md` in the same edit.
Done when: `NEXT.md`'s item 9 text no longer reads "STILL UNWITNESSED" for the GAP-1/live-kill claim specifically.

## Assumptions
- The $ figures below are read directly from each run's own `[metrics]` stdout line, not recomputed or estimated — HIGH confidence.
- "Recovery mechanics PASS on issue 902" and "escalation path PASS on issue 903" are both based on raw `git rev-parse`/`git log`/event-log output I read this session, not on the runtime's own self-reported success — HIGH confidence.
- The claim that the two earlier GAP-1 misses were a detection-latency bug (not task speed) rests on the `sentinel_ready` marker's `paused_at` timestamp versus my own check-time, both of which I read directly this session — HIGH confidence.

## Knowledge Captured
- `sentinel_ready` marker-file existence is a reliable, encoding-immune, near-instant detection signal for the `ITEM9_SENTINEL` pause point; text-scanning the live PowerShell `Tee-Object` log (`grep` or `Select-String`) is not reliable for this purpose on this machine.
- On this machine, `.venv\Scripts\python.exe` spawns as a parent/child PID pair sharing an identical `CommandLine` and creation timestamp, for both the orchestrator process and each hold-companion process (confirmed via `Get-CimInstance Win32_Process`) — cleanup must account for both members of a pair, not just one.
- For a small, single-function task, the real file edit can land within ~5–6 seconds of stdin delivery — before the sentinel's own leaf-worker-resolution polling (up to 10s) even finishes — so the marker can fire *after* the meaningful work is already done, structurally limiting how "pre-write" a first snapshot can be.
- Given an explicit staged multi-function task (write X, save+test, write Y, save+test, write Z), the model collapsed it into a single atomic write of only the first function across all three independent execution attempts on issue 903 (one killed mid-execution, two run to full natural completion under supervision) — this appears to be a property of the model's execution style on this task shape, not a timing artifact, since it recurred identically on fully-supervised runs.

## Testing / Verification Performed
- PASS: `check-config` against `config.yaml` (live) and `config.scratch-item9.yaml`, both RC:0, `OK: structure and environment valid`.
- PASS: GAP-1 live-child witness, issue 902 — `tasklist /FI "PID eq 49724"` showed `claude.exe` alive before kill; re-checked alive (orphaned) after `taskkill /PID 12556 /F`.
- PASS: GAP-1 live-child witness, issue 903 — same pattern, PID 41436, orchestrator PID 69356.
- PASS: recovery mechanics, issue 902 — `git log -1 --format="%H %P" 23266a8...` confirms second parent `95af1d8c...` equals `git rev-parse 95af1d8c...` (902-e2's `end_commit`); `git rev-parse refs/attempts/902/902-e1` resolves to `fad2714...`; `git rev-parse refs/attempts/902/902-e2` fails (absent, GC'd).
- PASS: escalation path, issue 903 — `git rev-parse refs/attempts/903/903-e{1,2,3}` all resolve; `git rev-parse scratch-work` equals the pre-run seed commit `bb9fbafa04c9717a401fe113b8a623e1ddfd1cff`; `git log --all --grep="903"` shows only the three attempt commits plus the seed commit, no merge.
- NOT TESTED: Layer-2 movement delta — `capture_work_liveness` returned correctly-formed snapshots on every call (cross-checked once against independent `sha256sum`, no discrepancy), but no run produced two differing snapshots while the orchestrator was dead.
- NOT TESTED (out of scope, by design): live StockPhotoAgent — zero commands executed against `C:\Projects\StockPhotoAgent` this session.

## Risks
- `capture_work_liveness` (Layer 2) has not demonstrated a real pre/post-kill content delta across three attempts on two different work shapes (one atomic single-function edit, one explicitly-staged three-function task that still collapsed to one write). If item 9's sign-off requires Layer-2 movement as a hard gate rather than "snapshot mechanism proven correct," that gate remains unmet and may need a fundamentally different work shape (e.g., a slow-to-write large file) to ever exercise — not just another retry with the same class of task.

## User Constraints
- No commit without explicit per-commit authorization — reaffirmed at each step this session (run authorization and commit authorization kept separate).
- Live StockPhotoAgent must not be touched — held throughout.
- PowerShell only for `check-config`/`run` invocations, never Git Bash directly (backslash/flag mangling) — hit directly this session (`$LASTEXITCODE` and `/FI` both mangled under Git Bash) and worked around via `powershell.exe -NoProfile -Command` every time.
- This handoff commit must contain only the handoff document — no other pending change in the working tree is to be swept in.

## Runtime & System State
- Commit at handoff: `da0ff7f` (before this handoff's own commit).
- Long-lived processes: none. Final `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` this session showed only two unrelated VSCode autopep8 LSP processes (PIDs 37052, 40224) — all scratch orchestrator/hold/leaf processes confirmed killed or exited naturally.
- Dev servers / ports: Ollama at `localhost:11434` — pre-existing, not started this session, left running.
- Open branches / worktrees: `issue-runtime` itself unchanged, still on `master`. Scratch repo (`C:\Users\adity\AppData\Local\Temp\ch-scratch-item9`) left checked out on `scratch-work`, tree clean, tip `bb9fbafa04c9717a401fe113b8a623e1ddfd1cff`.
- Memory files updated: none this session.

## Deferred Work
- Layer-2 movement-across-kill demonstration — deferred pending the user's choice between a slower/incremental work-shape retry and closing this sub-question as a documented limitation (see Open Questions).
- `NEXT.md` item 9 update — not done this session; see Next Action.
- Issue-19 decomposition (StockPhotoAgent, real) — still open per the prior handoff, not touched this session.
- Full nine-merge S-E witness sweep against StockPhotoAgent — still open per the prior handoff (1 of 9 witnessed as of session 30), not touched this session.
- `config.example.yaml` line-11 `<StockAgent>` placeholder — still scoped out per the prior handoff, not touched or re-verified this session.

## Open Questions

**Needs User Input**
- [non-blocking] Layer-2 movement: pursue a genuinely slow/incremental single-write target to try to catch a real pre/post-kill delta, or treat the `capture_work_liveness` snapshot mechanism itself (proven correct on every call) as the deliverable and close this sub-question as a documented, likely-structural limitation?
- [non-blocking] Scratch-artifact disposal: `config.scratch-item9.yaml`, the scratch git repo, and its event log were all left in place this session rather than deleted, in case they're useful for a Layer-2 retry. Delete now, or keep until the question above is settled?

**Model Uncertainty**
- The first (dead) sentinel-paused attempt on issue 902 completed real work (a correct `divide()` implementation, confirmed by direct file read) before its event log was wiped during cleanup — its actual API/subscription cost was never captured in any `$` figure, since no `ExecutionFinished` event was ever written for it. Amount unknown; not included in the cost tally below.

## Cost tally (tallied from `[metrics]` lines only; see Model Uncertainty above for one untallied cost)
- 900/901 completion run: `executions_this_run=2 proxy_dollars_this_run=$0.2427`
- 902 completion run (post live-kill): `executions_this_run=1 proxy_dollars_this_run=$0.1698`
- 903 run (crash + 2 review-rejected retries): `executions_this_run=2 proxy_dollars_this_run=$0.6116`
- **Total tallied: $1.0241**, plus one untracked real cost (see above).
