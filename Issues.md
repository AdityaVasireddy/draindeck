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