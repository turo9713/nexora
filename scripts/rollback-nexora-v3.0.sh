#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then echo "usage: $0 /absolute/path/to/nexora.sqlite3" >&2; exit 64; fi
db="$1"
[[ "$db" = /* && -f "$db" && ! -L "$db" ]] || { echo "unsafe database path" >&2; exit 65; }
root="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ "$(git -C "$root" status --porcelain)" = "" ]] || { echo "worktree is not clean" >&2; exit 66; }
git -C "$root" rev-parse --verify v2.5.0^{commit} >/dev/null
stamp="$(date -u +%Y%m%dT%H%M%SZ)"; backup="${db}.pre-v3.0-rollback-${stamp}"
python3 - "$db" "$backup" "$root" <<'PY'
import sqlite3, sys
from pathlib import Path
db, backup, root = map(Path, sys.argv[1:])
source=sqlite3.connect(db); target=sqlite3.connect(backup)
try:
    source.backup(target); assert target.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
finally: target.close(); source.close()
connection=sqlite3.connect(db)
try:
    connection.executescript((root/"database/migrations/010_agent_ecosystem.down.sql").read_text())
    assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
    assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]==9
finally: connection.close()
PY
chmod 600 "$backup" "$db"
echo "agent ecosystem schema rollback complete; OpenClaw and VPS services were not changed"
echo "backup=$backup"
