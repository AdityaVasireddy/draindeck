"""Artifact containment (docs/19 "Artifacts and diffs").

Route this backs: ``GET /api/repositories/{repo_id}/executions/{execution_id}/transcript``
(defined in app.py, wired before Phase 6 implementation per the explicit
gate requirement).

Artifact root is ``<resolved log parent>/artifacts`` — the SAME location
``runtime.main``'s ``_open_startup_recovery`` already computes
(``artifacts_dir = log_path.parent / "artifacts"``) and that
``runtime.engine.claude_headless`` / ``runtime.validation.runner`` write
transcripts and validation logs under. Dashboard never hardcodes
``.draindeck/state/artifacts``.

Containment is enforced by resolving BOTH the root and the candidate to
their FINAL filesystem paths before comparing. ``Path.resolve()`` on
Windows normalizes symlinks, NTFS junctions, AND 8.3 short names to the
same canonical long-form path — verified empirically against a real
junction and a real 8.3 alias, not assumed — so a stored path cannot
escape containment through any of those three redirection mechanisms.
"""
from __future__ import annotations

from pathlib import Path

from .errors import DashboardApiError


class ArtifactPathInvalid(DashboardApiError):
    status_code = 400

    def __init__(self, message: str, **kw) -> None:
        super().__init__("ARTIFACT_PATH_INVALID", message, **kw)


class ArtifactOutsideRoot(DashboardApiError):
    status_code = 403

    def __init__(self, message: str = "artifact path is outside the artifact root", **kw) -> None:
        super().__init__("ARTIFACT_OUTSIDE_ROOT", message, **kw)


class ArtifactNotFound(DashboardApiError):
    status_code = 404

    def __init__(self, message: str = "artifact not found", **kw) -> None:
        super().__init__("ARTIFACT_NOT_FOUND", message, **kw)


def artifact_root_for_log(log_path: str) -> Path:
    """``<resolved log parent>/artifacts``, itself already canonicalized
    so the root is never compared against in a stale/unresolved form."""
    return (Path(log_path).parent / "artifacts").resolve()


def resolve_contained_artifact(root: Path, stored_path: str) -> Path:
    """Validates `stored_path` (as found in an evidence payload, e.g.
    ``ExecutionFinished.payload.transcript_path``) against `root`
    (`artifact_root_for_log`'s result).

    Raises `ArtifactPathInvalid` (400) for a non-absolute stored path —
    rejected safely, never crashes; `ArtifactOutsideRoot` (403) if the
    canonicalized candidate escapes root (via a symlink, junction, 8.3
    alias, or plain `..` traversal); `ArtifactNotFound` (404) if it is
    contained but missing, or not a regular file, on disk. Returns the
    resolved, contained, absolute path on success.
    """
    candidate = Path(stored_path)
    if not candidate.is_absolute():
        raise ArtifactPathInvalid(
            f"stored artifact path must be absolute, got {stored_path!r}")

    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ArtifactOutsideRoot() from None

    if not resolved.is_file():
        raise ArtifactNotFound()
    return resolved
