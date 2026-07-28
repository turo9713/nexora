from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from nexora.operations.realtime import RealtimeService
from nexora.storage.repair_permissions import repair_permissions
from nexora.storage.secure_io import (
    ensure_private_directory,
    secure_atomic_write_json,
    secure_atomic_write_text,
)


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX mode assertions run on POSIX")


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_secure_writer_modes_atomic_replace_and_rewrite(tmp_path: Path) -> None:
    root = ensure_private_directory(tmp_path / "state")
    tasks = ensure_private_directory(root / "tasks", root=root)
    task = tasks / "NX-SECURE.json"
    history = tasks / "NX-SECURE.history.json"
    secure_atomic_write_json(task, {"status": "NEW"}, root=root)
    secure_atomic_write_json(history, [{"event": "CREATED"}], root=root)
    assert mode(root) == 0o700
    assert mode(tasks) == 0o700
    assert mode(task) == 0o600
    assert mode(history) == 0o600
    assert not list(tasks.glob(".*.tmp"))

    task.chmod(0o644)
    secure_atomic_write_text(task, '{"status":"COMPLETED"}', root=root)
    assert mode(task) == 0o600
    assert json.loads(task.read_text(encoding="utf-8"))["status"] == "COMPLETED"


def test_secure_writer_blocks_symlink_escape(tmp_path: Path) -> None:
    root = ensure_private_directory(tmp_path / "state")
    outside = ensure_private_directory(tmp_path / "outside")
    link = root / "tasks"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match="outside|symbolic"):
        secure_atomic_write_json(link / "escape.json", {"unsafe": True}, root=root)
    assert not (outside / "escape.json").exists()


def test_repair_permissions_is_allowlisted_and_dry_run_safe(tmp_path: Path) -> None:
    root = tmp_path / "state"
    tasks = root / "tasks"
    unrelated = root / "secrets"
    tasks.mkdir(parents=True)
    unrelated.mkdir()
    task = tasks / "legacy.json"
    secret = unrelated / "do-not-touch"
    task.write_text("{}", encoding="utf-8")
    secret.write_text("protected", encoding="utf-8")
    root.chmod(0o755)
    tasks.chmod(0o755)
    task.chmod(0o644)
    unrelated.chmod(0o755)
    secret.chmod(0o644)

    check = repair_permissions(root, apply=False)
    assert check["files_requiring_repair"] == 1
    assert mode(task) == 0o644
    applied = repair_permissions(root, apply=True)
    assert applied["files_requiring_repair"] == 1
    assert mode(root) == 0o700
    assert mode(tasks) == 0o700
    assert mode(task) == 0o600
    assert mode(unrelated) == 0o755
    assert mode(secret) == 0o644


def test_repair_does_not_follow_allowlisted_symlink(tmp_path: Path) -> None:
    root = tmp_path / "state"
    outside = tmp_path / "outside"
    root.mkdir(mode=0o700)
    outside.mkdir(mode=0o700)
    target = outside / "foreign.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o644)
    (root / "tasks").symlink_to(outside, target_is_directory=True)
    result = repair_permissions(root, apply=False)
    assert result["unsafe_entries"] == 1
    assert mode(target) == 0o644
