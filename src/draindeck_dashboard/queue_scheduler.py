"""ADR-30 review finding 4: autonomous persisted FIFO progression.

A single asyncio task, started with the Dashboard's own lifespan (alongside
the existing `ChangeTailer`/ingestion `Scheduler`), that periodically calls
`run_launcher.try_launch_next` for every registered repository. This is the
same orchestration entry point the enqueue route and the explicit
`/run-commands/drain` route already call -- this task adds no second launch
path, just a periodic trigger for it, so a repository's queue keeps
advancing without depending on a browser being open, an SSE-triggered
refresh, another enqueue arriving, or an operator hitting the drain route by
hand. It does not acquire or substitute for the runtime workspace lease --
`try_launch_next` itself never touches it -- and one active process per
repository remains enforced exclusively by the existing atomic SQLite claim
(`run_queue.claim_next_launchable_command`), this task's own concurrency
authority just like every other caller's.
"""
from __future__ import annotations

import asyncio
import sqlite3
from typing import Optional

from .repositories import list_repositories
from .run_launcher import try_launch_next
from .worktree_preflight import evaluate_worktree_preflight

# Short enough that a queued command starts promptly without a browser open;
# long enough not to hammer SQLite. Tests pass a much shorter interval.
DEFAULT_INTERVAL_SECONDS = 2.0


class QueueDrainScheduler:
    """One instance per process. `start()`/`stop()` are called from the
    app's lifespan, mirroring `ChangeTailer`/`Scheduler`'s own convention."""

    def __init__(self, conn: sqlite3.Connection, observer_executable: str,
                interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> None:
        self._conn = conn
        self._observer_executable = observer_executable
        self._interval_seconds = interval_seconds
        self._task: Optional["asyncio.Task"] = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            self.tick()
            await asyncio.sleep(self._interval_seconds)

    def tick(self) -> None:
        """One pass over every registered repository. Each repository's own
        `try_launch_next` call is independently exception-isolated so a
        failure reconciling/launching for one repository can never block or
        delay another, and never crashes the loop itself."""
        for repo in list_repositories(self._conn):
            try:
                # doc 33 Part A: the scheduler-driven dequeue enforces the same
                # authoritative clean-worktree gate as the request/drain paths,
                # so a target that turned dirty after enqueue is refused here
                # too rather than spawning a doomed CHECKOUT_FAILED run.
                try_launch_next(self._conn, repo["id"], executable=self._observer_executable,
                                worktree_probe=evaluate_worktree_preflight)
            except Exception:
                pass
