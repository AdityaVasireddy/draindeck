"""Append-only, fsync-durable event log (ADR-11, ADR-12).

Durability contract
───────────────────
* ``append()`` returns only after write → flush → ``os.fsync``. An intent
  event returned by append() is on disk before its action runs; therefore
  the only crash divergence reachable is "world ahead of log".
* One event per line; the file is never rewritten or reordered.
* ``event_id`` is contiguous from 1. A gap or a malformed line *before* the
  final line is corruption: the log refuses to load (fail loudly — a
  silently repaired middle would forge history).
* A malformed *final* line without a trailing newline is the signature of
  a crash during append. ``ReadOnlyEventLog`` reports it without mutation.
  An exclusively owned writable ``EventLog`` quarantines the torn bytes to
  a sidecar file and truncates to the last durable event. Because append()
  had not returned, this is repair of an un-acted-on write, not history
  rewriting.

Windows note: paths via pathlib; directory fsync is best-effort (POSIX
only) and guarded. File-handle fsync — the load-bearing one — works on
both platforms.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Iterator

from ..workspace_lease import (
    WAIT_ABANDONED,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    MutexApi,
    WindowsMutexApi,
    canonical_workspace_identity,
)
from .schema import Event, SchemaError


class CorruptionError(RuntimeError):
    """The log body violates the contract; refuse to operate."""


class IncompleteLogError(CorruptionError):
    """A read-only inspection found an unterminated final record."""


class EventLogUnavailable(RuntimeError):
    """Another cooperating process owns this authoritative log for writing."""


_held_writer_names: set[str] = set()
_held_writer_names_lock = threading.Lock()


def canonical_event_log_identity(path: Path | str) -> str:
    """Stable, Windows-case-normalized identity without creating the path."""
    return canonical_workspace_identity(path)


def writer_mutex_name_for_log(path: Path | str) -> str:
    identity = canonical_event_log_identity(path)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return "Global\\draindeck-event-log-v1-" + digest


class _WriterLease:
    """Private, nonblocking lifetime lease for one canonical event-log path."""

    def __init__(self, name: str, api: MutexApi, handle: int) -> None:
        self.name, self._api, self._handle = name, api, handle
        self._owner_thread = threading.get_ident()
        self._closed = False

    @classmethod
    def acquire(cls, path: Path | str, *, api: MutexApi | None = None) -> "_WriterLease":
        name = writer_mutex_name_for_log(path)
        with _held_writer_names_lock:
            if name in _held_writer_names:
                raise EventLogUnavailable("event log writer already owned by this process")
        try:
            api = api or WindowsMutexApi()
        except OSError as exc:
            raise EventLogUnavailable(f"event log writer mutex unavailable: {exc}") from exc
        handle, error = api.create_mutex(name)
        if handle is None:
            raise EventLogUnavailable(f"CreateMutexW failed: {error}")
        cleared, clear_error = api.clear_inherit(handle)
        inheritable, verify_error = api.is_inheritable(handle)
        if not cleared or inheritable is not False:
            api.close_handle(handle)
            raise EventLogUnavailable(
                "event log writer mutex inheritance verification failed: "
                f"clear={cleared} error={clear_error} verify={verify_error}")
        result, wait_error = api.wait_zero(handle)
        if result in (WAIT_OBJECT_0, WAIT_ABANDONED):
            with _held_writer_names_lock:
                _held_writer_names.add(name)
            return cls(name, api, handle)
        api.close_handle(handle)
        if result == WAIT_TIMEOUT:
            raise EventLogUnavailable("event log writer already owned")
        raise EventLogUnavailable(f"WaitForSingleObject failed: {wait_error}")

    def close(self) -> None:
        if self._closed:
            return
        if self._owner_thread != threading.get_ident():
            raise RuntimeError("event log writer lease must be released by its owner thread")
        self._closed = True
        try:
            ok, error = self._api.release_mutex(self._handle)
            if not ok:
                raise RuntimeError(f"ReleaseMutex failed: {error}")
        finally:
            with _held_writer_names_lock:
                _held_writer_names.discard(self.name)
            ok, error = self._api.close_handle(self._handle)
            if not ok:
                raise RuntimeError(f"CloseHandle failed: {error}")


class ReadOnlyEventLog:
    """Strictly observational access to an existing event log."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    def __enter__(self) -> "ReadOnlyEventLog":
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def replay(self) -> Iterator[Event]:
        yield from _replay(self.path, incomplete_is_error=True)


class EventLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._append_lock = threading.Lock()
        self._fh = None
        self._closed = False
        self._lease = _WriterLease.acquire(self.path)
        try:
            # Ownership precedes every filesystem mutation and every ID read.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._repair_torn_tail()
            self._last_event_id = self._scan_last_event_id()
            self._fh = open(self.path, "ab")
            self._fsync_dir_once()
        except Exception:
            self._lease.close()
            raise

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    # ── public API ───────────────────────────────────────────────
    def append(self, event: Event) -> int:
        """Assign the next event_id, persist durably, return it."""
        with self._append_lock:
            if self._closed or self._fh is None:
                raise ValueError("event log writer is closed")
            eid = self._last_event_id + 1
            persisted = Event(
                type=event.type,
                payload=event.payload,
                issue_id=event.issue_id,
                execution_id=event.execution_id,
                run_id=event.run_id,
                ts=event.ts,
                event_id=eid,
            )
            self._fh.write(persisted.to_line())
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._last_event_id = eid
            return eid

    def replay(self) -> Iterator[Event]:
        """Ordered full scan with contiguity enforcement."""
        expected = 1
        with open(self.path, "rb") as fh:
            for lineno, raw in enumerate(fh, start=1):
                if not raw.endswith(b"\n"):
                    # Only reachable if the tail tore *after* this handle
                    # opened; treat identically to load-time torn tail.
                    break
                try:
                    ev = Event.from_line(raw)
                except SchemaError as e:
                    raise CorruptionError(
                        f"{self.path}:{lineno}: {e}"
                    ) from e
                if ev.event_id != expected:
                    raise CorruptionError(
                        f"{self.path}:{lineno}: event_id gap — expected "
                        f"{expected}, found {ev.event_id}"
                    )
                expected += 1
                yield ev

    @property
    def last_event_id(self) -> int:
        return self._last_event_id

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
        finally:
            self._lease.close()

    # ── internals ────────────────────────────────────────────────
    def _repair_torn_tail(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        data = self.path.read_bytes()
        if data.endswith(b"\n"):
            tail_start = None
        else:
            tail_start = data.rfind(b"\n") + 1  # 0 if no newline at all
        if tail_start is None:
            return
        torn = data[tail_start:]
        sidecar = self.path.with_name(
            f"{self.path.name}.torn.{int(time.time() * 1000)}"
        )
        sidecar.write_bytes(torn)
        with open(self.path, "r+b") as fh:
            fh.truncate(tail_start)
            fh.flush()
            os.fsync(fh.fileno())

    def _scan_last_event_id(self) -> int:
        last = 0
        expected = 1
        if not self.path.exists():
            return 0
        with open(self.path, "rb") as fh:
            for lineno, raw in enumerate(fh, start=1):
                if not raw.endswith(b"\n"):
                    raise CorruptionError(
                        f"{self.path}:{lineno}: torn line survived repair"
                    )
                try:
                    ev = Event.from_line(raw)
                except SchemaError as e:
                    raise CorruptionError(f"{self.path}:{lineno}: {e}") from e
                if ev.event_id != expected:
                    raise CorruptionError(
                        f"{self.path}:{lineno}: event_id gap — expected "
                        f"{expected}, found {ev.event_id}"
                    )
                last, expected = ev.event_id, expected + 1
        return last

    def _fsync_dir_once(self) -> None:
        try:  # POSIX only; best-effort on other platforms
            dfd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass


def _replay(path: Path, *, incomplete_is_error: bool) -> Iterator[Event]:
    """Replay one stable read view without ever repairing it."""
    expected = 1
    with open(path, "rb") as fh:
        for lineno, raw in enumerate(fh, start=1):
            if not raw.endswith(b"\n"):
                if incomplete_is_error:
                    raise IncompleteLogError(
                        f"{path}:{lineno}: unterminated final line")
                break
            try:
                ev = Event.from_line(raw)
            except SchemaError as e:
                raise CorruptionError(f"{path}:{lineno}: {e}") from e
            if ev.event_id != expected:
                raise CorruptionError(
                    f"{path}:{lineno}: event_id gap — expected "
                    f"{expected}, found {ev.event_id}")
            expected += 1
            yield ev


def open_log(path: Path | str) -> EventLog:
    return EventLog(path)
