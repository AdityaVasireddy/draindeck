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

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
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
                _kill_tree(proc.pid)
                proc.wait()
            else:
                # (b) prompt fully delivered — ITEM9_SENTINEL (test-only,
                # item-9 fault-injection control): unset in production, this
                # branch is never taken and the wait/kill path below is
                # unchanged. The child now HAS its prompt and is doing real
                # work; pausing here cannot starve it of stdin (already
                # delivered+closed) and cannot deadlock it on stdout/stderr
                # (plain files, not pipes). See _sentinel_pause.
                if os.environ.get("ITEM9_SENTINEL") == "1":
                    _sentinel_pause(xdir, os.getpid(), proc.pid, execution_id)

                # (c) wait/timeout starts counting HERE, strictly after any
                # pause returns — cfg.timeout_seconds is the wall-clock
                # runaway backstop on the CHILD's own work, never on how long
                # a test-only sentinel held it paused first.
                try:
                    proc.wait(timeout=self.cfg.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _kill_tree(proc.pid)
                    proc.wait()  # unconditional reap; guarantees returncode
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


def _all_pid_ppid_pairs() -> dict[int, int]:
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
            capture_output=True, text=True, timeout=15,
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


def _walk_descendants(root_pid: int) -> tuple[list[int], dict[int, int]]:
    """BFS descendants of ``root_pid`` from one process-table snapshot.
    Returns (descendant_pids, depth_of) — depth_of maps each descendant to
    its depth below root (a direct child is depth 1). No cross-poll state:
    each call is a fresh, independent snapshot, by design (the caller polls
    repeatedly to observe the chain forming, not to trust one snapshot)."""
    pairs = _all_pid_ppid_pairs()
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


def _resolve_leaf_worker(
    root_pid: int,
    *,
    max_polls: int = _LEAF_MAX_POLLS,
    max_seconds: float = _LEAF_MAX_SECONDS,
    poll_interval: float = _LEAF_POLL_INTERVAL,
    stable_count: int = _LEAF_STABLE_COUNT,
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
        descendants, depth_of = _walk_descendants(root_pid)
        leaf = _deepest_pid(descendants, depth_of)
        poll_log.append({"poll": i, "descendant_pids": list(descendants), "leaf": leaf})
        if leaf is not None and leaf == last_leaf:
            stable_run += 1
        else:
            stable_run = 1 if leaf is not None else 0
        last_leaf = leaf
        if stable_run >= stable_count:
            return descendants, leaf, poll_log, None
        if i >= max_polls or time.monotonic() >= deadline:
            break
        time.sleep(poll_interval)
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
