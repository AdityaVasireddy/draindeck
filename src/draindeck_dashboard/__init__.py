"""Draindeck Dashboard — local FastAPI/Uvicorn read-only observability UI.

ADR-26 (docs/08 §5h) is the accepted architecture decision; docs/19 is the
public/operational contract. This package is an explicit framework carve-out:
FastAPI/Uvicorn live only here, behind the ``dashboard`` optional-dependency
extra. Core ``src/runtime`` stays framework-free and must never import from
this package or its dependencies.

Dashboard consumes ADR-25 only through the ``draindeck observe`` CLI (see
``runtime.observe`` / ``runtime.main``'s ``observe`` subcommand) — it never
parses ``events.jsonl`` directly, opens a Draindeck workspace/log mutex,
repairs a log, or invokes Git.
"""
from __future__ import annotations
