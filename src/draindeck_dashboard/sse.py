"""SSE change-feed (docs/19 "REST API, SSE, and UI states").

One indexed monotonic ``change_sequence`` is the only SSE cursor and event
ID. The latest 10,000 changes are retained; replay is capped at 1,000 per
connection; an expired or over-limit cursor returns
``CHANGE_RESYNC_REQUIRED`` before streaming. One ``ChangeTailer`` per
process polls the database and fans new rows out in memory to every
subscriber — individual SSE connections never poll the database
themselves.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from typing import AsyncIterator, Optional

RETENTION_LIMIT = 10_000
REPLAY_CAP = 1_000
HEARTBEAT_SECONDS = 15
RETRY_MS = 3000
TAIL_POLL_SECONDS = 1


def prune_changes(conn: sqlite3.Connection) -> None:
    """Retains only the latest RETENTION_LIMIT changes (docs/19)."""
    row = conn.execute("SELECT MAX(change_sequence) FROM changes").fetchone()
    max_seq = row[0]
    if max_seq is None:
        return
    cutoff = max_seq - RETENTION_LIMIT
    if cutoff > 0:
        conn.execute("DELETE FROM changes WHERE change_sequence <= ?", (cutoff,))


def needs_resync(*, min_retained: Optional[int], max_sequence: int,
                 after: Optional[int]) -> bool:
    """True iff `after` is expired (already pruned away) or would require
    replaying more than REPLAY_CAP changes (docs/19: "An expired or
    over-limit cursor returns CHANGE_RESYNC_REQUIRED"). `after=None` is a
    fresh connect with no prior cursor, never a resync case."""
    if after is None:
        return False
    if min_retained is not None and after < min_retained - 1:
        return True
    if (max_sequence - after) > REPLAY_CAP:
        return True
    return False


@dataclass(frozen=True)
class ChangeRecord:
    change_sequence: int
    repository_id: int
    entity_type: str
    entity_id: str
    created_at: str

    def to_sse_event(self) -> str:
        data = json.dumps({
            "repositoryId": self.repository_id, "entityType": self.entity_type,
            "entityId": self.entity_id, "createdAt": self.created_at,
        }, separators=(",", ":"))
        return f"id: {self.change_sequence}\nevent: change\ndata: {data}\n\n"


def resync_event() -> str:
    return 'event: resync\ndata: {"code":"CHANGE_RESYNC_REQUIRED"}\n\n'


def heartbeat_event() -> str:
    return ": heartbeat\n\n"


def retry_directive() -> str:
    return f"retry: {RETRY_MS}\n\n"


# Sentinel pushed into a subscriber's queue when it overflows (falls more
# than REPLAY_CAP changes behind) -- a plain object so it is never
# mistaken for a real ChangeRecord.
_OVERFLOW = object()


class ChangeTailer:
    """One instance per process. Polls the changes table on an interval
    and fans new rows out in memory to every subscriber's queue."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._subscribers: set = set()
        self._last_seen = self.max_sequence()
        self._task: Optional[asyncio.Task] = None

    def max_sequence(self) -> int:
        row = self._conn.execute("SELECT MAX(change_sequence) FROM changes").fetchone()
        return row[0] or 0

    def min_retained_sequence(self) -> Optional[int]:
        row = self._conn.execute("SELECT MIN(change_sequence) FROM changes").fetchone()
        return row[0]

    def replay(self, after: int) -> list:
        rows = self._conn.execute(
            "SELECT change_sequence, repository_id, entity_type, entity_id, created_at "
            "FROM changes WHERE change_sequence > ? ORDER BY change_sequence",
            (after,),
        ).fetchall()
        return [ChangeRecord(*r) for r in rows]

    def subscribe(self) -> asyncio.Queue:
        # Bounded at REPLAY_CAP: a subscriber this far behind is already in
        # "needs a resync" territory (docs/19's own replay-cap threshold),
        # so unbounded growth for a slow/stalled client is never the
        # alternative -- see the QueueFull handling in poll_once below.
        q: asyncio.Queue = asyncio.Queue(maxsize=REPLAY_CAP)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def poll_once(self) -> int:
        """Checks for new rows since the last poll and fans them out to
        every subscriber. Returns the count found. Exposed separately from
        `run_forever` so tests can drive one iteration deterministically,
        without sleeping."""
        new_max = self.max_sequence()
        if new_max <= self._last_seen:
            return 0
        rows = self.replay(self._last_seen)
        self._last_seen = new_max
        for q in list(self._subscribers):
            for row in rows:
                try:
                    q.put_nowait(row)
                except asyncio.QueueFull:
                    # This subscriber has fallen too far behind to catch up
                    # incrementally. Clear its backlog and hand it a single
                    # overflow sentinel instead: stream_events turns that
                    # into a forced resync, and the client's reconnect gets
                    # a real resync decision from actual DB state -- never
                    # unbounded queue growth for a slow/stalled consumer.
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    q.put_nowait(_OVERFLOW)
                    break
        return len(rows)

    async def run_forever(self) -> None:
        try:
            while True:
                await asyncio.sleep(TAIL_POLL_SECONDS)
                self.poll_once()
        except asyncio.CancelledError:
            pass

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run_forever())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None


async def stream_events(tailer: ChangeTailer, after: Optional[int]) -> AsyncIterator[str]:
    """The SSE body generator for one connection."""
    min_retained = tailer.min_retained_sequence()
    max_seq = tailer.max_sequence()
    if needs_resync(min_retained=min_retained, max_sequence=max_seq, after=after):
        yield resync_event()
        return

    yield retry_directive()
    if after is not None:
        for record in tailer.replay(after):
            yield record.to_sse_event()

    queue = tailer.subscribe()
    try:
        while True:
            try:
                record = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                if record is _OVERFLOW:
                    # Fell more than REPLAY_CAP changes behind (a slow or
                    # stalled consumer) -- force a resync rather than ever
                    # growing the queue unbounded.
                    yield resync_event()
                    return
                yield record.to_sse_event()
            except asyncio.TimeoutError:
                yield heartbeat_event()
    finally:
        tailer.unsubscribe(queue)
