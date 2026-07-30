"""Private, workspace-scoped task artifacts.

Only platform-generated, non-executable result formats are supported. Paths
are derived from validated internal identifiers; callers never provide a host
filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexora.security.audit.redaction import redact_text

from .secure_io import (
    ensure_private_directory,
    ensure_private_file,
    secure_atomic_write_bytes,
    secure_atomic_write_json,
)


ARTIFACT_ID = re.compile(r"^ART-[A-F0-9]{16}$")
SCOPE_ID = re.compile(r"^[A-Za-z0-9_-]{2,100}$")
TASK_ID = re.compile(r"^[A-Za-z0-9-]{3,100}$")
ALLOWED_FORMATS = {
    "markdown": (".md", "text/markdown; charset=utf-8"),
    "json": (".json", "application/json; charset=utf-8"),
}
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


class ArtifactError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _component(value: Any, pattern: re.Pattern[str], label: str) -> str:
    selected = str(value or "")
    if not pattern.fullmatch(selected):
        raise ArtifactError(f"invalid {label}")
    return selected


class ArtifactRepository:
    def __init__(self, root: Path) -> None:
        self.root = ensure_private_directory(Path(root))

    def _owner_root(self, owner: str, *, create: bool) -> Path | None:
        owner = _component(owner, SCOPE_ID, "owner scope")
        path = self.root / owner
        if not path.exists() and not create:
            return None
        return ensure_private_directory(path, root=self.root)

    def _workspace_root(self, owner: str, workspace_id: str) -> Path:
        workspace_id = _component(workspace_id, SCOPE_ID, "workspace scope")
        owner_root = self._owner_root(owner, create=True)
        assert owner_root is not None
        return ensure_private_directory(
            owner_root / workspace_id,
            root=self.root,
        )

    def _task_root(self, owner: str, workspace_id: str, task_id: str) -> Path:
        task_id = _component(task_id, TASK_ID, "task id")
        return ensure_private_directory(
            self._workspace_root(owner, workspace_id) / task_id,
            root=self.root,
        )

    def create(
        self,
        *,
        owner: str,
        workspace_id: str,
        task_id: str,
        title: str,
        kind: str,
        content: bytes,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        if kind not in ALLOWED_FORMATS:
            raise ArtifactError("artifact format is not allowed")
        payload = bytes(content)
        if not payload or len(payload) > MAX_ARTIFACT_BYTES:
            raise ArtifactError("artifact size is not allowed")
        extension, media_type = ALLOWED_FORMATS[kind]
        checksum = hashlib.sha256(payload).hexdigest()
        artifact_id = "ART-" + hashlib.sha256(
            f"{owner}:{workspace_id}:{task_id}:{kind}:{checksum}".encode("utf-8")
        ).hexdigest()[:16].upper()
        task_root = self._task_root(owner, workspace_id, task_id)
        artifact_root = ensure_private_directory(task_root / artifact_id, root=self.root)
        storage_name = f"result{extension}"
        filename = f"{task_id}-result{extension}"
        metadata = {
            "id": artifact_id,
            "owner": _component(owner, SCOPE_ID, "owner scope"),
            "workspace_id": _component(workspace_id, SCOPE_ID, "workspace scope"),
            "task_id": _component(task_id, TASK_ID, "task id"),
            "name": filename,
            "title": redact_text(title, 200),
            "kind": kind,
            "media_type": media_type,
            "size_bytes": len(payload),
            "checksum_sha256": checksum,
            "storage_name": storage_name,
            "status": "READY",
            "created_at": str(created_at or _utc_now())[:64],
        }
        secure_atomic_write_bytes(artifact_root / storage_name, payload, root=self.root)
        secure_atomic_write_json(artifact_root / "metadata.json", metadata, root=self.root)
        return self._public(metadata)

    def list(
        self,
        owner: str,
        workspace_id: str,
        *,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        owner = _component(owner, SCOPE_ID, "owner scope")
        workspace_id = _component(workspace_id, SCOPE_ID, "workspace scope")
        owner_root = self._owner_root(owner, create=False)
        if owner_root is None:
            return []
        workspace_root = owner_root / workspace_id
        if workspace_root.is_symlink() or not workspace_root.is_dir():
            return []
        ensure_private_directory(workspace_root, root=self.root)
        selected_task = _component(task_id, TASK_ID, "task id") if task_id else None
        task_roots = [workspace_root / selected_task] if selected_task else list(workspace_root.iterdir())
        values: list[dict[str, Any]] = []
        for task_root in task_roots:
            if task_root.is_symlink() or not task_root.is_dir():
                continue
            for artifact_root in task_root.iterdir():
                if artifact_root.is_symlink() or not artifact_root.is_dir() or not ARTIFACT_ID.fullmatch(artifact_root.name):
                    continue
                metadata = self._load_metadata(artifact_root)
                if metadata is not None and metadata.get("owner") == owner and metadata.get("workspace_id") == workspace_id:
                    values.append(self._public(metadata))
        values.sort(key=lambda item: (str(item.get("created_at") or ""), str(item["id"])), reverse=True)
        return values[: max(1, min(200, int(limit)))]

    def get(self, owner: str, artifact_id: str) -> dict[str, Any] | None:
        artifact_id = _component(artifact_id, ARTIFACT_ID, "artifact id")
        owner = _component(owner, SCOPE_ID, "owner scope")
        owner_root = self._owner_root(owner, create=False)
        if owner_root is None:
            return None
        for workspace_root in owner_root.iterdir():
            if workspace_root.is_symlink() or not workspace_root.is_dir():
                continue
            for task_root in workspace_root.iterdir():
                artifact_root = task_root / artifact_id
                if task_root.is_symlink() or artifact_root.is_symlink() or not artifact_root.is_dir():
                    continue
                metadata = self._load_metadata(artifact_root)
                if metadata is not None and metadata.get("owner") == owner:
                    return self._public(metadata)
        return None

    def read(self, owner: str, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        metadata = self.get(owner, artifact_id)
        if metadata is None:
            raise ArtifactError("artifact not found")
        artifact_root = (
            self.root
            / metadata["owner"]
            / metadata["workspace_id"]
            / metadata["task_id"]
            / metadata["id"]
        )
        storage_name = str(metadata.get("storage_name") or "")
        allowed_names = {f"result{value[0]}" for value in ALLOWED_FORMATS.values()}
        if storage_name not in allowed_names:
            raise ArtifactError("artifact storage metadata is invalid")
        path = artifact_root / storage_name
        ensure_private_file(path, root=self.root)
        payload = path.read_bytes()
        if len(payload) != int(metadata["size_bytes"]) or hashlib.sha256(payload).hexdigest() != metadata["checksum_sha256"]:
            raise ArtifactError("artifact integrity check failed")
        return metadata, payload

    def _load_metadata(self, artifact_root: Path) -> dict[str, Any] | None:
        path = artifact_root / "metadata.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            ensure_private_file(path, root=self.root)
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, ArtifactError, RuntimeError):
            return None
        if not isinstance(value, dict) or value.get("id") != artifact_root.name:
            return None
        return value

    @staticmethod
    def _public(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.get(key)
            for key in (
                "id",
                "workspace_id",
                "task_id",
                "name",
                "title",
                "kind",
                "media_type",
                "size_bytes",
                "checksum_sha256",
                "storage_name",
                "status",
                "created_at",
                "owner",
            )
        }


class ArtifactService:
    def __init__(self, repository: ArtifactRepository, database: Any, audit: Any) -> None:
        self.repository = repository
        self.database = database
        self.audit = audit

    def capture_task(self, task_id: str) -> list[dict[str, Any]]:
        task = self.database.get_task_artifact_source(task_id)
        if task is None or task.get("status") != "COMPLETED" or not task.get("workspace_id"):
            return []
        result = redact_text(task.get("result_summary"), 100_000).strip()
        if not result:
            return []
        title = redact_text(task.get("title"), 200)
        markdown = (
            f"# {title or task_id}\n\n"
            f"- Task: `{task_id}`\n"
            f"- Status: `COMPLETED`\n\n"
            f"## Result\n\n{result}\n"
        ).encode("utf-8")
        json_result = json.dumps(
            {
                "task_id": task_id,
                "title": title,
                "status": "COMPLETED",
                "result": result,
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        existing = self.repository.list(task["owner"], task["workspace_id"], task_id=task_id)
        recorded = {(item["kind"], item["checksum_sha256"]) for item in existing}
        artifacts = []
        for kind, payload in (("markdown", markdown), ("json", json_result)):
            checksum = hashlib.sha256(payload).hexdigest()
            if (kind, checksum) in recorded:
                continue
            artifacts.append(
                self.repository.create(
                    owner=task["owner"],
                    workspace_id=task["workspace_id"],
                    task_id=task_id,
                    title=title,
                    kind=kind,
                    content=payload,
                    created_at=task.get("completed_at") or task.get("updated_at"),
                )
            )
        for artifact in artifacts:
            self.audit.record(
                "ARTIFACT_CREATED",
                source="artifact_service",
                action_result="READY",
                task_id=task_id,
                workspace_id=task["workspace_id"],
                artifact_id=artifact["id"],
                kind=artifact["kind"],
            )
        return artifacts

    def event_sink(self, event: dict[str, Any]) -> None:
        if event.get("type") == "TASK_COMPLETED" and event.get("task_id"):
            self.capture_task(str(event["task_id"]))

    def backfill(self, owner: str, limit: int = 200) -> int:
        created = 0
        for task in self.database.list_tasks(owner, status="COMPLETED", limit=limit):
            existing = self.repository.list(owner, str(task.get("workspace_id") or ""), task_id=str(task["id"])) if task.get("workspace_id") else []
            if not existing:
                created += len(self.capture_task(str(task["id"])))
        return created

    def list(self, owner: str, workspace_id: str, *, task_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [self._safe(item) for item in self.repository.list(owner, workspace_id, task_id=task_id, limit=limit)]

    def details(self, owner: str, artifact_id: str) -> dict[str, Any] | None:
        item = self.repository.get(owner, artifact_id)
        if item is None:
            return None
        metadata, payload = self.repository.read(owner, artifact_id)
        safe = self._safe(metadata)
        safe["preview"] = payload[:16_384].decode("utf-8", errors="replace")
        return safe

    def download(self, owner: str, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        metadata, payload = self.repository.read(owner, artifact_id)
        return self._safe(metadata), payload

    @staticmethod
    def _safe(value: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": value["id"],
            "workspace_id": value["workspace_id"],
            "task_id": value["task_id"],
            "name": value["name"],
            "title": redact_text(value.get("title"), 200),
            "kind": value["kind"],
            "media_type": value["media_type"],
            "size_bytes": int(value["size_bytes"]),
            "checksum_sha256": value["checksum_sha256"],
            "status": value["status"],
            "created_at": value["created_at"],
        }
