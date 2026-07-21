from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .atomic import ensure_secure_directory


class AuditRepository:
    def __init__(self, root: Path) -> None:
        root = Path(root)
        ensure_secure_directory(root.parent)
        self.root = ensure_secure_directory(root)
        self.path = self.root / "events.jsonl"
        self._lock = threading.Lock()

    def append(self, event: dict[str, Any]) -> None:
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(self.path, 0o600)
