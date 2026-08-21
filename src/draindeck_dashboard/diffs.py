"""Derived Git diff safety (docs/19 "Artifacts and diffs").

Route this backs: ``GET /api/repositories/{repo_id}/executions/{execution_id}/diff``
(defined in app.py, wired before Phase 6 implementation per the explicit
gate requirement).

Runs against the repository's already-validated `projectPath` (an
absolute, existing Git work-tree, enforced at registration) using
`shell=False`. `--no-ext-diff` and `--no-textconv` are the two named
mechanisms by which a target repo's own `.gitattributes`/config could run
repository-controlled code during a diff (a custom diff driver, or a
textconv filter); both are disabled explicitly rather than trusted to be
absent. `--no-pager` avoids a pager subprocess. Output is capped, honestly
flagged as truncated when the cap binds, mirroring the same discipline
`runtime.observe` applies to its own bounded reads.
"""
from __future__ import annotations

import re
import subprocess

from .errors import DashboardApiError

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{4,40}$")
MAX_DIFF_BYTES = 1 * 1024 * 1024  # 1 MiB
DIFF_TIMEOUT_SECONDS = 30


class DiffInvalidCommit(DashboardApiError):
    status_code = 400

    def __init__(self, message: str, **kw) -> None:
        super().__init__("DIFF_INVALID_COMMIT", message, **kw)


class DiffUnavailable(DashboardApiError):
    status_code = 500

    def __init__(self, code: str, message: str, **kw) -> None:
        super().__init__(code, message, **kw)


def _validate_commit_ref(value, field_name: str) -> str:
    if not isinstance(value, str) or not _COMMIT_RE.match(value):
        raise DiffInvalidCommit(f"{field_name} is not a valid commit hash")
    return value


def compute_diff(repo_path: str, start_commit, end_commit) -> dict:
    """Returns {"diff": str, "truncated": bool, "sizeBytes": int}. Never
    builds the argv from unvalidated input -- both refs must match a
    strict hex-sha pattern before they are ever passed to the subprocess,
    so neither can be interpreted as an option or pathspec."""
    start = _validate_commit_ref(start_commit, "start_commit")
    end = _validate_commit_ref(end_commit, "end_commit")

    argv = ["git", "--no-pager", "diff", "--no-ext-diff", "--no-textconv", start, end, "--"]
    try:
        result = subprocess.run(
            argv, cwd=repo_path, shell=False, capture_output=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise DiffUnavailable("DIFF_TIMEOUT", "git diff timed out") from e
    except FileNotFoundError as e:
        raise DiffUnavailable("DIFF_GIT_NOT_FOUND", "git executable not found") from e

    if result.returncode != 0:
        raise DiffUnavailable("DIFF_FAILED", "git diff exited with a non-zero status")

    raw = result.stdout
    truncated = len(raw) > MAX_DIFF_BYTES
    body = raw[:MAX_DIFF_BYTES]
    text = body.decode("utf-8", errors="replace")
    return {"diff": text, "truncated": truncated, "sizeBytes": len(raw)}
