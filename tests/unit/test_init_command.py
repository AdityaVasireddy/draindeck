"""`command.py` tests for `draindeck init` (doc 16 §4/§4a, tasks/plan.md
Units 5-8). Temp-git-repo fixture mirrors `test_git_adapter.py`'s pattern.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from runtime.config import load_config  # noqa: E402
from runtime.init import command as command_module  # noqa: E402
from runtime.init.command import (  # noqa: E402
    InitAbort,
    cmd_init,
    confirm_and_run_install,
    confirm_detected_command,
    confirm_no_validation,
    resolve_validation_command,
    run_preflight,
    setup_branch,
)
from runtime.init.detect import CommandProposal  # noqa: E402
from runtime.repo.git_adapter import GitCliAdapter  # noqa: E402


def _run(cwd: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"setup git {args} failed: {p.stderr}")
    return p.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A temp repo on branch 'main' with one seed commit."""
    repo_dir = tmp_path / "target"
    repo_dir.mkdir()
    _run(repo_dir, "init", "-b", "main")
    _run(repo_dir, "config", "core.autocrlf", "false")
    (repo_dir / "README").write_text("seed\n")
    _run(repo_dir, "add", "-A")
    _run(repo_dir, "commit", "-m", "seed")
    return repo_dir


@pytest.fixture()
def adapter(repo: Path) -> GitCliAdapter:
    return GitCliAdapter(repo)


