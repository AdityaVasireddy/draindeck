"""ClaudeHeadlessEngine — the v1 execution engine (ADR-08 concrete, no ABC).

Spawns ``claude -p`` in the target workspace, enforces the wall-clock timeout
and ADR-18 env hygiene, and returns an ADVISORY ``EngineResult``. The real
output of an execution is the WORKSPACE MUTATION, observed by the orchestrator
through RepositoryAdapter (ADR-02/07): an engine can lie in its summary, never
in the diff. This wrapper never touches git. On Windows it receives an
injected authoritative writer for the narrow containment facts around the Job
boundary; RepositoryAdapter (via recovery/bindings.py and the orchestrator)
still owns every git contact, and doc 03 owns issue lifecycle events.

VERIFIED CLI contract (claude 2.1.207, Windows, 2026-07-11; re-verified at
2.1.211 on 2026-07-16; re-verified at 2.1.224 on 2026-08-07 (Session 35,
doc 08 §5b Amendment 2) — see the ADR-21 fence block below — re-pin on
upgrade):
  * argv: ``claude -p --output-format stream-json --verbose
    --no-session-persistence`` (+ ``--model`` when != "default", + permission
    scoping). ``--verbose`` is REQUIRED for stream-json in print mode. The
    prompt is delivered on STDIN (no positional arg needed).
  * NO ``--max-turns`` flag (removed in 2.1.207); ``--settings '{"maxTurns":N}'``
    is silently ignored (unknown keys are dropped in print mode). max_turns is
    enforced REACTIVELY: ``EngineResult.num_turns`` (from the result line) is
    read by the orchestrator, which on ``num_turns >= cfg.max_turns`` records
    doc 03 §5's turn-budget row ``IssueEscalated(NEEDS_DECOMPOSITION)``. The
    wall-clock ``timeout_seconds`` below is the hard runaway backstop.
  * stream-json emits newline-delimited JSON; the final ``result`` line carries
    ``usage{input_tokens,output_tokens}``, ``total_cost_usd`` (list-rate proxy,
    present even on the subscription — feeds ADR-09), ``num_turns``,
    ``stop_reason``, ``terminal_reason``. The ``system``/``init`` line carries
    ``apiKeySource`` ('none' under the subscription with no key).
  * On Windows ``claude`` is an npm ``.CMD`` shim: the contained launch plan
    makes trusted ``cmd.exe`` the suspended Job root, then resumes it only
    after durable containment establishment. The wrapper and its ordinary
    descendants are captured by that Job, not inferred from a PID tree.

pid discipline (I-h, verified against tests/crash/{worker,harness}.py): the
event log records the ORCHESTRATOR/WRITER pid (``os.getpid()``) in both
ExecutionSpawned and ExecutionFinished; I-h asserts they match as the
never-replayed rule. That pid is NEVER the engine child pid. The engine child
pid lives only in the on-disk pidfile, so a synchronous ``run()`` with no pid
on ``EngineResult`` satisfies I-h unchanged.

KNOWN LIMITATION (legacy Windows T5 orphan records): ``taskkill /F /T`` walks
the parent-child tree at kill time. A reparented grandchild can escape this
legacy cleanup, so T5 liveness is diagnostic only and never releases
containment. Current Windows executions use the Job boundary below; their
timeout/release proof is Job membership reaching zero.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..config import EngineCfg
from ..events.schema import Event, EventType
from .windows_job import (
    EmptyMembershipStatus, JobLifecycleError, MembershipQueryError,
    TerminationRequestError, WindowsJobController, WindowsJobError,
)

_CLAUDE_BIN = "claude"
_IS_WINDOWS = os.name == "nt"

# ruling (b): every env var whose presence could bill or route the engine off
# the Pro subscription. Stripped from the child env in subscription mode
# (ADR-18). Each, if present, would silently bill or redirect: AUTH_TOKEN (the
# credential chain), USE_BEDROCK/USE_VERTEX (3P provider billing), BASE_URL (a
# gateway redirect), MODEL (a silent model override — the model is config-driven
# via --model).
_SUBSCRIPTION_STRIP = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
)

# "bypassPermissions" skips the CLI's interactive Bash-approval heuristic —
# REQUIRED for a headless -p child to self-verify via pytest AT ALL.
# VERIFIED (Session 35, doc 08 §5b Amendment 2): under "default"/"acceptEdits",
# every Bash tool_use attempt — even a single, non-chained, single-file pytest
# command — is auto-denied: tool_result is_error=true,
# tool_result_meta.non_execution_kind="user-rejected". This is the CLI's own
# interactive-approval gate, DISTINCT from the denylist below, firing with no
# human present in -p mode to approve it. "plan" mode never reaches Bash at
# all (headless ExitPlanMode is unavailable). Only "bypassPermissions" lets a
# non-denied Bash command actually run (is_error=false, real pytest stdout
# observed). It does NOT act as a fence on its own — see _DENY_TOOLS below,
# whose enforcement is UNCHANGED and INDEPENDENT of this value: a denied
# command surfaces tool_result_meta.non_execution_kind="permission-rule",
# confirmed identical under default/acceptEdits/bypassPermissions (curl, rm,
# and git all denied this way under every mode tested).
# KNOWN RESIDUAL: the Write tool has no cwd confinement under ANY permission
# mode (pre-existing, not introduced by this change; unconfirmed whether the
# same escape reproduces under acceptEdits without model self-restraint
# intervening) — see doc 08 §5b Amendment 2 for the full record.
_DEFAULT_PERMISSION_MODE = "bypassPermissions"

# ─────────────────────── ADR-21: the engine fence ───────────────────────
# PROBE-VERIFIED against claude 2.1.207 (Windows, subscription, 2026-07-12).
# RE-VERIFIED at 2.1.211 (2026-07-16, doc 14 §2): deny enforcement, selectivity,
# chaining resistance, and --allowedTools non-restriction IDENTICAL (C1/C2/C4).
# Whole-tool-removal enforcement MECHANISM CHANGED at 2.1.211 — a denied whole
# tool is dropped from the session init `tools` manifest, so the model never
# attempts it: no tool_use, no is_error, no permission_denials entry (was:
# tool_result is_error with permission_denials EMPTY at 2.1.207; the
# Detection-signal note below now describes 2.1.207 only). Recorded as ADR-21
# Amendment 1 (doc 08, 2026-07-16 — manifest-absence is the only whole-tool-deny
# signal at 2.1.211). Re-pin on upgrade.
# The Session-4 forward-pointer assumed --allowedTools would
# fence the engine and that a disallowed tool records a `permission_denial`
# rather than running. BOTH are FALSE and were falsified empirically:
#   * --allowedTools does NOT restrict. In -p mode a tool matching neither an
#     allow nor a deny rule RUNS. `--allowedTools Read` still let Bash run
#     `whoami`; `--allowedTools "Bash(echo:*)"` still let `whoami` run. True
#     under both --permission-mode default AND acceptEdits.
#   * The ONLY working fence is the DENYLIST (--disallowedTools / settings
#     `deny`). It is enforced, SELECTIVE at the Bash(cmd:*) pattern level
#     (`Bash(curl:*)` denies curl while `echo hello` still runs), and
#     CHAINING-RESISTANT (`echo ok && curl ...` is denied by `Bash(curl:*)`).
#   * Detection signal (2.1.207): a denied *pattern* populates
#     result.permission_denials AND yields a tool_result is_error; a whole-tool
#     removal (`--disallowedTools Bash`) yields only the tool_result is_error
#     with permission_denials EMPTY. [2.1.207 ONLY — at 2.1.211 a denied whole
#     tool is dropped from the session init manifest and is never attempted
#     (C3, 2026-07-16); audit whole-tool denies by manifest ABSENCE. See header,
#     doc 14 §2, and ADR-21 Amendment 1 (doc 08).] Transcript-based auditing
#     must key on BOTH. The
#     transcript is advisory only (ADR-07) — nothing here gates a transition.
#
# We pass the WHOLE fence EXPLICITLY so it is self-contained: it does not rely
# on the operator's ambient ~/.claude/settings.json (explicit + ambient compose;
# deny always wins; a masking ambient `allow` cannot re-enable a denied tool).
#
# doc 02 §3 asks for "no network push, no credential access". With Bash present
# that is STRUCTURALLY UNCLOSABLE (a shell can read a local file and egress via
# curl/python), so ADR-21 accepts the residual and fences EGRESS + DESTRUCTION +
# PUSH + RECURSIVE-SPAWN instead. Compensating controls: no push path, egress
# tools denied, the engine never touches git (Bash(git:*) — also enforces
# ADR-07), reconciler check 3, the supervised Phase-2 run, and ADR-20's
# safe-to-experiment target. Every entry uses the PROVEN one-word `Bash(cmd:*)`
# colon form (or a whole-tool name) — no unprobed pattern shape is relied on.
_DENY_TOOLS = (
    # first-class network / sub-agent-escape tools (whole-tool removal)
    "WebFetch", "WebSearch", "Task",
    # network egress via the shell
    "Bash(curl:*)", "Bash(curl.exe:*)", "Bash(wget:*)", "Bash(wget.exe:*)",
    "Bash(ssh:*)", "Bash(scp:*)", "Bash(sftp:*)", "Bash(nc:*)", "Bash(telnet:*)",
    "Bash(powershell:*)", "Bash(pwsh:*)",
    "Bash(Invoke-WebRequest:*)", "Bash(iwr:*)",
    # git is the orchestrator's alone (ADR-07); deny the whole CLI, which also
    # closes the push path
    "Bash(git:*)",
    # destruction / privilege escalation
    "Bash(rm:*)", "Bash(sudo:*)", "Bash(chmod:*)",
    # block a recursive engine spawn (a child claude would re-bill and escape
    # this fence)
    "Bash(claude:*)", "Bash(claude.exe:*)", "Bash(npx:*)",
)


class EngineError(RuntimeError):
    """The engine could not be constructed or spawned (e.g. ``claude`` not on
    PATH). Nothing is swallowed."""


class EngineEnvError(EngineError):
    """An ADR-18 env-hygiene precondition failed. Raised BEFORE any spawn side
    effect in api_key mode (key required, missing), and if a stripped credential
    survives the strip or ``apiKeySource`` reveals a leak in subscription mode.
    Never an ``assert`` — asserts vanish under ``python -O`` and this is a
    billing invariant that must hold on every spawn."""


class EngineContainmentError(EngineError):
    """Containment is unreleased; callers must not treat this as a timeout."""


@dataclass(frozen=True)
class ContainmentExecutionContext:
    """Authoritative event context injected by the orchestrator writer path."""
    issue_id: str
    workspace_key: str
    containment_generation: str
    controller: dict
    append_event: Callable[[Event], None]
    lease: dict


@dataclass(frozen=True)
class EngineResult:
    """ADVISORY ONLY (ADR-02/07). Facts about the *process*, never about the
    *code*. The real output of an execution is the workspace mutation, observed
    by the orchestrator through RepositoryAdapter (snapshot_commit -> end_commit,
    diff derived per ADR-15). Nothing here may gate a transition on its own;
    ``exit_status``/``timed_out``/``num_turns`` may ONLY select WHICH doc 03 §5
    row the orchestrator records, never whether the work "worked". There is no
    success flag, no file list, no diff, no summary — treating this as truth is
    structurally impossible."""

    exit_status: int         # Popen.returncode; always set (we always reap)
    timed_out: bool          # wall-clock kill fired
    duration_s: float
    usage: dict              # {input_tokens, output_tokens, dollars}; dollars <-
                             # total_cost_usd. Values may be None if unparseable.
    num_turns: Optional[int]
    # ADVISORY CARVE-OUT EXTENSION: num_turns is engine-reported, like
    # exit_status/timed_out. It may ONLY decide which doc 03 §5 row the
    # orchestrator records (num_turns >= cfg.max_turns -> the turn-budget row,
    # IssueEscalated NEEDS_DECOMPOSITION). A garbled count cannot ship bad code
    # — validation and review still gate. None (unparseable) => no turn-budget
    # escalation; the wall-clock timeout remains the hard backstop.
    transcript_path: Path    # stdout archived verbatim (stream-json JSONL)
    stderr_tail: str         # last ~2KB of stderr, diagnostics only


class ClaudeHeadlessEngine:
    """Spawn ``claude -p`` per execution; enforce timeout + ADR-18 hygiene.

    Constructed once from ``config.engine`` and an ``artifacts_dir`` that lives
    under the runtime's own state directory — NEVER inside the target repo, or
    every transcript/pidfile would trip reconciler check 3 / ``is_dirty()``.
    """

    def __init__(self, cfg: EngineCfg, artifacts_dir: Path | str) -> None:
        self.cfg = cfg
        self.artifacts_dir = Path(artifacts_dir)
        exe = shutil.which(_CLAUDE_BIN)
        if exe is None:
            raise EngineError(
                f"{_CLAUDE_BIN!r} not found on PATH — cannot spawn the engine"
            )
        self._claude_exe = exe

    # ── env hygiene (ADR-18) ─────────────────────────────────────────
    def _hygienic_env(self) -> dict[str, str]:
        """Build the child environment fresh on every call (structural — no
        startup-check-then-drift window). Subscription mode strips the full
        billing/routing set; api_key mode fails fast if the key is absent."""
        env = dict(os.environ)
        # ADR-22 (B layer, sunset per doc 08 §5c): config-driven child-env vars
        # (engine.child_env — e.g. HISTORIAN_SWEEP_ACTIVE=1, the historian
        # hook's own recursion guard) merged AFTER the base env build and
        # BEFORE the ADR-18 strip, so the strip is applied LAST and always
        # wins: a child_env key that collides with a strip-list entry ends up
        # stripped, never present.
        env.update(self.cfg.child_env)
        if self.cfg.auth_mode == "subscription":
            for var in _SUBSCRIPTION_STRIP:
                env.pop(var, None)
            if "ANTHROPIC_API_KEY" in env:  # a raise, NEVER an assert (-O safe)
                raise EngineEnvError(
                    "ANTHROPIC_API_KEY survived the subscription-mode strip"
                )
        else:  # api_key
            if not env.get("ANTHROPIC_API_KEY"):
                raise EngineEnvError(
                    "engine.auth_mode=api_key but ANTHROPIC_API_KEY is unset — "
                    "refusing to spawn (would silently fall back to subscription "
                    "auth)"
                )
        return env

    # ── argv (test seam) ─────────────────────────────────────────────
    def _command(self, prompt_file: Path) -> list[str]:
        """The claude argv. Overridable in tests to substitute a dummy child.
        The prompt is delivered on stdin, so ``prompt_file`` is unused by the
        default command (a test dummy may consume it). Carries the ADR-21 fence
        (``--disallowedTools _DENY_TOOLS``) — the sole working restriction on the
        engine, self-contained (no reliance on ambient settings) — and the
        ADR-22 A-empty settings isolation (``--setting-sources ""``)."""
        argv = [
            self._claude_exe, "-p",
            "--output-format", "stream-json", "--verbose",
            "--no-session-persistence",
            "--permission-mode", _DEFAULT_PERMISSION_MODE,
            # ADR-22 (A-empty): the EMPTY value loads NO settings scopes, so the
            # operator's user-scope hooks (which write an unrequested knowledge/
            # tree into the child cwd — the target repo — and would trip
            # reconciler check 3 every run) never load in engine children.
            # "project,local" was rejected: it still loads project/local scope
            # from the child cwd, a cross-run injection vector. Probe-verified
            # at 2.1.211 (doc 14 §2.4 Probes 2/3: rc=0, clean 450 s,
            # apiKeySource unchanged, fence intact). The empty token MUST stay a
            # distinct argv element (list-form spawn only — never shell-join).
            # Joins the upgrade re-pin discipline: re-witness per ADR-22 on any
            # CLI version bump.
            "--setting-sources", "",
            # variadic flag: consumes tokens until the next "--flag", so it must
            # precede --model (which follows and re-anchors the parser).
            "--disallowedTools", *_DENY_TOOLS,
        ]
        if self.cfg.model and self.cfg.model != "default":
            argv += ["--model", self.cfg.model]
        return argv

    # ── the one spawn/wait/kill path ─────────────────────────────────
    def run(
        self, execution_id: str, prompt_file: Path | str, workspace: Path | str,
        *, containment: ContainmentExecutionContext | None = None,
    ) -> EngineResult:
        if _IS_WINDOWS:
            if containment is None:
                raise EngineContainmentError(
                    "Windows execution requires authoritative containment context")
            return self._run_windows_contained(
                execution_id, prompt_file, workspace, containment,
            )
        env = self._hygienic_env()  # api_key mode fails fast here, pre-spawn
        prompt_file = Path(prompt_file)
        workspace = Path(workspace)
        xdir = self._xdir(execution_id)
        xdir.mkdir(parents=True, exist_ok=True)
        transcript = xdir / "transcript.jsonl"
        stderr_log = xdir / "stderr.log"
        pidfile = self._pidfile(execution_id)
        argv = self._command(prompt_file)
        prompt_bytes = prompt_file.read_bytes()

        # POSIX: new session so os.killpg reaches the whole tree. Windows: no
        # special flag — taskkill /T walks the tree by pid.
        popen_kwargs = {} if _IS_WINDOWS else {"start_new_session": True}

        t0 = time.monotonic()
        timed_out = False
        with open(transcript, "wb") as out_f, open(stderr_log, "wb") as err_f:
            proc = subprocess.Popen(
                argv, cwd=str(workspace), env=env,
                stdin=subprocess.PIPE, stdout=out_f, stderr=err_f,
                **popen_kwargs,
            )
            # pidfile immediately after Popen — the crash-surviving record for
            # reap_orphans/is_execution_alive.
            self._write_pidfile(pidfile, proc.pid)
            # The shim becomes owned only after bounded worker resolution.

            # (a) prompt delivery, off-thread, BEFORE any pause/wait. stdin is
            # the only PIPE here (stdout/stderr are real files, out_f/err_f
            # above — the OS writes those straight to disk with no fixed
            # buffer to fill, so there is nothing to "drain" on that side at
            # any pause length). The stdin PIPE DOES have a small OS buffer,
            # so a synchronous write() would hang forever against a child
            # that never reads it — exactly what
            # test_timeout_arms_when_child_never_reads_stdin pins (a 500KB
            # prompt past the pipe buffer, a child that never reads stdin,
            # asserting the timeout still arms within cfg.timeout_seconds).
            # Writing on a bounded-join thread preserves that guarantee
            # unchanged: a stalled write is treated exactly like a stalled
            # child — timeout, kill, reap — and the sentinel is never reached
            # (there is no "prompt delivered" state to usefully pause on).
            write_err: list[BaseException] = []

            def _feed_stdin() -> None:
                try:
                    proc.stdin.write(prompt_bytes)
                    proc.stdin.close()
                except OSError as e:  # child exited / closed its end early
                    write_err.append(e)

            writer = threading.Thread(target=_feed_stdin, daemon=True)
            writer.start()
            writer.join(timeout=self.cfg.timeout_seconds)

            if writer.is_alive():
                # stdin never drained — same outcome the pre-split
                # communicate()-based code produced for this case.
                timed_out = True
                _finish_timeout_cleanup(
                    proc, err_f, self.cfg.containment_confirmation_seconds,
                )
            else:
                execution_deadline = time.monotonic() + self.cfg.timeout_seconds
                # If the shim has already exited, its process tree can no
                # longer be proved from a fresh snapshot. Keep the resolving
                # record for restart/recovery rather than guessing ownership.
                if proc.poll() is None:
                    self._resolve_and_persist_worker(
                        pidfile,
                        proc.pid,
                        deadline=execution_deadline,
                        root_alive=lambda: proc.poll() is None,
                    )

                # (b) prompt fully delivered — ITEM9_SENTINEL (test-only,
                # item-9 fault-injection control): unset in production, this
                # branch is never taken and the wait/kill path below is
                # unchanged. The child now HAS its prompt and is doing real
                # work; pausing here cannot starve it of stdin (already
                # delivered+closed) and cannot deadlock it on stdout/stderr
                # (plain files, not pipes). See _sentinel_pause.
                if os.environ.get("ITEM9_SENTINEL") == "1":
                    _sentinel_pause(xdir, os.getpid(), proc.pid, execution_id)

                # (c) Resolution and waiting share one execution deadline.
                # An unresolved worker remains conservative; it must never add
                # a second pre-timeout window before the existing kill path.
                try:
                    proc.wait(timeout=_remaining_seconds(execution_deadline))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _finish_timeout_cleanup(
                        proc, err_f, self.cfg.containment_confirmation_seconds,
                    )
        duration = time.monotonic() - t0
        pidfile.unlink(missing_ok=True)

        usage, num_turns, api_key_source = _parse_result(transcript)
        # in-band ADR-18 witness: a leaked credential shows up as a non-'none'
        # apiKeySource even though the strip happened pre-spawn. Fail loud.
        if self.cfg.auth_mode == "subscription" and api_key_source not in (
            None, "none",
        ):
            raise EngineEnvError(
                f"apiKeySource={api_key_source!r} in subscription mode — a "
                f"credential leaked into the engine despite the strip (ADR-18)"
            )

        rc = proc.returncode if proc.returncode is not None else -1
        return EngineResult(
            exit_status=rc,
            timed_out=timed_out,
            duration_s=duration,
            usage=usage,
            num_turns=num_turns,
            transcript_path=transcript,
            stderr_tail=_tail(stderr_log),
        )

    def _run_windows_contained(
        self, execution_id: str, prompt_file: Path | str, workspace: Path | str,
        containment: ContainmentExecutionContext,
    ) -> EngineResult:
        """Windows-only Job-contained execution.  Every ordinary result has a
        durable Released fact backed by positive zero Job membership."""
        import msvcrt

        env = self._hygienic_env()
        prompt_file, workspace = Path(prompt_file), Path(workspace)
        xdir = self._xdir(execution_id)
        xdir.mkdir(parents=True, exist_ok=True)
        transcript, stderr_log, pidfile = xdir / "transcript.jsonl", xdir / "stderr.log", self._pidfile(execution_id)
        prompt_bytes, argv = prompt_file.read_bytes(), self._command(prompt_file)
        try:
            self._append_containment(containment, execution_id, EventType.EXECUTION_CONTAINMENT_PREPARED, {
                "workspace_key": containment.workspace_key,
                "containment_generation": containment.containment_generation,
                "protocol_version": "windows-job-v1",
                "launch_mode": "windows-job-list-at-create",
                "controller": containment.controller,
                "lease": containment.lease,
            })
        except Exception as exc:
            # No root exists before Prepared is durable.  Still surface the
            # fail-closed boundary type rather than letting callers mistake a
            # storage exception for an ordinary engine failure.
            raise EngineContainmentError("containment Prepared was not durable") from exc
        controller: WindowsJobController | None = None
        prepared = None
        input_read = input_write = None
        writer: threading.Thread | None = None
        write_err: list[BaseException] = []
        t0, timed_out, released = time.monotonic(), False, False
        try:
            controller = WindowsJobController.create()
            input_read, input_write = os.pipe()
            with open(transcript, "wb") as out_f, open(stderr_log, "wb") as err_f:
                try:
                    prepared = controller.create_suspended_root(
                        argv, cwd=str(workspace), env=env,
                        stdio_handles=(msvcrt.get_osfhandle(input_read),
                                       msvcrt.get_osfhandle(out_f.fileno()),
                                       msvcrt.get_osfhandle(err_f.fileno())),
                    )
                except WindowsJobError as exc:
                    raise EngineContainmentError("contained root creation failed") from exc
                finally:
                    if input_read is not None:
                        os.close(input_read)
                        input_read = None
                self._append_containment(containment, execution_id, EventType.EXECUTION_CONTAINMENT_ESTABLISHED, {
                    "workspace_key": containment.workspace_key,
                    "containment_generation": containment.containment_generation,
                    "root_suspended": True,
                    "root": prepared.diagnostic_identity(),
                    "job": {"kill_on_job_close": True, "breakaway_ok": False,
                            "silent_breakaway_ok": False},
                    "membership": {"root_member": True,
                                   "member_count": prepared.initial_membership.member_count,
                                   "pids": list(prepared.initial_membership.pids)},
                })
                try:
                    self._write_pidfile(pidfile, prepared.pid)
                    prepared.resume()
                except Exception as exc:
                    self._append_unconfirmed(containment, execution_id, "resume", "resume-or-pid-record-failure", exc)
                    raise EngineContainmentError("contained root was not safely resumed") from exc

                def _feed_stdin() -> None:
                    try:
                        os.write(input_write, prompt_bytes)
                    except OSError as exc:
                        write_err.append(exc)
                    finally:
                        try: os.close(input_write)
                        except OSError: pass

                writer = threading.Thread(target=_feed_stdin, daemon=True)
                writer.start()
                writer.join(timeout=self.cfg.timeout_seconds)
                deadline = time.monotonic() + self.cfg.timeout_seconds
                if writer.is_alive():
                    timed_out = True
                else:
                    while prepared.root_wait_status() == "RUNNING" and time.monotonic() < deadline:
                        time.sleep(0.02)
                    timed_out = prepared.root_wait_status() == "RUNNING"
                if timed_out:
                    try:
                        prepared.terminate_job()
                    except TerminationRequestError as exc:
                        self._append_unconfirmed(containment, execution_id, "timeout", "terminate-job-failed", exc)
                        raise EngineContainmentError("Job termination request failed") from exc
                    outcome = prepared.wait_until_empty(
                        time.monotonic() + self.cfg.containment_confirmation_seconds)
                    if outcome.status is not EmptyMembershipStatus.EMPTY_CONFIRMED:
                        self._append_unconfirmed(containment, execution_id, "timeout", outcome.status.value.lower(), outcome.error)
                        raise EngineContainmentError("timed-out Job termination remains unconfirmed")
                    try:
                        self._wait_for_root_exit(prepared, self.cfg.containment_confirmation_seconds)
                    except EngineContainmentError as exc:
                        self._append_unconfirmed(containment, execution_id, "timeout", "root-exit-unconfirmed", exc)
                        raise
                    self._append_released(containment, execution_id, "job-member-count-zero", {"member_count": 0})
                    released = True
                    exit_status = prepared.exit_status()
                else:
                    exit_status = prepared.exit_status()
                    outcome = prepared.wait_until_empty(
                        time.monotonic() + self.cfg.containment_confirmation_seconds)
                    if outcome.status is not EmptyMembershipStatus.EMPTY_CONFIRMED:
                        self._append_unconfirmed(containment, execution_id, "normal-completion", outcome.status.value.lower(), outcome.error)
                        raise EngineContainmentError("normal root exit has unconfirmed Job termination")
                    self._append_released(containment, execution_id, "job-member-count-zero", {"member_count": 0})
                    released = True
        except EngineContainmentError:
            raise
        except Exception as exc:
            # Prepared-without-Established cannot legally become Unconfirmed;
            # its durable intent remains the conservative blocker.
            raise EngineContainmentError("Windows contained execution failed") from exc
        finally:
            if input_write is not None:
                try: os.close(input_write)
                except OSError: pass
            if prepared is not None:
                prepared.close()
            if controller is not None:
                controller.close()
            if released:
                pidfile.unlink(missing_ok=True)
        duration = time.monotonic() - t0
        usage, num_turns, api_key_source = _parse_result(transcript)
        if self.cfg.auth_mode == "subscription" and api_key_source not in (None, "none"):
            raise EngineEnvError(f"apiKeySource={api_key_source!r} in subscription mode â€” credential leaked")
        return EngineResult(exit_status=exit_status, timed_out=timed_out, duration_s=duration,
                            usage=usage, num_turns=num_turns, transcript_path=transcript,
                            stderr_tail=_tail(stderr_log))

    @staticmethod
    def _append_containment(context: ContainmentExecutionContext, execution_id: str,
                            event_type: EventType, payload: dict) -> None:
        context.append_event(Event(event_type, issue_id=context.issue_id,
                                   execution_id=execution_id, payload=payload))

    @staticmethod
    def _wait_for_root_exit(prepared, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while prepared.root_wait_status() == "RUNNING" and time.monotonic() < deadline:
            time.sleep(0.01)
        if prepared.root_wait_status() != "SIGNALED":
            raise EngineContainmentError("Job became empty but root process did not signal")

    def _append_released(self, context: ContainmentExecutionContext, execution_id: str,
                         proof_kind: str, proof: dict) -> None:
        try:
            self._append_containment(context, execution_id, EventType.EXECUTION_CONTAINMENT_RELEASED, {
                "workspace_key": context.workspace_key,
                "containment_generation": context.containment_generation,
                "proof_kind": proof_kind, "proof": proof,
                "proof_ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as exc:
            self._append_unconfirmed(context, execution_id, "release", "released-append-failed", exc)
            raise EngineContainmentError("zero membership was observed but Released was not durable") from exc

    def _append_unconfirmed(self, context: ContainmentExecutionContext, execution_id: str,
                            stage: str, category: str, error: BaseException | None) -> None:
        diagnostic = {"error_type": type(error).__name__ if error else None,
                      "detail": str(error) if error else "membership confirmation did not converge"}
        try:
            self._append_containment(context, execution_id, EventType.EXECUTION_TERMINATION_UNCONFIRMED, {
                "workspace_key": context.workspace_key,
                "containment_generation": context.containment_generation,
                "stage": stage, "category": category, "diagnostic": diagnostic,
            })
        except Exception as append_error:
            raise EngineContainmentError("termination remains unconfirmed and its durable latch could not be appended") from append_error

    # ── recovery integration ─────────────────────────────────────────
    # Margin above the execution's own wall-clock budget before a still-
    # "resolving" record is even considered for staleness — the true upper
    # bound of how long a legitimate execution (POSIX or Windows) may
    # legitimately hold a pidfile is its own timeout plus the containment
    # confirmation window; this absorbs startup/poll overhead and clock skew
    # on top of that, never used to shrink the real bound.
    _STALE_RESOLVING_MARGIN_SECONDS = 60

    def _default_stale_after_seconds(self) -> float:
        return (
            self.cfg.timeout_seconds
            + self.cfg.containment_confirmation_seconds
            + self._STALE_RESOLVING_MARGIN_SECONDS
        )

    def reap_orphans(self, *, stale_after_seconds: Optional[float] = None) -> list[str]:
        """Startup pre-step, run BEFORE ``recover()``: tree-kill any engine
        child that outlived an orchestrator crash, so ``is_execution_alive`` is
        False for every open execution when reconciler check 1 runs. Doc 03's
        "EXECUTING is abandonable, never resumed" is preserved — we kill the
        survivor and let check 1 do its normal crash-and-preserve; we never
        adopt it. This also restores the ADR-04 single-writer precondition that
        ``recover_workspace``'s stale-lock clear already presumes. Emits no
        event (doc 03 has no vocabulary for it); returns repair strings, the
        same evidence pattern as check 3's ``workspace_repairs``.

        ``stale_after_seconds`` (None → cfg-derived, see
        ``_default_stale_after_seconds``) is the age past which a still-
        "resolving" record (the crash window between ``_write_pidfile`` and
        worker resolution completing) is no longer given the benefit of the
        doubt and is classified by probing its ``shim`` identity, the same
        way a "resolved" record is classified by probing ``worker``. Exposed
        as a param solely so tests can inject a small value against a real
        record without waiting out the real cfg-derived bound."""
        repairs: list[str] = []
        if not self.artifacts_dir.exists():
            return repairs
        stale_after = (
            stale_after_seconds if stale_after_seconds is not None
            else self._default_stale_after_seconds()
        )
        now = datetime.now(timezone.utc)
        for pidfile in sorted(self.artifacts_dir.glob("*/pid")):
            rec = _read_pidfile(pidfile)
            state = _worker_liveness(rec, now=now, stale_after_seconds=stale_after)
            if state == "alive":
                pid_key = "worker" if rec.get("state") == "resolved" else "shim"
                pid = rec[pid_key]["pid"]
                _kill_tree(pid)
                repairs.append(
                    f"reaped orphan engine {pidfile.parent.name} "
                    f"(pid {pid})"
                )
                pidfile.unlink(missing_ok=True)
            elif state == "dead":
                pidfile.unlink(missing_ok=True)
            # Unknown records are retained: they do not prove ownership.
        return repairs

    def is_execution_alive(
        self, execution_id: str, *, stale_after_seconds: Optional[float] = None,
    ) -> bool:
        """Reconciler seam using the same conservative policy as reaping.

        A current match for a fully resolved worker identity is alive. A
        "resolving" record past ``stale_after_seconds`` (None → cfg-derived)
        is no longer merely retained — it is classified by probing its
        ``shim`` identity, same as ``reap_orphans``. A positively stale
        identity (resolved-and-dead, or resolving-past-timeout-and-dead) is
        removed; unresolved, malformed, fresh-resolving, or probe-ambiguous
        records are retained and report False.
        """
        stale_after = (
            stale_after_seconds if stale_after_seconds is not None
            else self._default_stale_after_seconds()
        )
        pidfile = self._pidfile(execution_id)
        rec = _read_pidfile(pidfile)
        state = _worker_liveness(rec, stale_after_seconds=stale_after)
        if state == "dead":
            pidfile.unlink(missing_ok=True)
        return state == "alive"

    # ── pidfile helpers ──────────────────────────────────────────────
    def _xdir(self, execution_id: str) -> Path:
        return self.artifacts_dir / execution_id

    def _pidfile(self, execution_id: str) -> Path:
        return self._xdir(execution_id) / "pid"

    @staticmethod
    def _write_pidfile(pidfile: Path, pid: int) -> None:
        # image captured AT SPAWN so is_execution_alive can compare identities
        # (the real image may be cmd.exe/node.exe, not claude.exe — recording it
        # rather than hardcoding a name is why the check survives that).
        _write_identity_record(pidfile, {
            "version": 2,
            "state": "resolving",
            "shim": _pid_identity(pid),
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    @staticmethod
    def _resolve_and_persist_worker(
        pidfile: Path,
        shim_pid: int,
        *,
        deadline: Optional[float] = None,
        root_alive: Optional[Callable[[], bool]] = None,
    ) -> None:
        max_seconds = _LEAF_MAX_SECONDS
        if deadline is not None:
            max_seconds = _remaining_seconds(deadline)
            if max_seconds <= 0:
                return
        descendants, worker_pid, _poll_log, _reason = _resolve_leaf_worker(
            shim_pid, max_seconds=max_seconds, root_alive=root_alive,
        )
        if worker_pid is None or worker_pid not in descendants:
            return
        if deadline is not None and _remaining_seconds(deadline) <= 0:
            return
        chain_pids = _ancestry_chain(
            shim_pid,
            worker_pid,
            timeout_seconds=_remaining_seconds(deadline) if deadline is not None else 15,
        )
        if chain_pids is None:
            return
        chain = []
        for pid in chain_pids:
            if deadline is not None and _remaining_seconds(deadline) <= 0:
                return
            chain.append(_pid_identity(
                pid,
                timeout_seconds=_remaining_seconds(deadline) if deadline is not None else 10,
            ))
        if any(identity is None for identity in chain):
            return
        shim = chain[0]
        worker = chain[-1]
        _write_identity_record(pidfile, {
            "version": 2,
            "state": "resolved",
            "shim": shim,
            "worker": worker,
            "ancestry": {"chain": chain},
            "started_at": datetime.now(timezone.utc).isoformat(),
        })


# ── module-level helpers (no instance state) ─────────────────────────

# LAYER 1 tuning (item-9 fault-injection control, ITEM9_SENTINEL=1 only).
# Confirmed 3x live against real StockPhotoAgent runs: the recorded child_pid
# (a claude.CMD shim -> cmd.exe) reliably exits shortly after handing off to
# the real worker, while work visibly continues on disk — "is child_pid
# alive" is unfalsifiable as an orphan witness. These constants bound the
# re-resolve loop that instead walks the real descendant chain to a stable
# leaf. 20 polls * 0.5s = 10s wall-clock cap; 3 consecutive identical
# "deepest pid" observations before a leaf is trusted as stable (a single
# repeat could be a poll-to-poll race, not settled process state).
_LEAF_MAX_POLLS = 20
_LEAF_MAX_SECONDS = 10.0
_LEAF_POLL_INTERVAL = 0.5
_LEAF_STABLE_COUNT = 3


def _all_pid_ppid_pairs(timeout_seconds: float = 15) -> dict[int, int]:
    """pid -> parent pid for every process currently running (Windows only,
    one CIM query per call). No psutil (deps frozen) — same constraint
    _pid_image already lives under; tasklist alone doesn't expose PPID, so
    this uses the same Win32_Process CIM class Windows itself uses to answer
    "who is whose parent", via powershell.exe (already an OS-provided tool,
    not a new dependency)."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | "
             "ForEach-Object { \"$($_.ProcessId),$($_.ParentProcessId)\" }"],
            capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    pairs: dict[int, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        pid_s, _, ppid_s = line.partition(",")
        try:
            pairs[int(pid_s)] = int(ppid_s)
        except ValueError:
            continue
    return pairs


def _walk_descendants(
    root_pid: int, *, timeout_seconds: float = 15,
) -> tuple[list[int], dict[int, int]]:
    """BFS descendants of ``root_pid`` from one process-table snapshot.
    Returns (descendant_pids, depth_of) — depth_of maps each descendant to
    its depth below root (a direct child is depth 1). No cross-poll state:
    each call is a fresh, independent snapshot, by design (the caller polls
    repeatedly to observe the chain forming, not to trust one snapshot)."""
    pairs = _all_pid_ppid_pairs(timeout_seconds)
    children: dict[int, list[int]] = {}
    for pid, ppid in pairs.items():
        children.setdefault(ppid, []).append(pid)
    depth_of: dict[int, int] = {}
    descendants: list[int] = []
    frontier = [root_pid]
    depth = 0
    while frontier:
        depth += 1
        nxt: list[int] = []
        for p in frontier:
            for c in children.get(p, []):
                if c in depth_of or c == root_pid:  # cycle guard
                    continue
                depth_of[c] = depth
                descendants.append(c)
                nxt.append(c)
        frontier = nxt
    return descendants, depth_of


def _deepest_pid(descendants: list[int], depth_of: dict[int, int]) -> Optional[int]:
    """The leaf candidate for one poll: the deepest descendant. Ties (branching,
    not expected for the linear shim->node->worker shape but not assumed away)
    break on lowest pid, deterministically."""
    if not descendants:
        return None
    max_depth = max(depth_of[p] for p in descendants)
    return min(p for p in descendants if depth_of[p] == max_depth)


def _ancestry_chain(
    root_pid: int, worker_pid: int, *, timeout_seconds: float = 15,
) -> Optional[list[int]]:
    """Return one bounded, contemporaneous root-to-worker PID chain.

    The later liveness check deliberately does not require the transient shim
    to remain alive. This snapshot is durable evidence that the worker was
    owned by that shim when the record became ``resolved``.
    """
    pairs = _all_pid_ppid_pairs(timeout_seconds)
    reverse_chain = [worker_pid]
    current = worker_pid
    for _ in range(64):
        if current == root_pid:
            return list(reversed(reverse_chain))
        parent = pairs.get(current)
        if parent is None or parent in reverse_chain:
            return None
        reverse_chain.append(parent)
        current = parent
    return None


def _remaining_seconds(deadline: float) -> float:
    """The non-negative remainder of one execution's shared deadline."""
    return max(0.0, deadline - time.monotonic())


def _resolve_leaf_worker(
    root_pid: int,
    *,
    max_polls: int = _LEAF_MAX_POLLS,
    max_seconds: float = _LEAF_MAX_SECONDS,
    poll_interval: float = _LEAF_POLL_INTERVAL,
    stable_count: int = _LEAF_STABLE_COUNT,
    root_alive: Optional[Callable[[], bool]] = None,
) -> tuple[list[int], Optional[int], list[dict], Optional[str]]:
    """Bounded re-resolve loop (LAYER 1). Repeatedly walks root_pid's
    descendant chain until the deepest pid repeats for ``stable_count``
    consecutive polls (settled — the shim has handed off and the real worker
    is up), or the poll/time cap is hit first. Returns (last_descendant_pids,
    leaf_worker_pid, poll_log, reason) — leaf_worker_pid is None (never the
    shim as a silent fallback) if it never stabilized; ``reason`` explains
    why, only set when leaf_worker_pid is None."""
    poll_log: list[dict] = []
    last_leaf: Optional[int] = None
    stable_run = 0
    deadline = time.monotonic() + max_seconds
    descendants: list[int] = []
    for i in range(1, max_polls + 1):
        remaining = _remaining_seconds(deadline)
        if remaining <= 0:
            break
        descendants, depth_of = _walk_descendants(
            root_pid, timeout_seconds=remaining,
        )
        leaf = _deepest_pid(descendants, depth_of)
        poll_log.append({"poll": i, "descendant_pids": list(descendants), "leaf": leaf})
        if leaf is None:
            if root_alive is not None and not root_alive():
                return descendants, None, poll_log, "root exited before worker resolution"
            if _pid_exists(root_pid, timeout_seconds=remaining) is False:
                return descendants, None, poll_log, "root exited before worker resolution"
        if leaf is not None and leaf == last_leaf:
            stable_run += 1
        else:
            stable_run = 1 if leaf is not None else 0
        last_leaf = leaf
        if stable_run >= stable_count:
            return descendants, leaf, poll_log, None
        remaining = _remaining_seconds(deadline)
        if i >= max_polls or remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))
    reason = (
        f"leaf did not repeat for {stable_count} consecutive polls within "
        f"{len(poll_log)} poll(s) / {max_seconds}s cap"
    )
    return descendants, None, poll_log, reason


