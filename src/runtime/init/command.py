"""`init` CLI assembly (doc 16 §3/§4/§4a). Preflight, branch safety,
interactive UX, and the optional install trust boundary each live as
their own small, dependency-injectable function; `cmd_init` composes
them in the spec's exact order and is the only place that decides what
happens after each step.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from ..repo.adapter import RepoError
from ..repo.git_adapter import GitCliAdapter
from .detect import CommandProposal, DetectionRow, build_command, detect_stacks
from .generate import render_config, write_config


class InitAbort(Exception):
    """A preflight or resolution step refused to continue. `cmd_init`
    turns this into a stderr message and a non-zero exit — never a raw
    traceback."""


# ── preflight + branch safety (doc 16 §4 steps 1 and 5) ───────────────
def run_preflight(repo_path: Path, config_dest: Path, force: bool) -> GitCliAdapter:
    """Constructing `GitCliAdapter` alone performs the git-repository and
    git-version(>=2.38) checks (`repo/git_adapter.py:40-43`)."""
    try:
        adapter = GitCliAdapter(repo_path)
    except RepoError as e:
        raise InitAbort(f"not a usable git repository at {repo_path}: {e}") from e
    if adapter.is_dirty():
        raise InitAbort(
            f"{repo_path} has uncommitted changes — refusing to init over "
            f"in-progress work. Commit or stash first."
        )
    if config_dest.exists() and not force:
        raise InitAbort(f"{config_dest} already exists — pass --force to overwrite.")
    return adapter


def setup_branch(adapter: GitCliAdapter, branch: str) -> tuple[str, str]:
    """Never pass `create_from` for a branch that already exists —
    `checkout_branch(..., create_from=X)` compiles to `git checkout -B
    branch X`, which force-resets an existing branch's tip
    (`repo/git_adapter.py:178-187`, doc 16 §0b item 7)."""
    existing_tip = adapter.head_of(branch)
    if existing_tip is None:
        head = adapter.current_commit()
        adapter.checkout_branch(branch, create_from=head)
    else:
        adapter.checkout_branch(branch)
    return branch, adapter.current_commit()


# ── detected-proposal confirmation (doc 16 §4 step 3) ──────────────────
def confirm_detected_command(
    stack: str,
    chosen: CommandProposal,
    *,
    yes: bool,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> bool:
    """A successfully detected proposal is still "a proposal... editable
    before write — never silently committed as truth" (doc 16 §4 step 3),
    distinct from the no-usable-command manual UX in §4a. Under `--yes`,
    accept the detected default without prompting; otherwise ask once —
    accepting is the default answer (Enter/`y`), anything else aborts the
    whole run (nothing written), matching every other refusal path's
    "cancel means nothing written" contract."""
    print_fn(f"Detected stack: {stack}")
    for c in chosen.commands:
        print_fn(f"  validation command: {c}")
    if yes:
        return True
    answer = input_fn("Use this validation command? [Y/n] ").strip().lower()
    return answer in ("", "y")


# ── manual-validation UX (doc 16 §4a, no usable proposal) ─────────────
def resolve_validation_command(
    detection_summary: str,
    *,
    yes: bool,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> Optional[str]:
    """Implements doc 16 §4a's 9-point contract exactly. Returns the
    confirmed command, or `None` on blank input / explicit cancel /
    `--yes` with nothing to accept — the caller's signal to abort
    non-zero without writing anything."""
    print_fn(detection_summary)
    print_fn("No automatic validation command could be proposed.")
    if yes:
        return None
    while True:
        raw = input_fn(
            "Enter a validation command to run in this repository "
            "(blank to cancel): "
        )
        command = raw.strip()
        if not command:
            return None
        print_fn(f"Will write this validation command:\n  {command}")
        confirm = input_fn("Write this config? [y/N] ").strip().lower()
        if confirm == "y":
            return command
        # anything else (including blank): revise — loop back to the
        # command prompt, no fixed retry limit (doc 16 §4a point 7)


# ── dependency install trust boundary (doc 16 §4 step 4) ──────────────
def _shell_argv_for_install(cmd: str) -> list[str]:
    """Mirrors `validation/runner.py`'s `_shell_argv`/`_IS_WINDOWS`
    platform dispatch — not a new invocation mechanism."""
    if os.name == "nt":
        return ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd]
    return ["/bin/sh", "-c", cmd]


def _default_run(command: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(_shell_argv_for_install(command), cwd=str(cwd))


def confirm_and_run_install(
    install_command: Optional[str],
    *,
    repo_path: Path,
    yes: bool,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    run_fn: Callable[[str, Path], subprocess.CompletedProcess] = _default_run,
) -> bool:
    """A different trust boundary from `resolve_validation_command` —
    this one gates a subprocess spawn, not a text write, so it is its
    own function. `--yes` accepts detected *configuration* defaults; it
    never authorizes a dependency install (doc 16 §11) — that is
    enforced here by construction: under `yes=True`, neither `input_fn`
    nor `run_fn` is ever called. Declining is not an error; the caller
    proceeds either way.

    A confirmed install is an OPTIONAL convenience, never a gate on
    initialization (doc 16 §4 step 4; corrective pass after the
    read-only review). If it fails — the spawned command exits
    non-zero, or the subprocess cannot be launched at all (`OSError`,
    e.g. `FileNotFoundError`) — that is reported via a prominent
    `print_fn` warning naming the actual exit code, and initialization
    continues; it is never reinterpreted as an initialization failure.
    Only the narrow `OSError` family (subprocess launch failure) is
    caught here — a broad `except Exception` would mask real
    programming defects, which is not this function's job."""
    if install_command is None:
        return False
    print_fn(f"Proposed install command: {install_command}")
    if yes:
        return False
    answer = input_fn("Run this install command now? [y/N] ").strip().lower()
    if answer != "y":
        return False
    try:
        result = run_fn(install_command, repo_path)
    except OSError as e:
        print_fn(
            f"[init] WARNING: could not launch install command "
            f"({install_command!r}): {e}. Dependencies may not be "
            f"installed — review before starting a drain."
        )
        return False
    returncode = getattr(result, "returncode", 0)
    if returncode != 0:
        print_fn(
            f"[init] WARNING: install command exited with code "
            f"{returncode}. Dependencies may not be installed — review "
            f"before starting a drain."
        )
    return True