# ── Unit 5: preflight ────────────────────────────────────────────────
def test_preflight_rejects_non_git_path(tmp_path: Path):
    with pytest.raises(InitAbort):
        run_preflight(tmp_path / "not-a-repo", tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_dirty_tree(repo: Path, tmp_path: Path):
    (repo / "dirty.txt").write_text("x")
    with pytest.raises(InitAbort):
        run_preflight(repo, tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_existing_config_without_force(repo: Path, tmp_path: Path):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("existing: true\n")
    with pytest.raises(InitAbort):
        run_preflight(repo, dest, force=False)


def test_preflight_proceeds_with_force_over_existing_config(repo: Path, tmp_path: Path):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("existing: true\n")
    adapter = run_preflight(repo, dest, force=True)
    assert adapter.current_commit()


def test_preflight_clean_new_config_dest_proceeds(repo: Path, tmp_path: Path):
    adapter = run_preflight(repo, tmp_path / "config.local.yaml", force=False)
    assert adapter.current_commit()


# ── Unit 5: branch safety — the direct regression test ──────────────
def test_setup_branch_creates_new_branch_at_current_head(adapter: GitCliAdapter):
    head = adapter.current_commit()
    branch, tip = setup_branch(adapter, "agent-work")
    assert branch == "agent-work"
    assert tip == head
    assert adapter.head_of("agent-work") == head


def test_setup_branch_preserves_existing_branch_tip_no_force_reset(
    adapter: GitCliAdapter, repo: Path,
):
    # Create the target branch and advance it past current 'main'.
    adapter.checkout_branch("agent-work", create_from=adapter.current_commit())
    (repo / "extra.txt").write_text("work in progress\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "prior work on agent-work")
    preserved_tip = adapter.current_commit()

    # Back to main (clean), simulating a fresh `init` invocation.
    adapter.checkout_branch("main")

    branch, tip = setup_branch(adapter, "agent-work")

    assert branch == "agent-work"
    assert tip == preserved_tip
    assert adapter.head_of("agent-work") == preserved_tip
    # the extra commit's file must still exist on disk after checkout
    assert (repo / "extra.txt").exists()


# ── Unit 6: manual-validation UX ──────────────────────────────────────
def test_manual_ux_blank_input_cancels_without_retry_loop():
    calls = []

    def input_fn(prompt):
        calls.append(prompt)
        return "   "

    result = resolve_validation_command(
        "no stack detected", yes=False, input_fn=input_fn, print_fn=lambda *_: None,
    )
    assert result is None
    assert len(calls) == 1


def test_manual_ux_decline_then_revise_then_confirm():
    answers = iter(["first attempt", "n", "second attempt", "y"])
    inputs = []

    def input_fn(prompt):
        inputs.append(prompt)
        return next(answers)

    result = resolve_validation_command(
        "no stack detected", yes=False, input_fn=input_fn, print_fn=lambda *_: None,
    )
    assert result == "second attempt"
    assert len(inputs) == 4


def test_manual_ux_confirm_on_first_try():
    answers = iter(["make test", "y"])
    result = resolve_validation_command(
        "no stack detected", yes=False,
        input_fn=lambda p: next(answers), print_fn=lambda *_: None,
    )
    assert result == "make test"


def test_manual_ux_yes_never_calls_input_fn():
    def input_fn(prompt):
        raise AssertionError("input_fn must never be called under yes=True")

    result = resolve_validation_command(
        "no stack detected", yes=True, input_fn=input_fn, print_fn=lambda *_: None,
    )
    assert result is None


# ── detected-command confirmation (doc 16 §4 step 3) ──────────────────
def test_confirm_detected_command_yes_never_prompts():
    def input_fn(prompt):
        raise AssertionError("must not prompt under yes=True")

    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    assert confirm_detected_command(
        "Rust", chosen, yes=True, input_fn=input_fn, print_fn=lambda *_: None,
    ) is True


def test_confirm_detected_command_blank_or_y_accepts():
    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    assert confirm_detected_command(
        "Rust", chosen, yes=False, input_fn=lambda p: "", print_fn=lambda *_: None,
    ) is True
    assert confirm_detected_command(
        "Rust", chosen, yes=False, input_fn=lambda p: "y", print_fn=lambda *_: None,
    ) is True


def test_confirm_detected_command_other_answer_rejects():
    chosen = CommandProposal(commands=["cargo test"], install_command="cargo fetch")
    assert confirm_detected_command(
        "Rust", chosen, yes=False, input_fn=lambda p: "n", print_fn=lambda *_: None,
    ) is False


# ── Unit 7: dependency install trust boundary ──────────────────────────
# Four outcomes, per doc 16 §4 step 4 + the corrective-pass review:
# install is an OPTIONAL convenience, never a gate on initialization.
def test_install_none_proposal_never_prompts_or_runs(tmp_path: Path):
    calls = {"input": 0, "run": 0}
    result = confirm_and_run_install(
        None, repo_path=tmp_path, yes=False,
        input_fn=lambda p: calls.__setitem__("input", calls["input"] + 1) or "y",
        print_fn=lambda *_: None,
        run_fn=lambda cmd, cwd: calls.__setitem__("run", calls["run"] + 1),
    )
    assert result is False
    assert calls == {"input": 0, "run": 0}


def test_install_yes_flag_never_triggers_install(tmp_path: Path):
    """Direct test: `--yes` cannot trigger an install."""
    calls = {"input": 0, "run": 0}
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=True,
        input_fn=lambda p: calls.__setitem__("input", calls["input"] + 1) or "y",
        print_fn=lambda *_: None,
        run_fn=lambda cmd, cwd: calls.__setitem__("run", calls["run"] + 1),
    )
    assert result is False
    assert calls == {"input": 0, "run": 0}


# 1. Decline
def test_install_decline_spawns_nothing_and_warns_nothing(tmp_path: Path):
    """Decline: `run_fn` never called; no failure warning; declining is
    not an error, initialization remains allowed."""
    run_calls = []
    messages = []
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=False,
        input_fn=lambda p: "n", print_fn=messages.append,
        run_fn=lambda cmd, cwd: run_calls.append((cmd, cwd)),
    )
    assert result is False
    assert run_calls == []
    assert not any("WARNING" in m for m in messages)


# 2. Confirmed success
def test_install_confirm_success_invokes_exact_command_no_warning(tmp_path: Path):
    """Confirmed install, exit code 0: `run_fn` called exactly once with
    exactly the proposed command; no failure warning."""
    run_calls = []
    messages = []
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=False,
        input_fn=lambda p: "y", print_fn=messages.append,
        run_fn=lambda cmd, cwd: run_calls.append((cmd, cwd)) or
        subprocess.CompletedProcess(args=[cmd], returncode=0),
    )
    assert result is True
    assert run_calls == [("cargo fetch", tmp_path)]
    assert not any("WARNING" in m for m in messages)


# 3. Confirmed, spawned command exits non-zero
def test_install_confirm_nonzero_warns_with_exit_code_but_does_not_fail(tmp_path: Path):
    """Confirmed install, non-zero exit: `run_fn` called exactly once;
    a prominent warning names the actual exit code and says dependencies
    may not be installed / should be reviewed; no exception escapes; a
    failed OPTIONAL install is not reinterpreted as an init failure."""
    run_calls = []
    messages = []
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=False,
        input_fn=lambda p: "y", print_fn=messages.append,
        run_fn=lambda cmd, cwd: run_calls.append((cmd, cwd)) or
        subprocess.CompletedProcess(args=[cmd], returncode=101),
    )
    assert result is True  # the command DID run — it just failed
    assert run_calls == [("cargo fetch", tmp_path)]
    warning = next((m for m in messages if "WARNING" in m), None)
    assert warning is not None, "expected a prominent warning on non-zero exit"
    assert "101" in warning
    assert "review" in warning.lower()
    assert "may not" in warning.lower() or "not be installed" in warning.lower()


