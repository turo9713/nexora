from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .atomic import ensure_secure_directory
from nexora.storage.secure_io import append_private_text


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
            append_private_text(self.path, payload, root=self.root)
