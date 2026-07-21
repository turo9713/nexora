#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".secrets"


def hash_password(password: str) -> str:
    if not 14 <= len(password) <= 256:
        raise ValueError("dashboard password must contain 14 to 256 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    encoded_salt = base64.urlsafe_b64encode(salt).decode().rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"scrypt${2**14}$8$1${encoded_salt}${encoded_digest}"


def atomic_secret(name: str, value: str) -> None:
    path = TARGET / name
    temporary = TARGET / f".{name}.{os.getpid()}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value.rstrip("\n") + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    if TARGET.is_symlink():
        raise RuntimeError("unsafe secret directory")
    TARGET.mkdir(mode=0o700, exist_ok=True)
    os.chmod(TARGET, 0o700)

    supplied = os.environ.get("NEXORA_DASHBOARD_PASSWORD")
    password = supplied or ("Nx2!" + secrets.token_urlsafe(18))
    atomic_secret("dashboard_password_hash", hash_password(password))
    atomic_secret("dashboard_session_key", secrets.token_hex(32))
    atomic_secret("dashboard_owner_namespace", secrets.token_hex(32))
    atomic_secret("api_webhook_master", secrets.token_hex(32))
    atomic_secret("agent_memory_key", secrets.token_hex(32))

    if os.environ.get("NEXORA_SUPPRESS_SECRET_OUTPUT") != "1":
        print("Dashboard password (shown once): " + password)
    password = ""
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
