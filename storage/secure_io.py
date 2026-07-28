"""Private, atomic filesystem helpers for Nexora state.

The helpers intentionally do not rely on the process umask.  Every directory
and file is normalised after creation, and temporary files are created with an
explicit private mode before they can contain state.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_allowed(path: Path, root: Path | None) -> None:
    if root is None:
        return
    selected_root = Path(root).resolve(strict=False)
    selected = Path(path).resolve(strict=False)
    if not _within(selected, selected_root):
        raise RuntimeError("storage path is outside the allowed root")


def _reject_symlinks(path: Path, stop: Path | None = None) -> None:
    current = Path(path)
    boundary = Path(stop).resolve(strict=False) if stop is not None else None
    while True:
        if current.exists() and current.is_symlink():
            raise RuntimeError("symbolic links are not allowed in private storage")
        if boundary is not None and current.resolve(strict=False) == boundary:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent


def ensure_private_directory(path: Path, *, root: Path | None = None) -> Path:
    selected = Path(path)
    _assert_allowed(selected, root)
    _reject_symlinks(selected, root)
    selected.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    if selected.is_symlink() or not selected.is_dir():
        raise RuntimeError("private storage directory is unsafe")
    os.chmod(selected, PRIVATE_DIRECTORY_MODE)
    return selected


def ensure_private_file(path: Path, *, root: Path | None = None) -> Path:
    selected = Path(path)
    _assert_allowed(selected, root)
    _reject_symlinks(selected, root)
    if selected.is_symlink() or not selected.is_file():
        raise RuntimeError("private storage file is unsafe")
    os.chmod(selected, PRIVATE_FILE_MODE)
    return selected


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace(source: Path, destination: Path) -> None:
    attempts = 5 if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(0.02 * (attempt + 1))


def secure_atomic_write_text(
    path: Path,
    value: str,
    *,
    encoding: str = "utf-8",
    root: Path | None = None,
) -> None:
    selected = Path(path)
    _assert_allowed(selected, root)
    parent = ensure_private_directory(selected.parent, root=root)
    _reject_symlinks(selected, root)
    if selected.exists() and (selected.is_symlink() or not selected.is_file()):
        raise RuntimeError("private storage target is unsafe")
    # Keep the temporary name deliberately short. Windows installations may
    # still enforce MAX_PATH, while state filenames can already be long hashes.
    temporary = parent / f".{uuid4().hex[:12]}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        PRIVATE_FILE_MODE,
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "w", encoding=encoding, newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, PRIVATE_FILE_MODE)
        _atomic_replace(temporary, selected)
        os.chmod(selected, PRIVATE_FILE_MODE)
        _fsync_directory(parent)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    finally:
        temporary.unlink(missing_ok=True)


def secure_atomic_write_json(
    path: Path,
    value: dict[str, Any] | list[Any],
    *,
    root: Path | None = None,
) -> None:
    secure_atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2),
        root=root,
    )


def append_private_text(path: Path, value: str, *, root: Path | None = None) -> None:
    selected = Path(path)
    _assert_allowed(selected, root)
    ensure_private_directory(selected.parent, root=root)
    _reject_symlinks(selected, root)
    if selected.exists() and (selected.is_symlink() or not selected.is_file()):
        raise RuntimeError("private storage target is unsafe")
    descriptor = os.open(
        selected,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT,
        PRIVATE_FILE_MODE,
    )
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "a", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(selected, PRIVATE_FILE_MODE)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
