"""Stack-detection tests for `draindeck init` (doc 16 §5, tasks/plan.md
Units 1-3). Pure, read-only functions over `pathlib` — no git, no
network, no disk writes beyond what `tmp_path` fixtures create for test
setup.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import runtime.init.detect as detect  # noqa: E402
from runtime.init.detect import (  # noqa: E402
    TABLE,
    CommandProposal,
    DetectionRow,
    build_command,
    detect_stacks,
    enumerate_js_files,
    resolve_interpreter,
)


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── simple rows (Rust / Node / React / Go) ─────────────────────────────
def test_rust_row_detected_and_proposes_cargo(tmp_path: Path):
    _write(tmp_path / "Cargo.toml", "[package]\nname='x'\n")
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Rust"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["cargo test"]
    assert proposal.install_command == "cargo fetch"


def test_node_test_row_detected_and_proposes_npm_test(tmp_path: Path):
    _write(tmp_path / "package.json", '{"scripts": {"test": "jest"}}')
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Node (test)"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["npm test"]
    assert proposal.install_command == "npm install"


def test_node_lint_row_when_lint_but_no_test_script(tmp_path: Path):
    _write(tmp_path / "package.json", '{"scripts": {"lint": "eslint ."}}')
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Node (lint)"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["npm run lint"]
    assert proposal.install_command == "npm install"


def test_react_row_when_react_dep_and_no_test_or_lint_script(tmp_path: Path):
    _write(
        tmp_path / "package.json",
        '{"dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"}}',
    )
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["React"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["npm run build"]
    assert proposal.install_command == "npm install"


def test_go_row_detected_and_proposes_go_test(tmp_path: Path):
    _write(tmp_path / "go.mod", "module x\n")
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Go"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["go test ./..."]
    assert proposal.install_command == "go mod download"


def test_malformed_package_json_does_not_crash_detection(tmp_path: Path):
    _write(tmp_path / "package.json", "{not valid json")
    matches = detect_stacks(tmp_path)
    assert matches == []


def test_no_marker_matches_nothing(tmp_path: Path):
    assert detect_stacks(tmp_path) == []


# ── multi-match ordering ────────────────────────────────────────────────
def test_multi_match_python_and_node_both_recorded_in_priority_order(tmp_path: Path):
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    _write(tmp_path / "package.json", '{"scripts": {"test": "jest"}}')
    # give the Python row a resolvable interpreter so it's a full match
    (tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
    interp = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    interp.write_text("", encoding="utf-8")

    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Python", "Node (test)"]


# ── "add a stack is one row" property, proven not asserted ─────────────
def test_adding_a_throwaway_row_needs_no_change_to_detect_or_build(tmp_path: Path):
    _write(tmp_path / "SENTINEL.marker", "")
    fake_row = DetectionRow(
        stack="Fake",
        matches=lambda repo: (repo / "SENTINEL.marker").exists(),
        build=lambda repo: CommandProposal(commands=["fake test"], install_command=None),
    )
    table_copy = list(TABLE) + [fake_row]

    matches = detect_stacks(tmp_path, table=table_copy)
    assert [m.stack for m in matches] == ["Fake"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal.commands == ["fake test"]

    # the real module table is untouched by the copy
    assert fake_row not in TABLE


def test_table_install_commands_match_spec_table():
    by_stack = {row.stack: row for row in TABLE}
    assert set(by_stack) == {
        "Python", "Rust", "Node (test)", "Node (lint)", "React", "Go", "Static web",
    }


# ── Unit 2: Python interpreter resolution ───────────────────────────────
def test_resolve_interpreter_prefers_venv(tmp_path: Path):
    venv_dir = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv_dir.mkdir(parents=True)
    interp = venv_dir / ("python.exe" if os.name == "nt" else "python")
    interp.write_text("", encoding="utf-8")

    found = resolve_interpreter(tmp_path)
    assert found == interp.resolve()


def test_resolve_interpreter_falls_back_to_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "runtime.init.detect.shutil.which",
        lambda name: r"C:\Fake\python.exe" if os.name == "nt" else "/usr/bin/python3",
    )
    found = resolve_interpreter(tmp_path)
    assert found is not None
    assert found.is_absolute()


def test_resolve_interpreter_returns_none_when_nothing_found(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("runtime.init.detect.shutil.which", lambda name: None)
    assert resolve_interpreter(tmp_path) is None


def test_python_row_build_returns_none_without_interpreter(tmp_path: Path, monkeypatch):
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")
    monkeypatch.setattr("runtime.init.detect.shutil.which", lambda name: None)
    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Python"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal is None


def test_python_row_build_produces_absolute_interpreter_and_install(tmp_path: Path):
    venv_dir = tmp_path / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    venv_dir.mkdir(parents=True)
    interp = venv_dir / ("python.exe" if os.name == "nt" else "python")
    interp.write_text("", encoding="utf-8")
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")

    matches = detect_stacks(tmp_path)
    proposal = build_command(matches[0], tmp_path)
    assert proposal is not None
    assert str(interp.resolve()) in proposal.commands[0]
    assert "-m pytest" in proposal.commands[0]
    assert "-m pip install -r requirements.txt" in proposal.install_command
    assert proposal.needs_rule2_confirm is True
    # never a bare `python` invocation (ADR-23 rule 1)
    assert not proposal.commands[0].startswith("python ")


# ── Unit 3: static-web JS enumeration ────────────────────────────────────
def test_enumerate_js_files_finds_and_excludes(tmp_path: Path):
    _write(tmp_path / "app.js", "")
    _write(tmp_path / "sub" / "widget.js", "")
    _write(tmp_path / ".git" / "hooks" / "ignored.js", "")
    _write(tmp_path / "node_modules" / "pkg" / "vendored.js", "")
    _write(tmp_path / "dist" / "bundle.js", "")

    files = enumerate_js_files(tmp_path)
    rel = sorted(f.relative_to(tmp_path).as_posix() for f in files)
    assert rel == ["app.js", "sub/widget.js"]


def test_enumerate_js_files_handles_space_in_filename(tmp_path: Path):
    _write(tmp_path / "my file.js", "")
    files = enumerate_js_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "my file.js"


def test_static_web_row_matches_and_proposes_one_command_per_file(tmp_path: Path):
    _write(tmp_path / "index.html", "<html></html>")
    _write(tmp_path / "app.js", "")
    _write(tmp_path / "widget.js", "")

    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Static web"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal is not None
    assert len(proposal.commands) == 2
    assert all(c.startswith('node --check "') for c in proposal.commands)
    assert proposal.install_command is None


def test_static_web_row_matches_but_zero_survivors_after_exclusion_returns_none(
    tmp_path: Path,
):
    _write(tmp_path / "index.html", "<html></html>")
    _write(tmp_path / "node_modules" / "pkg" / "vendored.js", "")

    matches = detect_stacks(tmp_path)
    assert [m.stack for m in matches] == ["Static web"]
    proposal = build_command(matches[0], tmp_path)
    assert proposal is None


def test_static_web_not_matched_when_package_json_present(tmp_path: Path):
    _write(tmp_path / "index.html", "<html></html>")
    _write(tmp_path / "app.js", "")
    _write(tmp_path / "package.json", "{}")
    assert detect_stacks(tmp_path) == []


# ── Windows PowerShell invocation regression test ───────────────────────
def test_invocable_uses_powershell_call_operator_for_path_with_spaces(monkeypatch):
    """Regression test for a real bug found during the build: PowerShell
    rejects a bare leading quoted path as an invocable command —
    `"C:\\a b\\python.exe" -m pytest` is a parser error there (verified
    empirically against a real PowerShell process during the build
    session; not re-spawned here). The call-operator form
    `& "C:\\a b\\python.exe" -m pytest` is required and is what
    `_invocable` must produce whenever Windows invocation semantics are
    selected — forced here via the module's platform constant rather
    than relying on the host OS, so this test is deterministic on any
    CI host."""
    monkeypatch.setattr(detect, "_IS_WINDOWS", True)
    interpreter = Path(r"C:\Program Files\Python312\python.exe")

    result = detect._invocable(interpreter)

    assert result == f'& "{interpreter}"'
    assert result.startswith('& "'), (
        "PowerShell requires the call operator to invoke a quoted "
        "leading path; a bare quoted path is a parser error there"
    )


def test_python_row_command_uses_call_operator_on_windows(tmp_path: Path, monkeypatch):
    """The same regression, exercised through the actual Python-row
    command construction path (`_build_python`), not just the helper in
    isolation."""
    monkeypatch.setattr(detect, "_IS_WINDOWS", True)
    venv_dir = tmp_path / ".venv" / "Scripts"
    venv_dir.mkdir(parents=True)
    interp = venv_dir / "python.exe"
    interp.write_text("", encoding="utf-8")
    _write(tmp_path / "pyproject.toml", "[project]\nname='x'\n")

    proposal = detect._build_python(tmp_path)

    assert proposal is not None
    assert proposal.commands[0].startswith('& "')
    assert proposal.install_command.startswith('& "')
