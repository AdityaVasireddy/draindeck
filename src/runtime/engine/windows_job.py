"""Narrow Windows Job Object boundary; deliberately independent of the engine.

This module owns native handles and process containment mechanics only.  It
does not write events, choose timeouts, or decide workspace/retry policy.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Sequence


class WindowsJobError(RuntimeError):
    category = "windows-job"

    def __init__(self, message: str, *, winerror: int | None = None) -> None:
        self.winerror = winerror
        suffix = f" (Win32 error {winerror})" if winerror else ""
        super().__init__(message + suffix)


class WindowsJobUnsupported(WindowsJobError): category = "unsupported"
class JobConfigurationError(WindowsJobError): category = "job-configuration"
class AttributeListError(WindowsJobError): category = "attribute-list"
class ProcessCreationError(WindowsJobError): category = "process-creation"
class LaunchPlanError(ProcessCreationError): category = "launch-plan"
class MembershipVerificationError(WindowsJobError): category = "membership-verification"
class MembershipQueryError(WindowsJobError): category = "membership-query"
class ResumeError(WindowsJobError): category = "resume"
class TerminationRequestError(WindowsJobError): category = "termination-request"
class JobLifecycleError(WindowsJobError): category = "lifecycle"


class EmptyMembershipStatus(str, Enum):
    EMPTY_CONFIRMED = "EMPTY_CONFIRMED"
    STILL_NONEMPTY = "STILL_NONEMPTY"
    QUERY_UNKNOWN = "QUERY_UNKNOWN"


class LaunchKind(str, Enum):
    """The native executable boundary selected before any process exists."""

    NATIVE = "native"
    BATCH = "batch"


@dataclass(frozen=True)
class WindowsLaunchPlan:
    """Validated CreateProcessW inputs, deliberately excluding raw argv."""

    kind: LaunchKind
    application_name: str
    command_line: str


@dataclass(frozen=True)
class JobConfigurationWitness:
    unnamed: bool = True
    kill_on_job_close: bool = True
    breakaway_ok: bool = False
    silent_breakaway_ok: bool = False
    handle_inheritable: bool = False
    launch_mode: str = "windows-job-list-at-create"


@dataclass(frozen=True)
class MembershipObservation:
    pids: tuple[int, ...]

    @property
    def member_count(self) -> int:
        return len(self.pids)

    @property
    def empty(self) -> bool:
        return not self.pids


@dataclass(frozen=True)
class EmptyMembershipResult:
    status: EmptyMembershipStatus
    observation: MembershipObservation | None
    error: WindowsJobError | None = None


# Process / Job constants from processthreadsapi.h and jobapi2.h.
CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
PROC_THREAD_ATTRIBUTE_JOB_LIST = 0x0002000D
PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicProcessIdList = 3
JobObjectExtendedLimitInformation = 9
HANDLE_FLAG_INHERIT = 1
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_MORE_DATA = 234
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 0x102
STARTF_USESTDHANDLES = 0x00000100


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32), ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p), ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32), ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32), ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32), ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_uint16), ("cbReserved2", ctypes.c_uint16),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p), ("hStdError", ctypes.c_void_p),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", ctypes.c_void_p), ("hThread", ctypes.c_void_p),
                ("dwProcessId", ctypes.c_uint32), ("dwThreadId", ctypes.c_uint32)]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_uint64), ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64), ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64), ("OtherTransferCount", ctypes.c_uint64)]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", _IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _process_list_type(capacity: int):
    class _JOB_PROCESS_LIST(ctypes.Structure):
        _fields_ = [("NumberOfAssignedProcesses", ctypes.c_uint32),
                    ("NumberOfProcessIdsInList", ctypes.c_uint32),
                    ("ProcessIdList", ctypes.c_size_t * max(capacity, 1))]
    return _JOB_PROCESS_LIST


def _cmd_quote_argument(argument: str) -> str:
    """Quote one already-validated argument for cmd's ``/s /c`` command.

    Every token is quoted so cmd metacharacters stay data.  Literal percent
    and quote characters are rejected by the boundary instead of attempting a
    fragile shell escape policy.  ``/v:off`` makes ``!`` literal.
    """
    trailing_backslashes = len(argument) - len(argument.rstrip("\\"))
    return '"' + argument + ("\\" * trailing_backslashes) + '"'


def plan_windows_launch(
    command: Sequence[str], *, cmd_path: str | None = None,
) -> WindowsLaunchPlan:
    """Return the one direct native or explicit batch launch boundary.

    This is pure planning: no path is executed and no process is created.
    ``cmd_path`` is injectable solely for deterministic tests; production
    obtains the trusted system interpreter through ``_trusted_cmd_exe``.
    """
    if (not command or not isinstance(command[0], str) or not command[0]
            or any(not isinstance(item, str) for item in command[1:])):
        raise LaunchPlanError("command requires a non-empty launcher and string arguments")
    launcher = command[0]
    suffix = os.path.splitext(launcher)[1].lower()
    if suffix not in {".cmd", ".bat"}:
        return WindowsLaunchPlan(
            LaunchKind.NATIVE, launcher, subprocess.list2cmdline(list(command)),
        )
    if not os.path.isabs(launcher):
        raise LaunchPlanError("batch launcher path must be absolute")
    if not cmd_path:
        raise LaunchPlanError("trusted cmd.exe path is unavailable")
    values = [*command, cmd_path]
    if any("\x00" in value for value in values):
        raise LaunchPlanError("NUL is not valid in a batch launch argument")
    if any("%" in value for value in values):
        raise LaunchPlanError("percent characters are unsupported in batch launch arguments")
    if any('"' in value for value in values):
        raise LaunchPlanError("embedded quote characters are unsupported in batch launch arguments")
    # /d disables AutoRun, /v:off makes ! data, and /s /c gives cmd's
    # documented batch invocation boundary.  The nested first quote is the
    # opening quote of the complete command after /c.
    inner = " ".join(_cmd_quote_argument(value) for value in command)
    command_line = _cmd_quote_argument(cmd_path) + " /d /v:off /s /c \"" + inner + "\""
    return WindowsLaunchPlan(LaunchKind.BATCH, cmd_path, command_line)


class _Kernel32:
    """Private typed ctypes boundary.  Import remains safe off Windows."""
    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsJobUnsupported("Windows Job Objects are unavailable on this platform")
        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        d = self.dll
        d.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        d.CreateJobObjectW.restype = ctypes.c_void_p
        d.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        d.SetInformationJobObject.restype = ctypes.c_int
        d.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        d.QueryInformationJobObject.restype = ctypes.c_int
        d.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        d.TerminateJobObject.restype = ctypes.c_int
        d.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        d.SetHandleInformation.restype = ctypes.c_int
        d.GetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        d.GetHandleInformation.restype = ctypes.c_int
        d.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t)]
        d.InitializeProcThreadAttributeList.restype = ctypes.c_int
        d.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
        d.UpdateProcThreadAttribute.restype = ctypes.c_int
        d.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        d.CreateProcessW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.POINTER(_STARTUPINFOEXW), ctypes.POINTER(_PROCESS_INFORMATION)]
        d.CreateProcessW.restype = ctypes.c_int
        d.ResumeThread.argtypes = [ctypes.c_void_p]
        d.ResumeThread.restype = ctypes.c_uint32
        d.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        d.WaitForSingleObject.restype = ctypes.c_uint32
        d.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        d.GetExitCodeProcess.restype = ctypes.c_int
        d.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        d.GetProcessTimes.restype = ctypes.c_int
        d.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        d.GetSystemDirectoryW.restype = ctypes.c_uint32
        d.CloseHandle.argtypes = [ctypes.c_void_p]
        d.CloseHandle.restype = ctypes.c_int

    @staticmethod
    def error() -> int:
        return ctypes.get_last_error()


def _raise(error_type: type[WindowsJobError], message: str, api: _Kernel32) -> None:
    raise error_type(message, winerror=api.error())


def _trusted_cmd_exe(api: _Kernel32) -> str:
    """Resolve cmd.exe from the Windows system directory, never PATH."""
    buffer = ctypes.create_unicode_buffer(32768)
    ctypes.set_last_error(0)
    length = api.dll.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        _raise(LaunchPlanError, "could not resolve the Windows system directory", api)
    candidate = os.path.join(buffer.value, "cmd.exe")
    if not os.path.isfile(candidate):
        raise LaunchPlanError("trusted cmd.exe was not found in the Windows system directory")
    return candidate


class WindowsJobController:
    """The sole intended owner of one unnamed KILL_ON_CLOSE Job handle."""
    def __init__(self, api: _Kernel32, handle: int) -> None:
        self._api, self._handle = api, handle
        self._closed = False
        self._owner_thread = threading.get_ident()
        self.witness = JobConfigurationWitness()

    @classmethod
    def create(cls) -> "WindowsJobController":
        api = _Kernel32()
        ctypes.set_last_error(0)
        raw = api.dll.CreateJobObjectW(None, None)  # unnamed by construction
        if not raw:
            _raise(JobConfigurationError, "CreateJobObjectW failed", api)
        handle = int(raw)
        try:
            ctypes.set_last_error(0)
            if not api.dll.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, 0):
                _raise(JobConfigurationError, "could not clear Job handle inheritance", api)
            flags = ctypes.c_uint32()
            ctypes.set_last_error(0)
            if not api.dll.GetHandleInformation(handle, ctypes.byref(flags)):
                _raise(JobConfigurationError, "could not verify Job handle inheritance", api)
            if flags.value & HANDLE_FLAG_INHERIT:
                raise JobConfigurationError("Job handle remained inheritable")
            limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ctypes.set_last_error(0)
            if not api.dll.SetInformationJobObject(handle, JobObjectExtendedLimitInformation,
                                                    ctypes.byref(limits), ctypes.sizeof(limits)):
                _raise(JobConfigurationError, "could not configure KILL_ON_JOB_CLOSE", api)
            return cls(api, handle)
        except Exception:
            api.dll.CloseHandle(handle)
            raise

    def _require_open(self) -> int:
        if self._closed or not self._handle:
            raise JobLifecycleError("Job controller is closed")
        if threading.get_ident() != self._owner_thread:
            raise JobLifecycleError("Job controller may only be used by its owner thread")
        return self._handle

    def membership(self) -> MembershipObservation:
        handle = self._require_open()
        capacity = 8
        while True:
            list_type = _process_list_type(capacity)
            buf = list_type()
            returned = ctypes.c_uint32()
            ctypes.set_last_error(0)
            ok = self._api.dll.QueryInformationJobObject(handle, JobObjectBasicProcessIdList,
                                                          ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(returned))
            if ok:
                listed = min(int(buf.NumberOfProcessIdsInList), capacity)
                return MembershipObservation(tuple(int(buf.ProcessIdList[i]) for i in range(listed)))
            error = self._api.error()
            if error != ERROR_MORE_DATA or capacity >= 65536:
                raise MembershipQueryError("QueryInformationJobObject membership failed", winerror=error)
            # The returned byte count includes the header plus as many PIDs as fit.
            capacity = max(capacity * 2, (int(returned.value) // ctypes.sizeof(ctypes.c_size_t)) + 1)

    def _verify_root_membership(self, pid: int) -> MembershipObservation:
        observed = self.membership()
        if pid not in observed.pids:
            raise MembershipVerificationError("suspended root is not a member of the configured Job")
        return observed

    def create_suspended_root(
        self, command: Sequence[str], *, cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        stdio_handles: tuple[int, int, int] | None = None,
    ) -> "PreparedContainedProcess":
        handle = self._require_open()
        suffix = os.path.splitext(command[0])[1].lower() \
            if command and isinstance(command[0], str) else ""
        launch = plan_windows_launch(
            command,
            cmd_path=_trusted_cmd_exe(self._api)
            if suffix in {".cmd", ".bat"} else None,
        )
        size = ctypes.c_size_t(0)
        attribute_count = 2 if stdio_handles is not None else 1
        child_handles: tuple[int, ...] = ()
        if stdio_handles is not None:
            if len(stdio_handles) != 3 or any(not isinstance(h, int) or h in (0, -1) for h in stdio_handles):
                raise ProcessCreationError("controlled stdio requires exactly three valid handles")
            if handle in stdio_handles:
                raise ProcessCreationError("Job handle must never be in the child handle allowlist")
            child_handles = tuple(dict.fromkeys(stdio_handles))
            for child_handle in child_handles:
                ctypes.set_last_error(0)
                if not self._api.dll.SetHandleInformation(child_handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT):
                    _raise(ProcessCreationError, "could not make required child stdio handle inheritable", self._api)
                flags = ctypes.c_uint32()
                if not self._api.dll.GetHandleInformation(child_handle, ctypes.byref(flags)) or not (flags.value & HANDLE_FLAG_INHERIT):
                    _raise(ProcessCreationError, "could not verify required child stdio handle inheritance", self._api)
        ctypes.set_last_error(0)
        initialized = self._api.dll.InitializeProcThreadAttributeList(None, attribute_count, 0, ctypes.byref(size))
        if initialized or self._api.error() != ERROR_INSUFFICIENT_BUFFER or not size.value:
            _raise(AttributeListError, "could not size process attribute list", self._api)
        storage = ctypes.create_string_buffer(size.value)
        attr_list = ctypes.cast(storage, ctypes.c_void_p)
        ctypes.set_last_error(0)
        if not self._api.dll.InitializeProcThreadAttributeList(attr_list, attribute_count, 0, ctypes.byref(size)):
            _raise(AttributeListError, "could not initialize process attribute list", self._api)
        pi = _PROCESS_INFORMATION()
        try:
            job_list = (ctypes.c_void_p * 1)(handle)
            ctypes.set_last_error(0)
            if not self._api.dll.UpdateProcThreadAttribute(attr_list, 0, PROC_THREAD_ATTRIBUTE_JOB_LIST,
                                                           ctypes.byref(job_list), ctypes.sizeof(job_list), None, None):
                _raise(AttributeListError, "could not attach Job list to process creation", self._api)
            handle_list = None
            if child_handles:
                handle_list = (ctypes.c_void_p * len(child_handles))(*child_handles)
                ctypes.set_last_error(0)
                if not self._api.dll.UpdateProcThreadAttribute(
                    attr_list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                    ctypes.byref(handle_list), ctypes.sizeof(handle_list), None, None,
                ):
                    _raise(AttributeListError, "could not attach explicit child handle allowlist", self._api)
            startup = _STARTUPINFOEXW()
            startup.StartupInfo.cb = ctypes.sizeof(startup)
            startup.lpAttributeList = attr_list
            if stdio_handles is not None:
                startup.StartupInfo.dwFlags |= STARTF_USESTDHANDLES
                startup.StartupInfo.hStdInput = stdio_handles[0]
                startup.StartupInfo.hStdOutput = stdio_handles[1]
                startup.StartupInfo.hStdError = stdio_handles[2]
            command_line = ctypes.create_unicode_buffer(launch.command_line)
            flags = CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT
            environment = None
            if env is not None:
                flags |= CREATE_UNICODE_ENVIRONMENT
                environment = ctypes.create_unicode_buffer("\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0")
            ctypes.set_last_error(0)
            if not self._api.dll.CreateProcessW(launch.application_name, command_line, None, None, bool(child_handles), flags,
                                                environment, cwd, ctypes.byref(startup), ctypes.byref(pi)):
                _raise(ProcessCreationError, "CreateProcessW with Job-list attribute failed", self._api)
        finally:
            self._api.dll.DeleteProcThreadAttributeList(attr_list)
            # These parent-owned handles are inheritable only during the exact
            # CreateProcess call; the Job handle was never made inheritable.
            for child_handle in child_handles:
                self._api.dll.SetHandleInformation(child_handle, HANDLE_FLAG_INHERIT, 0)
        process, thread = int(pi.hProcess), int(pi.hThread)
        try:
            observed = self._verify_root_membership(int(pi.dwProcessId))
            return PreparedContainedProcess(
                self, process, thread, int(pi.dwProcessId), observed, launch,
            )
        except Exception:
            self._api.dll.CloseHandle(thread)
            self._api.dll.CloseHandle(process)
            # Closing the sole KILL_ON_CLOSE handle is the fail-closed cleanup.
            self.close()
            raise

    def terminate_job(self, exit_code: int = 1) -> None:
        handle = self._require_open()
        ctypes.set_last_error(0)
        if not self._api.dll.TerminateJobObject(handle, exit_code):
            _raise(TerminationRequestError, "TerminateJobObject failed", self._api)

    def wait_until_empty(self, deadline_monotonic: float, *, poll_interval: float = 0.05) -> EmptyMembershipResult:
        if poll_interval < 0:
            raise JobLifecycleError("poll interval must not be negative")
        last: MembershipObservation | None = None
        while True:
            try:
                last = self.membership()
            except MembershipQueryError as exc:
                return EmptyMembershipResult(EmptyMembershipStatus.QUERY_UNKNOWN, last, exc)
            if last.empty:
                return EmptyMembershipResult(EmptyMembershipStatus.EMPTY_CONFIRMED, last)
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                return EmptyMembershipResult(EmptyMembershipStatus.STILL_NONEMPTY, last)
            time.sleep(min(poll_interval, remaining))

    def close(self) -> None:
        """Close the sole Job handle; live members are killed by configured policy."""
        if self._closed:
            return
        if threading.get_ident() != self._owner_thread:
            raise JobLifecycleError("Job controller may only be closed by its owner thread")
        handle, self._handle, self._closed = self._handle, 0, True
        ctypes.set_last_error(0)
        if handle and not self._api.dll.CloseHandle(handle):
            _raise(JobLifecycleError, "CloseHandle(Job) failed", self._api)

    def __enter__(self) -> "WindowsJobController":
        self._require_open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class PreparedContainedProcess:
    """A verified Job member deliberately left suspended until ``resume``."""
    def __init__(self, controller: WindowsJobController, process: int, thread: int,
                 pid: int, initial_membership: MembershipObservation,
                 launch_plan: WindowsLaunchPlan | None = None) -> None:
        self._controller, self._process, self._thread = controller, process, thread
        self.pid, self.initial_membership = pid, initial_membership
        self.launch_plan = launch_plan
        self._resumed = False
        self._closed = False

    @property
    def configuration_witness(self) -> JobConfigurationWitness:
        return self._controller.witness

    @property
    def root_suspended(self) -> bool:
        """True only during the durable-Established-before-resume window."""
        return not self._closed and not self._resumed

    def resume(self) -> None:
        if self._closed:
            raise JobLifecycleError("prepared root is closed")
        if self._resumed:
            raise JobLifecycleError("prepared root was already resumed")
        self._controller._require_open()
        ctypes.set_last_error(0)
        result = self._controller._api.dll.ResumeThread(self._thread)
        if result == 0xFFFFFFFF:
            _raise(ResumeError, "ResumeThread failed", self._controller._api)
        self._resumed = True

    def root_wait_status(self) -> str:
        if self._closed:
            raise JobLifecycleError("prepared root is closed")
        result = int(self._controller._api.dll.WaitForSingleObject(self._process, 0))
        if result == WAIT_OBJECT_0:
            return "SIGNALED"
        if result == WAIT_TIMEOUT:
            return "RUNNING"
        raise MembershipQueryError("WaitForSingleObject(root) failed", winerror=self._controller._api.error())

    def exit_status(self) -> int:
        if self.root_wait_status() != "SIGNALED":
            raise JobLifecycleError("root process has not exited")
        code = ctypes.c_uint32()
        if not self._controller._api.dll.GetExitCodeProcess(self._process, ctypes.byref(code)):
            _raise(MembershipQueryError, "GetExitCodeProcess failed", self._controller._api)
        return int(code.value)

    def diagnostic_identity(self) -> dict:
        created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
        if not self._controller._api.dll.GetProcessTimes(
            self._process, ctypes.byref(created), ctypes.byref(exited),
            ctypes.byref(kernel), ctypes.byref(user),
        ):
            _raise(MembershipQueryError, "GetProcessTimes(root) failed", self._controller._api)
        return {"pid": self.pid, "creation_time": str(created.value)}

    def membership(self) -> MembershipObservation:
        return self._controller.membership()

    def terminate_job(self, exit_code: int = 1) -> None:
        self._controller.terminate_job(exit_code)

    def wait_until_empty(self, deadline_monotonic: float, *, poll_interval: float = 0.05) -> EmptyMembershipResult:
        return self._controller.wait_until_empty(deadline_monotonic, poll_interval=poll_interval)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in (self._thread, self._process):
            if handle:
                self._controller._api.dll.CloseHandle(handle)
        self._thread = self._process = 0
