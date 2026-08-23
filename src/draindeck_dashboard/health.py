"""Repository health projection (docs/19 "REST API, SSE, and UI states").

Everything here is derived from Dashboard's OWN persisted state — never a
live re-poll. `observe status` is registration diagnostics only and is
never called from this module or the hot path.
"""
from __future__ import annotations

import sqlite3

from runtime.events.schema import EventType

from . import lease

_KNOWN_EVENT_TYPES = frozenset(t.value for t in EventType)


def build_health(conn: sqlite3.Connection, repo_id: int) -> dict:
    checkpoint = conn.execute(
        "SELECT identity_generation_id, halted_oversized, reduced_confidence, availability "
        "FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()

    generation = None
    corrupt_count = 0
    unknown_event_type_count = 0
    if checkpoint is not None:
        gen_row = conn.execute(
            "SELECT generation_number, content_lineage, file_generation_available "
            "FROM identity_generations WHERE id = ?",
            (checkpoint[0],),
        ).fetchone()
        if gen_row is not None:
            generation = {
                "number": gen_row[0],
                "contentLineage": gen_row[1],
                "fileGenerationAvailable": bool(gen_row[2]),
            }
        corrupt_count = conn.execute(
            "SELECT COUNT(*) FROM corruptions WHERE repository_id = ? "
            "AND identity_generation_id = ?",
            (repo_id, checkpoint[0]),
        ).fetchone()[0]
        type_counts = conn.execute(
            "SELECT event_type, COUNT(*) FROM evidence WHERE repository_id = ? "
            "AND identity_generation_id = ? AND integrity = 'OK' GROUP BY event_type",
            (repo_id, checkpoint[0]),
        ).fetchall()
        unknown_event_type_count = sum(
            count for event_type, count in type_counts if event_type not in _KNOWN_EVENT_TYPES
        )

    lease_state = lease.read_state(conn)

    return {
        "repositoryId": repo_id,
        "availability": checkpoint[3] if checkpoint is not None else None,
        "haltedOversized": bool(checkpoint[1]) if checkpoint is not None else False,
        "reducedConfidence": bool(checkpoint[2]) if checkpoint is not None else False,
        "identityGeneration": generation,
        "corruptCount": corrupt_count,
        "unknownEventTypeCount": unknown_event_type_count,
        # ownerToken is deliberately never included (docs/27 SS11: "Do not
        # expose ... lease owner token ... in cross-repository UI
        # summaries") -- no consumer needs it, only its status/age.
        "lease": {
            "status": lease_state.status,
            "ageSeconds": lease_state.age_seconds,
        },
    }
