"""Unit 15 (docs/27 SS14): deterministic Dashboard-owned scale fixture --
20 repositories, 1,000 issues, 10,000 executions, 100,000 evidence rows.

Writes directly into the Dashboard's own v2 read-model/evidence tables
(never through a real observer subprocess or a target repository's event
log) so this stays entirely Dashboard-owned per docs/27 SS13.5's "use a
temporary Dashboard database and deterministic seeded repositories/
evidence." Deterministic given a fixed seed -- re-running against a fresh
database produces the same row counts and id distribution every time.
"""
from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from draindeck_dashboard.db import connect_and_init

N_REPOSITORIES = 20
N_ISSUES = 1_000
N_EXECUTIONS = 10_000
N_EVIDENCE = 100_000

_ISSUE_STATES = ["OPEN", "IN_PROGRESS", "DONE", "NEEDS_DECOMPOSITION", "NEEDS_HUMAN"]
_EXECUTION_STATES = ["PENDING", "VALIDATING", "REVIEWING", "ACCEPTED", "REJECTED", "CRASHED"]
_EVENT_TYPES = [
    "IssueActivated", "IssueCompleted", "IssueEscalated", "ExecutionSpawned",
    "ExecutionFinished", "CommitIntent", "CommitCreated", "ReviewApproved", "ValidationPassed",
]


def build_fixture(conn: sqlite3.Connection, *, seed: int = 42) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        counts = _build_fixture_locked(conn, seed=seed)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return counts


def _build_fixture_locked(conn: sqlite3.Connection, *, seed: int) -> dict:
    # The connection is opened with isolation_level=None (autocommit) --
    # build_fixture() wraps this whole seed in one explicit transaction so
    # 100,000+ inserts don't each pay an individual WAL commit/fsync.
    rng = random.Random(seed)
    now = "2026-08-23T00:00:00Z"

    repo_ids: list[int] = []
    gen_ids: dict[int, int] = {}
    for i in range(N_REPOSITORIES):
        cur = conn.execute(
            "INSERT INTO repositories (project_path, log_path, canonical_log_path, created_at) "
            "VALUES (?, ?, ?, ?)",
            (f"C:/scale/repo{i}", f"C:/scale/repo{i}/events.jsonl",
             f"c:/scale/repo{i}/events.jsonl", now),
        )
        repo_id = cur.lastrowid
        gen_id = conn.execute(
            "INSERT INTO identity_generations (repository_id, generation_number, content_lineage, "
            "file_generation_device, file_generation_file_index, file_generation_available, opened_at) "
            "VALUES (?, 1, 'lineage', 1, 1, 1, ?)",
            (repo_id, now),
        ).lastrowid
        conn.execute(
            "INSERT INTO checkpoints (repository_id, identity_generation_id, last_record_cursor, "
            "last_record_hash, halted_oversized, reduced_confidence, availability, updated_at) "
            "VALUES (?, ?, NULL, NULL, 0, 0, 'AVAILABLE', ?)",
            (repo_id, gen_id, now),
        )
        repo_ids.append(repo_id)
        gen_ids[repo_id] = gen_id

    issue_ids: list[tuple[int, str]] = []
    issues_per_repo = N_ISSUES // N_REPOSITORIES
    for repo_id in repo_ids:
        gen_id = gen_ids[repo_id]
        rows = []
        for j in range(issues_per_repo):
            issue_id = f"{repo_id}-i{j}"
            rows.append((repo_id, gen_id, issue_id, rng.choice(_ISSUE_STATES),
                         f"Issue {j} in repo {repo_id}", 0, None, now))
            issue_ids.append((repo_id, issue_id))
        conn.executemany(
            "INSERT INTO issue_views (repository_id, identity_generation_id, issue_id, state, "
            "title, inconsistent, last_event_id, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    run_ids: list[tuple[int, str]] = []
    runs_per_repo = 100
    for repo_id in repo_ids:
        gen_id = gen_ids[repo_id]
        rows = []
        for k in range(runs_per_repo):
            run_id = f"{repo_id}-r{k}"
            rows.append((repo_id, gen_id, run_id, "anthropic", "claude-sonnet-5", "anthropic",
                        "claude-sonnet-5", "{}", "digest", "COMPLETED", 0, None, now, now, now))
            run_ids.append((repo_id, run_id))
        conn.executemany(
            "INSERT INTO run_views (repository_id, identity_generation_id, run_id, engine_provider, "
            "engine_model, reviewer_provider, reviewer_model, budget_json, config_digest, outcome, "
            "inconsistent, last_event_id, observed_started_at, observed_finished_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    execution_ids: list[tuple[int, str]] = []
    executions_per_repo = N_EXECUTIONS // N_REPOSITORIES
    for repo_id in repo_ids:
        gen_id = gen_ids[repo_id]
        repo_issues = [iid for rid, iid in issue_ids if rid == repo_id]
        repo_runs = [rid_ for rid, rid_ in run_ids if rid == repo_id]
        rows = []
        for m in range(executions_per_repo):
            execution_id = f"{repo_id}-e{m}"
            issue_id = rng.choice(repo_issues) if repo_issues else None
            run_id = rng.choice(repo_runs) if repo_runs else None
            rows.append((repo_id, gen_id, execution_id, issue_id, rng.choice(_EXECUTION_STATES),
                        0, m, run_id, now))
            execution_ids.append((repo_id, execution_id))
        conn.executemany(
            "INSERT INTO execution_views (repository_id, identity_generation_id, execution_id, "
            "issue_id, state, inconsistent, last_event_id, run_id, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    evidence_per_repo = N_EVIDENCE // N_REPOSITORIES
    for repo_id in repo_ids:
        gen_id = gen_ids[repo_id]
        repo_issues = [iid for rid, iid in issue_ids if rid == repo_id]
        repo_executions = [eid for rid, eid in execution_ids if rid == repo_id]
        repo_runs = [rid_ for rid, rid_ in run_ids if rid == repo_id]
        rows = []
        for n in range(evidence_per_repo):
            event_type = rng.choice(_EVENT_TYPES)
            rows.append((
                repo_id, gen_id, f"cursor-{repo_id}-{n}", "OK", n, event_type, 1,
                rng.choice(repo_issues) if repo_issues else None,
                rng.choice(repo_executions) if repo_executions else None,
                rng.choice(repo_runs) if repo_runs else None,
                now, f"hash-{repo_id}-{n}", 250, now,
            ))
        conn.executemany(
            "INSERT INTO evidence (repository_id, identity_generation_id, record_cursor, integrity, "
            "event_id, event_type, schema_version, issue_id, execution_id, run_id, event_ts, "
            "record_hash, length_bytes, stored_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "INSERT OR REPLACE INTO read_model_state (repository_id, identity_generation_id, status, "
            "completed_evidence_id, started_at, completed_at, error_code) "
            "VALUES (?, ?, 'READY', ?, ?, ?, NULL)",
            (repo_id, gen_id, evidence_per_repo - 1, now, now),
        )

    return {
        "repositories": len(repo_ids), "issues": len(issue_ids), "runs": len(run_ids),
        "executions": len(execution_ids), "evidence": N_EVIDENCE,
    }


def main() -> None:
    import sys
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scale_fixture.sqlite3")
    conn = connect_and_init(db_path)
    counts = build_fixture(conn)
    conn.close()
    print(f"Seeded {db_path}: {counts}")


if __name__ == "__main__":
    main()
