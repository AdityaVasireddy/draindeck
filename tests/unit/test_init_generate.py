"""Config-generation tests for `draindeck init` (doc 16 §4 step 6, tasks/
plan.md Unit 4). Every generated config must round-trip through the real
`load_config()` — this is the acceptance criterion "byte-identical in
schema to what the engine already parses" made concrete.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import load_config  # noqa: E402
from runtime.init.detect import CommandProposal, DetectionRow  # noqa: E402
from runtime.init.generate import render_config, write_config  # noqa: E402

_PY_ROW = DetectionRow("Python", lambda p: True, lambda p: None)
_RUST_ROW = DetectionRow("Rust", lambda p: True, lambda p: None)


def test_python_row_config_round_trips(tmp_path: Path):
    chosen = CommandProposal(
        commands=[r'C:\envs\proj\Scripts\python.exe -m pytest'],
        install_command=r'C:\envs\proj\Scripts\python.exe -m pip install -r requirements.txt',
        needs_rule2_confirm=True,
    )
    text = render_config(
        repo_path=tmp_path,
        branch="agent-work",
        branch_tip="a" * 40,
        all_matches=[_PY_ROW],
        chosen_stack="Python",
        chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.validation.commands == chosen.commands
    assert "# TODO" in text
    assert "ADR-23 rule 2" in text


def test_static_web_multi_command_config_round_trips(tmp_path: Path):
    chosen = CommandProposal(
        commands=['node --check "app.js"', 'node --check "sub/widget.js"'],
        install_command=None,
    )
    text = render_config(
        repo_path=tmp_path,
        branch="agent-work",
        branch_tip="b" * 40,
        all_matches=[DetectionRow("Static web", lambda p: True, lambda p: None)],
        chosen_stack="Static web",
        chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.validation.commands == chosen.commands


def test_manually_entered_command_config_round_trips(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path,
        branch="agent-work",
        branch_tip="c" * 40,
        all_matches=[],
        chosen_stack="manual",
        chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.validation.commands == ["make test"]


def test_quoting_windows_interpreter_path_with_space(tmp_path: Path):
    interp = r'C:\Program Files\Python312\python.exe'
    command = f'& "{interp}" -m pytest'
    chosen = CommandProposal(commands=[command], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="d" * 40,
        all_matches=[], chosen_stack="Python", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.validation.commands[0] == command
    # the whole document must still parse as ONE document (regression
    # test for the yaml.safe_dump "..." document-end-marker bug found
    # during this build — a naive bare-scalar dump would have corrupted
    # this structure for any value not requiring quotes)
    assert text.count("...") == 0


def test_quoting_repo_path_with_space(tmp_path: Path):
    repo = tmp_path / "a b" / "repo with spaces"
    repo.mkdir(parents=True)
    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    text = render_config(
        repo_path=repo, branch="agent-work", branch_tip="e" * 40,
        all_matches=[_RUST_ROW], chosen_stack="Rust", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.repository == str(repo)


def test_quoting_js_filename_with_space(tmp_path: Path):
    command = 'node --check "my file.js"'
    chosen = CommandProposal(commands=[command], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="f" * 40,
        all_matches=[], chosen_stack="Static web", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.project.validation.commands[0] == command


def test_other_matches_comment_block_present_for_multi_stack(tmp_path: Path):
    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="1" * 40,
        all_matches=[_RUST_ROW, DetectionRow("Node (test)", lambda p: True, lambda p: None)],
        chosen_stack="Rust", chosen=chosen,
    )
    assert "Also detected: Node (test)" in text


def test_no_extra_schema_keys_beyond_what_config_accepts(tmp_path: Path):
    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="2" * 40,
        all_matches=[_RUST_ROW], chosen_stack="Rust", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    # Config's _Frozen base has extra="forbid" — load_config() would
    # already raise on an unrecognized key; succeeding here is the proof.
    load_config(dest)


def test_write_config_writes_exact_text(tmp_path: Path):
    dest = tmp_path / "config.local.yaml"
    write_config(dest, "hello: world\n")
    assert dest.read_text(encoding="utf-8") == "hello: world\n"
