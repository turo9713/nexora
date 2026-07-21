from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4


def ensure_secure_directory(path: Path) -> Path:
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError("unsafe storage directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def atomic_write_json(path: Path, value: dict[str, Any] | list[Any]) -> None:
    path = Path(path)
    ensure_secure_directory(path.parent)
    if path.is_symlink():
        raise RuntimeError("unsafe storage file")
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    payload = json.dumps(value, ensure_ascii=False, indent=2)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    path = Path(path)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("unsafe storage file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