# 4. Launch failure (OSError / FileNotFoundError)
def test_install_launch_failure_warns_and_does_not_raise(tmp_path: Path):
    """Subprocess launch failure: no raw exception escapes; a warning is
    emitted; no fallback command is run; no automatic retry."""
    call_count = {"n": 0}

    def raising_run(cmd, cwd):
        call_count["n"] += 1
        raise FileNotFoundError("powershell.exe not found")

    messages = []
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=False,
        input_fn=lambda p: "y", print_fn=messages.append,
        run_fn=raising_run,
    )
    assert result is False
    assert call_count["n"] == 1  # no retry
    warning = next((m for m in messages if "WARNING" in m), None)
    assert warning is not None
    assert "launch" in warning.lower()
    assert "may not" in warning.lower() or "not be installed" in warning.lower()


def test_install_confirm_invokes_exactly_the_proposed_command(tmp_path: Path):
    """Direct test: explicit confirmation invokes only the proposed
    install command (no other command, no fallback)."""
    run_calls = []
    result = confirm_and_run_install(
        "cargo fetch", repo_path=tmp_path, yes=False,
        input_fn=lambda p: "y", print_fn=lambda *_: None,
        run_fn=lambda cmd, cwd: run_calls.append((cmd, cwd)) or
        subprocess.CompletedProcess(args=[cmd], returncode=0),
    )
    assert result is True
    assert run_calls == [("cargo fetch", tmp_path)]


# ── Unit 8: cmd_init end-to-end ──────────────────────────────────────
class _Args:
    def __init__(self, repo_path, branch="agent-work", yes=False, force=False,
                 no_validation=False, yes_no_validation=False):
        self.repo_path = str(repo_path)
        self.branch = branch
        self.yes = yes
        self.force = force
        self.no_validation = no_validation
        self.yes_no_validation = yes_no_validation


def test_cmd_init_end_to_end_rust_yes(tmp_path: Path, monkeypatch, repo: Path):
    _run(repo, "rm", "README")  # keep the tree minimal
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    install_calls = []

    rc = cmd_init(
        _Args(repo, yes=True),
        run_fn=lambda cmd, cwd: install_calls.append((cmd, cwd)),
    )
    assert rc == 0

    dest = workdir / "config.local.yaml"
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.project.validation.commands == ["cargo test"]
    assert install_calls == []  # --yes must never trigger the install


def test_cmd_init_end_to_end_static_web_with_files(tmp_path: Path, monkeypatch, repo: Path):
    (repo / "index.html").write_text("<html></html>")
    (repo / "app.js").write_text("")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add static site")

    workdir = tmp_path / "cwd2"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 0
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == ['node --check "app.js"']


def test_cmd_init_unknown_stack_yes_refuses_writes_nothing(tmp_path: Path, monkeypatch, repo: Path):
    workdir = tmp_path / "cwd3"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 1
    assert not (workdir / "config.local.yaml").exists()


def test_cmd_init_dirty_tree_refuses(tmp_path: Path, monkeypatch, repo: Path):
    (repo / "dirty.txt").write_text("x")
    workdir = tmp_path / "cwd4"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 1
    assert not (workdir / "config.local.yaml").exists()


def test_cmd_init_non_git_path_refuses(tmp_path: Path, monkeypatch):
    workdir = tmp_path / "cwd5"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(tmp_path / "not-a-repo", yes=True))
    assert rc == 1
    assert not (workdir / "config.local.yaml").exists()


def test_cmd_init_existing_config_without_force_refuses(tmp_path: Path, monkeypatch, repo: Path):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd6"
    workdir.mkdir()
    (workdir / "config.local.yaml").write_text("existing: true\n")
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True, force=False))
    assert rc == 1
    assert (workdir / "config.local.yaml").read_text(encoding="utf-8") == "existing: true\n"


def test_cmd_init_existing_branch_tip_preserved_end_to_end(tmp_path: Path, monkeypatch, repo: Path):
    adapter = GitCliAdapter(repo)
    adapter.checkout_branch("agent-work", create_from=adapter.current_commit())
    (repo / "prior.txt").write_text("prior work\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "prior work on agent-work")
    preserved_tip = adapter.current_commit()
    adapter.checkout_branch("main")

    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd7"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, branch="agent-work", yes=True))
    assert rc == 0
    assert adapter.head_of("agent-work") == preserved_tip


def test_cmd_init_static_web_zero_survivors_falls_into_manual_ux(
    tmp_path: Path, monkeypatch, repo: Path,
):
    (repo / "index.html").write_text("<html></html>")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "vendored.js").write_text("")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "vendored only")

    workdir = tmp_path / "cwd8"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    answers = iter(["node --check index.html", "y"])  # scripted manual entry

    rc = cmd_init(_Args(repo, yes=False), input_fn=lambda prompt: next(answers))
    assert rc == 0
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == ["node --check index.html"]


