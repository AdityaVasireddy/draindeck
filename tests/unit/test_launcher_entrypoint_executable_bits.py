"""Repository-level verification for docs/32 review Blocker 5: the POSIX
entry points (.command, .sh) must be tracked as executable (git index mode
100755), not merely documented as skipped.

This repository has `core.fileMode=false` (confirmed via
``git config core.fileMode``), so git does NOT auto-capture a filesystem
executable bit on `git add` regardless of host OS -- the bit must be set
explicitly with `git update-index --chmod=+x <path>`, which the bounded
review item for this fix explicitly authorized and this session applied:

    git add Start-DraindeckDashboard.command start-draindeck-dashboard.sh
    git update-index --chmod=+x Start-DraindeckDashboard.command start-draindeck-dashboard.sh

Windows cannot represent a real POSIX executable bit on NTFS at all
(verified: os.chmod() with S_IEXEC set is silently a no-op on this host's
filesystem) -- the filesystem-level check below is skipped there, and the
git-index check is the authoritative, platform-independent one.
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_POSIX_ENTRY_POINTS = ("Start-DraindeckDashboard.command", "start-draindeck-dashboard.sh")


def _git_tracked_mode(relpath: str) -> str | None:
    result = subprocess.run(
        ["git", "ls-files", "-s", relpath], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    if not result.stdout.strip():
        return None
    return result.stdout.split()[0]  # e.g. "100755" or "100644"


@pytest.mark.parametrize("relpath", _POSIX_ENTRY_POINTS)
def test_posix_entry_point_is_executable_in_the_git_index(relpath):
    """The authoritative, platform-independent check: what mode git will
    actually check out on any machine that clones this repo."""
    mode = _git_tracked_mode(relpath)
    assert mode == "100755", (
        f"{relpath} must be tracked with mode 100755 (executable), got {mode!r}. "
        f"Fix: git add {relpath} && git update-index --chmod=+x {relpath}"
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX exec bits are not representable on Windows/NTFS")
@pytest.mark.parametrize("relpath", _POSIX_ENTRY_POINTS)
def test_posix_entry_point_has_the_filesystem_executable_bit(relpath):
    """On a real POSIX host, the working-tree file itself should also be
    directly executable (so `./start-draindeck-dashboard.sh` works without
    a manual chmod first)."""
    mode = (REPO_ROOT / relpath).stat().st_mode
    assert mode & stat.S_IXUSR, f"{relpath} is missing the owner-executable bit; run: chmod +x {relpath}"
