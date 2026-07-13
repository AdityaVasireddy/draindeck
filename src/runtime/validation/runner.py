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

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# v1 taxonomy: config carries a flat command list, so a failure is reported as
# validation-test. The finer lint/type/build/e2e split (doc 02 §6) lands when
# config gains labeled gates — noted, not invented here.
_DEFAULT_FAIL_TAXONOMY = "validation-test"


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
    ) -> None:
        if not commands:
            raise ValueError("Validator requires at least one command")
        self.commands = list(commands)
        self.timeout = timeout_seconds
        self.artifacts_dir = Path(artifacts_dir)

    def validate(self, workspace: Path | str, validated_commit: str,
                 execution_id: str) -> ValidationResult:
        workspace = Path(workspace)
        logdir = self.artifacts_dir / execution_id / "validation"
        logdir.mkdir(parents=True, exist_ok=True)
        result = ValidationResult(passed=True, validated_commit=validated_commit)

        for i, cmd in enumerate(self.commands):
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

    def _run_once(self, cmd: str, workspace: Path, log_path: Path,
                  *, append: bool = False) -> tuple[bool, float]:
        mode = "ab" if append else "wb"
        t0 = time.monotonic()
        with open(log_path, mode) as log:
            if append:
                log.write(b"\n--- flake-retry ---\n")
            try:
                proc = subprocess.run(
                    cmd, cwd=str(workspace), shell=True,
                    stdout=log, stderr=subprocess.STDOUT,
                    timeout=self.timeout,
                )
                ok = proc.returncode == 0
            except subprocess.TimeoutExpired:
                log.write(b"\n--- validation command timed out ---\n")
                ok = False
        return ok, time.monotonic() - t0
