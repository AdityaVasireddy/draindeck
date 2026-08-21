"""Bounded, concurrency-limited observer polling (docs/19 "Registration and
polling"). This module owns pagination bounding, the global concurrency
cap, and OVERSIZED terminal handling; Phase 4 wires durable checkpoint
persistence and identity-generation semantics on top of the PollResult
returned here.

Hot polling uses ONLY ``observe events`` — availability is read from its
``metadata.availability`` field. ``observe status`` is registration
diagnostics only and is never called from this module.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from .observer_client import ObserverError, invoke_observer_events

MAX_PAGES_PER_TICK = 4
PAGE_LIMIT = 500
NORMAL_INTERVAL_SECONDS = 2
BACKOFF_MIN_SECONDS = 2
BACKOFF_MAX_SECONDS = 60

# Global concurrency across every repository's observer invocation in this
# process (docs/19 "global concurrency four"). One repository's poll holds
# one slot for its whole tick — its own pages are inherently sequential
# (each needs the prior page's cursor), so this bounds how many
# repositories can be actively polling at once, which is what "global
# concurrency" is protecting: total concurrent observer subprocesses.
_global_semaphore = asyncio.Semaphore(4)


@dataclass
class PollResult:
    pages_fetched: int = 0
    records: list = field(default_factory=list)
    next_cursor: Optional[str] = None
    availability: Optional[str] = None
    halted_oversized: bool = False
    error: Optional[ObserverError] = None


def next_backoff_seconds(current_backoff: Optional[float]) -> float:
    """Exponential backoff from 2s to a 60s ceiling (docs/19
    OFFLINE/NOT_INITIALIZED — the same schedule applies to both)."""
    if current_backoff is None:
        return BACKOFF_MIN_SECONDS
    return min(current_backoff * 2, BACKOFF_MAX_SECONDS)


async def poll_pages(executable: str, log_path: str, after: Optional[str]):
    """Async generator: up to MAX_PAGES_PER_TICK raw observer-response pages
    for one repository's tick, holding the global concurrency slot for the
    whole generator's lifetime (one repository occupies one of the four
    slots for its entire tick, since its own pages are inherently
    sequential). Yields each page as returned by `observe events`, then
    stops — without a further observer call — at a caught-up page (hasMore
    false) or an OVERSIZED tail (terminal: ADR-25 exposes no safe cursor
    beyond it, so this never chases hasMore past it). An ObserverError
    propagates to the caller after any pages already yielded."""
    cursor = after
    async with _global_semaphore:
        for _ in range(MAX_PAGES_PER_TICK):
            page = await asyncio.to_thread(
                invoke_observer_events, executable, log_path,
                after=cursor, limit=PAGE_LIMIT,
            )
            yield page
            if any(r["integrity"] == "OVERSIZED" for r in page["records"]):
                return
            cursor = page["nextCursor"]
            if not page["hasMore"]:
                return


async def poll_repository_once(executable: str, log_path: str,
                                after: Optional[str]) -> PollResult:
    """One tick for one repository, aggregated into a single PollResult —
    see `poll_pages` for the per-page bounding rules this is built on.
    Phase 4's indexer uses `poll_pages` directly instead, so each page can
    be persisted in its own transaction."""
    result = PollResult()
    try:
        async for page in poll_pages(executable, log_path, after):
            result.pages_fetched += 1
            result.availability = page["metadata"]["availability"]
            records = page["records"]
            result.records.extend(records)
            result.next_cursor = page["nextCursor"]
            if any(r["integrity"] == "OVERSIZED" for r in records):
                result.halted_oversized = True
    except ObserverError as e:
        result.error = e
    return result
