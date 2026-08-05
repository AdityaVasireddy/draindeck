# Session Handoff — Issue-runtime hygiene commits; issue-19 decomposed and shipped to StockPhotoAgent; both repos' working trees cleaned to zero-untracked baseline
Continues from: C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-03_session31-item9-scratch-fault-injection.md — no conflicts (that handoff is authoritative for Group-S GAP-1 witnessing and the open Layer-2 movement-across-kill question, neither of which this session touched beyond closing out issue-903, one of session-31's scratch fixtures)

## Objective
Cold-started from issue-runtime HEAD f7573f8 with a dirty tree and two open escalations (issue-19 needs-decomposition, issue-903 needs-human) plus a deferred model-tag-pin check. Worked as EXECUTOR under a strict evidence-only protocol (raw terminal output only, explicit go-ahead before every write/commit/delete) to: clean up issue-runtime's own tree, resolve the model-tag-pin and issue-903 items, investigate and decompose issue-19 into real StockPhotoAgent backlog work, and bring StockPhotoAgent's dirty `agent-work` tree to a clean, fully-committed baseline.

## Current Status
- Completed:
  - issue-runtime: committed `.gitignore` fix + session-26 gate-(c) correction (aedc659), committed a stray session-27 handoff doc (d6342bf), deleted scratch residue (`config.scratch-item9.yaml`, `scratch/`). Tree clean at d6342bf.
  - Model-tag pin: closed as already-satisfied, no change made — `qwen2.5-coder:14b` is already git-committed in StockPhotoAgent's `config.yaml` under `reviewer.qwen.model` with a verification comment.
  - issue-903: closed as synthetic/no-action — it was a session-31 fault-injection fixture (harness now deleted), not real backlog, its purpose already witnessed.
  - issue-19: investigated (three-way country-derivation divergence confirmed in raw source), decomposed into issues 23/24/25, appended to StockPhotoAgent's `Issues.md`, parse-verified, committed as adf9ab4.
  - StockPhotoAgent `agent-work` tree: inventoried, 8 cruft items deleted individually by name, 4 real-work items reviewed/secret-scanned and committed in two commits (f4a9c27, 1c9c8d5). Tree verified fully clean.
- In Progress: none — every gated task this session reached either a commit or an explicit hold point.
- Blocked: any live StockPhotoAgent `cmd_run` — hard-gated on Adi's explicit fresh go-ahead per standing project rule; not requested this session.
- Not yet built: the `derive_country()` helper itself and its call-site migration (issue 23/24) — this session only decomposed and queued the work; no implementation code was written or run against StockPhotoAgent.

## Decisions & Rationale
- Committed the session-27 handoff doc rather than deleting it — content review confirmed it was a legitimate historical record (Group-S gate corrections), not scratch residue. Lives at `C:\Projects\issue-runtime\docs\handoffs\HANDOFF_2026-08-02_session27-gate-c-corrected-gate-d-witnessed-sd-verified.md`.
- Closed the model-tag-pin item without any write — the tag was found to already be git-committed with a verification comment, not a live-Ollama-only assumption as the open item description implied.
- Closed issue-903 as synthetic/no-action rather than reconstructing it — its defining harness script was already deleted as scratch residue earlier in the session, and its escalation behavior (cap-hit after 3 REJECTed attempts) was already witnessed per the session-31 handoff.
- Approved country-derivation default policy for issue 23: on no match, `derive_country` returns `"United States"` and logs a warning — Adi's explicit call, matching Getty's existing warn behavior more than Pond5's silent-default behavior.
- Used bare sequential integer ids (23/24/25) for the new issues rather than letter-suffixed ids (19a/19b/19c) — matches the existing convention in `Issues.md` (ids 7-22 are all bare integers); the parser itself has no preference (confirmed by reading `src/runtime/queue/issues_md.py` — id regex is `[A-Za-z0-9][A-Za-z0-9_-]*`, no numeric/monotonic constraint).
- Wrote the three new issue blocks with plain ASCII (`STATUS: OPEN - not started.` using a hyphen) rather than matching the file's existing em-dash convention — explicit instruction from Adi, given this session's repeated trouble with em-dashes getting mangled in PowerShell console output.
- Deleted `getty_session.json` and the two one-off `patch_*.py` scripts rather than keeping them — session-cache-shaped data should never be committed regardless of disposition, and the patch scripts were hardcoded to a specific already-processed 2026-06-14 output batch, not reusable tooling (confirmed by reading their contents).

## Key Files
- `C:\Projects\issue-runtime\config.yaml` — reviewer.qwen.model pin, confirmed already committed with verification comment; no change made.
- `C:\Projects\issue-runtime\src\runtime\queue\issues_md.py` — the real Issues.md parser; governs the exact schema any future issue-authoring must follow (id regex, unbulleted `Depends-On:` requirement, `### Acceptance` bullet format).
- `C:\Projects\StockPhotoAgent\Issues.md` — issues 23/24/25 appended this session (commit adf9ab4); real backlog for the country-derivation unification work.
- `C:\Projects\StockPhotoAgent\src\csv_generator.py` (lines ~305-321 Getty, ~383-407 Pond5) and `C:\Projects\StockPhotoAgent\src\utils\review_manager.py` (lines ~236-260 promote) — the three divergent country-derivation sites issues 23/24/25 target; unmodified this session, read-only confirmation of the defect.

## Next Action
Before requesting Adi's go-ahead for a live StockPhotoAgent `cmd_run` against issues 23/24/25, re-verify the Step-3 live-run preconditions from scratch (do not trust this session's snapshot) — Ollama `qwen2.5-coder:14b` reachability at `localhost:11434`, `Issues.md` parses cleanly with no id collisions, StockPhotoAgent's baseline validation command still exits 0, and `agent-work` is still at a clean `git status`.
Done when: all four checks have fresh raw command output pasted in the same session as the go-ahead request — a check reused from an earlier session does not satisfy this.

