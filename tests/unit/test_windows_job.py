"""Synthetic Windows Job controller tests; never invoke the runtime or providers."""
from __future__ import annotations

import os
import json
import sys
import time
from types import SimpleNamespace
from unittest import mock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from runtime.engine import windows_job as job  # noqa: E402


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests")


def _deadline(seconds: float = 3.0) -> float:
    return time.monotonic() + seconds


def _sleeping_root(seconds: float = 10.0) -> list[str]:
    return [sys.executable, "-c", f"import time; time.sleep({seconds!r})"]


def test_unnamed_kill_on_close_controller_and_suspended_member_are_verified():
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        # This root exits immediately if it ever executes.  Seeing it alive
        # while unresumed directly demonstrates suspended-at-create behavior.
        prepared = controller.create_suspended_root([sys.executable, "-c", "raise SystemExit(0)"])
        assert prepared.configuration_witness.unnamed
        assert prepared.configuration_witness.kill_on_job_close
        assert not prepared.configuration_witness.breakaway_ok
        assert not prepared.configuration_witness.silent_breakaway_ok
        assert not prepared.configuration_witness.handle_inheritable
        assert prepared.root_suspended
        assert prepared.launch_plan is not None
        assert prepared.launch_plan.kind is job.LaunchKind.NATIVE
        assert prepared.launch_plan.application_name == sys.executable
        assert prepared.pid in prepared.initial_membership.pids
        assert prepared.root_wait_status() == "RUNNING"
    finally:
        if prepared:
            prepared.close()
        controller.close()


def test_resume_captures_ordinary_descendant_and_normal_completion_proves_empty():
    source = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(.2)']);"
        "time.sleep(.4)"
    )
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root([sys.executable, "-c", source])
        prepared.resume()
        time.sleep(0.05)
        observed = prepared.membership()
        assert prepared.pid in observed.pids
        assert observed.member_count >= 2
        result = prepared.wait_until_empty(_deadline())
        assert result.status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
        assert result.observation is not None and result.observation.empty
    finally:
        if prepared:
            prepared.close()
        controller.close()


def test_controlled_stdio_allowlist_preserves_io_and_excludes_inheritable_sentinel():
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    sentinel_read, sentinel_write = os.pipe()
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        # A deliberately inheritable unrelated handle is a negative control:
        # HANDLE_LIST must keep it out even though bInheritHandles=True.
        import ctypes
        import msvcrt
        sentinel_handle = msvcrt.get_osfhandle(sentinel_write)
        ctypes.WinDLL("kernel32", use_last_error=True).SetHandleInformation(sentinel_handle, 1, 1)
        source = (
            "import os,sys\n"
            "h=int(sys.argv[1])\n"
            "data=sys.stdin.read()\n"
            "try:\n"
            "    os.write(h,b'LEAK'); sentinel='leaked'\n"
            "except OSError:\n"
            "    sentinel='blocked'\n"
            "sys.stdout.write('OUT:'+data+':'+sentinel)\n"
            "sys.stderr.write('ERR')\n"
        )
        prepared = controller.create_suspended_root(
            [sys.executable, "-c", source, str(sentinel_handle)],
            stdio_handles=(msvcrt.get_osfhandle(stdin_read),
                           msvcrt.get_osfhandle(stdout_write),
                           msvcrt.get_osfhandle(stderr_write)),
        )
        assert prepared.root_suspended
        assert prepared.pid in prepared.initial_membership.pids
        prepared.resume()
        os.close(stdin_read); os.close(stdout_write); os.close(stderr_write)
        os.write(stdin_write, b"hello")
        os.close(stdin_write)
        os.close(sentinel_write)
        assert os.read(stdout_read, 128) == b"OUT:hello:blocked"
        assert os.read(stderr_read, 128) == b"ERR"
        assert os.read(sentinel_read, 128) == b""
        assert prepared.wait_until_empty(_deadline()).status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
    finally:
        for fd in (stdin_read, stdin_write, stdout_read, stdout_write, stderr_read, stderr_write, sentinel_read, sentinel_write):
            try: os.close(fd)
            except OSError: pass
        if prepared:
            prepared.close()
        controller.close()


