"""Cross-platform, standard-library-only exclusive launcher-operation lock
(docs/32 review Blocker 9).

Guards the brief critical section in ``launcher.main()`` that loads state,
checks port/identity, decides reuse/collision/start, replaces a stale
process, spawns the child, and writes the new state -- so two concurrent
launcher invocations (e.g. a double-clicked shortcut) cannot both conclude
the port is free and start competing Dashboard children.

Uses a real OS-held exclusive file lock -- ``fcntl.flock`` on POSIX,
``msvcrt.locking`` on Windows -- never a stale-prone "lock file exists"
convention. The lock is always released (``finally``) on success, error,
exception, or early return from the ``with`` block. This module never
kills or inspects the process currently holding the lock; contention is
reported by raising, never resolved by force.
"""
from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path
from typing import Iterator


class LauncherLockTimeout(Exception):
    """Raised when the launcher-operation lock could not be acquired
    within the bounded wait window -- another launcher invocation
    currently owns it."""


if sys.platform == "win32":
    import msvcrt

    def _ensure_lockable_byte(fh) -> None:
        # msvcrt.locking locks a byte RANGE starting at the current file
        # position; an empty file has no byte to lock, so ensure exactly
        # one exists, then rewind before every lock/unlock call.
        if os.fstat(fh.fileno()).st_size == 0:
            fh.write(b"\0")
            fh.flush()

    def _try_lock(fh) -> bool:
        _ensure_lockable_byte(fh)
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fh) -> None:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_lock(fh) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextlib.contextmanager
def launcher_operation_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = 3.0,
    poll_seconds: float = 0.1,
    sleep=time.sleep,
    clock=time.monotonic,
) -> Iterator[None]:
    """Exclusive, OS-held lock scoped to one launcher decide/act critical
    section. Retries acquisition (non-blocking) until ``timeout_seconds``
    (per ``clock``) elapses, then raises ``LauncherLockTimeout`` -- never
    kills or otherwise touches whatever currently holds the lock.

    ``sleep``/``clock`` are injected so tests can drive this deterministically
    without a real wait; real callers use the real ``time`` functions.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # 'a+b' rather than 'w' -- never truncates a lock file another process
    # might concurrently be opening; the byte content itself is unused.
    fh = open(lock_path, "a+b")
    try:
        start = clock()
        while not _try_lock(fh):
            if clock() - start >= timeout_seconds:
                raise LauncherLockTimeout(
                    f"could not acquire launcher operation lock at {lock_path} "
                    f"within {timeout_seconds}s -- another launcher invocation "
                    "is in progress"
                )
            sleep(poll_seconds)
        try:
            yield
        finally:
            _unlock(fh)
    finally:
        fh.close()
