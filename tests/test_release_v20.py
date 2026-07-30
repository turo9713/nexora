from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import yaml

from nexora.examples.demo_content_workflow import run_demo


ROOT = Path(__file__).resolve().parents[1]


def test_version_and_public_boundary() -> None:
    assert (ROOT / "VERSION").read_text().strip() == "4.2.0"
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "SECURITY.md").is_file()
    assert (ROOT / "core/README.md").is_file()
    assert (ROOT / "extensions/README.md").is_file()
    assert not (ROOT / "LICENSE.template").exists()
    assert not list(ROOT.glob("rollback-nexora-v*.sh"))


def test_env_example_is_empty_placeholders_only() -> None:
    lines = (ROOT / ".env.example").read_text().splitlines()
    assert lines == ["OPENAI_API_KEY=", "TELEGRAM_BOT_TOKEN=", "DATABASE_URL="]


def test_docker_context_excludes_secrets_and_runtime_state() -> None:
    rules = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in rules
    assert ".secrets" in rules
    assert "runtime/state" in rules
    assert ".git" in rules


def test_release_compose_is_hardened() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.release.yml").read_text())
    services = compose["services"]
    assert set(services) == {"database", "nexora-runtime", "nexora-dashboard", "nexora-api"}
    for service in services.values():
        assert service["read_only"] is True
        assert service["user"] == "10001:10001"
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert not service.get("privileged", False)
        assert "/var/run/docker.sock" not in json.dumps(service)
    ports = [str(port) for service in services.values() for port in service.get("ports", [])]
    assert ports and all(port.startswith("127.0.0.1:") for port in ports)
    assert "openclaw" not in (ROOT / "docker-compose.release.yml").read_text().lower()


def test_offline_demo_completes_without_publication(tmp_path: Path) -> None:
    result = run_demo(tmp_path)
    assert result["status"] == "PASS"
    assert result["final_status"] == "COMPLETED"
    assert result["network"] == "disabled"
    assert result["published"] is False
    if os.name == "posix":
        for directory in tmp_path.rglob("*"):
            mode = stat.S_IMODE(directory.stat().st_mode)
            if directory.is_dir():
                assert mode == 0o700
            elif directory.is_file():
                assert mode == 0o600


def test_release_tree_has_no_local_secret_or_state() -> None:
    output = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], check=True, capture_output=True, text=True,
    ).stdout
    relative = set(output.splitlines())
    assert ".env" not in relative
    assert ".secrets" not in relative
    assert not any(value == "runtime/state" or value.startswith("runtime/state/") for value in relative)
