"""RED test, ULTRA-REVIEW-001 finding 2: the launcher-readiness Ollama
probe must not block the Dashboard's asyncio event loop.

Root cause under test: `src/draindeck_dashboard/app.py`'s
`async def launcher_readiness(...)` route calls
`evaluate_repository_run_readiness(...)` directly (never `await`ed, never
offloaded via `run_in_threadpool`/`asyncio.to_thread`), which in turn calls
`src/draindeck_dashboard/launcher_readiness.py`'s
`check_reviewer_model_present`, a synchronous, blocking
`urllib.request.urlopen(...)` call. A slow or unreachable Ollama endpoint
therefore blocks the ENTIRE single-threaded event loop for the duration of
that request -- starving every other concurrent request the Dashboard
process is serving (SSE streams, other API calls), not just the one making
the readiness check.

Proven here by running two requests concurrently, in-process, against the
real ASGI app on one asyncio event loop (`httpx.ASGITransport` runs the
app directly on the calling loop -- no separate thread/process, so if the
readiness route ever truly blocks the loop, an unrelated concurrent
`/api/health` request cannot be scheduled until it releases the loop).

Planning-gate only (docs/32 review, ULTRA-REVIEW-001): no `src/` change here.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from draindeck_dashboard import app as app_module
from draindeck_dashboard import launcher_readiness
from draindeck_dashboard.app import create_app
from draindeck_dashboard.config import DashboardConfig

_SLOW_PROBE_SECONDS = 0.4
_HEALTH_START_DELAY_SECONDS = 0.05
# A generous, non-flaky ceiling: if the loop were genuinely free, /api/health
# (a trivial handler) resolves in low single-digit milliseconds. Anything
# anywhere near _SLOW_PROBE_SECONDS proves it was stuck behind the blocking
# probe instead.
_MAX_ACCEPTABLE_HEALTH_LATENCY_SECONDS = 0.2


def _cfg(tmp_path: Path) -> DashboardConfig:
    return DashboardConfig(
        db_path=str(tmp_path / "dashboard.sqlite3"),
        observer_executable=str(tmp_path / "draindeck.exe"),
    )


def _git_worktree(tmp_path, name="repo"):
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True)
    return repo


_VALID_CONFIG_YAML = """
project:
  name: T
  repository: {repository!r}
  branch: agent-work
  issues_file: Issues.md
  validation:
    commands: ["echo ok"]
engine:
  provider: claude-headless
  auth_mode: subscription
  model: default
  max_turns: 30
  timeout_seconds: 1800
reviewer:
  provider: qwen
  qwen:
    endpoint: http://localhost:11434
    model: qwen2.5-coder
budget:
  max_attempts_per_issue: 3
  max_executions_per_run: 10
  hard_stop_proxy_cost_per_run_usd: 15.0
  proxy_pricing: api_list_rates
experiment:
  sample_size: 20
  attempt1_success_min: 0.3
  cost_per_shipped_issue_max_usd: 3.0
billing:
  posture: p
  headless_split_status: paused
  verified_on: '2026-07-10'
  reverify_at: x
"""


def _slow_urlopen(url, timeout=None):
    # Simulates a slow/unreachable Ollama instance -- entirely synchronous,
    # exactly like the real urllib.request.urlopen call it replaces.
    time.sleep(_SLOW_PROBE_SECONDS)
    raise TimeoutError("simulated slow/unreachable ollama")


def test_launcher_readiness_ollama_probe_does_not_block_concurrent_requests(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    app = create_app(cfg)

    # Register a repository with a real reviewer model configured so the
    # readiness route actually reaches check_reviewer_model_present (an
    # omitted repoId, or no configured reviewer model, short-circuits
    # before ever touching Ollama and would not exercise this bug).
    repo = _git_worktree(tmp_path)
    draindeck_dir = repo / ".draindeck"
    draindeck_dir.mkdir()
    config_path = draindeck_dir / "config.local.yaml"
    config_path.write_text(_VALID_CONFIG_YAML.format(repository=str(repo)), encoding="utf-8")

    monkeypatch.setattr(app_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    monkeypatch.setattr(launcher_readiness.urllib.request, "urlopen", _slow_urlopen)

    async def run():
        transport = httpx.ASGITransport(app=app)
        # Must be a loopback Host header -- LoopbackOnlyMiddleware (docs/19
        # "Local web security") rejects anything else with 403, including
        # httpx's default "http://test" AsyncClient base_url.
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            created = await client.post(
                "/api/repositories", json={"projectPath": str(repo), "configPath": str(config_path)},
            )
            assert created.status_code == 201
            repo_id = created.json()["id"]

            health_latency = {}

            async def call_readiness():
                await client.get(f"/api/launcher/readiness?repoId={repo_id}")

            async def call_health():
                # Timer started BEFORE the head-start delay: if the event
                # loop is blocked, this asyncio.sleep's own timer callback
                # cannot fire on time either, so measuring only from after
                # the delay would hide exactly the effect under test (the
                # delayed wakeup already absorbs the blocked time, making
                # the subsequent request look artificially fast).
                t0 = time.monotonic()
                # Give the readiness call a head start so it has already
                # entered the blocking probe before /api/health is issued.
                await asyncio.sleep(_HEALTH_START_DELAY_SECONDS)
                resp = await client.get("/api/health")
                health_latency["seconds"] = time.monotonic() - t0
                assert resp.status_code == 200

            await asyncio.gather(call_readiness(), call_health())
            return health_latency["seconds"]

    health_elapsed = asyncio.run(run())

    assert health_elapsed < _MAX_ACCEPTABLE_HEALTH_LATENCY_SECONDS, (
        f"RED (finding 2): a concurrent, unrelated GET /api/health took "
        f"{health_elapsed:.3f}s to respond while GET /api/launcher/readiness was "
        f"blocked inside a synchronous {_SLOW_PROBE_SECONDS}s Ollama probe -- the "
        f"asyncio event loop was starved instead of remaining responsive. "
        f"src/draindeck_dashboard/app.py:launcher_readiness calls "
        f"evaluate_repository_run_readiness synchronously inside the coroutine; "
        f"src/draindeck_dashboard/launcher_readiness.py:check_reviewer_model_present "
        f"uses a blocking urllib.request.urlopen with no threadpool offload."
    )