def test_cmd_init_interactive_install_confirm_invokes_exact_command(
    tmp_path: Path, monkeypatch, repo: Path,
):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd9"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    install_calls = []
    # first prompt: accept detected command ("y"); second: confirm install ("y")
    answers = iter(["y", "y"])

    rc = cmd_init(
        _Args(repo, yes=False),
        input_fn=lambda prompt: next(answers),
        run_fn=lambda cmd, cwd: install_calls.append((cmd, cwd)),
    )
    assert rc == 0
    assert install_calls == [("cargo fetch", Path(repo).resolve())]


def test_cmd_init_interactive_install_nonzero_still_completes(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """A confirmed install that exits non-zero warns but does not turn
    initialization into a failure: the config is still written and
    `cmd_init` still returns 0 when everything else succeeds."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd10"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    messages = []
    answers = iter(["y", "y"])  # accept detected command, confirm install

    rc = cmd_init(
        _Args(repo, yes=False),
        input_fn=lambda prompt: next(answers),
        print_fn=messages.append,
        run_fn=lambda cmd, cwd: subprocess.CompletedProcess(args=[cmd], returncode=1),
    )
    assert rc == 0
    dest = workdir / "config.local.yaml"
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.project.validation.commands == ["cargo test"]
    assert any("WARNING" in m for m in messages)


def test_cmd_init_interactive_install_launch_failure_still_completes(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """A confirmed install that can't even be launched (OSError) warns
    but does not crash `cmd_init` or block initialization: the config is
    still written and `cmd_init` still returns 0."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd11"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    messages = []
    answers = iter(["y", "y"])

    def raising_run(cmd, cwd):
        raise FileNotFoundError("no shell available")

    rc = cmd_init(
        _Args(repo, yes=False),
        input_fn=lambda prompt: next(answers),
        print_fn=messages.append,
        run_fn=raising_run,
    )
    assert rc == 0
    dest = workdir / "config.local.yaml"
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.project.validation.commands == ["cargo test"]
    assert any("WARNING" in m for m in messages)


# ── ADR-24 (doc 08 §5f): confirm_no_validation ──────────────────────────

def test_confirm_no_validation_yes_no_validation_true_never_prompts():
    calls = {"input": 0}
    result = confirm_no_validation(
        yes_no_validation=True,
        input_fn=lambda p: calls.__setitem__("input", calls["input"] + 1) or "y",
    )
    assert result is True
    assert calls == {"input": 0}


def test_confirm_no_validation_interactive_confirm():
    result = confirm_no_validation(yes_no_validation=False, input_fn=lambda p: "y")
    assert result is True


def test_confirm_no_validation_interactive_decline():
    result = confirm_no_validation(yes_no_validation=False, input_fn=lambda p: "n")
    assert result is False


def test_confirm_no_validation_interactive_blank_declines():
    result = confirm_no_validation(yes_no_validation=False, input_fn=lambda p: "")
    assert result is False


# ── ADR-24: cmd_init full --no-validation / --yes / --yes-no-validation
# truth table (doc 17 §2h) ──────────────────────────────────────────────

def test_yes_no_validation_without_no_validation_is_invalid_usage(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Row 6: invalid CLI usage, refused BEFORE any preflight/detection
    work — zero calls to run_preflight/detect_stacks."""
    workdir = tmp_path / "cwd-invalid"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    preflight_calls = []
    detect_calls = []
    monkeypatch.setattr(command_module, "run_preflight",
                         lambda *a, **k: preflight_calls.append((a, k)))
    monkeypatch.setattr(command_module, "detect_stacks",
                         lambda *a, **k: detect_calls.append((a, k)))

    messages = []
    rc = cmd_init(_Args(repo, yes_no_validation=True, no_validation=False),
                   print_fn=messages.append)
    assert rc == 1
    assert preflight_calls == []
    assert detect_calls == []
    assert not (workdir / "config.local.yaml").exists()


def test_no_validation_alone_prompts_and_decline_writes_nothing(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Row 3 decline: dedicated prompt fires; declining aborts non-zero,
    nothing written."""
    workdir = tmp_path / "cwd-decline"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=False, no_validation=True),
                   input_fn=lambda p: "n")
    assert rc == 1
    assert not (workdir / "config.local.yaml").exists()


