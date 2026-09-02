## ULTRA-REVIEW-001: Prepare gated fixes for launcher review findings

Prepare the approved pre-implementation gate for the six unique launcher-review findings. Finding 7 is a duplicate of finding 2.

Do not edit production source files under `src/`. Do not change launcher behavior. Do not commit, merge, or push.

Document an outcome matrix and a failing-test inventory for these fixes:

1. Malformed but valid JSON Ollama model responses (`[]`, `null`, or wrong item shapes) must not cause a 500.
2. The launcher-readiness Ollama probe must not block the Dashboard event loop.
3. A POSIX identity-check-to-kill race (`ProcessLookupError`) must not leak a traceback and must clean up stale launcher state safely.
4. Invalid, zero, or negative PIDs—including the unverified-occupant sentinel—must never be passed to `os.kill`.
5. Homebrew elevation messaging must correctly distinguish formula installs from the Claude Code cask.
6. Cancel must close both the reviewer-model dialog and the equivalent run-control dialog.

Add focused RED tests that prove each behavior would fail against the current implementation. Run those tests and report the RED evidence. Stop after the planning gate and RED evidence; wait for explicit approval before changing `src/`.

### Acceptance
- An outcome-matrix row and RED-test entry exists for each of the six unique findings.
- Each proposed test names the precise behavior and affected file.
- The RED tests fail for behavioral reasons, not collection/import errors.
- No production source files under `src/` are changed.
- No commit, merge, or push is performed.
- The final report contains the raw RED test output and `git status --short`.

## DASHBOARD-QUEUE-RECOVERY-001: Plan safe recovery for an abnormal Dashboard run command

The Dashboard correctly fail-closes a repository after a run command reaches `ABNORMAL_EXIT`, but it currently has no operator-visible, safe recovery or retry path. This blocks later selected runs even when the underlying cause has been corrected.

Create the pre-implementation outcome matrix and RED-test plan for a user-controlled recovery action. It must revalidate the configured target, issue-file revision, workspace ownership, and current runtime event state before it releases or retries a blocked queue command. It must never repair `events.jsonl`, mutate a workspace lease, delete queue rows manually, or silently start another run.

Do not edit production source files under `src/`. Do not commit, merge, or push. Stop after producing the planning gate and RED-test evidence.

### Acceptance
- The plan defines when an `ABNORMAL_EXIT` command may be retried, acknowledged, or remain blocked.
- The plan explicitly rejects unsafe recovery when runtime ownership or event evidence is ambiguous.
- RED tests cover: corrected pre-start failure, unresolved runtime state, stale issue-file revision, concurrent retry attempts, and foreign/unknown process ownership.
- No production source files are changed.
- The final report includes RED test output and `git status --short`.