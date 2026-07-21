from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request

from nexora.agents.registry import AgentRegistry
from nexora.database import SQLiteRepository
from nexora.security.policies import PolicyEngine
from nexora.skills import SkillRegistry


HOST = "0.0.0.0"
PORT = 18882
ROOT = Path("/workspace/nexora")
DATABASE = ROOT / "runtime/state/database/nexora.sqlite3"


def state() -> dict[str, object]:
    database = SQLiteRepository(DATABASE)
    registry = AgentRegistry(ROOT / "agents").load()
    PolicyEngine(registry, ROOT)
    skills = SkillRegistry(
        ROOT / "skills/manifests", database=database, agent_registry=registry,
        platform_version="2.0.0",
    ).load()
    return {
        "status": "ok",
        "database": database.schema_version(),
        "agents": len(registry.all()),
        "skills": len(skills.list()),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "NexoraRuntime/2.0"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(404)
            return
        try:
            body, status = state(), 200
        except Exception:
            body, status = {"status": "error"}, 503
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def healthcheck() -> int:
    try:
        with request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=3) as response:
            return 0 if response.status == 200 else 1
    except Exception:
        return 1


def run() -> int:
    state()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(healthcheck() if "--healthcheck" in sys.argv[1:] else run())
