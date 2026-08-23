"""Item 9 (2026-08-23 build-auto continuation): proves the ASGI event loop
stays responsive and lease renewal cannot starve during (a) an active
100,000-row `rebuild_read_models` full-generation rebuild and (b) a
maximum 2,000-record tick (4 pages x 500-record PAGE_LIMIT, docs/27's
MAX_PAGES_PER_TICK/PAGE_LIMIT), against a real `ReadModelWorker` (the same
class `Scheduler` uses in production) on its own background thread.

Two things are measured concurrently with the heavy worker job(s):
  1. Event-loop responsiveness: a tight `asyncio.sleep(0.01)` probe loop
     records the actual gap between wakeups. A stall attributable to
     Dashboard SQLite work leaking onto the event loop's own thread would
     show up here as a gap far exceeding 10ms.
  2. Lease renewal latency: mimics `Scheduler._lease_loop`'s own call
     shape -- `worker.submit(fn, priority=True)` every `HEARTBEAT_SECONDS`
     -- and records submit-to-complete latency each time. This must stay
     well under `TTL_SECONDS` (10s) even while a large ordinary job is
     in flight on the same worker thread.

Exits non-zero if the event loop stalls past 50ms or a lease renewal
takes longer than half the 10s TTL (5s) -- both would be a real
production risk, not just a slow benchmark number.
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from draindeck_dashboard import lease  # noqa: E402
from draindeck_dashboard.db import connect_and_init  # noqa: E402
from draindeck_dashboard.read_model_worker import ReadModelWorker  # noqa: E402
from draindeck_dashboard.read_models import rebuild_read_models  # noqa: E402

N_EVIDENCE_SINGLE_REPO = 100_000
N_TICK_RECORDS = 2_000
EVENT_LOOP_PROBE_INTERVAL = 0.01
EVENT_LOOP_STALL_BUDGET_MS = 50.0
LEASE_LATENCY_BUDGET_S = lease.TTL_SECONDS / 2

_EVENT_TYPES = [
    "IssueActivated", "IssueCompleted", "IssueEscalated", "ExecutionSpawned",
    "ExecutionFinished", "CommitIntent", "CommitCreated", "ReviewApproved", "ValidationPassed",
]


def _seed_single_repo(conn: sqlite3.Connection, *, n_evidence: int, seed: int = 42) -> tuple[int, int]:
    """A single repository with n_evidence OK evidence rows -- the
    worst-case shape for one `rebuild_read_models` call (unlike the
    20-repository scale fixture, which spreads 100,000 rows across many
    smaller per-repo rebuilds)."""
    rng = random.Random(seed)
    now = "2026-08-23T00:00:00Z"
    conn.execute("BEGIN IMMEDIATE")
    cur = conn.execute(
        "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
        "VALUES ('C:/scale/big', 'C:/scale/big/events.jsonl', 'c:/scale/big/events.jsonl', ?)",
        (now,),
    )
    repo_id = cur.lastrowid
    gen_id = conn.execute(
        "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
        "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
        "VALUES (?, 1, 'lineage', 1, 1, 1, ?)", (repo_id, now),
    ).lastrowid
    conn.execute(
        "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
        "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
        "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', ?)", (repo_id, gen_id, now),
    )
    conn.execute(
        "INSERT INTO read_model_state (repository_id, identity_generation_id, status, "
        "completed_evidence_id, started_at, completed_at, error_code) "
        "VALUES (?, ?, 'PREPARING', NULL, ?, NULL, NULL)", (repo_id, gen_id, now),
    )
    rows = []
    for n in range(n_evidence):
        rows.append((
            repo_id, gen_id, f"cursor-{n}", "OK", n, rng.choice(_EVENT_TYPES), 1,
            None, None, None, now, f"hash-{n}", 250, now,
        ))
    conn.executemany(
        "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
        "event_id, event_type, schema_version, issue_id, execution_id, run_id, event_ts, "
        "record_hash, length_bytes, stored_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute("COMMIT")
    return repo_id, gen_id


async def _event_loop_probe(stop: asyncio.Event, gaps_ms: list[float]) -> None:
    last = time.perf_counter()
    while not stop.is_set():
        await asyncio.sleep(EVENT_LOOP_PROBE_INTERVAL)
        now = time.perf_counter()
        gaps_ms.append((now - last) * 1000)
        last = now


async def _lease_renewal_probe(worker: ReadModelWorker, conn: sqlite3.Connection,
                                owner_token: str, stop: asyncio.Event,
                                latencies_s: list[float]) -> None:
    while not stop.is_set():
        t0 = time.perf_counter()
        await worker.submit(lambda c: lease.acquire_or_renew(c, owner_token), priority=True)
        latencies_s.append(time.perf_counter() - t0)
        await asyncio.sleep(lease.HEARTBEAT_SECONDS)


async def _run_rebuild_scenario(db_path: Path) -> tuple[list[float], list[float], float]:
    lease_conn = connect_and_init(db_path)
    repo_id, gen_id = _seed_single_repo(lease_conn, n_evidence=N_EVIDENCE_SINGLE_REPO)
    owner_token = "rebuild-scenario-owner"

    worker = ReadModelWorker(str(db_path.resolve()))
    worker.start()
    # Acquire the lease for this scenario's owner_token BEFORE submitting
    # the rebuild job -- rebuild_read_models now requires the caller to
    # already hold the lease (this session's merge-blocker fix), and the
    # renewal probe task below isn't guaranteed to have run its first
    # iteration yet by the time the rebuild is submitted.
    await worker.submit(lambda c: lease.acquire_or_renew(c, owner_token), priority=True)
    stop = asyncio.Event()
    gaps_ms: list[float] = []
    lease_latencies_s: list[float] = []
    probe_task = asyncio.create_task(_event_loop_probe(stop, gaps_ms))
    lease_task = asyncio.create_task(
        _lease_renewal_probe(worker, lease_conn, owner_token, stop, lease_latencies_s))

    t0 = time.perf_counter()
    await worker.submit(lambda c: rebuild_read_models(c, repo_id, gen_id, owner_token))
    rebuild_elapsed = time.perf_counter() - t0

    # Let the probes observe a bit more steady-state after the rebuild
    # completes, then stop.
    await asyncio.sleep(2 * lease.HEARTBEAT_SECONDS)
    stop.set()
    await probe_task
    lease_task.cancel()
    try:
        await lease_task
    except asyncio.CancelledError:
        pass
    await worker.stop()
    lease_conn.close()
    return gaps_ms, lease_latencies_s, rebuild_elapsed


async def _run_tick_scenario(db_path: Path) -> tuple[list[float], list[float], float]:
    """Simulates a maximum 2,000-record tick as 4 separate 500-record
    page-persist jobs submitted to the SAME worker in immediate
    succession (matching indexer.py's real per-page `await persist(...)`
    shape -- `ingest_repository_tick` awaits one page's persist before
    starting the next, it never batches all 2,000 records into a single
    worker job)."""
    lease_conn = connect_and_init(db_path)
    repo_id, gen_id = _seed_single_repo(lease_conn, n_evidence=0)

    worker = ReadModelWorker(str(db_path.resolve()))
    worker.start()
    stop = asyncio.Event()
    gaps_ms: list[float] = []
    lease_latencies_s: list[float] = []
    probe_task = asyncio.create_task(_event_loop_probe(stop, gaps_ms))
    lease_task = asyncio.create_task(
        _lease_renewal_probe(worker, lease_conn, "tick-scenario-owner", stop, lease_latencies_s))

    def _persist_page(c: sqlite3.Connection, page_index: int, page_size: int) -> None:
        c.execute("BEGIN IMMEDIATE")
        try:
            rows = []
            base = page_index * page_size
            for i in range(page_size):
                n = base + i
                rows.append((
                    repo_id, gen_id, f"tick-cursor-{n}", "OK", n, "IssueActivated", 1,
                    None, None, None, "2026-08-23T00:00:00Z", f"tick-hash-{n}", 250,
                    "2026-08-23T00:00:00Z",
                ))
            c.executemany(
                "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, "
                "integrity, event_id, event_type, schema_version, issue_id, execution_id, run_id, "
                "event_ts, record_hash, length_bytes, stored_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows,
            )
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")

    t0 = time.perf_counter()
    page_size = 500
    for page_index in range(N_TICK_RECORDS // page_size):
        await worker.submit(lambda c, _pi=page_index: _persist_page(c, _pi, page_size))
    tick_elapsed = time.perf_counter() - t0

    await asyncio.sleep(2 * lease.HEARTBEAT_SECONDS)
    stop.set()
    await probe_task
    lease_task.cancel()
    try:
        await lease_task
    except asyncio.CancelledError:
        pass
    await worker.stop()
    lease_conn.close()
    return gaps_ms, lease_latencies_s, tick_elapsed


def _report(label: str, gaps_ms: list[float], lease_latencies_s: list[float],
            elapsed_s: float) -> bool:
    max_gap = max(gaps_ms) if gaps_ms else 0.0
    max_lease_latency = max(lease_latencies_s) if lease_latencies_s else 0.0
    ok = max_gap <= EVENT_LOOP_STALL_BUDGET_MS and max_lease_latency <= LEASE_LATENCY_BUDGET_S
    print(f"\n{label}")
    print(f"  job elapsed:              {elapsed_s * 1000:.1f}ms")
    print(f"  event-loop probe samples: {len(gaps_ms)}")
    print(f"  max event-loop gap:       {max_gap:.1f}ms (budget {EVENT_LOOP_STALL_BUDGET_MS}ms)")
    print(f"  lease renewal samples:    {len(lease_latencies_s)}")
    print(f"  max lease renewal delay:  {max_lease_latency:.3f}s (budget {LEASE_LATENCY_BUDGET_S}s, TTL {lease.TTL_SECONDS}s)")
    print(f"  result: {'PASS' if ok else 'FAIL'}")
    return ok


async def _main_async() -> int:
    rebuild_db = Path("scale_rebuild_fixture.sqlite3")
    tick_db = Path("scale_tick_fixture.sqlite3")
    for db_path in (rebuild_db, tick_db):
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)

    rebuild_gaps, rebuild_lease, rebuild_elapsed = await _run_rebuild_scenario(rebuild_db)
    tick_gaps, tick_lease, tick_elapsed = await _run_tick_scenario(tick_db)

    ok1 = _report(f"Scenario A: active {N_EVIDENCE_SINGLE_REPO:,}-row rebuild_read_models",
                  rebuild_gaps, rebuild_lease, rebuild_elapsed)
    ok2 = _report(f"Scenario B: maximum {N_TICK_RECORDS:,}-record tick (4 x 500-row pages)",
                  tick_gaps, tick_lease, tick_elapsed)

    for db_path in (rebuild_db, tick_db):
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)

    return 0 if (ok1 and ok2) else 1


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