def _sentinel_pause(
    xdir: Path, orchestrator_pid: int, child_pid: int, execution_id: str
) -> None:
    """ITEM9_SENTINEL=1 only (see the single call site in ``run()``). Fires
    AFTER the pidfile is written (child confirmed live, pid durable) and
    BEFORE ``proc.communicate()`` (i.e. before ExecutionFinished can ever be
    emitted back in loop.py) — the exact window a real orphan can exist in.
    Runs LAYER 1's bounded re-resolve loop against ``child_pid`` (the shim)
    to find the real leaf worker BEFORE the chain can change further, writes
    a witnessed-ready marker naming the whole chain, then blocks on an
    external ``sentinel_resume`` file. Never kills anything itself — a fault
    -injection harness (or a human) does that from outside, at leisure,
    against the pids this marker names, instead of racing real wall-clock
    execution time or trusting a shim pid that may already be gone."""
    marker = xdir / "sentinel_ready"
    resume = xdir / "sentinel_resume"
    chain_log = xdir / "sentinel_chain_log.jsonl"
    hold_ready = xdir / "hold_ready"

    descendants, leaf_worker_pid, poll_log, reason = _resolve_leaf_worker(child_pid)
    with open(chain_log, "w", encoding="utf-8") as f:
        for entry in poll_log:
            f.write(json.dumps(entry) + "\n")

    # Orchestrator-side companion hold process (Group-S hold-alive redesign,
    # item 9). Deliberately a child of THIS process (os.getpid()), never of
    # child_pid/proc.pid — it exists to give the external witness a
    # STRUCTURALLY guaranteed-alive pid (it cannot exit before `resume`
    # exists, by construction), decoupled from however long the real
    # descendants of child_pid happen to live. _resolve_leaf_worker(child_pid)
    # above is UNCHANGED and still the production-shape witness/
    # shape-falsification instrument — this addition never touches that walk.
    hold_script = (
        "import pathlib, time;"
        f"pathlib.Path(r'{hold_ready}').touch();"
        f"\nwhile not pathlib.Path(r'{resume}').exists():"
        "\n    time.sleep(0.2)"
    )
    hold_proc = subprocess.Popen([sys.executable, "-c", hold_script])

    # Popen returning a pid only proves the process was CREATED, not that it
    # has run past the initial `touch` yet — wait (bounded) for hold_ready
    # before advertising hold_pid, so the witness gate's guarantee holds at
    # WRITE time, not just eventually. A stuck/failed hold child surfaces as
    # a raised error here, not a silent race.
    hold_deadline = time.monotonic() + 2.0
    while not hold_ready.exists():
        if time.monotonic() >= hold_deadline:
            raise RuntimeError(
                f"hold_proc (pid={hold_proc.pid}) did not reach its loop "
                f"body within 2s — hold_ready never appeared"
            )
        time.sleep(0.05)

    marker.write_text(json.dumps({
        "orchestrator_pid": orchestrator_pid,
        "child_pid": child_pid,
        "execution_id": execution_id,
        "paused_at": datetime.now(timezone.utc).isoformat(),
        "descendant_pids": descendants,
        "leaf_worker_pid": leaf_worker_pid,
        "leaf_worker_reason": reason,
        "hold_pid": hold_proc.pid,
        "chain_log_path": str(chain_log),
    }), encoding="utf-8")
    print(f"[sentinel] paused: orchestrator_pid={orchestrator_pid} "
          f"child_pid={child_pid} leaf_worker_pid={leaf_worker_pid} "
          f"execution_id={execution_id} hold_pid={hold_proc.pid}", flush=True)
    while not resume.exists():
        time.sleep(0.5)


