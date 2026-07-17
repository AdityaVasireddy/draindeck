"""ClaudeHeadlessEngine — the v1 execution engine (ADR-08 concrete, no ABC).

Spawns ``claude -p`` in the target workspace, enforces the wall-clock timeout
and ADR-18 env hygiene, and returns an ADVISORY ``EngineResult``. The real
output of an execution is the WORKSPACE MUTATION, observed by the orchestrator
through RepositoryAdapter (ADR-02/07): an engine can lie in its summary, never
in the diff. This wrapper therefore never touches git and never appends events
— it stays strictly on the subprocess/artifacts side; RepositoryAdapter (via
recovery/bindings.py and the orchestrator) owns every git contact, and doc 03
§5 owns every event.

VERIFIED CLI contract (claude 2.1.207, Windows, 2026-07-11; re-verified at
2.1.211 on 2026-07-16 — see the ADR-21 fence block below and doc 14 §2 —
re-pin on upgrade):
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
  * On Windows ``claude`` is an npm ``.CMD`` shim: it MUST be resolved with
    ``shutil.which`` (a bare "claude" raises FileNotFoundError) and runs under
    cmd.exe, so the real node/claude process and its tool subprocesses are
    DESCENDANTS of ``proc.pid`` — tree-kill is required, not a single kill.

pid discipline (I-h, verified against tests/crash/{worker,harness}.py): the
event log records the ORCHESTRATOR/WRITER pid (``os.getpid()``) in both
ExecutionSpawned and ExecutionFinished; I-h asserts they match as the
never-replayed rule. That pid is NEVER the engine child pid. The engine child
pid lives only in the on-disk pidfile, so a synchronous ``run()`` with no pid
on ``EngineResult`` satisfies I-h unchanged.

KNOWN LIMITATION (Windows tree-kill): ``taskkill /F /T`` walks the parent-child
tree AT KILL TIME. A grandchild whose parent already exited is reparented and
escapes the sweep; since only the direct child pid is in the pidfile,
``reap_orphans``/``is_execution_alive`` cannot observe such a survivor either.
Reconciler check 3 (dirty workspace) is the partial backstop for anything the
survivor dirtied BEFORE recovery ran; a survivor that dirties the workspace
AFTER recovery completes is invisible until the next ``is_dirty()`` witness.
Accepted for v1 — no psutil (deps are frozen to pyyaml/pydantic/pytest).
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import EngineCfg

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

# "acceptEdits" auto-accepts file-edit tool calls without a TTY prompt (-p mode
# has none to show). It does NOT act as a fence — see _DENY_TOOLS below.
_DEFAULT_PERMISSION_MODE = "acceptEdits"

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
        self, execution_id: str, prompt_file: Path | str, workspace: Path | str
    ) -> EngineResult:
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
            try:
                # communicate covers stdin-write + wait + timeout as ONE
                # operation — no bare stdin.write() that could block before the
                # timeout arms (stdout/stderr are files, nothing else to drain).
                proc.communicate(
                    input=prompt_bytes, timeout=self.cfg.timeout_seconds
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc.pid)
                proc.communicate()  # unconditional reap; guarantees returncode
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

    # ── recovery integration ─────────────────────────────────────────
    def reap_orphans(self) -> list[str]:
        """Startup pre-step, run BEFORE ``recover()``: tree-kill any engine
        child that outlived an orchestrator crash, so ``is_execution_alive`` is
        False for every open execution when reconciler check 1 runs. Doc 03's
        "EXECUTING is abandonable, never resumed" is preserved — we kill the
        survivor and let check 1 do its normal crash-and-preserve; we never
        adopt it. This also restores the ADR-04 single-writer precondition that
        ``recover_workspace``'s stale-lock clear already presumes. Emits no
        event (doc 03 has no vocabulary for it); returns repair strings, the
        same evidence pattern as check 3's ``workspace_repairs``."""
        repairs: list[str] = []
        if not self.artifacts_dir.exists():
            return repairs
        for pidfile in sorted(self.artifacts_dir.glob("*/pid")):
            rec = _read_pidfile(pidfile)
            if rec is not None and _alive_by_record(rec):
                _kill_tree(rec["pid"])
                repairs.append(
                    f"reaped orphan engine {pidfile.parent.name} "
                    f"(pid {rec['pid']})"
                )
            pidfile.unlink(missing_ok=True)
        return repairs

    def is_execution_alive(self, execution_id: str) -> bool:
        """Reconciler seam. True only if the pidfile exists, the pid is running,
        AND its current image matches the image recorded at spawn (defeats PID
        reuse without psutil). Any mismatch/missing → False, and the stale
        pidfile is removed. No locks: doc 01 guarantees single-writer,
        sequential execution, and recovery is startup-only, so there is no
        concurrent access to guard."""
        pidfile = self._pidfile(execution_id)
        rec = _read_pidfile(pidfile)
        if rec is None:
            return False
        if _alive_by_record(rec):
            return True
        pidfile.unlink(missing_ok=True)  # stale — clean up
        return False

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
        pidfile.write_text(
            json.dumps({
                "pid": pid,
                "image": _pid_image(pid),
                "started_at": datetime.now(timezone.utc).isoformat(),
            }),
            encoding="utf-8",
        )


# ── module-level helpers (no instance state) ─────────────────────────
def _kill_tree(pid: int) -> None:
    """Uncatchably terminate ``pid`` and its descendants (mirrors
    tests/crash/worker.py::_hard_kill_self's SIGKILL/TerminateProcess). Windows:
    ``taskkill /F /T`` (force, tree) — a nonzero rc when the pid already exited
    in the race window is TOLERATED, not checked; the caller reaps unconditionally
    afterwards. POSIX: SIGKILL the process group (spawned with start_new_session)."""
    try:
        if _IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=15,
            )
        else:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass  # already dead / race — the unconditional reap handles it


def _pid_image(pid: int) -> Optional[str]:
    """Current image/comm name of ``pid``, or None if it is not running. No
    psutil (deps frozen)."""
    try:
        if _IS_WINDOWS:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if not out or not out.startswith('"'):
                return None  # "INFO: No tasks..." => not running
            return out.split('","', 1)[0].strip('"')  # first CSV field = image
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _read_pidfile(pidfile: Path) -> Optional[dict]:
    try:
        return json.loads(pidfile.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive_by_record(rec: dict) -> bool:
    pid = rec.get("pid")
    if not isinstance(pid, int):
        return False
    current = _pid_image(pid)
    if current is None:
        return False  # not running
    recorded = rec.get("image")
    if recorded and current != recorded:
        return False  # pid reuse — a different executable holds the pid now
    return True


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
