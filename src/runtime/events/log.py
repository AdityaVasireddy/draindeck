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
  a crash during append. Because append() had not returned, no action was
  taken on that event; the torn bytes are quarantined to a sidecar file
  and the log truncated to the last durable event. This is repair of an
  un-acted-on write, not history rewriting.

Windows note: paths via pathlib; directory fsync is best-effort (POSIX
only) and guarded. File-handle fsync — the load-bearing one — works on
both platforms.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

from .schema import Event, SchemaError


class CorruptionError(RuntimeError):
    """The log body violates the contract; refuse to operate."""


class EventLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._repair_torn_tail()
        self._last_event_id = self._scan_last_event_id()
        self._fh = open(self.path, "ab")
        self._fsync_dir_once()

    # ── public API ───────────────────────────────────────────────
    def append(self, event: Event) -> int:
        """Assign the next event_id, persist durably, return it."""
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
        self._fh.close()

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


def open_log(path: Path | str) -> EventLog:
    return EventLog(path)
