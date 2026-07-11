# issue-runtime

Autonomous issue-resolution runtime. Durability-first: an append-only,
fsync-durable event log is the source of truth; all state is a replayed
projection; recovery runs unconditionally at startup.

Docs 01–10 define the frozen architecture. Doc 03 is the implementation
contract; the code was reconciled against it verbatim (doc 10 is the
reconciliation report).

    pip install pyyaml pydantic pytest
    pytest tests/unit
    python tests/crash/harness.py /tmp/crash-harness   # Phase 1 gate
