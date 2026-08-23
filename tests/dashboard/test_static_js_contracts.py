"""Unit 7+ (docs/27 SS13.3): drives the plain-Node unit tests for
static/js's pure functions as subprocesses -- "the current lightweight
test approach", no new production dependency (no Jest/Vitest/npm
install). Each `tests/dashboard/js/test_*.mjs` file is self-contained and
asserts internally; a non-zero exit code fails this pytest wrapper with
the real Node stdout/stderr attached for diagnosis.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_JS_TEST_DIR = Path(__file__).parent / "js"
_REPO_ROOT = Path(__file__).parents[2]


def _node_test_files() -> list[Path]:
    if not _JS_TEST_DIR.exists():
        return []
    return sorted(_JS_TEST_DIR.glob("test_*.mjs"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("js_test_file", _node_test_files(), ids=lambda p: p.name)
def test_node_js_contract(js_test_file: Path) -> None:
    result = subprocess.run(
        ["node", str(js_test_file)], cwd=str(_REPO_ROOT),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"{js_test_file.name} failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
