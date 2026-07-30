"""Private input files and task-scoped project workspaces.

The dashboard may accept a small, explicitly allowlisted source file before a
task is created.  Files are stored outside the web root, scoped by owner and
workspace, and can only be bound once to a task in the same scope.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from nexora.security.audit.redaction import redact_text

from .secure_io import (
    ensure_private_directory,
    ensure_private_file,
    secure_atomic_write_bytes,
    secure_atomic_write_json,
)


INPUT_ID = re.compile(r"^INP-[A-F0-9]{16}$")
SCOPE_ID = re.compile(r"^[A-Za-z0-9_-]{2,100}$")
TASK_ID = re.compile(r"^[A-Za-z0-9-]{3,100}$")
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_CONTEXT_CHARS = 24_000
ALLOWED_INPUTS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class ProjectWorkspaceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scope(value: Any, pattern: re.Pattern[str], label: str) -> str:
    selected = str(value or "")
    if not pattern.fullmatch(selected):
        raise ProjectWorkspaceError(f"invalid {label}")
    return selected


def _safe_name(value: Any) -> str:
    name = Path(str(value or "").replace("\\", "/")).name.strip()
    if not name or name in {".", ".."} or len(name) > 160:
        raise ProjectWorkspaceError("invalid input filename")
    if any(ord(char) < 32 for char in name):
        raise ProjectWorkspaceError("invalid input filename")
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_INPUTS:
        raise ProjectWorkspaceError("input file type is not allowed")
    return name


def _verify_signature(name: str, content: bytes) -> None:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf" and not content.startswith(b"%PDF-"):
        raise ProjectWorkspaceError("input file content is invalid")
    if suffix == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProjectWorkspaceError("input file content is invalid")
    if suffix in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise ProjectWorkspaceError("input file content is invalid")
    if suffix in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                required = "word/document.xml" if suffix == ".docx" else "xl/workbook.xml"
                if required not in archive.namelist():
                    raise ProjectWorkspaceError("input file content is invalid")
        except (zipfile.BadZipFile, OSError):
            raise ProjectWorkspaceError("input file content is invalid") from None


class ProjectWorkspaceRepository:
    def __init__(self, root: Path) -> None:
        self.root = ensure_private_directory(Path(root))

    def _workspace_root(self, owner: str, workspace_id: str) -> Path:
        owner = _scope(owner, SCOPE_ID, "owner scope")
        workspace_id = _scope(workspace_id, SCOPE_ID, "workspace scope")
        owner_root = ensure_private_directory(self.root / owner, root=self.root)
        return ensure_private_directory(owner_root / workspace_id, root=self.root)

    def create(self, owner: str, workspace_id: str, filename: str, content: bytes) -> dict[str, Any]:
        name = _safe_name(filename)
        payload = bytes(content)
        if not payload or len(payload) > MAX_INPUT_BYTES:
            raise ProjectWorkspaceError("input file size is not allowed")
        _verify_signature(name, payload)
        workspace_root = self._workspace_root(owner, workspace_id)
        input_id = "INP-" + uuid4().hex[:16].upper()
        input_root = ensure_private_directory(workspace_root / input_id, root=self.root)
        suffix = Path(name).suffix.lower()
        storage_name = f"source{suffix}"
        metadata = {
            "id": input_id,
            "owner": _scope(owner, SCOPE_ID, "owner scope"),
            "workspace_id": _scope(workspace_id, SCOPE_ID, "workspace scope"),
            "task_id": None,
            "name": redact_text(name, 160),
            "media_type": ALLOWED_INPUTS[suffix],
            "size_bytes": len(payload),
            "checksum_sha256": hashlib.sha256(payload).hexdigest(),
            "storage_name": storage_name,
            "status": "UPLOADED",
            "created_at": _now(),
        }
        secure_atomic_write_bytes(input_root / storage_name, payload, root=self.root)
        secure_atomic_write_json(input_root / "metadata.json", metadata, root=self.root)
        return self._public(metadata)

    def _root_for(self, owner: str, workspace_id: str, input_id: str) -> Path:
        input_id = _scope(input_id, INPUT_ID, "input id")
        return self._workspace_root(owner, workspace_id) / input_id

    def get(self, owner: str, workspace_id: str, input_id: str) -> dict[str, Any] | None:
        input_root = self._root_for(owner, workspace_id, input_id)
        metadata_path = input_root / "metadata.json"
        if input_root.is_symlink() or metadata_path.is_symlink() or not metadata_path.is_file():
            return None
        try:
            ensure_private_file(metadata_path, root=self.root)
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, RuntimeError):
            return None
        if (
            not isinstance(value, dict)
            or value.get("id") != input_id
            or value.get("owner") != owner
            or value.get("workspace_id") != workspace_id
        ):
            return None
        return value

    def bind(self, owner: str, workspace_id: str, task_id: str, input_ids: list[str]) -> list[dict[str, Any]]:
        task_id = _scope(task_id, TASK_ID, "task id")
        if len(input_ids) > 5 or len(set(input_ids)) != len(input_ids):
            raise ProjectWorkspaceError("invalid task inputs")
        selected: list[tuple[Path, dict[str, Any]]] = []
        for input_id in input_ids:
            metadata = self.get(owner, workspace_id, input_id)
            if metadata is None or metadata.get("task_id") not in {None, task_id}:
                raise ProjectWorkspaceError("input file is unavailable")
            selected.append((self._root_for(owner, workspace_id, input_id), metadata))
        for input_root, metadata in selected:
            metadata["task_id"] = task_id
            metadata["status"] = "BOUND"
            secure_atomic_write_json(input_root / "metadata.json", metadata, root=self.root)
        return [self._public(metadata) for _, metadata in selected]

    def list_for_task(self, owner: str, workspace_id: str, task_id: str) -> list[dict[str, Any]]:
        task_id = _scope(task_id, TASK_ID, "task id")
        workspace_root = self._workspace_root(owner, workspace_id)
        values: list[dict[str, Any]] = []
        for child in workspace_root.iterdir():
            if child.is_symlink() or not child.is_dir() or not INPUT_ID.fullmatch(child.name):
                continue
            metadata = self.get(owner, workspace_id, child.name)
            if metadata is not None and metadata.get("task_id") == task_id:
                values.append(self._public(metadata))
        return sorted(values, key=lambda item: (item["created_at"], item["id"]))

    def read(self, owner: str, workspace_id: str, input_id: str) -> tuple[dict[str, Any], bytes]:
        metadata = self.get(owner, workspace_id, input_id)
        if metadata is None:
            raise ProjectWorkspaceError("input file is unavailable")
        path = self._root_for(owner, workspace_id, input_id) / str(metadata["storage_name"])
        ensure_private_file(path, root=self.root)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != metadata["checksum_sha256"]:
            raise ProjectWorkspaceError("input file integrity check failed")
        return metadata, payload

    @staticmethod
    def _public(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value.get(key)
            for key in (
                "id", "workspace_id", "task_id", "name", "media_type",
                "size_bytes", "checksum_sha256", "status", "created_at",
            )
        }


class ProjectWorkspaceService:
    def __init__(self, repository: ProjectWorkspaceRepository, audit: Any) -> None:
        self.repository = repository
        self.audit = audit

    def upload(self, owner: str, workspace_id: str, filename: str, content: bytes) -> dict[str, Any]:
        item = self.repository.create(owner, workspace_id, filename, content)
        self.audit.record(
            "PROJECT_INPUT_UPLOADED",
            source="project_workspace",
            action_result="READY",
            workspace_id=workspace_id,
            input_id=item["id"],
            size_bytes=item["size_bytes"],
        )
        return item

    def bind(self, owner: str, workspace_id: str, task_id: str, input_ids: list[str]) -> list[dict[str, Any]]:
        items = self.repository.bind(owner, workspace_id, task_id, input_ids)
        for item in items:
            self.audit.record(
                "PROJECT_INPUT_BOUND",
                source="project_workspace",
                action_result="BOUND",
                workspace_id=workspace_id,
                task_id=task_id,
                input_id=item["id"],
            )
        return items

    def task_inputs(self, owner: str, workspace_id: str, task_id: str) -> list[dict[str, Any]]:
        return self.repository.list_for_task(owner, workspace_id, task_id)

    def context(self, owner: str, workspace_id: str, input_ids: list[str]) -> str:
        blocks: list[str] = []
        remaining = MAX_CONTEXT_CHARS
        for input_id in input_ids:
            metadata, payload = self.repository.read(owner, workspace_id, input_id)
            extracted = self._extract(metadata["name"], payload)
            block = f"\nSOURCE FILE: {metadata['name']}\n{extracted or '[binary source attached; content extraction unavailable]'}\n"
            block = block[:remaining]
            blocks.append(block)
            remaining -= len(block)
            if remaining <= 0:
                break
        return "".join(blocks)

    @staticmethod
    def _extract(name: str, payload: bytes) -> str:
        suffix = Path(name).suffix.lower()
        if suffix in {".txt", ".md", ".csv", ".json"}:
            return redact_text(payload.decode("utf-8", errors="replace"), MAX_CONTEXT_CHARS)
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(BytesIO(payload)) as archive:
                    root = ElementTree.fromstring(archive.read("word/document.xml"))
                text = " ".join(value.strip() for value in root.itertext() if value.strip())
                return redact_text(text, MAX_CONTEXT_CHARS)
            except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
                return ""
        return ""