# LAYER 2 (Group-S witness helper, built now, not called against
# StockPhotoAgent this phase): captures a work-target's mtime + content hash
# at call time, independent of any process-liveness signal — the whole
# reason Layer 1 exists is that process pids alone proved unreliable, so
# Group S's pre-kill/post-kill/post-interval witness on the actual edited
# file is a second, orthogonal discriminator, not a replacement for Layer 1.
def capture_work_liveness(path: Path | str) -> dict:
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return {"path": str(p), "exists": False, "mtime": None, "sha256": None}
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return {
        "path": str(p), "exists": True,
        "mtime": stat.st_mtime, "sha256": h.hexdigest(),
    }


def _finish_timeout_cleanup(
    proc: subprocess.Popen, stderr_log, confirmation_seconds: float,
) -> None:
    """Legacy non-Windows tree cleanup with an explicit reap policy.

    Windows Job-contained executions do not call this helper: their boundary
    is ``TerminateJobObject`` followed by a positive Job-empty observation.
    """
    kill_error = _kill_tree(proc.pid)
    if kill_error is not None:
        stderr_log.write(f"[timeout cleanup] {kill_error}\n".encode("utf-8"))
        stderr_log.flush()
    try:
        proc.wait(timeout=confirmation_seconds)
    except subprocess.TimeoutExpired as exc:
        detail = kill_error or "process tree termination was not confirmed"
        raise EngineError(
            f"timeout cleanup did not reap pid {proc.pid} within "
            f"{confirmation_seconds}s: {detail}"
        ) from exc