def test_unsafe_batch_argument_fails_before_any_root_is_created(tmp_path):
    batch = _batch_fixture(tmp_path)
    controller = job.WindowsJobController.create()
    try:
        with pytest.raises(job.LaunchPlanError, match="percent"):
            controller.create_suspended_root([str(batch), "unsafe%argument"])
        assert controller.membership().empty
    finally:
        controller.close()


def test_launch_plan_keeps_native_executables_direct_and_wraps_batch_files():
    native = job.plan_windows_launch([r"C:\Tools\runner.exe", "plain value"])
    assert native.kind is job.LaunchKind.NATIVE
    assert native.application_name == r"C:\Tools\runner.exe"
    assert "cmd.exe" not in native.command_line.lower()

    batch = job.plan_windows_launch(
        [r"C:\Batch Space\runner.CMD", "plain value", ""],
        cmd_path=r"C:\Windows\System32\cmd.exe",
    )
    assert batch.kind is job.LaunchKind.BATCH
    assert batch.application_name == r"C:\Windows\System32\cmd.exe"
    assert batch.command_line.startswith('"C:\\Windows\\System32\\cmd.exe" /d /v:off /s /c ')
    assert r"C:\Batch Space\runner.CMD" in batch.command_line


def test_batch_launch_plan_rejects_percent_and_quote_before_process_creation():
    with pytest.raises(job.LaunchPlanError, match="percent"):
        job.plan_windows_launch([r"C:\x\runner.cmd", "has%percent"], cmd_path=r"C:\cmd.exe")
    with pytest.raises(job.LaunchPlanError, match="quote"):
        job.plan_windows_launch([r"C:\x\runner.cmd", 'has"quote'], cmd_path=r"C:\cmd.exe")


def _batch_fixture(tmp_path):
    launcher_dir = tmp_path / "batch launcher space"
    launcher_dir.mkdir()
    capture = launcher_dir / "capture.py"
    capture.write_text(
        "import json, os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "Path(os.environ['T7_BATCH_STARTED']).write_text('started')\n"
        "print(json.dumps(sys.argv[1:]), flush=True)\n"
        "print('batch-stderr', file=sys.stderr, flush=True)\n"
        "if os.environ.get('T7_BATCH_CHILD') == '1':\n"
        "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.35)'])\n"
        "time.sleep(float(os.environ.get('T7_BATCH_HOLD', '.45')))\n",
        encoding="utf-8",
    )
    batch = launcher_dir / "synthetic runner.CMD"
    batch.write_text(
        "@echo off\r\n"
        "\"%T7_BATCH_PYTHON%\" \"%~dp0capture.py\" %*\r\n",
        encoding="utf-8",
    )
    return batch


def _batch_env(tmp_path, *, hold=".45", child=True):
    return {
        "T7_BATCH_PYTHON": sys.executable,
        "T7_BATCH_STARTED": str(tmp_path / "started.txt"),
        "T7_BATCH_HOLD": hold,
        "T7_BATCH_CHILD": "1" if child else "0",
    }