## Assumptions
- HIGH — model-tag pin is correctly closed: verified directly by reading `config.yaml` and grepping `qwen_ollama.py`'s constructor this session, not inferred.
- HIGH — issue-903 is correctly closed as non-real: verified via absence of an `IssueCreated` event for id 903 in issue-runtime's main `state/events.jsonl`, plus the session-31 handoff's own account; the defining harness script was not re-read this session (already deleted before this session's recon).
- HIGH — issues 23/24/25's `Depends-On` chain is correct: directly parse-verified with `runtime.queue.issues_md.parse()` before commit (`24 depends: [['23']]`, `25 depends: [['24']]`), not assumed from the diff alone.
- MED — the two kept scripts (`getty_keyword_automation.py`, `regenerate_getty_csv.py`) are genuinely reusable tooling rather than also-stale one-offs: based on reading their docstrings/usage sections (general-purpose framing, no hardcoded one-off output paths) and a clean secret scan, not on running them.
- LOW — StockPhotoAgent's baseline validation command (`config.yaml`'s `project.validation.commands`) still passes: not re-run this session; last known verification was dated 2026-07-25 per `config.yaml`'s own inline comment, predates this session by over a week.

## Knowledge Captured
- Parser gotcha: `Issues.md`'s `Depends-On:` field must NOT be bulleted. `- Depends-On: 23` silently fails to match the parser's `^Depends-On\s*:\s*...` regex after `.strip()` (the dash survives stripping) and falls through into ordinary body text — no exception, no error, `parse()` returns cleanly with `depends_on` simply empty. The only way to catch this is to assert on the specific field value after parsing, not just confirm the parse doesn't raise.
- `Select-String` has no `-Recurse` parameter in this environment's PowerShell version, regardless of whether `-Path` is a single directory or a wildcard glob — always route through `Get-ChildItem -Recurse -File | Select-String` instead.
- This session's PowerShell console silently mangles em-dashes and other non-ASCII characters in `Get-Content`/`git diff` output display (rendered as `�?"` or similar) — confirmed via byte-level inspection that the underlying files are correctly UTF-8 encoded; it is a console/display artifact only, not file corruption. Don't trust console-rendered text to judge a file's actual byte content when non-ASCII is involved — check with `[System.IO.File]::ReadAllBytes` or Python's `open(..., 'rb')` instead.
- StockPhotoAgent's `agent-work` tree contained an undocumented bug artifact: a broken path-join somewhere in past test tooling replaced `:` with a private-use-area Unicode character and failed to use `\` as a path separator, producing files with the entire intended nested path crammed into one flat filename (plus a companion empty directory with the same mangled name, visible only via `git clean -nd` since git doesn't track empty directories). Not traced to a specific script this session — flagging in case it recurs.
- One of the deleted one-off scripts (`patch_ss_csv.py`, internally headed `patch_getty_country.py`) was a manual hand-patch defaulting empty `country` fields to `"United States"` for a specific 2026-06-14 batch — independent evidence that the country-derivation defect issue-19/23/24/25 addresses is real and was previously worked around by hand.