def _kill_tree(pid: int) -> Optional[str]:
    """Uncatchably terminate ``pid`` and its descendants (mirrors
    tests/crash/worker.py::_hard_kill_self's SIGKILL/TerminateProcess). Windows:
    ``taskkill /F /T`` (force, tree) — a nonzero rc when the pid already exited
    in the race window is TOLERATED, not checked; the caller reaps unconditionally
    afterwards. POSIX: SIGKILL the process group (spawned with start_new_session)."""
    # A nonzero taskkill result is diagnostic data, not proof that the child
    # remains alive: the caller performs a bounded direct-child reap next.
    try:
        if _IS_WINDOWS:
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
            )
            if completed.returncode != 0:
                stdout = completed.stdout.strip()[-1024:]
                stderr = completed.stderr.strip()[-1024:]
                return (
                    f"taskkill rc={completed.returncode} for pid {pid}; "
                    f"stdout={stdout!r}; stderr={stderr!r}"
                )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"tree-kill invocation failed for pid {pid}: {exc}"
    return None


def _pid_image(pid: int, *, timeout_seconds: float = 10) -> Optional[str]:
    """Current image/comm name of ``pid``, or None if it is not running. No
    psutil (deps frozen)."""
    try:
        if _IS_WINDOWS:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
            ).stdout.strip()
            if not out or not out.startswith('"'):
                return None  # "INFO: No tasks..." => not running
            return out.split('","', 1)[0].strip('"')  # first CSV field = image
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
        ).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _pid_creation_time(pid: int, *, timeout_seconds: float = 10) -> Optional[str]:
    """Creation time is the second anti-PID-reuse discriminator."""
    try:
        if _IS_WINDOWS:
            out = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter 'ProcessId = "
                 + str(pid) + "' | Select-Object -ExpandProperty CreationDate"],
                capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
            ).stdout.strip()
        else:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
            ).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _pid_identity(pid: int, *, timeout_seconds: float = 10) -> Optional[dict]:
    image = _pid_image(pid, timeout_seconds=timeout_seconds)
    creation_time = _pid_creation_time(pid, timeout_seconds=timeout_seconds)
    if image is None or creation_time is None:
        return None
    return {"pid": pid, "image": image, "creation_time": creation_time}


