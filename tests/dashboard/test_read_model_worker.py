"""Unit 2, Sub-step B (docs/27 SS8.1): the lease-owned off-thread write
worker. Its own dedicated connection means no SQLite write ever executes
on the ASGI event loop's thread. A 16-job FIFO caps pending ordinary work
(producers await capacity); a separate priority lane always drains first
so a bounded/backed-up ordinary queue can never starve lease-renewal
heartbeats."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from draindeck_dashboard.db import connect_and_init
from draindeck_dashboard.read_model_worker import ReadModelWorker


async def _start_worker(tmp_path):
    db_path = tmp_path / "dash.sqlite3"
    connect_and_init(db_path).close()  # create the file/schema first
    worker = ReadModelWorker(str(db_path))
    worker.start()
    return worker


def test_submitted_job_runs_on_a_different_thread_than_the_caller(tmp_path):
    async def run():
        worker = await _start_worker(tmp_path)
        caller_thread = threading.get_ident()
        try:
            job_thread = await worker.submit(lambda conn: threading.get_ident())
        finally:
            await worker.stop()
        assert job_thread != caller_thread

    asyncio.run(run())


def test_job_receives_a_connection_and_can_write(tmp_path):
    async def run():
        worker = await _start_worker(tmp_path)
        try:
            def write(conn):
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
                    "VALUES ('C:/x', NULL, NULL, '2026-08-23T00:00:00Z')"
                )
                conn.execute("COMMIT")
                return conn.execute("SELECT COUNT(*) FROM repositories").fetchone()[0]
            count = await worker.submit(write)
        finally:
            await worker.stop()
        assert count == 1

    asyncio.run(run())


def test_job_exception_propagates_to_the_awaiting_caller(tmp_path):
    async def run():
        worker = await _start_worker(tmp_path)
        try:
            def boom(conn):
                raise ValueError("job failed")
            with pytest.raises(ValueError, match="job failed"):
                await worker.submit(boom)
        finally:
            await worker.stop()

    asyncio.run(run())


def test_jobs_execute_in_fifo_order_within_one_lane(tmp_path):
    async def run():
        worker = await _start_worker(tmp_path)
        order = []
        try:
            async def submit_n(n):
                await worker.submit(lambda conn, n=n: order.append(n))
            await asyncio.gather(*(submit_n(i) for i in range(10)))
        finally:
            await worker.stop()
        assert order == list(range(10))

    asyncio.run(run())


def test_priority_job_runs_before_queued_ordinary_jobs(tmp_path):
    """A lease-renewal (priority=True) job submitted while ordinary jobs
    are still queued must be picked up before the queued ordinary work --
    proving a backed-up page/backfill queue cannot starve the heartbeat."""
    async def run():
        worker = await _start_worker(tmp_path)
        order = []
        release = threading.Event()
        try:
            # Occupy the worker thread with one long-running ordinary job
            # so the next ones queue up behind it.
            first = asyncio.ensure_future(
                worker.submit(lambda conn: (release.wait(2), order.append("first"))))
            await asyncio.sleep(0.05)  # let it actually start executing

            ordinary = asyncio.ensure_future(
                worker.submit(lambda conn: order.append("ordinary")))
            await asyncio.sleep(0.02)
            priority = asyncio.ensure_future(
                worker.submit(lambda conn: order.append("priority"), priority=True))
            await asyncio.sleep(0.02)

            release.set()
            await asyncio.gather(first, ordinary, priority)
        finally:
            release.set()
            await worker.stop()
        assert order == ["first", "priority", "ordinary"]

    asyncio.run(run())


def test_ordinary_queue_backpressure_blocks_the_seventeenth_submit(tmp_path):
    """The ordinary FIFO is capped at 16 pending jobs -- a producer must
    await capacity rather than growing the queue unboundedly."""
    async def run():
        worker = await _start_worker(tmp_path)
        release = threading.Event()
        try:
            blocker = asyncio.ensure_future(
                worker.submit(lambda conn: release.wait(2)))
            await asyncio.sleep(0.05)  # blocker now occupies the worker thread

            pending = [asyncio.ensure_future(worker.submit(lambda conn, i=i: i))
                      for i in range(16)]
            await asyncio.sleep(0.05)  # all 16 should have been accepted into the queue

            seventeenth_done = {"value": False}

            async def submit_seventeenth():
                await worker.submit(lambda conn: 16)
                seventeenth_done["value"] = True

            seventeenth = asyncio.ensure_future(submit_seventeenth())
            await asyncio.sleep(0.05)
            assert seventeenth_done["value"] is False  # still blocked on a full queue

            release.set()
            await blocker
            await asyncio.gather(*pending)
            await seventeenth
            assert seventeenth_done["value"] is True
        finally:
            release.set()
            await worker.stop()

    asyncio.run(run())


def test_stop_joins_the_thread_and_closes_the_connection(tmp_path):
    async def run():
        worker = await _start_worker(tmp_path)
        await worker.stop()
        assert worker.is_alive() is False

    asyncio.run(run())
