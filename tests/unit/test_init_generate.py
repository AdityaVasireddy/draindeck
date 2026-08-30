"""Config-generation tests for `draindeck init` (doc 16 §4 step 6, tasks/
plan.md Unit 4). Every generated config must round-trip through the real
`load_config()` — this is the acceptance criterion "byte-identical in
schema to what the engine already parses" made concrete.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import load_config  # noqa: E402
from runtime.init import generate as generate_module  # noqa: E402
from runtime.init.detect import CommandProposal, DetectionRow  # noqa: E402
from runtime.init.generate import (  # noqa: E402
    _REVIEWER_MODEL,
    render_config,
    write_config,
)

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


# --- reviewer.model: full canonical tag, not the bare/incomplete placeholder ---


def test_reviewer_model_is_full_canonical_tag(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="5" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    # the tag survives YAML rendering/load_config round-trip unchanged
    assert cfg.reviewer.qwen.model == "qwen2.5-coder:14b"
    assert cfg.reviewer.qwen.model == _REVIEWER_MODEL


def test_reviewer_model_tag_is_not_silently_stripped_in_generated_text(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="6" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
    )
    assert "model: qwen2.5-coder:14b" in text
    # the old, incomplete `qwen2.5-coder` (no :14b suffix) must not appear
    # as the value of reviewer.qwen.model any more
    assert not re.search(r"^\s*model: qwen2\.5-coder\s*(#.*)?$", text, re.MULTILINE)


def test_reviewer_provider_and_endpoint_unchanged(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="7" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.reviewer.provider == "qwen"
    assert cfg.reviewer.qwen.endpoint == "http://localhost:11434"


# --- billing.verified_on: real deterministic date, not "TODO: confirm" ---


def test_billing_verified_on_uses_injected_date_no_placeholder(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    frozen = date(2026, 1, 5)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="8" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
        today=lambda: frozen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.billing.verified_on == "2026-01-05"
    assert cfg.billing.verified_on != "TODO: confirm"


def test_billing_verified_on_matches_yyyy_mm_dd_format(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    frozen = date(2026, 12, 31)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="9" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
        today=lambda: frozen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", cfg.billing.verified_on)


def test_billing_verified_on_defaults_to_real_today_without_injection(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="a" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.billing.verified_on == date.today().isoformat()


def test_billing_posture_and_reverify_at_unchanged(tmp_path: Path):
    chosen = CommandProposal(commands=["make test"], install_command=None)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="b" * 40,
        all_matches=[], chosen_stack="manual", chosen=chosen,
        today=lambda: date(2026, 2, 2),
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)
    assert cfg.billing.posture == "pro_subscription_headless"
    assert cfg.billing.headless_split_status == "paused"
    assert cfg.billing.reverify_at == "phase-2-gate"


# --- combined regression: both fixes together on a normal init-generated config ---


def test_normal_init_config_has_real_reviewer_model_and_billing_metadata(tmp_path: Path):
    chosen = CommandProposal(
        commands=[r'C:\envs\proj\Scripts\python.exe -m pytest'],
        install_command=None,
        needs_rule2_confirm=True,
    )
    frozen = date(2026, 3, 1)
    text = render_config(
        repo_path=tmp_path, branch="agent-work", branch_tip="c" * 40,
        all_matches=[_PY_ROW], chosen_stack="Python", chosen=chosen,
        today=lambda: frozen,
    )
    dest = tmp_path / "config.local.yaml"
    write_config(dest, text)
    cfg = load_config(dest)  # must still load cleanly
    assert cfg.reviewer.qwen.model == "qwen2.5-coder:14b"
    assert cfg.billing.verified_on == "2026-03-01"
    assert cfg.billing.verified_on != "TODO: confirm"


# ── ADR-29 outcome matrix: atomic publication crash-window predictions ──
# write_config is the sole config writer (runtime.init.service.publisher
# default). These prove each predicted failure window leaves the exact
# destination state the outcome matrix commits to -- never a truncated or
# falsely-published file.

def test_write_config_temp_creation_failure_leaves_destination_absent(tmp_path: Path, monkeypatch):
    dest = tmp_path / "sub" / "config.local.yaml"

    def _boom(*a, **kw):
        raise OSError("simulated: cannot create temp file")

    monkeypatch.setattr(generate_module.tempfile, "mkstemp", _boom)

    with pytest.raises(OSError):
        write_config(dest, "project: {}\n")

    assert not dest.exists()
    assert list(dest.parent.glob("*")) == []  # no orphaned temp artifact


def test_write_config_temp_fsync_failure_leaves_old_destination_and_cleans_temp(
    tmp_path: Path, monkeypatch,
):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("old bytes\n", encoding="utf-8")

    def _boom(fd):
        raise OSError("simulated: fsync failed")

    monkeypatch.setattr(generate_module.os, "fsync", _boom)

    with pytest.raises(OSError):
        write_config(dest, "new bytes\n")

    assert dest.read_text(encoding="utf-8") == "old bytes\n"
    leftovers = [p for p in dest.parent.glob("*") if p != dest]
    assert leftovers == []  # temp artifact cleaned up


def test_write_config_replace_failure_leaves_old_destination_and_cleans_temp(
    tmp_path: Path, monkeypatch,
):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("old bytes\n", encoding="utf-8")

    def _boom(src, dst):
        raise OSError("simulated: replace failed")

    monkeypatch.setattr(generate_module.os, "replace", _boom)

    with pytest.raises(OSError):
        write_config(dest, "new bytes\n")

    assert dest.read_text(encoding="utf-8") == "old bytes\n"
    leftovers = [p for p in dest.parent.glob("*") if p != dest]
    assert leftovers == []  # temp artifact cleaned up, not left as residue


def test_write_config_post_replace_fsync_failure_still_leaves_new_bytes_published(
    tmp_path: Path, monkeypatch,
):
    """Outcome matrix: 'Post-replace final-file fsync fails -> Return
    CONFIG_PUBLICATION_FAILED [caller's typed wrapping]; ... next preview
    reports actual bytes/digest.' The replace already happened -- the new
    bytes are genuinely on disk even though durability confirmation failed."""
    dest = tmp_path / "config.local.yaml"
    dest.write_text("old bytes\n", encoding="utf-8")
    real_fsync = os.fsync
    calls = {"n": 0}

    def _fail_second_call(fd):
        calls["n"] += 1
        if calls["n"] >= 2:  # first call is the temp-file fsync; let it pass
            raise OSError("simulated: post-replace fsync failed")
        return real_fsync(fd)

    monkeypatch.setattr(generate_module.os, "fsync", _fail_second_call)

    with pytest.raises(OSError):
        write_config(dest, "new bytes\n")

    assert dest.read_text(encoding="utf-8") == "new bytes\n"


def test_write_config_parent_directory_fsync_unavailable_still_publishes_and_fsyncs_file(
    tmp_path: Path, monkeypatch,
):
    """Outcome matrix: 'Parent directory fsync unsupported -> Final-file
    fsync remains required; platform limitation is recorded, not silently
    replaced with weaker in-place writing.' Simulates the always-true-on-
    Windows case explicitly, so the guarantee is proven regardless of the
    platform running this test."""
    dest = tmp_path / "config.local.yaml"
    real_fsync = os.fsync
    real_open = os.open
    fsync_calls = []

    def _tracking_fsync(fd):
        fsync_calls.append(fd)
        return real_fsync(fd)

    def _boom_only_for_directory(path, flags, *a, **kw):
        # tempfile.mkstemp shares this same os.open under the hood -- only
        # refuse the specific directory-fsync call write_config makes, or
        # every other call (temp-file creation) would break too.
        if os.path.abspath(path) == os.path.abspath(dest.parent) and flags == os.O_RDONLY:
            raise OSError("simulated: platform cannot open a directory this way")
        return real_open(path, flags, *a, **kw)

    monkeypatch.setattr(generate_module.os, "fsync", _tracking_fsync)
    monkeypatch.setattr(generate_module.os, "open", _boom_only_for_directory)

    write_config(dest, "new bytes\n")  # must not raise

    assert dest.read_text(encoding="utf-8") == "new bytes\n"
    assert len(fsync_calls) == 2  # temp-file fsync + final-file fsync, both real
