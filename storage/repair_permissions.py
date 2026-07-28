"""Check or repair private modes inside the allowlisted Nexora state tree."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .secure_io import (
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    append_private_text,
    ensure_private_directory,
)


DEFAULT_STATE_ROOT = Path(
    os.environ.get("NEXORA_STATE_ROOT", "/workspace/nexora/runtime/state")
)
ALLOWED_STORAGE_NAMES = {"tasks", "telegram_v14", "telegram_sessions"}


def _mode(path: Path) -> int:
    return path.stat(follow_symlinks=False).st_mode & 0o777


def repair_permissions(state_root: Path = DEFAULT_STATE_ROOT, *, apply: bool = False) -> dict[str, Any]:
    root = Path(state_root)
    if root.is_symlink():
        raise RuntimeError("state root must not be a symbolic link")
    if not root.exists():
        if not apply:
            raise RuntimeError("state root does not exist")
        ensure_private_directory(root)
    if not root.is_dir():
        raise RuntimeError("state root is not a directory")
    targets = [root / name for name in sorted(ALLOWED_STORAGE_NAMES) if (root / name).exists()]
    files: list[Path] = []
    directories: list[Path] = [root]
    unsafe = 0
    for target in targets:
        if target.is_symlink():
            unsafe += 1
            continue
        for current, names, filenames in os.walk(target, topdown=True, followlinks=False):
            directory = Path(current)
            if directory.is_symlink():
                unsafe += 1
                names[:] = []
                continue
            directories.append(directory)
            safe_names = []
            for name in names:
                candidate = directory / name
                if candidate.is_symlink():
                    unsafe += 1
                else:
                    safe_names.append(name)
            names[:] = safe_names
            for name in filenames:
                candidate = directory / name
                if candidate.is_symlink() or not candidate.is_file():
                    unsafe += 1
                else:
                    files.append(candidate)
    wrong_files = [path for path in files if _mode(path) != PRIVATE_FILE_MODE]
    wrong_directories = [path for path in directories if _mode(path) != PRIVATE_DIRECTORY_MODE]
    if apply:
        for path in wrong_directories:
            os.chmod(path, PRIVATE_DIRECTORY_MODE)
        for path in wrong_files:
            os.chmod(path, PRIVATE_FILE_MODE)
        audit_root = ensure_private_directory(root / "audit", root=root)
        record = {
            "event": "STORAGE_PERMISSIONS_REPAIRED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": "SUCCESS" if unsafe == 0 else "PARTIAL",
            "files_repaired": len(wrong_files),
            "directories_repaired": len(wrong_directories),
            "unsafe_entries": unsafe,
        }
        append_private_text(
            audit_root / "repair_permissions.jsonl",
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n",
            root=root,
        )
    return {
        "mode": "apply" if apply else "check",
        "files_checked": len(files),
        "directories_checked": len(directories),
        "files_requiring_repair": len(wrong_files),
        "directories_requiring_repair": len(wrong_directories),
        "unsafe_entries": unsafe,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or repair Nexora state permissions")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    arguments = parser.parse_args()
    result = repair_permissions(arguments.state_root, apply=arguments.apply)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["unsafe_entries"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
