"""Windows-local workspace ownership and controller identity proof.

This module deliberately owns only *cooperating runtime* exclusion.  A mutex
is not execution-containment evidence: callers must separately replay the
authoritative containment events before touching the workspace.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


class LeaseState(str, Enum):
    ACQUIRED = "ACQUIRED"
    ABANDONED_ACQUIRED = "ABANDONED_ACQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class ControllerIdentityState(str, Enum):
    LIVE_MATCH = "LIVE_MATCH"
    DEAD = "DEAD"
    PID_REUSED = "PID_REUSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ControllerIdentityResult:
    state: ControllerIdentityState
    detail: str


class MutexApi(Protocol):
    def create_mutex(self, name: str) -> tuple[int | None, int]: ...
    def clear_inherit(self, handle: int) -> tuple[bool, int]: ...
    def is_inheritable(self, handle: int) -> tuple[bool | None, int]: ...
    def wait_zero(self, handle: int) -> tuple[int, int]: ...
    def release_mutex(self, handle: int) -> tuple[bool, int]: ...
    def close_handle(self, handle: int) -> tuple[bool, int]: ...


WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80
WAIT_TIMEOUT = 0x102
WAIT_FAILED = 0xFFFFFFFF
_held_mutex_names: set[str] = set()
_held_mutex_names_lock = threading.Lock()


def canonical_workspace_identity(workspace: Path | str) -> str:
    """Stable, case-normalized identity without creating any path."""
    return os.path.normcase(str(Path(workspace).resolve(strict=False)))


def workspace_key(workspace: Path | str) -> str:
    return hashlib.sha256(canonical_workspace_identity(workspace).encode("utf-8")).hexdigest()


def mutex_name_for_workspace(workspace: Path | str) -> str:
    # Do not fall back to Local\\: session-wide exclusion is an architectural
    # change, not an availability workaround for Global\\.
    return "Global\\draindeck-workspace-v1-" + workspace_key(workspace)


class WindowsMutexApi:
    """The small Win32 seam; tests use a fake and never invoke this API."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows named mutexes are unavailable on this platform")
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self._k32.CreateMutexW.restype = ctypes.c_void_p
        self._k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._k32.WaitForSingleObject.restype = ctypes.c_uint32
        self._k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self._k32.ReleaseMutex.restype = ctypes.c_int
        self._k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._k32.CloseHandle.restype = ctypes.c_int
        self._k32.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        self._k32.SetHandleInformation.restype = ctypes.c_int
        self._k32.GetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self._k32.GetHandleInformation.restype = ctypes.c_int

    def create_mutex(self, name: str) -> tuple[int | None, int]:
        ctypes.set_last_error(0)
        handle = self._k32.CreateMutexW(None, False, name)
        return (int(handle) if handle else None, ctypes.get_last_error())

    def clear_inherit(self, handle: int) -> tuple[bool, int]:
        ctypes.set_last_error(0)
        ok = bool(self._k32.SetHandleInformation(handle, 1, 0))
        return ok, ctypes.get_last_error()

    def is_inheritable(self, handle: int) -> tuple[bool | None, int]:
        flags = ctypes.c_uint32()
        ctypes.set_last_error(0)
        if not self._k32.GetHandleInformation(handle, ctypes.byref(flags)):
            return None, ctypes.get_last_error()
        return bool(flags.value & 1), 0

    def wait_zero(self, handle: int) -> tuple[int, int]:
        ctypes.set_last_error(0)
        result = int(self._k32.WaitForSingleObject(handle, 0))
        return result, ctypes.get_last_error()

    def release_mutex(self, handle: int) -> tuple[bool, int]:
        ctypes.set_last_error(0)
        ok = bool(self._k32.ReleaseMutex(handle))
        return ok, ctypes.get_last_error()

    def close_handle(self, handle: int) -> tuple[bool, int]:
        ctypes.set_last_error(0)
        ok = bool(self._k32.CloseHandle(handle))
        return ok, ctypes.get_last_error()


