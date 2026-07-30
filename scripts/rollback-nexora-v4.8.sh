#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 /absolute/path/to/nexora.sqlite3" >&2
  exit 64
fi

db="$1"
[[ "$db" = /* && -f "$db" && ! -L "$db" ]] || {
  echo "unsafe database path" >&2
  exit 65
}

root="$(cd "$(dirname "$0")/.." && pwd -P)"
[[ "$(git -C "$root" status --porcelain)" = "" ]] || {
  echo "worktree is not clean" >&2
  exit 66
}

version="$(python3 - "$db" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as db:
    print(db.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0])
PY
)"
[[ "$version" = "14" ]] || {
  echo "expected database schema 14, found $version" >&2
  exit 67
}

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${db}.pre-v4.8-rollback-${stamp}"
python3 - "$db" "$backup" "$root" <<'PY'
import sqlite3, sys
from pathlib import Path

db, backup, root = map(Path, sys.argv[1:])
source = sqlite3.connect(db)
target = sqlite3.connect(backup)
try:
    source.backup(target)
    assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
finally:
    target.close()
    source.close()

connection = sqlite3.connect(db)
try:
    active = connection.execute(
        "SELECT COUNT(*) FROM execution_jobs WHERE status IN ('QUEUED','RUNNING','RETRY_WAIT')"
    ).fetchone()[0]
    if active:
        raise RuntimeError(f"refusing rollback with {active} active execution jobs")
    connection.executescript(
        (root / "database/migrations/014_execution_queue.down.sql").read_text(encoding="utf-8")
    )
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 13
    connection.commit()
finally:
    connection.close()
PY

chmod 600 "$backup" "$db"
echo "execution queue schema rollback complete; OpenClaw and VPS were not changed"
echo "backup=$backup"
