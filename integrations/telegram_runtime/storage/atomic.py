from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nexora.storage.secure_io import ensure_private_directory, secure_atomic_write_json


def ensure_secure_directory(path: Path) -> Path:
    return ensure_private_directory(Path(path))


def atomic_write_json(path: Path, value: dict[str, Any] | list[Any]) -> None:
    path = Path(path)
    secure_atomic_write_json(path, value, root=path.parent)


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
