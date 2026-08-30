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
    resolve_config_dest,
    resolve_validation_command,
    run_preflight,
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


def _default_dest(repo_path) -> Path:
    """The new target-repo-derived default (doc 16 §0c) — never CWD."""
    return Path(repo_path).resolve() / ".draindeck" / "config.local.yaml"


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


# ── Unit 5: preflight ────────────────────────────────────────────────
def test_preflight_rejects_non_git_path(tmp_path: Path):
    with pytest.raises(InitAbort):
        run_preflight(tmp_path / "not-a-repo", tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_tracked_dirty_tree(repo: Path, tmp_path: Path):
    (repo / "README").write_text("locally modified\n")  # tracked, unstaged
    with pytest.raises(InitAbort):
        run_preflight(repo, tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_staged_change(repo: Path, tmp_path: Path):
    (repo / "README").write_text("staged\n")
    _run(repo, "add", "README")
    with pytest.raises(InitAbort):
        run_preflight(repo, tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_tracked_deletion(repo: Path, tmp_path: Path):
    (repo / "README").unlink()
    with pytest.raises(InitAbort):
        run_preflight(repo, tmp_path / "config.local.yaml", force=False)


def test_preflight_rejects_conflicted_merge(repo: Path, tmp_path: Path):
    _run(repo, "checkout", "-b", "side")
    (repo / "README").write_text("side\n")
    _run(repo, "commit", "-am", "side change")
    _run(repo, "checkout", "main")
    (repo / "README").write_text("main\n")
    _run(repo, "commit", "-am", "main change")
    p = subprocess.run(["git", "merge", "side"], cwd=repo, capture_output=True, text=True)
    assert p.returncode != 0  # real conflict, as intended
    try:
        with pytest.raises(InitAbort):
            run_preflight(repo, tmp_path / "config.local.yaml", force=False)
    finally:
        _run(repo, "merge", "--abort")


# ── untracked-only preflight: the bug this session fixes ───────────────
def test_preflight_allows_untracked_only_with_note(repo: Path, tmp_path: Path):
    (repo / "Issues.md").write_text("scratch notes\n")  # untracked
    notes = []
    run_preflight(
        repo, tmp_path / "config.local.yaml", force=False, print_fn=notes.append,
    )
    assert any("NOTE" in n and "untracked" in n for n in notes)


def test_preflight_untracked_files_left_byte_unchanged(repo: Path, tmp_path: Path):
    (repo / "Issues.md").write_text("scratch notes\n")
    run_preflight(repo, tmp_path / "config.local.yaml", force=False, print_fn=lambda *_: None)
    assert (repo / "Issues.md").read_text() == "scratch notes\n"


def test_preflight_untracked_files_not_staged_or_removed(repo: Path, tmp_path: Path):
    (repo / "Issues.md").write_text("scratch notes\n")
    run_preflight(repo, tmp_path / "config.local.yaml", force=False, print_fn=lambda *_: None)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
    ).stdout
    assert status.strip() == "?? Issues.md"  # still untracked, not staged ("A ")


def test_preflight_rejects_existing_config_without_force(repo: Path, tmp_path: Path):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("existing: true\n")
    with pytest.raises(InitAbort):
        run_preflight(repo, dest, force=False)


def test_preflight_proceeds_with_force_over_existing_config(repo: Path, tmp_path: Path):
    dest = tmp_path / "config.local.yaml"
    dest.write_text("existing: true\n")
    run_preflight(repo, dest, force=True)  # must not raise


def test_preflight_clean_new_config_dest_proceeds(repo: Path, tmp_path: Path):
    run_preflight(repo, tmp_path / "config.local.yaml", force=False)  # must not raise


# Branch-checkout mechanics (CREATE at head, CHECKOUT preserves tip with no
# force-reset, untracked-only allowed, real-conflict refuses cleanly with no
# mutation) moved to tests/unit/test_target_configuration_service.py: since
# ADR-29's full migration, `cmd_init` no longer performs its own branch
# mutation — apply_target_configuration (manage_branch=True) is the only
# path, so the guarantee is proven there, end-to-end through the shared
# service, not through a CLI-local setup_branch helper that no longer exists.


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
                 no_validation=False, yes_no_validation=False, config_out=None):
        self.repo_path = str(repo_path)
        self.branch = branch
        self.yes = yes
        self.force = force
        self.no_validation = no_validation
        self.yes_no_validation = yes_no_validation
        self.config_out = config_out


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

    dest = _default_dest(repo)
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.project.validation.commands == ["cargo test"]
    assert install_calls == []  # --yes must never trigger the install
    assert not (workdir / "config.local.yaml").exists()  # CWD never used


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
    cfg = load_config(_default_dest(repo))
    assert cfg.project.validation.commands == ['node --check "app.js"']


def test_cmd_init_unknown_stack_yes_refuses_writes_nothing(tmp_path: Path, monkeypatch, repo: Path):
    workdir = tmp_path / "cwd3"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 1
    assert not _default_dest(repo).exists()


def test_cmd_init_dirty_tree_refuses(tmp_path: Path, monkeypatch, repo: Path):
    (repo / "README").write_text("locally modified\n")  # tracked, unstaged
    workdir = tmp_path / "cwd4"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 1
    assert not _default_dest(repo).exists()


def test_cmd_init_untracked_only_does_not_refuse(tmp_path: Path, monkeypatch, repo: Path):
    """The exact real-world bug: an untracked Issues.md must not block
    `init`, must be left untouched, and the target-derived config must
    still be written."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")
    (repo / "Issues.md").write_text("scratch notes\n")  # untracked, harmless

    workdir = tmp_path / "cwd4b"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    messages = []
    rc = cmd_init(_Args(repo, yes=True), print_fn=messages.append)
    assert rc == 0
    assert (repo / "Issues.md").read_text() == "scratch notes\n"  # untouched
    assert any("NOTE" in m and "untracked" in m for m in messages)
    cfg = load_config(_default_dest(repo))
    assert cfg.project.validation.commands == ["cargo test"]


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

    dest = _default_dest(repo)
    dest.parent.mkdir(parents=True)
    dest.write_text("existing: true\n")

    workdir = tmp_path / "cwd6"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True, force=False))
    assert rc == 1
    assert dest.read_text(encoding="utf-8") == "existing: true\n"


def test_cmd_init_unrelated_cwd_config_ignored_and_untouched(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """The bug this session fixes: an unrelated config.local.yaml sitting
    in the invocation directory (e.g. Draindeck's own StockPhotoAgent
    config) must be completely irrelevant to a different target repo's
    init — never inspected for existence, never overwritten, not even
    under --force."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd6b"
    workdir.mkdir()
    unrelated = workdir / "config.local.yaml"
    unrelated_text = "project:\n  name: StockPhotoAgent\n  repository: 'C:\\\\unrelated'\n"
    unrelated.write_text(unrelated_text, encoding="utf-8")
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True, force=True))  # --force: still must not touch it
    assert rc == 0
    assert unrelated.read_text(encoding="utf-8") == unrelated_text
    assert _default_dest(repo).exists()


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
    cfg = load_config(_default_dest(repo))
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
    dest = _default_dest(repo)
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
    dest = _default_dest(repo)
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
    cfg = load_config(_default_dest(repo))
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
    cfg = load_config(_default_dest(repo))
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
    cfg = load_config(_default_dest(repo))
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
    cfg = load_config(_default_dest(repo))
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
    cfg = load_config(_default_dest(repo))
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
    cfg = load_config(_default_dest(repo))
    assert cfg.project.validation.commands == []