@dataclass
class WorkspaceLease:
    workspace_identity: str
    workspace_key: str
    mutex_name: str
    state: LeaseState
    detail: str
    _api: MutexApi | None = None
    _handle: int | None = None
    _owned: bool = False
    _owner_thread: int | None = None

    @property
    def acquired(self) -> bool:
        return self.state in (LeaseState.ACQUIRED, LeaseState.ABANDONED_ACQUIRED)

    @classmethod
    def acquire(cls, workspace: Path | str, *, api: MutexApi | None = None) -> "WorkspaceLease":
        identity = canonical_workspace_identity(workspace)
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        name = "Global\\draindeck-workspace-v1-" + key
        with _held_mutex_names_lock:
            if name in _held_mutex_names:
                return cls(identity, key, name, LeaseState.ERROR,
                           "workspace lease already acquired by this runtime process")
        try:
            api = api or WindowsMutexApi()
        except OSError as exc:
            return cls(identity, key, name, LeaseState.ERROR, str(exc))
        handle, error = api.create_mutex(name)
        if handle is None:
            return cls(identity, key, name, LeaseState.ERROR, f"CreateMutexW failed: {error}", api)
        cleared, error = api.clear_inherit(handle)
        inheritable, verify_error = api.is_inheritable(handle)
        if not cleared or inheritable is not False:
            api.close_handle(handle)
            detail = f"mutex handle inheritance verification failed: clear={cleared} error={error} verify={verify_error}"
            return cls(identity, key, name, LeaseState.ERROR, detail, api)
        result, error = api.wait_zero(handle)
        if result == WAIT_OBJECT_0:
            with _held_mutex_names_lock:
                _held_mutex_names.add(name)
            return cls(identity, key, name, LeaseState.ACQUIRED, "acquired", api, handle, True,
                       threading.get_ident())
        if result == WAIT_ABANDONED:
            with _held_mutex_names_lock:
                _held_mutex_names.add(name)
            return cls(identity, key, name, LeaseState.ABANDONED_ACQUIRED,
                       "acquired abandoned mutex; not containment proof", api, handle, True,
                       threading.get_ident())
        if result == WAIT_TIMEOUT:
            api.close_handle(handle)
            return cls(identity, key, name, LeaseState.UNAVAILABLE, "already owned", api)
        api.close_handle(handle)
        return cls(identity, key, name, LeaseState.ERROR, f"WaitForSingleObject failed: {error}", api)

    def release_and_close(self) -> None:
        """Balance this acquisition exactly once.  Call only after a safe exit."""
        if self._handle is None:
            return
        if self._owned and self._owner_thread != threading.get_ident():
            raise RuntimeError("workspace lease must be released by its designated owner thread")
        handle, self._handle = self._handle, None
        if self._owned:
            ok, error = self._api.release_mutex(handle)  # type: ignore[union-attr]
            self._owned = False
            if not ok:
                self._api.close_handle(handle)  # type: ignore[union-attr]
                raise RuntimeError(f"ReleaseMutex failed: {error}")
            with _held_mutex_names_lock:
                _held_mutex_names.discard(self.mutex_name)
        ok, error = self._api.close_handle(handle)  # type: ignore[union-attr]
        if not ok:
            raise RuntimeError(f"CloseHandle failed: {error}")


class ProcessIdentityApi(Protocol):
    def probe(self, pid: int) -> tuple[str, str | None, int]: ...


class WindowsProcessIdentityApi:
    """Query a concrete process object; no WMI/tasklist/name inference."""
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows process identity probing is unavailable on this platform")
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self._k32.OpenProcess.restype = ctypes.c_void_p
        self._k32.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        self._k32.GetProcessTimes.restype = ctypes.c_int
        self._k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._k32.WaitForSingleObject.restype = ctypes.c_uint32
        self._k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._k32.CloseHandle.restype = ctypes.c_int

    def probe(self, pid: int) -> tuple[str, str | None, int]:
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
        ctypes.set_last_error(0)
        handle = self._k32.OpenProcess(0x00100000 | 0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            return ("dead", None, error) if error == 87 else ("unknown", None, error)
        try:
            wait = int(self._k32.WaitForSingleObject(handle, 0))
            if wait == WAIT_OBJECT_0:
                return "dead", None, 0
            if wait != WAIT_TIMEOUT:
                return "unknown", None, ctypes.get_last_error()
            created, exited, kernel, user = (ctypes.c_uint64() for _ in range(4))
            if not self._k32.GetProcessTimes(
                handle, ctypes.byref(created), ctypes.byref(exited),
                ctypes.byref(kernel), ctypes.byref(user),
            ):
                return "unknown", None, ctypes.get_last_error()
            return "live", str(created.value), 0
        finally:
            self._k32.CloseHandle(handle)


def probe_controller_identity(identity: object, *, api: ProcessIdentityApi | None = None) -> ControllerIdentityResult:
    if not isinstance(identity, dict):
        return ControllerIdentityResult(ControllerIdentityState.UNKNOWN, "controller identity is not a mapping")
    pid, creation_time = identity.get("pid"), identity.get("creation_time")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1 or not isinstance(creation_time, str) or not creation_time:
        return ControllerIdentityResult(ControllerIdentityState.UNKNOWN, "controller identity is malformed")
    try:
        api = api or WindowsProcessIdentityApi()
    except OSError as exc:
        return ControllerIdentityResult(ControllerIdentityState.UNKNOWN, str(exc))
    observed, current_creation_time, error = api.probe(pid)
    if observed == "dead":
        return ControllerIdentityResult(ControllerIdentityState.DEAD, f"PID {pid} is absent/signaled ({error})")
    if observed != "live" or not current_creation_time:
        return ControllerIdentityResult(ControllerIdentityState.UNKNOWN, f"PID {pid} probe ambiguous ({error})")
    if current_creation_time == creation_time:
        return ControllerIdentityResult(ControllerIdentityState.LIVE_MATCH, f"PID {pid} creation time matches")
    return ControllerIdentityResult(ControllerIdentityState.PID_REUSED, f"PID {pid} creation time differs")


def current_process_identity(*, api: ProcessIdentityApi | None = None) -> dict:
    """Current runtime PID plus its kernel creation-time identity.

    This is persisted before a contained root can run; a failure is not
    downgraded to a name-based or timestamp-only identity.
    """
    try:
        api = api or WindowsProcessIdentityApi()
    except OSError as exc:
        raise RuntimeError(f"controller process identity unavailable: {exc}") from exc
    observed, created, error = api.probe(os.getpid())
    if observed != "live" or not created:
        raise RuntimeError(f"controller process identity ambiguous: {error}")
    return {"pid": os.getpid(), "creation_time": created}
