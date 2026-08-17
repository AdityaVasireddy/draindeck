"""Validator — the deterministic gate chain (doc 09 §6.5, doc 02 §1/§6).

Runs ``config.project.validation.commands`` in order against the workspace,
cheapest-first (the config author owns ordering). First failure short-circuits.
A failed command is retried ONCE before being blamed (doc 02 flake-retry); a
pass-on-retry is recorded as flaky, not failed. Per-command stdout+stderr is
archived under the runtime's OWN artifacts dir — never inside the target repo,
or the log capture would itself dirty the workspace and trip reconciler check 3.

The result is a fact the orchestrator pins to ``validated_commit`` (the tree the
gate ran against) so the I3 pin gate can compare end == validated == reviewed.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# v1 taxonomy: config carries a flat command list, so a failure is reported as
# validation-test. The finer lint/type/build/e2e split (doc 02 §6) lands when
# config gains labeled gates — noted, not invented here.
_DEFAULT_FAIL_TAXONOMY = "validation-test"
_POWERSHELL = "powershell.exe"
_IS_WINDOWS = os.name == "nt"


def _shell_argv(cmd: str) -> list[str]:
    """The platform shell invocation for one validation command string.

    Windows: unchanged from the pre-existing PowerShell invocation (config's
    ``project.validation.commands`` are authored as PowerShell today; this
    repo's production runs are Windows-only). POSIX: ``/bin/sh -c``, the
    portable shell entrypoint — never exercised in production yet, so this is
    new capability, not a behavior change to any existing path.
    """
    if _IS_WINDOWS:
        return [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", cmd]
    return ["/bin/sh", "-c", cmd]


@dataclass
class ValidationResult:
    passed: bool
    validated_commit: str
    per_command: list[dict] = field(default_factory=list)  # {name,passed,duration_s,log_path}
    flake_retries: int = 0
    taxonomy_category: str | None = None  # set only on failure

    def gate_results(self) -> list[dict]:
        """doc 03 §3 #6 ValidationPassed/Failed payload shape."""
        return [
            {"gate": c["name"], "passed": c["passed"],
             "duration_s": c["duration_s"], "log_path": c["log_path"]}
            for c in self.per_command
        ]


class Validator:
    def __init__(
        self,
        commands: list[str],
        *,
        timeout_seconds: int,
        artifacts_dir: Path | str,
        env: dict[str, str | None] | None = None,
    ) -> None:
        if not commands:
            raise ValueError("Validator requires at least one command")
        if any("$" in command for command in commands):
            raise ValueError("validation commands containing '$' must use a .ps1 file with -File")
        self.commands = list(commands)
        self.timeout = timeout_seconds
        self.artifacts_dir = Path(artifacts_dir)
        # ADR-23 rule 3 (doc 08 §5d): the config-supplied env overlay for the
        # validation child. Copied so a later mutation of the caller's dict
        # can't drift what this Validator applies. A None VALUE unsets its key
        # (see _child_env); an empty/omitted overlay means "inherit the parent
        # env unchanged" — the pre-ADR-23 behaviour, so existing callers are
        # unaffected.
        self.env: dict[str, str | None] = dict(env) if env else {}

    def validate(self, workspace: Path | str, validated_commit: str,
                 execution_id: str,
                 extra_commands: list[str] | None = None) -> ValidationResult:
        """``extra_commands`` (Gap-2, doc 08 §5d Design A) are appended AFTER
        ``self.commands`` for this call only — ``self.commands`` (the
        config-sourced fixed list) is never mutated, so it stays the
        always-run, auditable baseline independent of any single execution.
        Typically child-authored new test files the caller detected via
        ``RepositoryAdapter.added_files`` and turned into pinned-interpreter
        commands (ADR-23 rule 1) before calling here."""
        workspace = Path(workspace)
        logdir = self.artifacts_dir / execution_id / "validation"
        logdir.mkdir(parents=True, exist_ok=True)
        result = ValidationResult(passed=True, validated_commit=validated_commit)

        commands = self.commands + list(extra_commands or [])
        if any("$" in command for command in commands):
            raise ValueError("validation commands containing '$' must use a .ps1 file with -File")
        for i, cmd in enumerate(commands):
            log_path = logdir / f"{i}.log"
            ok, dur = self._run_once(cmd, workspace, log_path)
            if not ok:
                # flake-retry once before blaming the code (doc 02).
                ok_retry, dur2 = self._run_once(cmd, workspace, log_path, append=True)
                result.flake_retries += 1
                ok, dur = ok_retry, dur + dur2
            result.per_command.append({
                "name": cmd, "passed": ok, "duration_s": round(dur, 3),
                "log_path": str(log_path),
            })
            if not ok:
                result.passed = False
                result.taxonomy_category = _DEFAULT_FAIL_TAXONOMY
                break  # cheapest-first short-circuit
        return result

    def _child_env(self) -> dict[str, str]:
        """Build the validation child's environment (ADR-23 rule 3, doc 08 §5d).

        Start from a FRESH snapshot of the parent env (built per call, like the
        engine's ``_hygienic_env()`` — no startup-check-then-drift window), then
        apply the config overlay in a SINGLE pass over its items, mutating the
        base: a ``None`` value POPS the key FROM THE BASE (so an *inherited*
        variable named with ``None`` is genuinely absent from the child, not
        merely empty — ``VIRTUAL_ENV=""`` still tests True under ``in os.environ``
        while an unset one tests False); any other value sets/overrides it.

        Popping from the *base* — not from the overlay — is the whole point of
        the ``str | None`` design: the parent env already carries the variable,
        so removing it from the overlay would leave the inherited copy in place
        and neutralize nothing.

        This closes the enumerated ambient vectors (PATH, VIRTUAL_ENV,
        PYTHONPATH, PYTHONHOME) named in config. It does NOT close the
        unenumerated tail: any inherited variable not mentioned in the overlay
        still reaches the child (ADR-23 option F, deferred).
        """
        built = dict(os.environ)
        for key, value in self.env.items():
            if value is None:
                built.pop(key, None)
            else:
                built[key] = value
        return built

    def _run_once(self, cmd: str, workspace: Path, log_path: Path,
                  *, append: bool = False) -> tuple[bool, float]:
        mode = "ab" if append else "wb"
        t0 = time.monotonic()
        with open(log_path, mode) as log:
            if append:
                log.write(b"\n--- flake-retry ---\n")
            try:
                proc = subprocess.run(
                    _shell_argv(cmd),
                    cwd=str(workspace), shell=False,
                    stdout=log, stderr=subprocess.STDOUT,
                    env=self._child_env(),  # ADR-23: explicit child env, not inherited
                    timeout=self.timeout,
                )
                ok = proc.returncode == 0
            except subprocess.TimeoutExpired:
                log.write(b"\n--- validation command timed out ---\n")
                ok = False
        return ok, time.monotonic() - t0
