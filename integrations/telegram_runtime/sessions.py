from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from nexora.storage.secure_io import ensure_private_directory, secure_atomic_write_json


DEFAULT_SESSIONS_PATH = Path("/workspace/nexora/runtime/state/telegram_sessions")
SESSION_TTL_SECONDS = 6 * 60 * 60
MAX_SESSION_TURNS = 12
MAX_SESSION_CHARACTERS = 12_000
MAX_TURN_CHARACTERS = 3_000


class DialogueSessionStore:
    """Owner-only, bounded dialogue state stored inside the Nexora workspace."""

    def __init__(
        self,
        root: Path = DEFAULT_SESSIONS_PATH,
        ttl_seconds: int = SESSION_TTL_SECONDS,
        max_turns: int = MAX_SESSION_TURNS,
        max_characters: int = MAX_SESSION_CHARACTERS,
    ) -> None:
        self.root = Path(root)
        self.path = self.root / "active.json"
        self.ttl_seconds = ttl_seconds
        self.max_turns = max_turns
        self.max_characters = max_characters

    def _ensure_root(self) -> None:
        ensure_private_directory(self.root)

    def new(self) -> dict[str, Any]:
        now = int(time.time())
        return {
            "version": 1,
            "session_id": str(uuid4()),
            "created_at": now,
            "updated_at": now,
            "last_task_id": None,
            "turns": [],
        }

    def bind_workspace(
        self,
        session: dict[str, Any],
        *,
        owner_namespace: str,
        organization_id: str,
        workspace_id: str,
    ) -> dict[str, Any]:
        updated = dict(session)
        updated["owner_namespace"] = str(owner_namespace)
        updated["organization_id"] = str(organization_id)
        updated["workspace_id"] = str(workspace_id)
        updated["updated_at"] = int(time.time())
        return updated

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimeError("unsafe dialogue session file")
        try:
            session = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.clear()
            return None
        if not self._is_valid(session):
            self.clear()
            return None
        if int(time.time()) - int(session["updated_at"]) > self.ttl_seconds:
            self.clear()
            return None
        return session

    def _is_valid(self, session: Any) -> bool:
        if not isinstance(session, dict) or session.get("version") != 1:
            return False
        if not isinstance(session.get("session_id"), str):
            return False
        if not isinstance(session.get("created_at"), int):
            return False
        if not isinstance(session.get("updated_at"), int):
            return False
        if session.get("last_task_id") is not None and not isinstance(session.get("last_task_id"), str):
            return False
        if session.get("active_task_id") is not None and not isinstance(session.get("active_task_id"), str):
            return False
        for key in ("owner_namespace", "organization_id", "workspace_id"):
            if session.get(key) is not None and not isinstance(session.get(key), str):
                return False
        turns = session.get("turns")
        if not isinstance(turns, list):
            return False
        return all(
            isinstance(turn, dict)
            and turn.get("role") in {"user", "assistant"}
            and isinstance(turn.get("content"), str)
            for turn in turns
        )

    def add_turn(self, session: dict[str, Any], role: str, content: str) -> dict[str, Any]:
        if role not in {"user", "assistant"}:
            raise ValueError("unsupported dialogue role")
        cleaned = content.replace("\x00", "").strip()
        if not cleaned:
            raise ValueError("empty dialogue turn")
        cleaned = cleaned[:MAX_TURN_CHARACTERS]

        updated = dict(session)
        turns = [dict(turn) for turn in session.get("turns", [])]
        turns.append({"role": role, "content": cleaned})
        turns = turns[-self.max_turns :]
        while len(turns) > 1 and sum(len(turn["content"]) for turn in turns) > self.max_characters:
            turns.pop(0)
        updated["turns"] = turns
        updated["updated_at"] = int(time.time())
        return updated

    def set_last_task(self, session: dict[str, Any], task_id: str) -> dict[str, Any]:
        updated = dict(session)
        updated["last_task_id"] = task_id
        updated["updated_at"] = int(time.time())
        return updated

    def build_prompt(self, session: dict[str, Any]) -> str:
        lines = [
            "Continue the existing owner-only Telegram dialogue.",
            "Use facts already provided in earlier turns and answer the latest owner message.",
            "Do not claim that you performed external actions. Do not use tools or reveal internal secrets.",
            "Conversation:",
        ]
        labels = {"user": "OWNER", "assistant": "ASSISTANT"}
        for turn in session.get("turns", []):
            lines.append(f"{labels[turn['role']]}: {turn['content']}")
        return "\n".join(lines)

    def save(self, session: dict[str, Any]) -> None:
        if not self._is_valid(session):
            raise ValueError("invalid dialogue session")
        self._ensure_root()
        secure_atomic_write_json(self.path, session, root=self.root)

    def clear(self) -> None:
        if self.path.is_symlink():
            raise RuntimeError("unsafe dialogue session file")
        self.path.unlink(missing_ok=True)
