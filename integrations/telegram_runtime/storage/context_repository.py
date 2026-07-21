from __future__ import annotations

from pathlib import Path
from typing import Any

from ..sessions import DEFAULT_SESSIONS_PATH, DialogueSessionStore


class ContextRepository(DialogueSessionStore):
    def __init__(self, root: Path = DEFAULT_SESSIONS_PATH, **kwargs: Any) -> None:
        super().__init__(root=root, **kwargs)

    def set_active_task(self, session: dict[str, Any], task_id: str | None) -> dict[str, Any]:
        updated = dict(session)
        updated["active_task_id"] = task_id
        return updated

    def active_task_id(self) -> str | None:
        session = self.load()
        if session is None:
            return None
        value = session.get("active_task_id") or session.get("last_task_id")
        return str(value) if value else None