def _valid_identity(identity: object) -> bool:
    if not isinstance(identity, dict):
        return False
    pid = identity.get("pid")
    image = identity.get("image")
    creation_time = identity.get("creation_time")
    return (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and isinstance(image, str)
        and bool(image)
        and isinstance(creation_time, str)
        and bool(creation_time)
    )


def _pid_exists(pid: int, *, timeout_seconds: float = 10) -> Optional[bool]:
    """Return True/False for an observed process, or None when probing fails."""
    try:
        if _IS_WINDOWS:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
            ).stdout.strip()
            return bool(out and out.startswith('"'))
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid="],
            capture_output=True, text=True, timeout=max(0.01, timeout_seconds),
        ).stdout.strip()
        return bool(out)
    except (OSError, subprocess.SubprocessError):
        return None


def _identity_liveness(identity: object) -> str:
    """Classify a full identity without converting probe failure into death."""
    if not _valid_identity(identity):
        return "unknown"
    pid = identity["pid"]
    image = _pid_image(pid)
    if image is None:
        exists = _pid_exists(pid)
        return "dead" if exists is False else "unknown"
    if image != identity["image"]:
        return "dead"
    creation_time = _pid_creation_time(pid)
    if creation_time is None:
        exists = _pid_exists(pid)
        return "dead" if exists is False else "unknown"
    return "alive" if creation_time == identity["creation_time"] else "dead"


