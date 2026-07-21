#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import yaml


root = Path(__file__).resolve().parents[1]
document = yaml.safe_load((root / "docker-compose.release.yml").read_text(encoding="utf-8"))
services = document.get("services", {})
required = {"database", "nexora-runtime", "nexora-dashboard", "nexora-api"}
assert set(services) == required, "unexpected release services"

for name, service in services.items():
    assert service.get("privileged") is not True, f"{name}: privileged"
    assert service.get("read_only") is True, f"{name}: root filesystem is writable"
    assert str(service.get("user", "")).split(":")[0] not in {"", "0", "root"}, f"{name}: root user"
    assert "ALL" in service.get("cap_drop", []), f"{name}: capabilities not dropped"
    assert "no-new-privileges:true" in service.get("security_opt", []), f"{name}: no-new-privileges missing"
    assert service.get("network_mode") not in {"host", "none"}, f"{name}: invalid network mode"
    for volume in service.get("volumes", []):
        rendered = str(volume)
        assert "/var/run/docker.sock" not in rendered, f"{name}: Docker socket mounted"
        assert not rendered.startswith("/:"), f"{name}: host root mounted"
    for item in service.get("ports", []):
        assert str(item).startswith("127.0.0.1:"), f"{name}: public port"

text = (root / "docker-compose.release.yml").read_text(encoding="utf-8").lower()
assert "openclaw" not in text, "release Compose must not manage or expose OpenClaw"
print("release_permissions=PASS")
