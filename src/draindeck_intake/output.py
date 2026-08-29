"""Managed, atomic publication of generated Issues.md content."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .compiler import MANAGED_MARKER


class OutputError(RuntimeError):
    """Generated output could not be safely published."""


def _identity(path: Path) -> tuple[int, int, int, int, int]:
    """Return a stable-enough identity used to detect a changed destination."""
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def publish_managed(
    path: str | Path, content: str, *, force: bool = False
) -> bool:
    """Atomically publish managed UTF-8 content; return whether bytes changed."""
    if not isinstance(content, str) or not content.startswith(f"{MANAGED_MARKER}\n"):
        raise OutputError("output content is not Draindeck Intake managed content")
    if "\r" in content or not content.endswith("\n") or content.endswith("\n\n"):
        raise OutputError("output content must use LF with one trailing newline")
    destination = Path(path)
    parent = destination.parent
    if not parent.exists() or not parent.is_dir():
        raise OutputError("output parent directory does not exist")

    encoded = content.encode("utf-8")
    lock_path = parent / f".{destination.name}.draindeck-intake.lock"
    try:
        lock_descriptor = os.open(
            lock_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except FileExistsError as exc:
        raise OutputError("another Intake publication holds the output lock") from exc
    except OSError as exc:
        raise OutputError(f"unable to acquire output lock: {exc.__class__.__name__}") from exc

    temporary: Path | None = None
    try:
        expected_identity: tuple[int, int, int, int, int] | None = None
        if destination.is_symlink():
            raise OutputError("output path must not be a symbolic link")
        if destination.exists():
            if not destination.is_file():
                raise OutputError("output path is not a regular file")
            try:
                with destination.open("rb") as stream:
                    prefix = stream.read(len(f"{MANAGED_MARKER}\n".encode("utf-8")))
                expected_identity = _identity(destination)
            except OSError as exc:
                raise OutputError(
                    f"unable to inspect output: {exc.__class__.__name__}"
                ) from exc
            if prefix != f"{MANAGED_MARKER}\n".encode("utf-8") and not force:
                raise OutputError("refusing to replace an unmanaged output file")
            try:
                if destination.stat().st_size == len(encoded) and destination.read_bytes() == encoded:
                    return False
            except OSError as exc:
                raise OutputError(
                    f"unable to compare output: {exc.__class__.__name__}"
                ) from exc

        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

        if destination.is_symlink():
            raise OutputError("output path must not be a symbolic link")
        if expected_identity is None:
            if destination.exists():
                raise OutputError("output changed while preparing publication")
        else:
            try:
                if _identity(destination) != expected_identity:
                    raise OutputError("output changed while preparing publication")
            except FileNotFoundError as exc:
                raise OutputError("output changed while preparing publication") from exc
        os.replace(temporary, destination)
        temporary = None
        return True
    except OSError as exc:
        raise OutputError(
            f"unable to publish managed output: {exc.__class__.__name__}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            os.close(lock_descriptor)
        finally:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