def test_no_validation_alone_confirm_writes_commands_empty(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Row 3 confirm: commands: [] path taken."""
    workdir = tmp_path / "cwd-confirm"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=False, no_validation=True),
                   input_fn=lambda p: "y")
    assert rc == 0
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []
    assert cfg.project.validation.acknowledged_no_gate is True


def test_yes_and_no_validation_still_prompts(tmp_path: Path, monkeypatch, repo: Path):
    """Row 4: --yes does NOT satisfy the dedicated acknowledgement --
    input_fn IS called."""
    workdir = tmp_path / "cwd-yes-no-validation"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    calls = {"input": 0}

    def input_fn(p):
        calls["input"] += 1
        return "y"

    rc = cmd_init(_Args(repo, yes=True, no_validation=True), input_fn=input_fn)
    assert rc == 0
    assert calls["input"] >= 1
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []


def test_no_validation_and_yes_no_validation_bypasses_prompt(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Row 5: dedicated acknowledgement satisfied non-interactively --
    input_fn never called."""
    workdir = tmp_path / "cwd-bypass"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    calls = {"input": 0}

    def input_fn(p):
        calls["input"] += 1
        return "y"

    rc = cmd_init(_Args(repo, yes=False, no_validation=True, yes_no_validation=True),
                   input_fn=input_fn)
    assert rc == 0
    assert calls == {"input": 0}
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []
    assert cfg.project.validation.acknowledged_no_gate is True


def test_all_three_flags_fully_noninteractive_and_install_still_gated(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Row 6 (fully non-interactive): validation selection is
    non-interactive AND --yes still never authorizes the install (Rust
    row proposes `cargo fetch`; confirm_and_run_install's own --yes gate
    is untouched by any of this)."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-all-three"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    install_calls = []

    def input_fn(p):
        raise AssertionError(f"input_fn must not be called; got prompt: {p!r}")

    rc = cmd_init(
        _Args(repo, yes=True, no_validation=True, yes_no_validation=True),
        input_fn=input_fn,
        run_fn=lambda cmd, cwd: install_calls.append((cmd, cwd)),
    )
    assert rc == 0
    assert install_calls == []
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []
    assert cfg.project.validation.acknowledged_no_gate is True


def test_detected_proposal_with_no_validation_prints_override_note_and_skips_confirm_detected_command(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Detection override semantics (doc 17 §2h): a usable detected
    proposal is NOT sent through confirm_detected_command; a visible NOTE
    names what was overridden."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-override-note"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    confirm_detected_calls = []
    monkeypatch.setattr(
        command_module, "confirm_detected_command",
        lambda *a, **k: confirm_detected_calls.append((a, k)) or True,
    )

    messages = []
    rc = cmd_init(
        _Args(repo, yes=True, no_validation=True, yes_no_validation=True),
        print_fn=messages.append,
    )
    assert rc == 0
    assert confirm_detected_calls == []
    assert any("NOTE" in m and "Rust" in m for m in messages)
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []


def test_no_proposal_with_no_validation_skips_resolve_validation_command(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """No usable proposal exists (Unknown stack) + --no-validation: the
    manual-resolution prompt is bypassed entirely -- the operator is
    never asked to type a command by hand only to have it discarded."""
    workdir = tmp_path / "cwd-no-proposal"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    resolve_calls = []
    monkeypatch.setattr(
        command_module, "resolve_validation_command",
        lambda *a, **k: resolve_calls.append((a, k)) or None,
    )

    rc = cmd_init(
        _Args(repo, yes=False, no_validation=True, yes_no_validation=True),
    )
    assert rc == 0
    assert resolve_calls == []
    cfg = load_config(workdir / "config.local.yaml")
    assert cfg.project.validation.commands == []


def test_no_mutation_before_acknowledgement_succeeds(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Decline path: branch/config mutation must not occur before
    acknowledgement succeeds -- setup_branch/write_config never called."""
    workdir = tmp_path / "cwd-no-mutation"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    setup_branch_calls = []
    write_config_calls = []
    monkeypatch.setattr(
        command_module, "setup_branch",
        lambda *a, **k: setup_branch_calls.append((a, k)) or ("agent-work", "deadbeef"),
    )
    monkeypatch.setattr(
        command_module, "write_config",
        lambda *a, **k: write_config_calls.append((a, k)),
    )

    rc = cmd_init(_Args(repo, yes=False, no_validation=True),
                   input_fn=lambda p: "n")
    assert rc == 1
    assert setup_branch_calls == []
    assert write_config_calls == []
