"""Automatic ingestion scheduler (docs/19 "Registration and polling";
ADR-26 decision 2/3).

Runs only while this process holds the single indexer-writer lease —
followers never call `ingest_repository_tick`, they only serve API/SSE
reads. One dedicated asyncio task per registered repository, each with
its own independent cadence and exponential backoff, so a failing or
stalled repository can never block or delay a healthy one; each task's
own sequential tick-then-sleep loop makes overlapping ticks for the same
repository structurally impossible, not merely guarded. Global
concurrency, the 10-second observer timeout, and the 4-pages-per-tick
cap are unchanged — they live in `poller.py`/`observer_client.py` and are
inherited automatically since every task still calls the same
`ingest_repository_tick` entry point.
"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from typing import Optional

from . import lease
from .indexer import ingest_repository_tick
from .poller import NORMAL_INTERVAL_SECONDS, next_backoff_seconds

# Statuses that must back off even if the checkpoint's last-known
# availability is stale (docs/19: "transient/unavailable probes retain
# the checkpoint and back off"; a hard observer error is the same class).
_BACKOFF_STATUSES = frozenset({"error", "cursor_replaced_retained"})
_BACKOFF_AVAILABILITIES = frozenset({"OFFLINE", "NOT_INITIALIZED"})


class Scheduler:
    """One instance per process. `start()`/`stop()` are called from the
    app's lifespan, alongside the existing `ChangeTailer`."""

    def __init__(self, conn: sqlite3.Connection, observer_executable: str,
                 owner_token: Optional[str] = None) -> None:
        self._conn = conn
        self._observer_executable = observer_executable
        self._owner_token = owner_token or uuid.uuid4().hex
        self._is_leader = False
        self._repo_tasks: dict[int, asyncio.Task] = {}
        self._lease_task: Optional[asyncio.Task] = None

    def is_leader(self) -> bool:
        return self._is_leader

    def scheduled_repository_ids(self) -> frozenset:
        return frozenset(self._repo_tasks.keys())

    def start(self) -> None:
        if self._lease_task is None:
            self._lease_task = asyncio.create_task(self._lease_loop())

    async def stop(self) -> None:
        if self._lease_task is not None:
            self._lease_task.cancel()
            try:
                await self._lease_task
            except asyncio.CancelledError:
                pass
            self._lease_task = None
        await self._stop_all_repo_tasks()
        self._is_leader = False

    async def _stop_all_repo_tasks(self) -> None:
        tasks = list(self._repo_tasks.values())
        self._repo_tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                # A repo task's own loop already isolates and backs off on
                # its own failures (see _repo_loop); a shutdown-time
                # exception here must never block the rest of stop().
                pass

    async def _lease_loop(self) -> None:
        try:
            while True:
                acquired = lease.acquire_or_renew(self._conn, self._owner_token)
                if acquired:
                    self._is_leader = True
                    self._reconcile_repo_tasks()
                elif self._is_leader:
                    # Lost the lease: stop indexing immediately, become a
                    # read-only follower.
                    self._is_leader = False
                    await self._stop_all_repo_tasks()
                await asyncio.sleep(lease.HEARTBEAT_SECONDS)
        except asyncio.CancelledError:
            raise

    def _registered_repositories(self) -> dict:
        rows = self._conn.execute(
            "SELECT id, log_path FROM repositories WHERE log_path IS NOT NULL"
        ).fetchall()
        return {repo_id: log_path for repo_id, log_path in rows}

    def _reconcile_repo_tasks(self) -> None:
        """Starts a task for each newly-registered (and log-path-bearing)
        repository, and stops tasks for repositories no longer registered
        or that lost their log path. Called on every lease-renewal tick
        while leading, so new registrations are picked up without a
        separate watch mechanism."""
        current = self._registered_repositories()
        for repo_id, log_path in current.items():
            if repo_id not in self._repo_tasks:
                self._repo_tasks[repo_id] = asyncio.create_task(
                    self._repo_loop(repo_id, log_path))
        for repo_id in list(self._repo_tasks):
            if repo_id not in current:
                self._repo_tasks.pop(repo_id).cancel()

    def _current_availability(self, repo_id: int) -> Optional[str]:
        row = self._conn.execute(
            "SELECT availability FROM checkpoints WHERE repository_id = ?", (repo_id,)
        ).fetchone()
        return row[0] if row is not None else None

    def _tick_needs_backoff(self, repo_id: int, outcome) -> bool:
        if outcome.status in _BACKOFF_STATUSES:
            return True
        return self._current_availability(repo_id) in _BACKOFF_AVAILABILITIES

    async def _repo_loop(self, repo_id: int, log_path: str) -> None:
        """One dedicated task per repository: tick, decide the next
        interval from this repo's OWN backoff state, sleep, repeat. The
        sequential structure itself is what prevents overlapping ticks —
        the next tick is never started until this one's await returns."""
        backoff: Optional[float] = None
        try:
            while True:
                try:
                    outcome = await ingest_repository_tick(
                        self._conn, repo_id, self._observer_executable, log_path)
                    needs_backoff = self._tick_needs_backoff(repo_id, outcome)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # An unexpected failure for THIS repository must never
                    # kill its loop permanently (it would then silently
                    # stop being indexed with nothing to notice) and must
                    # never propagate to affect any other repository's
                    # task -- back off and keep retrying.
                    needs_backoff = True

                if needs_backoff:
                    backoff = next_backoff_seconds(backoff)
                    sleep_for = backoff
                else:
                    backoff = None
                    sleep_for = NORMAL_INTERVAL_SECONDS
                await asyncio.sleep(sleep_for)
        except asyncio.CancelledError:
            raise