def test_batch_root_is_suspended_then_preserves_stdio_arguments_and_descendant_capture(tmp_path):
    import msvcrt
    batch = _batch_fixture(tmp_path)
    env = _batch_env(tmp_path)
    arguments = ["plain", "space value", "", "ends-in-backslash\\", "amp&pipe|<>", "bang!caret^paren()"]
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root(
            [str(batch), *arguments], env=env,
            stdio_handles=(msvcrt.get_osfhandle(stdin_read),
                           msvcrt.get_osfhandle(stdout_write),
                           msvcrt.get_osfhandle(stderr_write)),
        )
        assert prepared.root_suspended
        assert prepared.launch_plan is not None
        assert prepared.launch_plan.kind is job.LaunchKind.BATCH
        assert prepared.launch_plan.application_name.lower().endswith("\\system32\\cmd.exe")
        assert prepared.pid in prepared.initial_membership.pids
        assert not (tmp_path / "started.txt").exists()
        prepared.resume()
        os.close(stdin_read); stdin_read = None
        os.close(stdout_write); stdout_write = None
        os.close(stderr_write); stderr_write = None
        os.close(stdin_write); stdin_write = None
        deadline = _deadline()
        while not (tmp_path / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (tmp_path / "started.txt").exists()
        time.sleep(.05)
        assert prepared.membership().member_count >= 2
        stdout = os.read(stdout_read, 4096)
        stderr = os.read(stderr_read, 4096)
        assert json.loads(stdout.decode("utf-8")) == arguments
        assert stderr == b"batch-stderr\r\n"
        assert prepared.wait_until_empty(_deadline()).status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
    finally:
        for fd in (stdin_read, stdin_write, stdout_read, stdout_write, stderr_read, stderr_write):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        if prepared:
            prepared.close()
        controller.close()


def test_batch_metacharacter_argument_does_not_inject_an_extra_command(tmp_path):
    import msvcrt
    batch = _batch_fixture(tmp_path)
    env = _batch_env(tmp_path, child=False)
    marker = tmp_path / "injected.txt"
    argument = f"safe&echo injected>{marker}"
    stdin_fd = os.open(os.devnull, os.O_RDONLY)
    stdout_read, stdout_write = os.pipe()
    stderr_read, stderr_write = os.pipe()
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root(
            [str(batch), argument], env=env,
            stdio_handles=(msvcrt.get_osfhandle(stdin_fd),
                           msvcrt.get_osfhandle(stdout_write),
                           msvcrt.get_osfhandle(stderr_write)),
        )
        prepared.resume()
        os.close(stdout_write); stdout_write = None
        os.close(stderr_write); stderr_write = None
        assert json.loads(os.read(stdout_read, 4096).decode("utf-8")) == [argument]
        assert not marker.exists()
        assert prepared.wait_until_empty(_deadline()).status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
    finally:
        for fd in (stdin_fd, stdout_read, stdout_write, stderr_read, stderr_write):
            if fd is not None:
                try: os.close(fd)
                except OSError: pass
        if prepared:
            prepared.close()
        controller.close()


def test_batch_timeout_terminates_cmd_and_descendants_then_proves_empty(tmp_path):
    batch = _batch_fixture(tmp_path)
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root([str(batch)], env=_batch_env(tmp_path, hold="10"))
        prepared.resume()
        deadline = _deadline()
        while not (tmp_path / "started.txt").exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (tmp_path / "started.txt").exists()
        assert prepared.membership().member_count >= 2
        prepared.terminate_job()
        result = prepared.wait_until_empty(_deadline())
        assert result.status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
        root_deadline = _deadline()
        while prepared.root_wait_status() != "SIGNALED" and time.monotonic() < root_deadline:
            time.sleep(.02)
        assert prepared.root_wait_status() == "SIGNALED"
    finally:
        if prepared:
            prepared.close()
        controller.close()


def test_terminate_job_requires_and_then_observes_positive_empty_membership():
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root(_sleeping_root())
        prepared.resume()
        prepared.terminate_job()
        result = prepared.wait_until_empty(_deadline())
        assert result.status is job.EmptyMembershipStatus.EMPTY_CONFIRMED
        assert result.observation is not None and result.observation.member_count == 0
    finally:
        if prepared:
            prepared.close()
        controller.close()


def test_last_job_handle_close_terminates_live_and_suspended_members():
    for resume in (True, False):
        controller = job.WindowsJobController.create()
        prepared = controller.create_suspended_root(_sleeping_root())
        try:
            if resume:
                prepared.resume()
            controller.close()
            deadline = _deadline()
            while prepared.root_wait_status() != "SIGNALED" and time.monotonic() < deadline:
                time.sleep(0.02)
            assert prepared.root_wait_status() == "SIGNALED"
        finally:
            prepared.close()
            controller.close()


def test_member_requested_breakaway_child_remains_in_configured_job():
    source = (
        "import subprocess,sys,time;"
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(.4)'],"
        "creationflags=0x01000000);time.sleep(.5)"
    )
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root([sys.executable, "-c", source])
        prepared.resume()
        time.sleep(0.08)
        assert prepared.membership().member_count >= 2
    finally:
        if prepared:
            prepared.terminate_job()
            prepared.wait_until_empty(_deadline())
            prepared.close()
        controller.close()


def test_double_resume_is_rejected():
    controller = job.WindowsJobController.create()
    prepared = None
    try:
        prepared = controller.create_suspended_root(_sleeping_root())
        prepared.resume()
        with pytest.raises(job.JobLifecycleError):
            prepared.resume()
    finally:
        if prepared:
            prepared.terminate_job()
            prepared.wait_until_empty(_deadline())
            prepared.close()
        controller.close()


def test_wait_result_does_not_convert_query_failure_or_nonempty_into_empty():
    controller = object.__new__(job.WindowsJobController)
    controller.membership = lambda: (_ for _ in ()).throw(job.MembershipQueryError("synthetic query failure"))
    unknown = controller.wait_until_empty(time.monotonic())
    assert unknown.status is job.EmptyMembershipStatus.QUERY_UNKNOWN

    controller.membership = lambda: job.MembershipObservation((999,))
    nonempty = controller.wait_until_empty(time.monotonic() - 0.01)
    assert nonempty.status is job.EmptyMembershipStatus.STILL_NONEMPTY


class _FailingDll:
    def __init__(self, *, resume=0, terminate=True, query=True):
        self.resume, self.terminate, self.query = resume, terminate, query
        self.closed = []

    def ResumeThread(self, _thread): return self.resume
    def TerminateJobObject(self, _job, _exit): return self.terminate
    def QueryInformationJobObject(self, *_args): return self.query
    def CloseHandle(self, handle): self.closed.append(handle); return True


def _fake_controller(dll):
    return job.WindowsJobController(SimpleNamespace(dll=dll, error=lambda: 5), 1)


def test_native_error_categories_and_cleanup_are_deterministic_under_the_seam():
    resume_controller = _fake_controller(_FailingDll(resume=0xFFFFFFFF))
    prepared = job.PreparedContainedProcess(resume_controller, 2, 3, 4, job.MembershipObservation((4,)))
    with pytest.raises(job.ResumeError) as resume_error:
        prepared.resume()
    assert resume_error.value.category == "resume"

    terminate_controller = _fake_controller(_FailingDll(terminate=False))
    with pytest.raises(job.TerminationRequestError) as terminate_error:
        terminate_controller.terminate_job()
    assert terminate_error.value.category == "termination-request"

    query_controller = _fake_controller(_FailingDll(query=False))
    with pytest.raises(job.MembershipQueryError) as query_error:
        query_controller.membership()
    assert query_error.value.category == "membership-query"

    verification_controller = _fake_controller(_FailingDll())
    verification_controller.membership = lambda: job.MembershipObservation((88,))
    with pytest.raises(job.MembershipVerificationError) as verification_error:
        verification_controller._verify_root_membership(77)
    assert verification_error.value.category == "membership-verification"

    cleanup_dll = _FailingDll()
    cleanup_controller = _fake_controller(cleanup_dll)
    cleanup_prepared = job.PreparedContainedProcess(cleanup_controller, 2, 3, 4, job.MembershipObservation((4,)))
    cleanup_prepared.close()
    cleanup_prepared.close()
    cleanup_controller.close()
    cleanup_controller.close()
    assert cleanup_dll.closed == [3, 2, 1]


def test_non_windows_creation_is_explicitly_unsupported():
    with mock.patch.object(job.os, "name", "posix"):
        with pytest.raises(job.WindowsJobUnsupported):
            job.WindowsJobController.create()
