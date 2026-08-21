"""Phase 6 acceptance: artifact root resolution and containment
(docs/19 "Artifacts and diffs") -- relative-path rejection,
traversal/junction/8.3-alias escape detection, outside-root=403,
contained-missing=404.

Junctions and 8.3 short names are created for REAL on disk (not mocked)
so this proves Path.resolve()'s actual behavior on this filesystem, the
same empirical verification done manually before writing this module.
"""
from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path

import pytest

from draindeck_dashboard.artifacts import (
    ArtifactNotFound,
    ArtifactOutsideRoot,
    ArtifactPathInvalid,
    artifact_root_for_log,
    resolve_contained_artifact,
)


def _make_junction(link: Path, target: Path) -> None:
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                   check=True, capture_output=True)


def _short_path(path: Path) -> Path:
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 260)  # type: ignore[attr-defined]
    return Path(buf.value)


def test_artifact_root_matches_runtime_main_convention(tmp_path):
    log_path = tmp_path / "state" / "events.jsonl"
    log_path.parent.mkdir(parents=True)
    root = artifact_root_for_log(str(log_path))
    assert root == (log_path.parent / "artifacts").resolve()


def test_non_absolute_stored_path_is_rejected_safely(tmp_path):
    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactPathInvalid):
        resolve_contained_artifact(root, "relative/transcript.jsonl")


def test_contained_and_present_file_resolves(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    transcript = artifacts_dir / "1-e1" / "transcript.jsonl"
    transcript.parent.mkdir()
    transcript.write_text("hello")

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    resolved = resolve_contained_artifact(root, str(transcript))
    assert resolved == transcript.resolve()


def test_contained_but_missing_is_404(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    missing = artifacts_dir / "1-e1" / "transcript.jsonl"

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactNotFound):
        resolve_contained_artifact(root, str(missing))


def test_plain_traversal_outside_root_is_403(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    traversal_path = artifacts_dir / ".." / "outside.txt"

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactOutsideRoot):
        resolve_contained_artifact(root, str(traversal_path))


def test_junction_escape_is_detected_even_when_missing(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    real_outside = tmp_path / "real-outside"
    real_outside.mkdir()

    junction = artifacts_dir / "escape-link"
    _make_junction(junction, real_outside)

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    # Even a path segment through the junction that doesn't exist on disk
    # must still be caught as an escape, not silently 404'd.
    with pytest.raises(ArtifactOutsideRoot):
        resolve_contained_artifact(root, str(junction / "does-not-exist.txt"))


def test_junction_escape_to_a_real_file_is_403_not_served(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    real_outside = tmp_path / "real-outside"
    real_outside.mkdir()
    secret = real_outside / "secret.txt"
    secret.write_text("do not serve this")

    junction = artifacts_dir / "escape-link"
    _make_junction(junction, real_outside)

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactOutsideRoot):
        resolve_contained_artifact(root, str(junction / "secret.txt"))


def test_eight_dot_three_alias_still_resolves_to_true_long_path(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    long_named = artifacts_dir / "A Long Execution Directory Name"
    long_named.mkdir(parents=True)
    transcript = long_named / "transcript.jsonl"
    transcript.write_text("hello")

    short_form = _short_path(long_named) / "transcript.jsonl"
    if "~" not in str(short_form):
        pytest.skip("filesystem did not generate an 8.3 short name for this directory")

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    resolved = resolve_contained_artifact(root, str(short_form))
    assert resolved == transcript.resolve()


def test_eight_dot_three_alias_cannot_be_used_to_escape_root(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    real_outside_long = tmp_path / "A Long Outside Directory Name"
    real_outside_long.mkdir()
    secret = real_outside_long / "secret.txt"
    secret.write_text("do not serve this")

    short_form = _short_path(real_outside_long) / "secret.txt"
    if "~" not in str(short_form):
        pytest.skip("filesystem did not generate an 8.3 short name for this directory")

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactOutsideRoot):
        resolve_contained_artifact(root, str(short_form))


def test_directory_stored_as_transcript_path_is_not_found_not_served(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    a_directory = artifacts_dir / "1-e1"
    a_directory.mkdir(parents=True)

    root = artifact_root_for_log(str(tmp_path / "events.jsonl"))
    with pytest.raises(ArtifactNotFound):
        resolve_contained_artifact(root, str(a_directory))
