"""Unit 15 (docs/27 SS14): performance-acceptance measurement against the
20/1,000/10,000/100,000 scale fixture. Prints observed p95 per endpoint
against the documented budget and exits non-zero if any budget is missed.

Uses FastAPI's TestClient (in-process ASGI calls, no real socket) so the
numbers isolate Dashboard code cost from network/OS scheduling noise --
consistent with docs/27 SS13.5's "temporary Dashboard database and
deterministic seeded repositories/evidence," run from the repository root.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from seed_fixture import build_fixture  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from draindeck_dashboard.app import create_app  # noqa: E402
from draindeck_dashboard.config import DashboardConfig  # noqa: E402
from draindeck_dashboard.db import connect_and_init  # noqa: E402

N_WARMUP = 3
N_SAMPLES = 20

# (label, path, budget_ms)
_LIST_ENDPOINTS = [
    ("overview", "/api/overview", 300),
    ("repository-summaries", "/api/repository-summaries?limit=50", 300),
    ("search", "/api/search?q=repo1&limit=10", 300),
    ("issues list", "/api/issues?limit=50", 300),
    ("runs list", "/api/runs?limit=50", 300),
    ("executions list", "/api/executions?limit=50", 300),
    ("executions groupBy=issue", "/api/executions?limit=50&groupBy=issue", 300),
    ("evidence keyset", "/api/evidence?limit=50", 300),
]
_DETAIL_ENDPOINTS = [
    ("repository health", "/api/repositories/1/health", 200),
    ("repository issues", "/api/repositories/1/issues?limit=50", 200),
    ("issue timeline", "/api/repositories/1/issues/1-i0/timeline?limit=50", 200),
    ("issue topology", "/api/repositories/1/issues/1-i0/topology", 200),
]


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return ordered[idx]


def _measure(client: TestClient, path: str) -> float:
    for _ in range(N_WARMUP):
        client.get(path)
    samples = []
    for _ in range(N_SAMPLES):
        t0 = time.perf_counter()
        resp = client.get(path)
        samples.append((time.perf_counter() - t0) * 1000)
        assert resp.status_code == 200, f"{path} -> {resp.status_code}: {resp.text[:200]}"
    return _p95(samples)


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("scale_fixture.sqlite3")
    if db_path.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(db_path) + suffix).unlink(missing_ok=True)
    conn = connect_and_init(db_path)
    t0 = time.perf_counter()
    counts = build_fixture(conn)
    seed_elapsed = time.perf_counter() - t0
    conn.close()
    print(f"Seeded {counts} in {seed_elapsed:.2f}s")

    cfg = DashboardConfig(db_path=str(db_path.resolve()), observer_executable=str(db_path.resolve()))
    app = create_app(cfg)
    client = TestClient(app, base_url="http://127.0.0.1")

    failures = []
    print(f"\n{'endpoint':<32} {'p95 (ms)':>10} {'budget (ms)':>12}  result")
    for label, path, budget in _LIST_ENDPOINTS + _DETAIL_ENDPOINTS:
        p95 = _measure(client, path)
        ok = p95 <= budget
        print(f"{label:<32} {p95:>10.1f} {budget:>12}  {'PASS' if ok else 'FAIL'}")
        if not ok:
            failures.append((label, p95, budget))

    print()
    if failures:
        print(f"{len(failures)} endpoint(s) missed budget:")
        for label, p95, budget in failures:
            print(f"  - {label}: {p95:.1f}ms > {budget}ms")
        return 1
    print("All endpoints within budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