## Testing / Verification Performed
- PASS: issue-runtime commit aedc659 scope — `git show --stat --format="%H %s" aedc659` showed exactly `.gitignore` and the session-26 handoff doc, 2 files changed.
- PASS: issue-runtime and StockPhotoAgent trees both independently verified clean via `git status --porcelain=v1 --branch` at multiple checkpoints, final states `d6342bf`/`##master` (nothing untracked) and `1c9c8d5`/`##agent-work` (nothing untracked) respectively.
- PASS: StockPhotoAgent `Issues.md` diff scope — `git diff -- Issues.md` confirmed only the three appended blocks changed, both before and after the `Depends-On` bullet fix, nothing else in the file touched.
- PASS: issue 23/24/25 dependency chain — `runtime.queue.issues_md.parse()` run directly against the live file returned `24 depends: [['23']]`, `25 depends: [['24']]`, 17 total issues parsed with ids 7-10,13-25 all present.
- PASS: secret scan on the two committed scripts — `Select-String -Pattern "password","passwd","api_key","apikey","token","secret","cookie","Authorization","Bearer"` against `getty_keyword_automation.py` and `regenerate_getty_csv.py` returned zero hits.
- NOT TESTED: StockPhotoAgent's baseline pytest validation command — not re-run this session, no code under test/validation changed (only `Issues.md`, docs, and two standalone scripts unrelated to the test suite were touched).
- NOT TESTED: issue-runtime's 60/60-both-seeds durability gate — not re-run, no `src/` changes made to issue-runtime this session.
- NOT TESTED: live Ollama reachability at `localhost:11434` — relied on the committed verification comment in `config.yaml`, not re-checked live this session.

## User Constraints
- No live `cmd_run` / issue execution without Adi's explicit fresh go-ahead each time — approval does not carry over between turns or sessions.
- Raw, unsummarized terminal output required on every commit-adjacent turn — enforced strictly and repeatedly this session; continue this discipline.
- No blanket `git clean -fd` — cruft deletions must be explicit, by name, individually reviewed.
- Every process must be identified by full command line before any kill — no blanket `python.exe`/`claude.exe` kills (not exercised this session, no processes were killed).
- issue-runtime `src/` changes require 60/60 both seeds (42, 1337) before merge — not applicable this session, no `src/` changes made.

## Runtime & System State
- Commit at handoff (issue-runtime, master): d6342bf
- Commit at handoff (StockPhotoAgent, agent-work): 1c9c8d5
- Long-lived processes: none started this session.
- Dev servers / ports: none.
- Open branches / worktrees: none created; both repos on their existing default branches (master / agent-work).
- Memory files updated: none this session.

## Deferred Work
- S-E full-nine-merge witness sweep — only 1 of 9 merges witnessed to date (commit 779fb3e); explicitly deferred, not attempted this session.
- Layer-2 `capture_work_liveness` movement-across-kill — open since session 31, untouched this session, still awaiting Adi's design decision (long single-write target vs. close as snapshot-capability-delivered).
- Live StockPhotoAgent `cmd_run` against issues 23/24/25 — deferred pending Adi's explicit fresh go-ahead; the queue is ready but nothing was run.

## Open Questions
**Needs User Input**
- [non-blocking] S-E full-nine-merge sweep vs. Layer-2 movement-across-kill vs. live StockPhotoAgent cmd_run on 23/24/25 — which open item to pursue next is Adi's call; none is implied by this session's work.
- [non-blocking] Layer-2 `capture_work_liveness` design direction (long single-write target vs. close as snapshot-capability-delivered) — carried forward unresolved from session 31, still needs Adi's decision.

**Model Uncertainty**
- The root cause of the mangled-path bug artifact found in StockPhotoAgent's `agent-work` tree (colon-to-PUA-char substitution, flattened nested paths) was not traced to a specific script this session — worth investigating if it recurs, since it suggests a live bug in some test-writing code path, not just historical cruft.
