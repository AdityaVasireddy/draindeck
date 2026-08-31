"""Draindeck Dashboard — local FastAPI/Uvicorn operator UI.

ADR-26 (docs/08 §5h) is the accepted architecture decision; docs/19 is the
public/operational contract. This package is an explicit framework carve-out:
FastAPI/Uvicorn live only here, behind the ``dashboard`` optional-dependency
extra. Core ``src/runtime`` stays framework-free and must never import from
this package or its dependencies.

Two narrow, ADR-gated exceptions to an otherwise read-only, observation-only
boundary exist. ADR-29 (docs/08 §5k) lets the Dashboard write exactly one
target-owned file, ``.draindeck/config.local.yaml``, through the shared
``runtime.init.service`` policy gate. ADR-30 (docs/adr/ADR-30-dashboard-issue-
selection-and-run-control.md, docs/08 §5l) additionally makes the Dashboard
launch-capable: for a registered repository, it may plan an exact
dependency-safe issue batch and launch at most one ``runtime.main run``
process per repository via a fixed argv vector (``shell=False``).

Outside those two gates the boundary is unchanged. Dashboard consumes ADR-25
only through the ``draindeck observe`` CLI (see ``runtime.observe`` /
``runtime.main``'s ``observe`` subcommand) — it never parses ``events.jsonl``
directly, opens a Draindeck workspace/log mutex, repairs a log, or invokes
Git itself; the launched runtime process remains the sole owner of all of
that.
"""
from __future__ import annotations
