from __future__ import annotations

import os
from pathlib import Path

from .security.access_control import AccessControl
from .services.task_service import TaskService
from .storage.atomic import read_json
from .storage.context_repository import ContextRepository
from .storage.task_repository import TaskRepository


BASE_PATH = Path("/workspace/nexora")
LEGACY_TASKS = BASE_PATH / "runtime" / "state" / "tasks"
V14_TASKS = BASE_PATH / "runtime" / "state" / "telegram_v14" / "tasks"
CONTEXT_PATH = BASE_PATH / "runtime" / "state" / "telegram_sessions"
NAMESPACE_KEY_FILE = Path("/run/secrets/namespace_key")


def main() -> int:
    owner = os.environ.get("NEXORA_TELEGRAM_OWNER_ID", "").strip()
    if not owner.isdigit():
        raise RuntimeError("NEXORA_TELEGRAM_OWNER_ID is unavailable")
    key = NAMESPACE_KEY_FILE.read_bytes().strip()
    if len(key) < 32:
        raise RuntimeError("namespace key is invalid")
    namespace = AccessControl(int(owner), key).owner_namespace
    tasks = TaskService(TaskRepository(V14_TASKS))
    imported = 0
    skipped = 0
    for path in LEGACY_TASKS.glob("*.json"):
        if path.name.endswith(".history.json"):
            continue
        legacy = read_json(path)
        if not isinstance(legacy, dict) or legacy.get("created_by") != "telegram-owner":
            skipped += 1
            continue
        if tasks.import_legacy(namespace, legacy) is None:
            skipped += 1
        else:
            imported += 1

    context = ContextRepository(root=CONTEXT_PATH)
    session = context.load()
    if session and not session.get("active_task_id") and session.get("last_task_id"):
        legacy_id = str(session["last_task_id"])
        if tasks.get(namespace, legacy_id) is not None:
            context.save(context.set_active_task(session, legacy_id))

    print(f"migration_imported={imported}")
    print(f"migration_skipped={skipped}")
    print("legacy_data_deleted=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
