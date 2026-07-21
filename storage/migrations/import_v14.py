from __future__ import annotations

import argparse
from pathlib import Path

from nexora.database import SQLiteRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror Nexora v1.4 task JSON into SQLite")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    task_files = list((args.state / "tasks").glob("*/*.json"))
    if args.dry_run:
        print(f"eligible_task_files={len(task_files)}")
        return 0
    repository = SQLiteRepository(args.database)
    repository.migrate()
    imported = repository.import_task_directory(args.state / "tasks")
    print(f"imported_tasks={imported} schema_version={repository.schema_version()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
