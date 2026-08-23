"""Attention condition detection/reconciliation (ADR-27 decision 3;
docs/27 SS6.4, SS8.5).

Dashboard-derived history, not a runtime warning stream: `first_detected_at`
/`last_detected_at` mean "detected by this Dashboard database," never the
runtime's own onset time. The kind/severity/message/target vocabulary is
closed (docs/27 SS6.4's table) -- this module never invents or escalates a
severity. Conditions are never dismissible; resolution comes only from a
later reconciliation no longer deriving the same condition.

Two independent condition sets: repository-scoped (derived from that
repository's current-generation checkpoint/evidence/read-model rows) and
system-wide (derived from the single indexer lease, `repository_id NULL`).
Reconciling one never touches the other's open rows.

`Pending reconciliation`, a TORN evidence row, and `no controlled finish
observed` are honest observed states on their own entity screens but are
deliberately never derived as attention conditions here.

The `LEASE_UNCLAIMED` 10-second-TTL "no startup flash" visibility gate
(docs/27 SS6.4) is intentionally NOT enforced in this module: the
condition row opens on first detection (so its own `first_detected_at` is
an accurate anchor), and gating when it is *surfaced* to an operator is a
query-layer concern -- Unit 4's `/api/attention` filtering, which this
module's row makes possible to implement, not a rule this derivation/
reconciliation layer itself should second-guess.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from runtime.events.schema import EventType

from . import lease

_KNOWN_EVENT_TYPES = frozenset(t.value for t in EventType)
_EXECUTION_TERMINAL_STATES = frozenset({"ACCEPTED", "REJECTED", "CRASHED"})
_CONTAINMENT_OPEN_STATES = frozenset({"PREPARED", "ESTABLISHED", "UNCONFIRMED"})


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _condition_key(*, repository_id: Optional[int], identity_generation_id: Optional[int],
                   kind: str, disambiguator: Optional[str] = None) -> str:
    """Stable hash over (repository-or-system, generation-or-none, kind,
    disambiguator-or-none). `disambiguator` is usually the subject id, but
    for containment it also folds in containment_generation so two
    generations of the same execution never collide into one row."""
    parts = [
        str(repository_id) if repository_id is not None else "system",
        str(identity_generation_id) if identity_generation_id is not None else "-",
        kind,
        disambiguator or "-",
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Condition:
    condition_key: str
    repository_id: Optional[int]
    identity_generation_id: Optional[int]
    kind: str
    severity: str  # "critical" | "warning" -- "information" reserved, unused in v2
    subject_type: Optional[str]
    subject_id: Optional[str]
    message: str
    target_url: str


def derive_repository_conditions(conn: sqlite3.Connection, repo_id: int) -> list:
    """The current, complete repository-scoped condition set -- a pure
    function of Dashboard's own persisted state for repo_id's CURRENT
    checkpoint generation. Never touches other repositories or system-wide
    (lease) conditions."""
    checkpoint = conn.execute(
        "SELECT identity_generation_id, halted_oversized, reduced_confidence, availability "
        "FROM checkpoints WHERE repository_id = ?",
        (repo_id,),
    ).fetchone()
    if checkpoint is None:
        return []
    gen_id, halted_oversized, reduced_confidence, availability = checkpoint

    conditions: list[Condition] = []

    def _repo_scoped(kind, severity, message, target_url, *, subject_type=None,
                     subject_id=None, disambiguator=None) -> Condition:
        return Condition(
            condition_key=_condition_key(
                repository_id=repo_id, identity_generation_id=gen_id, kind=kind,
                disambiguator=disambiguator if disambiguator is not None else subject_id,
            ),
            repository_id=repo_id, identity_generation_id=gen_id, kind=kind, severity=severity,
            subject_type=subject_type, subject_id=subject_id, message=message, target_url=target_url,
        )

    if halted_oversized:
        conditions.append(_repo_scoped(
            "INDEXING_HALTED_OVERSIZED", "critical",
            "Indexing halted at an oversized record; operator remediation required.",
            f"/repositories/{repo_id}/evidence",
        ))

    if availability == "OFFLINE":
        conditions.append(_repo_scoped(
            "REPOSITORY_OFFLINE", "warning", "Registered log is currently offline.",
            f"/repositories/{repo_id}",
        ))

    if reduced_confidence:
        conditions.append(_repo_scoped(
            "REDUCED_IDENTITY_CONFIDENCE", "warning",
            "Identity generation is lineage-only; file-generation identity unavailable.",
            f"/repositories/{repo_id}",
        ))

    corrupt_event_ids = conn.execute(
        "SELECT DISTINCT event_id FROM corruptions WHERE repository_id = ? "
        "AND identity_generation_id = ?",
        (repo_id, gen_id),
    ).fetchall()
    for (event_id,) in corrupt_event_ids:
        conditions.append(_repo_scoped(
            "CORRUPT_EVIDENCE", "critical", f"Conflicting OK records share event ID {event_id}.",
            f"/repositories/{repo_id}/evidence", subject_type="event", subject_id=str(event_id),
        ))

    malformed_count = conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE repository_id = ? AND identity_generation_id = ? "
        "AND integrity = 'MALFORMED'",
        (repo_id, gen_id),
    ).fetchone()[0]
    if malformed_count > 0:
        conditions.append(_repo_scoped(
            "MALFORMED_EVIDENCE", "warning",
            "Malformed complete evidence is present in the current generation.",
            f"/repositories/{repo_id}/evidence",
        ))

    type_counts = conn.execute(
        "SELECT event_type, COUNT(*) FROM evidence WHERE repository_id = ? "
        "AND identity_generation_id = ? AND integrity = 'OK' GROUP BY event_type",
        (repo_id, gen_id),
    ).fetchall()
    unknown_count = sum(
        count for event_type, count in type_counts if event_type not in _KNOWN_EVENT_TYPES
    )
    if unknown_count > 0:
        conditions.append(_repo_scoped(
            "UNKNOWN_EVENT_TYPES", "warning",
            f"{unknown_count} unknown complete event types retained as evidence.",
            f"/repositories/{repo_id}/evidence",
        ))

    issue_rows = conn.execute(
        "SELECT issue_id, state, inconsistent FROM issue_views "
        "WHERE repository_id = ? AND identity_generation_id = ?",
        (repo_id, gen_id),
    ).fetchall()
    for issue_id, state, inconsistent in issue_rows:
        target = f"/repositories/{repo_id}/issues/{issue_id}"
        if state == "NEEDS_HUMAN":
            conditions.append(_repo_scoped(
                "ISSUE_NEEDS_HUMAN", "warning", "Issue requires human intervention.", target,
                subject_type="issue", subject_id=issue_id,
            ))
        elif state == "NEEDS_DECOMPOSITION":
            conditions.append(_repo_scoped(
                "ISSUE_NEEDS_DECOMPOSITION", "warning", "Issue requires decomposition.", target,
                subject_type="issue", subject_id=issue_id,
            ))
        if inconsistent:
            conditions.append(_repo_scoped(
                "INCONSISTENT_ISSUE", "warning", "Inconsistent issue lifecycle evidence observed.",
                target, subject_type="issue", subject_id=issue_id,
            ))

    exec_rows = conn.execute(
        "SELECT execution_id, state, inconsistent FROM execution_views "
        "WHERE repository_id = ? AND identity_generation_id = ?",
        (repo_id, gen_id),
    ).fetchall()
    for execution_id, exec_state, inconsistent in exec_rows:
        target = f"/repositories/{repo_id}/executions/{execution_id}"
        if inconsistent:
            conditions.append(_repo_scoped(
                "INCONSISTENT_EXECUTION", "warning",
                "Inconsistent execution lifecycle evidence observed.", target,
                subject_type="execution", subject_id=execution_id,
            ))

        containment_rows = conn.execute(
            "SELECT containment_generation, state FROM containment_views "
            "WHERE repository_id = ? AND identity_generation_id = ? AND execution_id = ?",
            (repo_id, gen_id, execution_id),
        ).fetchall()
        for cgen, cstate in containment_rows:
            if cstate == "UNCONFIRMED":
                conditions.append(_repo_scoped(
                    "CONTAINMENT_UNCONFIRMED", "critical",
                    f"Termination could not be confirmed for containment {cgen}.", target,
                    subject_type="execution", subject_id=execution_id,
                    disambiguator=f"{execution_id}:{cgen}",
                ))
            if exec_state in _EXECUTION_TERMINAL_STATES and cstate in _CONTAINMENT_OPEN_STATES:
                conditions.append(_repo_scoped(
                    "CONTAINMENT_UNRELEASED", "critical",
                    f"Terminal execution retains unreleased containment {cgen}.", target,
                    subject_type="execution", subject_id=execution_id,
                    disambiguator=f"{execution_id}:{cgen}:unreleased",
                ))

    run_rows = conn.execute(
        "SELECT run_id, inconsistent FROM run_views WHERE repository_id = ? "
        "AND identity_generation_id = ?",
        (repo_id, gen_id),
    ).fetchall()
    for run_id, inconsistent in run_rows:
        if inconsistent:
            conditions.append(_repo_scoped(
                "INCONSISTENT_RUN", "warning", "Inconsistent run lifecycle evidence observed.",
                f"/repositories/{repo_id}/runs/{run_id}", subject_type="run", subject_id=run_id,
            ))

    return conditions


def derive_system_conditions(conn: sqlite3.Connection) -> list:
    """LEASE_STALE (critical, immediate) and LEASE_UNCLAIMED (warning) are
    mutually exclusive -- read_state's status is exactly one of
    held/expired/unclaimed. A held lease produces no condition."""
    state = lease.read_state(conn)
    if state.status == "expired":
        return [Condition(
            condition_key=_condition_key(repository_id=None, identity_generation_id=None,
                                         kind="LEASE_STALE"),
            repository_id=None, identity_generation_id=None, kind="LEASE_STALE",
            severity="critical", subject_type=None, subject_id=None,
            message="Indexer lease expired; Dashboard freshness is not advancing.",
            target_url="/about",
        )]
    if state.status == "unclaimed":
        return [Condition(
            condition_key=_condition_key(repository_id=None, identity_generation_id=None,
                                         kind="LEASE_UNCLAIMED"),
            repository_id=None, identity_generation_id=None, kind="LEASE_UNCLAIMED",
            severity="warning", subject_type=None, subject_id=None,
            message="Indexer lease remains unclaimed.", target_url="/about",
        )]
    return []


def _record_change(conn: sqlite3.Connection, repo_id: int, entity_type: str, entity_id: str,
                   now: str) -> None:
    conn.execute(
        "INSERT INTO changes (repository_id, entity_type, entity_id, created_at) VALUES (?, ?, ?, ?)",
        (repo_id, entity_type, entity_id, now),
    )


def _upsert_open(conn: sqlite3.Connection, c: Condition, now: str) -> bool:
    """Returns True iff this call newly OPENED the condition (a fresh
    insert or a recur after resolution) -- False for a mere refresh of an
    already-open row. Only an open/resolve transition gets an SSE
    invalidation (docs/27 SS8.5); a refresh must not re-invalidate."""
    existing = conn.execute(
        "SELECT id FROM attention_conditions WHERE condition_key = ? AND resolved_at IS NULL",
        (c.condition_key,),
    ).fetchone()
    if existing is not None:
        conn.execute(
            "UPDATE attention_conditions SET last_detected_at = ?, message = ?, target_url = ? "
            "WHERE id = ?",
            (now, c.message, c.target_url, existing[0]),
        )
        return False
    last_occurrence = conn.execute(
        "SELECT MAX(occurrence) FROM attention_conditions WHERE condition_key = ?",
        (c.condition_key,),
    ).fetchone()[0]
    occurrence = (last_occurrence or 0) + 1
    conn.execute(
        "INSERT INTO attention_conditions (condition_key, occurrence, repository_id, "
        "identity_generation_id, kind, severity, subject_type, subject_id, message, target_url, "
        "first_detected_at, last_detected_at, resolved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (c.condition_key, occurrence, c.repository_id, c.identity_generation_id, c.kind,
         c.severity, c.subject_type, c.subject_id, c.message, c.target_url, now, now),
    )
    return True


def _resolve_stale(conn: sqlite3.Connection, *, repository_id: Optional[int],
                   current_keys: set, now: str) -> list:
    """Returns the condition_keys resolved this call, for the caller to
    invalidate."""
    if repository_id is None:
        rows = conn.execute(
            "SELECT id, condition_key FROM attention_conditions "
            "WHERE repository_id IS NULL AND resolved_at IS NULL"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, condition_key FROM attention_conditions "
            "WHERE repository_id = ? AND resolved_at IS NULL", (repository_id,)
        ).fetchall()
    resolved_keys = []
    for row_id, key in rows:
        if key not in current_keys:
            conn.execute("UPDATE attention_conditions SET resolved_at = ? WHERE id = ?", (now, row_id))
            resolved_keys.append(key)
    return resolved_keys


# Reserved system-wide changes-table repository_id (docs/27 SS3.2 decision
# 6 / SS8.5) -- real repository IDs begin at one.
SYSTEM_CHANGE_REPOSITORY_ID = 0


def reconcile_repository_conditions(conn: sqlite3.Connection, repo_id: int, conditions: list) -> None:
    """`conditions` must be repo_id's complete CURRENT set (from
    ``derive_repository_conditions``). Opens/refreshes each; resolves any
    previously-open repo_id-scoped row whose key is no longer present --
    including, with no special-casing needed, every stale condition from a
    superseded identity generation after rollover. Records one `attention`
    changes-table invalidation per opened or resolved condition (never for
    a mere refresh)."""
    now = _now()
    current_keys = set()
    for c in conditions:
        current_keys.add(c.condition_key)
        if _upsert_open(conn, c, now):
            _record_change(conn, repo_id, "attention", c.condition_key, now)
    resolved_keys = _resolve_stale(conn, repository_id=repo_id, current_keys=current_keys, now=now)
    for key in resolved_keys:
        _record_change(conn, repo_id, "attention", key, now)


def reconcile_system_conditions(conn: sqlite3.Connection, conditions: list) -> None:
    """Same as ``reconcile_repository_conditions`` but scoped to
    repository_id IS NULL rows (system-wide lease conditions) only;
    invalidations use the reserved system repository_id 0."""
    now = _now()
    current_keys = set()
    for c in conditions:
        current_keys.add(c.condition_key)
        if _upsert_open(conn, c, now):
            _record_change(conn, SYSTEM_CHANGE_REPOSITORY_ID, "attention", c.condition_key, now)
    resolved_keys = _resolve_stale(conn, repository_id=None, current_keys=current_keys, now=now)
    for key in resolved_keys:
        _record_change(conn, SYSTEM_CHANGE_REPOSITORY_ID, "attention", key, now)