def test_no_mutation_before_acknowledgement_succeeds(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Decline path: branch/config mutation must not occur before
    acknowledgement succeeds -- apply_target_configuration (the sole
    mutation gate, ADR-29) is never called."""
    workdir = tmp_path / "cwd-no-mutation"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    apply_calls = []
    monkeypatch.setattr(
        command_module, "apply_target_configuration",
        lambda *a, **k: apply_calls.append((a, k)),
    )

    rc = cmd_init(_Args(repo, yes=False, no_validation=True),
                   input_fn=lambda p: "n")
    assert rc == 1
    assert apply_calls == []


# ── resolve_config_dest: unit-level (doc 16 §0c) ────────────────────────

def test_resolve_config_dest_default_is_target_repo_derived(tmp_path: Path):
    repo_path = (tmp_path / "target").resolve()
    dest = resolve_config_dest(repo_path, None)
    assert dest == repo_path / ".draindeck" / "config.local.yaml"


def test_resolve_config_dest_two_repos_get_different_defaults(tmp_path: Path):
    a = (tmp_path / "repo-a").resolve()
    b = (tmp_path / "repo-b").resolve()
    assert resolve_config_dest(a, None) != resolve_config_dest(b, None)


def test_resolve_config_dest_config_out_absolute_used_as_is(tmp_path: Path):
    repo_path = (tmp_path / "target").resolve()
    explicit = tmp_path / "elsewhere" / "custom.yaml"
    dest = resolve_config_dest(repo_path, str(explicit))
    assert dest == explicit.resolve()


def test_resolve_config_dest_config_out_relative_resolves_against_cwd(
    tmp_path: Path, monkeypatch,
):
    repo_path = (tmp_path / "target").resolve()
    cwd = tmp_path / "somewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    dest = resolve_config_dest(repo_path, "custom.yaml")
    assert dest == (cwd / "custom.yaml").resolve()
    assert dest != repo_path / "custom.yaml"  # not resolved against repo_path


# ── CWD-independence regression (the real bug: doc 16 §0c item 2) ──────

def test_cwd_independence_same_repo_same_dest_from_draindeck_root_vs_repo_itself(
    tmp_path: Path, monkeypatch, repo: Path,
):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    draindeck_root = tmp_path / "draindeck-root"
    draindeck_root.mkdir()
    monkeypatch.chdir(draindeck_root)
    rc1 = cmd_init(_Args(repo, yes=True))
    assert rc1 == 0
    dest1 = _default_dest(repo)
    assert dest1.exists()
    content1 = dest1.read_text(encoding="utf-8")

    # Re-run from a second, unrelated CWD (arbitrary directory) — same
    # target repo must resolve to the SAME destination path.
    another_dir = tmp_path / "some-other-arbitrary-dir"
    another_dir.mkdir()
    monkeypatch.chdir(another_dir)
    dest2 = resolve_config_dest(Path(repo).resolve(), None)
    assert dest2 == dest1
    _ = content1  # dest1 already proven written; dest2 is the same path


def test_cwd_independence_cwd_equals_repo_itself(repo: Path, monkeypatch):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    monkeypatch.chdir(repo)  # CWD == the target repo itself
    dest_from_inside = resolve_config_dest(Path(repo).resolve(), None)
    assert dest_from_inside == repo.resolve() / ".draindeck" / "config.local.yaml"


def test_cwd_independence_cwd_equals_unrelated_repo_b(
    tmp_path: Path, monkeypatch, repo: Path,
):
    repo_b = tmp_path / "repo-b"
    repo_b.mkdir()
    monkeypatch.chdir(repo_b)  # CWD is a wholly different repo
    dest = resolve_config_dest(Path(repo).resolve(), None)
    assert dest == Path(repo).resolve() / ".draindeck" / "config.local.yaml"
    assert not (repo_b / "config.local.yaml").exists()


def test_cwd_independence_two_target_repos_different_destinations(
    tmp_path: Path, monkeypatch, repo: Path,
):
    """Regression for the exact collision this session's bug caused:
    onboarding two different target repos from the same Draindeck
    invocation directory must never collide."""
    repo_b_dir = tmp_path / "repo-b"
    repo_b_dir.mkdir()
    _run(repo_b_dir, "init", "-b", "main")
    _run(repo_b_dir, "config", "core.autocrlf", "false")
    (repo_b_dir / "README").write_text("seed\n")
    (repo_b_dir / "Cargo.toml").write_text("[package]\nname='y'\n")
    _run(repo_b_dir, "add", "-A")
    _run(repo_b_dir, "commit", "-m", "seed")

    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    shared_cwd = tmp_path / "shared-cwd"
    shared_cwd.mkdir()
    monkeypatch.chdir(shared_cwd)

    rc_a = cmd_init(_Args(repo, yes=True))
    rc_b = cmd_init(_Args(repo_b_dir, yes=True))
    assert rc_a == 0 and rc_b == 0

    dest_a = _default_dest(repo)
    dest_b = _default_dest(repo_b_dir)
    assert dest_a != dest_b
    assert dest_a.exists() and dest_b.exists()
    assert load_config(dest_a).project.name == Path(repo).resolve().name
    assert load_config(dest_b).project.name == Path(repo_b_dir).resolve().name


# ── --config-out override ───────────────────────────────────────────────

def test_config_out_overrides_default_destination(tmp_path: Path, monkeypatch, repo: Path):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-config-out"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    custom = tmp_path / "custom-dest" / "my-config.yaml"

    rc = cmd_init(_Args(repo, yes=True, config_out=str(custom)))
    assert rc == 0
    assert custom.exists()
    assert not _default_dest(repo).exists()
    cfg = load_config(custom)
    assert cfg.project.validation.commands == ["cargo test"]


def test_config_out_existing_destination_without_force_refuses(
    tmp_path: Path, monkeypatch, repo: Path,
):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-config-out-refuse"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    custom = tmp_path / "custom-dest2" / "my-config.yaml"
    custom.parent.mkdir(parents=True)
    custom.write_text("existing: true\n")

    rc = cmd_init(_Args(repo, yes=True, config_out=str(custom), force=False))
    assert rc == 1
    assert custom.read_text(encoding="utf-8") == "existing: true\n"


def test_config_out_force_overwrites_only_resolved_destination(
    tmp_path: Path, monkeypatch, repo: Path,
):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-config-out-force"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    custom = tmp_path / "custom-dest3" / "my-config.yaml"
    custom.parent.mkdir(parents=True)
    custom.write_text("existing: true\n")
    unrelated = workdir / "config.local.yaml"
    unrelated.write_text("unrelated: true\n", encoding="utf-8")

    rc = cmd_init(_Args(repo, yes=True, config_out=str(custom), force=True))
    assert rc == 0
    cfg = load_config(custom)
    assert cfg.project.validation.commands == ["cargo test"]
    # --force touched ONLY the resolved --config-out destination
    assert unrelated.read_text(encoding="utf-8") == "unrelated: true\n"


# ── post-init output references the exact resolved path ────────────────

def test_post_init_output_references_exact_config_path(
    tmp_path: Path, monkeypatch, repo: Path, capsys,
):
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")

    workdir = tmp_path / "cwd-post-init"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(repo, yes=True))
    assert rc == 0
    out = capsys.readouterr().out
    dest = _default_dest(repo)
    assert str(dest) in out
    assert f'check-config "{dest}"' in out
    assert f'run --config "{dest}"' in out


def test_target_path_with_spaces_end_to_end(tmp_path: Path, monkeypatch):
    spaced = tmp_path / "Target Repo With Spaces"
    spaced.mkdir()
    _run(spaced, "init", "-b", "main")
    _run(spaced, "config", "core.autocrlf", "false")
    (spaced / "README").write_text("seed\n")
    (spaced / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(spaced, "add", "-A")
    _run(spaced, "commit", "-m", "seed")

    workdir = tmp_path / "cwd-spaces"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    rc = cmd_init(_Args(spaced, yes=True))
    assert rc == 0
    dest = _default_dest(spaced)
    assert dest.exists()
    cfg = load_config(dest)
    assert cfg.project.repository == str(spaced.resolve())
    assert cfg.project.validation.commands == ["cargo test"]


# ── combined real-world regression: both fixes together ────────────────

def test_combined_regression_untracked_only_plus_unrelated_cwd_config(
    tmp_path: Path, monkeypatch, repo: Path, capsys,
):
    """The exact scenario that exposed both bugs in one session: a target
    repo with a clean tracked tree but a harmless untracked file, invoked
    from a directory holding an unrelated existing config.local.yaml
    (e.g. Draindeck's own StockPhotoAgent config)."""
    (repo / "Cargo.toml").write_text("[package]\nname='x'\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "add cargo")
    (repo / "Issues.md").write_text("real-world untracked backlog file\n")

    draindeck_root = tmp_path / "draindeck-root"
    draindeck_root.mkdir()
    unrelated = draindeck_root / "config.local.yaml"
    unrelated_text = "project:\n  name: StockPhotoAgent\n  repository: 'C:\\\\SPA'\n"
    unrelated.write_text(unrelated_text, encoding="utf-8")
    monkeypatch.chdir(draindeck_root)

    messages = []
    rc = cmd_init(_Args(repo, branch="agent-work", yes=True), print_fn=messages.append)

    assert rc == 0
    # untracked-only did not block init
    assert any("NOTE" in m and "untracked" in m for m in messages)
    # unrelated CWD config ignored and untouched
    assert unrelated.read_text(encoding="utf-8") == unrelated_text
    # branch setup proceeded safely
    adapter = GitCliAdapter(repo)
    assert adapter.head_of("agent-work") is not None
    # target-specific config generated, untracked file untouched
    dest = _default_dest(repo)
    assert dest.exists()
    assert (repo / "Issues.md").read_text() == "real-world untracked backlog file\n"
    cfg = load_config(dest)
    assert cfg.project.repository == str(Path(repo).resolve())
    assert cfg.project.validation.commands == ["cargo test"]
    # post-init output points to the target-specific config
    out = capsys.readouterr().out
    assert str(dest) in out
