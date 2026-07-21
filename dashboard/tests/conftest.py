from __future__ import annotations

import os
from pathlib import Path

import pytest

from nexora.dashboard.auth import hash_password
from nexora.dashboard.backend.server import DashboardConfig, create_application


PROJECT = Path(__file__).resolve().parents[2]
PASSWORD = "Nexora-Dashboard-Test-Password-2026!"
NAMESPACE = "b" * 32
ORIGIN = "http://dashboard.test"


@pytest.fixture
def dashboard_factory(tmp_path: Path):
    created = []

    def factory(*, ttl: int = 1800):
        secrets_root = tmp_path / f"secrets-{len(created)}"
        secrets_root.mkdir(mode=0o700)
        files = {
            "password": secrets_root / "password_hash",
            "session": secrets_root / "session_key",
            "namespace": secrets_root / "namespace",
            "webhook": secrets_root / "webhook_master",
        }
        files["password"].write_text(hash_password(PASSWORD), encoding="ascii")
        files["session"].write_bytes(b"dashboard-test-session-signing-key-32-bytes-minimum")
        files["namespace"].write_text(NAMESPACE, encoding="ascii")
        files["webhook"].write_bytes(b"dashboard-test-webhook-master-key-32-bytes-minimum")
        for path in files.values():
            os.chmod(path, 0o600)
        status = tmp_path / f"status-{len(created)}.txt"
        status.write_text("openclaw=healthy\ntelegram=healthy\n", encoding="utf-8")
        state_root = tmp_path / f"state-{len(created)}" / "telegram_v14"
        config = DashboardConfig(
            host="127.0.0.1",
            port=0,
            project_root=PROJECT,
            state_root=state_root,
            database_path=tmp_path / f"db-{len(created)}" / "nexora.sqlite3",
            password_hash_file=files["password"],
            session_key_file=files["session"],
            owner_namespace_file=files["namespace"],
            tls_cert_file=None,
            tls_key_file=None,
            webhook_master_file=files["webhook"],
            allowed_origins=(ORIGIN,),
            session_ttl_seconds=ttl,
        )
        application = create_application(config)
        application.api.status_file = status
        created.append(application)
        return application, config

    return factory