def _legacy_liveness(rec: dict) -> str:
    """Legacy shim-only records are never sufficient evidence to kill."""
    pid = rec.get("pid")
    image = rec.get("image")
    if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(image, str):
        return "unknown"
    current = _pid_image(pid)
    if current is None:
        exists = _pid_exists(pid)
        return "dead" if exists is False else "unknown"
    return "unknown" if current == image else "dead"

def _read_pidfile(pidfile: Path) -> Optional[dict]:
    try:
        return json.loads(pidfile.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_identity_record(pidfile: Path, record: dict) -> None:
    """Durably replace a record; readers see either old or complete new JSON."""
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    tmpfile: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", delete=False, dir=pidfile.parent,
            prefix=f".{pidfile.name}.", suffix=".tmp",
        ) as f:
            tmpfile = Path(f.name)
            json.dump(record, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        # Windows requires the named file to be closed before replacement.
        os.replace(tmpfile, pidfile)
        tmpfile = None
    finally:
        if tmpfile is not None:
            try:
                tmpfile.unlink(missing_ok=True)
            except OSError:
                pass


def _stale_resolving(rec: dict, *, now: datetime, stale_after_seconds: float) -> Optional[bool]:
    """True if a v2 ``resolving`` record's ``started_at`` is older than
    ``stale_after_seconds`` relative to ``now``. None if ``started_at`` is
    missing or unparseable — malformed timestamps must not be treated as
    infinitely stale (that would invert the conservative-on-ambiguity policy
    every other branch here follows)."""
    started_at = rec.get("started_at")
    if not isinstance(started_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    if started.tzinfo is None:
        return None
    return (now - started).total_seconds() > stale_after_seconds


def _worker_liveness(
    rec: object, *, now: Optional[datetime] = None, stale_after_seconds: float = 0.0,
) -> str:
    """Return alive, dead, or unknown under the shared ownership policy.

    Unknown is intentionally non-destructive: a fresh resolving, malformed,
    or legacy-live record cannot prove which process is the owned worker.

    A ``resolving`` record past ``stale_after_seconds`` (age measured from
    ``started_at``) is no longer given that benefit: the crash window between
    ``_write_pidfile`` and worker resolution completing (or, on Windows, the
    entire legitimate run — see ``_run_windows_contained``) is classified by
    probing the one identity such a record has, ``shim``, exactly as a
    ``resolved`` record is classified by probing ``worker``. ``now`` defaults
    to the current UTC time; callers pass it explicitly only in tests that
    need a fixed instant.
    """
    if not isinstance(rec, dict):
        return "unknown"
    if rec.get("version") == 2:
        if rec.get("state") == "resolving":
            stale = _stale_resolving(
                rec, now=now or datetime.now(timezone.utc),
                stale_after_seconds=stale_after_seconds,
            )
            if not stale:  # fresh (False) or unparseable (None) — unchanged
                return "unknown"
            shim = rec.get("shim")
            if not _valid_identity(shim):
                return "unknown"
            return _identity_liveness(shim)
        if rec.get("state") != "resolved":
            return "unknown"
        worker = rec.get("worker")
        shim = rec.get("shim")
        ancestry = rec.get("ancestry")
        if (
            not _valid_identity(worker)
            or not _valid_identity(shim)
            or not isinstance(ancestry, dict)
            or not isinstance(ancestry.get("chain"), list)
        ):
            return "unknown"
        chain = ancestry["chain"]
        if (
            len(chain) < 2
            or any(not _valid_identity(identity) for identity in chain)
            or chain[0] != shim
            or chain[-1] != worker
            or len({identity["pid"] for identity in chain}) != len(chain)
        ):
            return "unknown"
        return _identity_liveness(worker)

    # v1 records stored only the launcher. A live launcher is ambiguous, but a
    # missing/reused one is safely stale and may be removed.
    if "pid" in rec and "image" in rec:
        return _legacy_liveness(rec)
    return "unknown"


def _parse_result(
    transcript: Path,
) -> tuple[dict, Optional[int], Optional[str]]:
    """Advisory extraction from the stream-json transcript. Best-effort: any
    parse failure yields empty usage / None and NEVER raises — EngineResult is
    advisory (ADR-07) and must not gate on a malformed or partial transcript
    (a timeout kill leaves a valid partial JSONL, hence line-by-line parsing)."""
    usage: dict = {}
    num_turns: Optional[int] = None
    api_key_source: Optional[str] = None
    try:
        text = transcript.read_text(encoding="utf-8")
    except OSError:
        return usage, num_turns, api_key_source
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue  # partial/truncated final line after a kill — skip
        kind = obj.get("type")
        if kind == "system" and obj.get("subtype") == "init":
            api_key_source = obj.get("apiKeySource")
        elif kind == "result":
            u = obj.get("usage") or {}
            usage = {
                "input_tokens": u.get("input_tokens"),
                "output_tokens": u.get("output_tokens"),
                "dollars": obj.get("total_cost_usd"),
            }
            nt = obj.get("num_turns")
            num_turns = nt if isinstance(nt, int) else None
    return usage, num_turns, api_key_source


def _tail(path: Path, n: int = 2048) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-n:].decode("utf-8", errors="replace")
