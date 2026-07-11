# NEXT

## Resume point
Session 2 complete AND reconciled against doc 03 (see doc 10 report).
Event names, envelope, states, transitions, and recovery semantics now
match the frozen contract verbatim. 19 unit tests + 46 harness
scenarios × 2 seeds green on Linux; harness mutation-tested (I-h).

## Before Session 3
1. Run both suites on Windows to confirm the cross-platform kill path:
   `python -m pytest tests\unit -q` (expect 19)
   `python tests\crash\harness.py %TEMP%\ch` (expect 46; self-calibrates
   its kill window to Windows process-spawn speed).
   The harness now uses TerminateProcess on Windows (SIGKILL on POSIX);
   fsync + os.replace remain cross-platform by contract.
2. Fill in `project.validation.commands` in config.yaml (StockAgent
   test command); resolve StockAgent vs StockPhotoAgent path naming.
3. Commit: this tree + docs 01–10 into the runtime repo.

## Session 3 (per doc 07 ordering)
RepositoryAdapter (`repo/adapter.py`, `repo/git_adapter.py`); bind
reconciler seams: `preserve_residue` → residue-to-attempt-ref for real,
check 2 (unwitnessed commit → CommitCreated(backfilled=true)), check 3
(dirty workspace). Extend the harness with a temp git repo as the world.