# ── explicit no-validation acknowledgement (ADR-24, doc 08 §5f) ───────
def confirm_no_validation(
    *,
    yes_no_validation: bool,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> bool:
    """The dedicated trust boundary `--no-validation` must pass through —
    distinct from `confirm_detected_command`/`resolve_validation_command`
    (those confirm/collect a validation *command*; this confirms running
    with NONE at all) and distinct from `--yes` (`--yes` accepts a
    detected configuration default; there is no default to accept here).
    `--yes-no-validation` satisfies this non-interactively — `input_fn` is
    never called in that case, mirroring `confirm_and_run_install`'s own
    `yes=True` shape. Otherwise prompts once; only an explicit `y`/`Y`
    proceeds, matching every other refusal path's contract."""
    if yes_no_validation:
        return True
    answer = input_fn(
        "Proceed without any validation gate? [y/N] "
    ).strip().lower()
    return answer == "y"


# ── CLI assembly (doc 16 §4) ───────────────────────────────────────────
def _format_detection_summary(matches: list[DetectionRow]) -> str:
    if not matches:
        return "No recognized stack marker found."
    names = ", ".join(row.stack for row in matches)
    return f"Detected stack marker(s): {names}."


def _print_report(
    chosen_stack: str,
    branch_name: str,
    branch_tip: str,
    chosen: CommandProposal,
    config_dest: Path,
) -> None:
    print(f"[init] stack: {chosen_stack}")
    print(f"[init] branch: {branch_name} @ {branch_tip[:12]}")
    if chosen.commands:
        print("[init] validation command(s):")
        for c in chosen.commands:
            print(f"    {c}")
    else:
        # ADR-24: no fake validation command is ever printed here.
        print("[init] validation: NONE (acknowledged_no_gate)")
    print(f"[init] wrote {config_dest}")
    print(f"[init] next: python -m runtime.main check-config {config_dest}")
    print(f"[init] then: python -m runtime.main run --config {config_dest}")


def cmd_init(
    args,
    *,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    run_fn: Callable[[str, Path], subprocess.CompletedProcess] = _default_run,
) -> int:
    """`input_fn`/`print_fn`/`run_fn` are threaded through to every
    interactive/subprocess sub-step (`confirm_detected_command`,
    `resolve_validation_command`, `confirm_and_run_install`) rather than
    left at their own defaults — this is what makes the full CLI path
    scriptable end-to-end in tests without a real TTY or a real
    subprocess spawn, not just each function in isolation. (A default
    keyword argument is bound once, at `def` time — patching the module
    attribute after import does not reach an already-bound default, so
    threading the override through the call chain is the only way to
    make this genuinely injectable at the `cmd_init` layer.)"""
    no_validation = args.no_validation
    yes_no_validation = args.yes_no_validation

    # ADR-24 (doc 08 §5f): invalid flag combination refused before any
    # preflight/detection work — zero git/filesystem side effects for an
    # invocation that can never succeed.
    if yes_no_validation and not no_validation:
        print(
            "INIT ABORTED: --yes-no-validation requires --no-validation",
            file=sys.stderr,
        )
        return 1

    repo_path = Path(args.repo_path).resolve()
    config_dest = Path.cwd() / "config.local.yaml"
    yes = args.yes

    try:
        adapter = run_preflight(repo_path, config_dest, args.force)
    except InitAbort as e:
        print(f"INIT ABORTED: {e}", file=sys.stderr)
        return 1

    matches = detect_stacks(repo_path)
    detection_summary = _format_detection_summary(matches)
    chosen_row = matches[0] if matches else None
    chosen = build_command(chosen_row, repo_path) if chosen_row is not None else None

    if no_validation:
        # ADR-24: an explicit no-gate acknowledgement OVERRIDES automatic
        # validation selection — this is not a rejection of the detected
        # proposal, just a visible change of path. Neither
        # confirm_detected_command nor resolve_validation_command is
        # called: the operator already opted out of a validation command
        # entirely, so there is nothing to confirm/collect there.
        chosen_stack = chosen_row.stack if chosen_row is not None else "none"
        # Install proposal (if any) is independent of the validation-
        # command decision (doc 17 §2h) — preserved across the override
        # so confirm_and_run_install below can still offer it.
        detected_install_command = chosen.install_command if chosen is not None else None
        if chosen is not None:
            print_fn(
                f"[init] NOTE: --no-validation set; overriding detected "
                f"validation command(s) for {chosen_stack}."
            )
        if not confirm_no_validation(
            yes_no_validation=yes_no_validation,
            input_fn=input_fn, print_fn=print_fn,
        ):
            print(
                "INIT ABORTED: no-validation not confirmed; nothing written.",
                file=sys.stderr,
            )
            return 1
        chosen = CommandProposal(commands=[], install_command=detected_install_command)
    elif chosen is not None:
        chosen_stack = chosen_row.stack
        if not confirm_detected_command(
            chosen_stack, chosen, yes=yes, input_fn=input_fn, print_fn=print_fn
        ):
            print(
                "INIT ABORTED: validation command not confirmed; nothing written.",
                file=sys.stderr,
            )
            return 1
    else:
        command_text = resolve_validation_command(
            detection_summary, yes=yes, input_fn=input_fn, print_fn=print_fn
        )
        if command_text is None:
            print(
                "INIT ABORTED: no validation command available; nothing written.",
                file=sys.stderr,
            )
            return 1
        chosen = CommandProposal(commands=[command_text])
        chosen_stack = "manual"

    confirm_and_run_install(
        chosen.install_command,
        repo_path=repo_path,
        yes=yes,
        input_fn=input_fn,
        print_fn=print_fn,
        run_fn=run_fn,
    )

    branch_name, branch_tip = setup_branch(adapter, args.branch)

    text = render_config(
        repo_path=repo_path,
        branch=branch_name,
        branch_tip=branch_tip,
        all_matches=matches,
        chosen_stack=chosen_stack,
        chosen=chosen,
    )
    write_config(config_dest, text)
    _print_report(chosen_stack, branch_name, branch_tip, chosen, config_dest)
    return 0
