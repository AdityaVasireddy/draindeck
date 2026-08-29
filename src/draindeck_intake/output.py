"""Managed, atomic publication of generated Issues.md content."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .compiler import MANAGED_MARKER


class OutputError(RuntimeError):
    """Generated output could not be safely published."""


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
    if destination.is_symlink():
        raise OutputError("output path must not be a symbolic link")

    encoded = content.encode("utf-8")
    if destination.exists():
        if not destination.is_file():
            raise OutputError("output path is not a regular file")
        try:
            with destination.open("rb") as stream:
                prefix = stream.read(len(f"{MANAGED_MARKER}\n".encode("utf-8")))
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

    temporary: Path | None = None
    try:
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
        os.replace(temporary, destination)
        temporary = None
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
    return True
