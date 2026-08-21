"""Phase 6 acceptance: derived Git diff safety (docs/19 "Artifacts and
diffs") -- invalid-commit rejection, external-diff/textconv neutralization
(verified against a REAL configured driver, with a vacuity check proving
the fixture can actually detect the vulnerability), and the size cap.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from draindeck_dashboard.diffs import (
    DiffInvalidCommit,
    DiffUnavailable,
    compute_diff,
)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_diff_between_two_real_commits(tmp_path):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "original content\n", "first")
    c2 = _commit(repo, "file.txt", "changed content\n", "second")

    result = compute_diff(str(repo), c1, c2)

    assert "-original content" in result["diff"]
    assert "+changed content" in result["diff"]
    assert result["truncated"] is False


@pytest.mark.parametrize("bad_ref", [
    "not-a-hash", "--upload-pack=/bin/sh", "", "g" * 10, "a" * 41, "../../etc/passwd",
])
def test_invalid_commit_ref_is_rejected(tmp_path, bad_ref):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "a\n", "first")
    with pytest.raises(DiffInvalidCommit):
        compute_diff(str(repo), bad_ref, c1)
    with pytest.raises(DiffInvalidCommit):
        compute_diff(str(repo), c1, bad_ref)


def test_nonexistent_but_hex_shaped_commit_maps_to_diff_unavailable(tmp_path):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "a\n", "first")
    with pytest.raises(DiffUnavailable):
        compute_diff(str(repo), c1, "deadbeef")


def test_output_is_capped_and_flagged_truncated(tmp_path, monkeypatch):
    import draindeck_dashboard.diffs as diffs_module
    monkeypatch.setattr(diffs_module, "MAX_DIFF_BYTES", 20)

    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "a\n" * 5, "first")
    c2 = _commit(repo, "file.txt", "b\n" * 500, "second")

    result = compute_diff(str(repo), c1, c2)
    assert result["truncated"] is True
    assert len(result["diff"].encode("utf-8", errors="replace")) <= 20
    assert result["sizeBytes"] > 20


def test_no_ext_diff_and_no_textconv_neutralize_a_configured_driver(tmp_path):
    """A real diff driver is configured (as `.gitattributes` + a repo-local
    command would let a malicious/compromised target repo do) and must
    NEVER execute when Dashboard computes a diff."""
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "original content\n", "first")

    (repo / ".gitattributes").write_text("file.txt diff=fake\n")
    subprocess.run(["git", "add", ".gitattributes"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "attributes"], cwd=repo, check=True)

    marker = repo / "EXTERNAL_DRIVER_RAN"
    script = repo / "fake-diff.sh"
    script.write_text(f'#!/bin/sh\ntouch "{marker.as_posix()}"\necho EXTERNAL_DIFF_OUTPUT\n')
    script.chmod(0o755)
    subprocess.run(["git", "config", "diff.fake.command", script.as_posix()], cwd=repo, check=True)
    subprocess.run(["git", "config", "diff.fake.textconv", script.as_posix()], cwd=repo, check=True)

    c2 = _commit(repo, "file.txt", "changed content\n", "second")

    # Vacuity check FIRST: prove this fixture can actually detect the
    # vulnerability if our safety flags were absent -- otherwise a
    # negative result below would be meaningless.
    unsafe = subprocess.run(["git", "diff", c1, c2], cwd=repo, capture_output=True, text=True)
    assert marker.exists(), "fixture is not exercising the external driver -- test is vacuous"
    assert "EXTERNAL_DIFF_OUTPUT" in unsafe.stdout
    marker.unlink()

    result = compute_diff(str(repo), c1, c2)

    assert not marker.exists(), "the external diff driver executed despite --no-ext-diff"
    assert "EXTERNAL_DIFF_OUTPUT" not in result["diff"]
    assert "-original content" in result["diff"] or "+changed content" in result["diff"]


def test_diff_invocation_never_uses_a_shell(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    c1 = _commit(repo, "file.txt", "a\n", "first")
    c2 = _commit(repo, "file.txt", "b\n", "second")

    calls = {}
    real_run = subprocess.run

    def spy(argv, **kwargs):
        calls["shell"] = kwargs.get("shell")
        calls["argv"] = argv
        return real_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy)
    compute_diff(str(repo), c1, c2)

    assert calls["shell"] is False
    assert isinstance(calls["argv"], list)
    assert "--no-pager" in calls["argv"]
    assert "--no-ext-diff" in calls["argv"]
    assert "--no-textconv" in calls["argv"]
