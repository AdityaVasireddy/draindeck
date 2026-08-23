"""Lease-owned off-thread write worker (ADR-27 decision 8; docs/27 SS8.1).

One dedicated background thread with its own SQLite connection executes
every Dashboard SQLite write -- page persistence/projection, generation
rollover pruning, and lease acquire/renew. The ASGI event loop never
touches SQLite for a write; it only submits callables here and awaits
their result via an ``asyncio.Future`` bridged across the thread boundary
with ``loop.call_soon_threadsafe``.

Two lanes: a small, always-drained-first priority lane for lease
acquire/renew (so a backed-up ordinary queue can never starve the
2-second heartbeat), and a 16-slot-capped ordinary FIFO for page/backfill
work. ``submit()`` on the ordinary lane awaits capacity via
``asyncio.to_thread(queue.put, ...)`` rather than blocking the event loop
directly -- backpressure without unbounded memory growth.
"""
from __future__ import annotations

import asyncio
import queue
import sqlite3
import threading
from typing import Callable, TypeVar

from . import db

T = TypeVar("T")

ORDINARY_QUEUE_MAXSIZE = 16
# Worst-case added latency before a priority (lease renewal) job is
# noticed while the worker thread is idly blocked on the ordinary queue.
# Negligible against the production 2s heartbeat / 10s lease TTL.
_POLL_TIMEOUT_SECONDS = 0.01
_SHUTDOWN = object()


class ReadModelWorker:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._thread: threading.Thread | None = None
        self._priority_queue: "queue.Queue" = queue.Queue()
        self._ordinary_queue: "queue.Queue" = queue.Queue(maxsize=ORDINARY_QUEUE_MAXSIZE)
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._loop = asyncio.get_event_loop()
        self._conn = db.connect(self._db_path)
        self._thread = threading.Thread(target=self._run, name="dashboard-read-model-worker",
                                        daemon=True)
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    async def submit(self, fn: Callable[[sqlite3.Connection], T], *, priority: bool = False) -> T:
        """Enqueue ``fn`` to run on the worker thread against its
        dedicated connection; await its result. Ordinary (non-priority)
        submission blocks the CALLING coroutine (not the event loop --
        the blocking queue.put happens via asyncio.to_thread) while the
        16-slot queue is full."""
        assert self._loop is not None, "start() must be called before submit()"
        fut: asyncio.Future = self._loop.create_future()
        job = (fn, fut, self._loop)
        if priority:
            self._priority_queue.put_nowait(job)
        else:
            # Fast path: put_nowait() is synchronous and runs inline on
            # the calling coroutine, preserving submission order across
            # concurrently-scheduled callers (no thread hop = no race).
            # Only fall back to a blocking off-thread put when the queue
            # is genuinely full -- that's the actual backpressure case.
            try:
                self._ordinary_queue.put_nowait(job)
            except queue.Full:
                await asyncio.to_thread(self._ordinary_queue.put, job)
        return await fut

    async def stop(self) -> None:
        if self._thread is None:
            return
        self._priority_queue.put_nowait(_SHUTDOWN)
        await asyncio.to_thread(self._thread.join, 5)
        self._thread = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _next_job(self):
        """Priority lane is always checked first (non-blocking); only
        when it is empty do we take one ordinary job, polling briefly so
        shutdown/new priority work is noticed promptly."""
        try:
            return self._priority_queue.get_nowait()
        except queue.Empty:
            pass
        try:
            return self._ordinary_queue.get(timeout=_POLL_TIMEOUT_SECONDS)
        except queue.Empty:
            return None

    def _run(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                continue
            if job is _SHUTDOWN:
                return
            fn, fut, loop = job
            try:
                result = fn(self._conn)
            except BaseException as exc:  # noqa: BLE001 -- propagate to the awaiting caller
                if not loop.is_closed():
                    loop.call_soon_threadsafe(_set_exception, fut, exc)
            else:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(_set_result, fut, result)


def _set_result(fut: asyncio.Future, result) -> None:
    if not fut.done():
        fut.set_result(result)


def _set_exception(fut: asyncio.Future, exc: BaseException) -> None:
    if not fut.done():
        fut.set_exception(exc)
