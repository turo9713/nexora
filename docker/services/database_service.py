from __future__ import annotations

import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request

from nexora.database import SQLiteRepository


HOST = "0.0.0.0"
PORT = 18883
DATABASE = Path("/workspace/nexora/runtime/state/database/nexora.sqlite3")


def check() -> bool:
    repository = SQLiteRepository(DATABASE)
    if repository.schema_version() != 14:
        return False
    with sqlite3.connect(DATABASE, timeout=5) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


class Handler(BaseHTTPRequestHandler):
    server_version = "NexoraDatabase/2.0"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(404)
            return
        payload = json.dumps({"status": "ok" if check() else "error"}).encode()
        self.send_response(200 if check() else 503)
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
    SQLiteRepository(DATABASE).migrate()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(healthcheck() if "--healthcheck" in sys.argv[1:] else run())
