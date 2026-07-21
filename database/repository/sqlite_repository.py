from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nexora.database.models import HealthSummary


ACTIVE_STATUSES = ("NEW", "CLARIFYING", "QUEUED", "PLANNING", "IN_PROGRESS", "WAITING_APPROVAL")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Additive v1.5 database mirror; v1.4 JSON remains the source of truth."""

    def __init__(self, path: Path, migrations_root: Path | None = None) -> None:
        self.path = Path(path)
        self.migrations_root = migrations_root or Path(__file__).resolve().parents[1] / "migrations"
        self._secure_directory(self.path.parent)
        if self.path.is_symlink():
            raise RuntimeError("unsafe database path")

    @staticmethod
    def _secure_directory(path: Path) -> None:
        if path.is_symlink():
            raise RuntimeError("unsafe database directory")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _secure_database(self) -> None:
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def migrate(self) -> int:
        scripts = (
            (1, self.migrations_root / "001_platform.sql"),
            (2, self.migrations_root / "002_dashboard.sql"),
            (3, self.migrations_root / "003_skills.sql"),
            (4, self.migrations_root / "004_public_api.sql"),
        )
        with self._connect() as connection:
            for version, path in scripts:
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (version, utc_now()),
                )
        self._secure_database()
        return self.schema_version()

    def rollback(self, version: int = 4) -> None:
        if version not in {1, 2, 3, 4}:
            raise ValueError("unsupported migration rollback")
        current = self.schema_version()
        if current > version:
            raise RuntimeError(f"rollback migration {current} first")
        names = {1: "platform", 2: "dashboard", 3: "skills", 4: "public_api"}
        script = (self.migrations_root / f"{version:03d}_{names[version]}.down.sql").read_text(encoding="utf-8")
        with self._connect() as connection:
            connection.executescript(script)
        self._secure_database()

    def schema_version(self) -> int:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations").fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row["version"]) if row is not None else 0

    def ensure_user(self, external_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users(external_hash, created_at, status) VALUES(?, ?, 'ACTIVE')",
                (external_hash, utc_now()),
            )
        self._secure_database()

    def upsert_task(self, task: dict[str, Any]) -> None:
        owner = str(task["owner_namespace"])
        self.ensure_user(owner)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(id, owner, title, status, progress, agent, created_at, updated_at,
                                  completed_at, result_summary, error_code)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    owner=excluded.owner, title=excluded.title, status=excluded.status,
                    progress=excluded.progress, agent=excluded.agent, updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at, result_summary=excluded.result_summary,
                    error_code=excluded.error_code
                """,
                (
                    str(task["task_id"]), owner, str(task.get("title") or "")[:200],
                    str(task.get("status") or "NEW"), max(0, min(100, int(task.get("progress", 0)))),
                    str(task.get("assigned_agent") or "unknown")[:100], str(task.get("created_at") or utc_now()),
                    str(task.get("updated_at") or utc_now()), task.get("completed_at"),
                    str(task.get("result_summary") or "")[:1500], task.get("error_code"),
                ),
            )
        self._secure_database()

    def insert_task_event(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO task_events(id, task_id, event_type, payload, created_at) VALUES(?, ?, ?, ?, ?)",
                (
                    str(event["event_id"]), event.get("task_id"), str(event["type"]),
                    json.dumps(event.get("metadata", {}), ensure_ascii=False, separators=(",", ":")),
                    str(event["timestamp"]),
                ),
            )
        self._secure_database()

    def upsert_approval(self, approval: dict[str, Any]) -> None:
        owner = str(approval["owner_namespace"])
        self.ensure_user(owner)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO approvals(id, task_id, owner, action_type, status, expires_at, used_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET status=excluded.status, used_at=excluded.used_at
                """,
                (
                    str(approval["approval_id"]), str(approval["task_id"]), owner,
                    str(approval.get("action_type") or "unknown")[:100], str(approval.get("status") or "PENDING"),
                    str(approval.get("expires_at") or utc_now()), approval.get("used_at"),
                ),
            )
        self._secure_database()

    def insert_audit(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO audit_logs(event, severity, source, action_result, hash, payload, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record["event"]), str(record["severity"]), str(record["source"]),
                    str(record["action_result"]), str(record["hash"]),
                    json.dumps(record.get("metadata", {}), ensure_ascii=False, separators=(",", ":")),
                    str(record["timestamp"]),
                ),
            )
        self._secure_database()

    def health_summary(self, namespace: str) -> HealthSummary:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as connection:
            active = connection.execute(
                f"SELECT COUNT(*) AS n FROM tasks WHERE owner=? AND status IN ({placeholders})",
                (namespace, *ACTIVE_STATUSES),
            ).fetchone()["n"]
            completed = connection.execute(
                "SELECT COUNT(*) AS n FROM tasks WHERE owner=? AND status='COMPLETED' AND substr(completed_at, 1, 10)=?",
                (namespace, today),
            ).fetchone()["n"]
            denied = connection.execute(
                "SELECT COUNT(*) AS n FROM audit_logs WHERE event IN ('ACCESS_DENIED', 'SECURITY_DENIED')"
            ).fetchone()["n"]
            pending = connection.execute(
                "SELECT COUNT(*) AS n FROM approvals WHERE owner=? AND status='PENDING'",
                (namespace,),
            ).fetchone()["n"]
        return HealthSummary(int(active), int(completed), int(denied), int(pending))

    def check(self) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute("PRAGMA quick_check").fetchone()
            return row is not None and str(row[0]).lower() == "ok" and self.schema_version() == 4
        except sqlite3.Error:
            return False

    def import_task_directory(self, root: Path) -> int:
        imported = 0
        root = Path(root)
        if not root.is_dir() or root.is_symlink():
            return imported
        for namespace_dir in root.iterdir():
            if not namespace_dir.is_dir() or namespace_dir.is_symlink():
                continue
            for path in namespace_dir.glob("*.json"):
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    task = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(task, dict) and task.get("owner_namespace") == namespace_dir.name:
                        self.upsert_task(task)
                        imported += 1
                except (OSError, ValueError, KeyError, TypeError):
                    continue
        return imported

    def list_tasks(
        self,
        owner: str,
        *,
        limit: int = 100,
        status: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["owner = ?"]
        values: list[Any] = [owner]
        if status:
            clauses.append("status = ?")
            values.append(status)
        if search:
            clauses.append("(id LIKE ? OR title LIKE ?)")
            pattern = f"%{search[:100]}%"
            values.extend((pattern, pattern))
        values.append(max(1, min(200, int(limit))))
        query = (
            "SELECT id, title, status, progress, agent, created_at, updated_at, completed_at, "
            "result_summary, error_code FROM tasks WHERE " + " AND ".join(clauses) +
            " ORDER BY updated_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def get_task_details(self, owner: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            task = connection.execute(
                "SELECT id, title, status, progress, agent, created_at, updated_at, completed_at, "
                "result_summary, error_code FROM tasks WHERE owner=? AND id=?",
                (owner, task_id),
            ).fetchone()
            if task is None:
                return None
            events = connection.execute(
                "SELECT id, event_type, payload, created_at FROM task_events WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
            approvals = connection.execute(
                "SELECT id, action_type, status, expires_at, used_at FROM approvals WHERE owner=? AND task_id=? ORDER BY expires_at DESC",
                (owner, task_id),
            ).fetchall()
        value = dict(task)
        value["events"] = [dict(row) for row in events]
        value["approvals"] = [dict(row) for row in approvals]
        return value

    def list_agent_tasks(self, owner: str, agent: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, status, progress, created_at, updated_at FROM tasks "
                "WHERE owner=? AND lower(agent)=lower(?) ORDER BY updated_at DESC LIMIT ?",
                (owner, agent, max(1, min(50, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_approvals(self, owner: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = (
            "SELECT id, task_id, action_type, status, expires_at, used_at FROM approvals WHERE owner=?"
        )
        values: list[Any] = [owner]
        if status:
            query += " AND status=?"
            values.append(status)
        query += " ORDER BY expires_at DESC LIMIT ?"
        values.append(max(1, min(200, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def list_audit(
        self,
        *,
        limit: int = 100,
        severity: str | None = None,
        source: str | None = None,
        event: str | None = None,
        date_prefix: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        values: list[Any] = []
        for column, value in (("severity", severity), ("source", source), ("event", event)):
            if value:
                clauses.append(f"{column}=?")
                values.append(value)
        if date_prefix:
            clauses.append("substr(created_at, 1, 10)=?")
            values.append(date_prefix)
        values.append(max(1, min(200, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event, severity, source, action_result, hash, payload, created_at FROM audit_logs "
                f"WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_agent_override(self, agent_id: str, enabled: bool, approval_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_overrides(agent_id, enabled, updated_at, updated_by, approval_id)
                VALUES(?, ?, ?, 'dashboard', ?)
                ON CONFLICT(agent_id) DO UPDATE SET enabled=excluded.enabled,
                    updated_at=excluded.updated_at, updated_by=excluded.updated_by,
                    approval_id=excluded.approval_id
                """,
                (agent_id, 1 if enabled else 0, utc_now(), approval_id),
            )
        self._secure_database()

    def get_agent_override(self, agent_id: str) -> bool | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT enabled FROM agent_overrides WHERE agent_id=?",
                    (agent_id,),
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        return None if row is None else bool(row["enabled"])

    def agent_enabled(self, agent_id: str) -> bool | None:
        return self.get_agent_override(agent_id)

    def task_overview(self, owner: str) -> dict[str, int]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as connection:
            running = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE owner=? AND status IN ('NEW','CLARIFYING','QUEUED','PLANNING','IN_PROGRESS')",
                (owner,),
            ).fetchone()[0]
            completed = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE owner=? AND status='COMPLETED' AND substr(completed_at,1,10)=?",
                (owner, today),
            ).fetchone()[0]
            failed = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE owner=? AND status='FAILED'",
                (owner,),
            ).fetchone()[0]
            waiting = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE owner=? AND status='WAITING_APPROVAL'",
                (owner,),
            ).fetchone()[0]
        return {"running": int(running), "completed_today": int(completed), "failed": int(failed), "waiting_approval": int(waiting)}

    def register_skill(self, manifest: Any, *, initial_status: str) -> bool:
        created_at = utc_now()
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM skills WHERE id=?", (manifest.id,)).fetchone() is not None
            if exists:
                connection.execute(
                    "UPDATE skills SET name=?, version=?, risk=?, agent=?, manifest_hash=?, updated_at=? WHERE id=?",
                    (manifest.name, manifest.version, manifest.risk.upper(), manifest.agent, manifest.manifest_hash, created_at, manifest.id),
                )
            else:
                connection.execute(
                    "INSERT INTO skills(id,name,version,status,risk,agent,manifest_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (manifest.id, manifest.name, manifest.version, initial_status, manifest.risk.upper(), manifest.agent, manifest.manifest_hash, created_at, created_at),
                )
        self.replace_skill_permissions(manifest.id, self._skill_permission_rows(manifest))
        self._secure_database()
        return not exists

    def update_skill_manifest(self, manifest: Any) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE skills SET name=?,version=?,risk=?,agent=?,manifest_hash=?,updated_at=? WHERE id=? AND status!='REMOVED'",
                (manifest.name, manifest.version, manifest.risk.upper(), manifest.agent, manifest.manifest_hash, utc_now(), manifest.id),
            )
        if updated.rowcount != 1:
            raise KeyError("skill unavailable")
        self._secure_database()

    def replace_skill_permissions(self, skill_id: str, rows: list[tuple[str, str]]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM skill_permissions WHERE skill_id=?", (skill_id,))
            connection.executemany(
                "INSERT INTO skill_permissions(skill_id,permission,scope) VALUES(?,?,?)",
                [(skill_id, permission, scope) for permission, scope in rows],
            )
        self._secure_database()

    def insert_skill_event(self, skill_id: str, event: str, result: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO skill_events(skill_id,event,result,created_at) VALUES(?,?,?,?)",
                (skill_id, str(event)[:80], str(result)[:80], utc_now()),
            )
        self._secure_database()

    def set_skill_status(self, skill_id: str, status: str) -> None:
        allowed = {"DISCOVERED", "VALIDATED", "INSTALLED", "ACTIVE", "DISABLED", "FAILED", "REMOVED"}
        if status not in allowed:
            raise ValueError("invalid skill status")
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE skills SET status=?,updated_at=? WHERE id=? AND status!='REMOVED'",
                (status, utc_now(), skill_id),
            )
        if updated.rowcount != 1:
            raise KeyError("skill unavailable")
        self._secure_database()

    def get_skill_status(self, skill_id: str) -> str | None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT status FROM skills WHERE id=?", (skill_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
        return None if row is None else str(row["status"])

    def skill_exists(self, skill_id: str) -> bool:
        return self.get_skill_status(skill_id) is not None

    def list_skills(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,name,version,status,risk,agent,created_at,updated_at FROM skills WHERE status!='REMOVED' ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_skill_details(self, skill_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            skill = connection.execute(
                "SELECT id,name,version,status,risk,agent,created_at,updated_at FROM skills WHERE id=? AND status!='REMOVED'",
                (skill_id,),
            ).fetchone()
            if skill is None:
                return None
            permissions = connection.execute(
                "SELECT permission,scope FROM skill_permissions WHERE skill_id=? ORDER BY permission,scope",
                (skill_id,),
            ).fetchall()
            events = connection.execute(
                "SELECT event,result,created_at FROM skill_events WHERE skill_id=? ORDER BY id DESC LIMIT 50",
                (skill_id,),
            ).fetchall()
        result = dict(skill)
        result["permission_rows"] = [dict(row) for row in permissions]
        result["events"] = [dict(row) for row in events]
        return result

    @staticmethod
    def _skill_permission_rows(manifest: Any) -> list[tuple[str, str]]:
        rows = [("filesystem", f"{scope}:{manifest.permissions['filesystem']['mode']}") for scope in manifest.permissions["filesystem"]["scope"]]
        rows.extend([
            ("network", str(manifest.permissions["network"]["mode"])),
            ("shell", "disabled"),
            ("production", "disabled"),
        ])
        return rows

    def create_pending_api_key(
        self,
        key_id: str,
        owner: str,
        name: str,
        scopes: list[str],
        expires_at: str | None,
    ) -> None:
        self.ensure_user(owner)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO api_keys(id,owner,name,key_hash,scopes,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,'PENDING')",
                (key_id, owner, name[:100], "", json.dumps(sorted(set(scopes))), utc_now(), expires_at),
            )
        self._secure_database()

    def attach_api_key_approval(self, key_id: str, approval_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE api_keys SET approval_id=? WHERE id=? AND status!='DELETED'",
                (approval_id, key_id),
            ).rowcount
        if changed != 1:
            raise KeyError("api key request unavailable")

    def activate_api_key(self, key_id: str, key_hash: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE api_keys SET key_hash=?,status='ACTIVE' WHERE id=? AND status='PENDING'",
                (key_hash, key_id),
            ).rowcount
        if changed != 1:
            raise KeyError("api key request unavailable")
        self._secure_database()

    def get_api_key_record(self, key_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,owner,name,key_hash,scopes,created_at,expires_at,last_used_at,status,approval_id FROM api_keys WHERE id=?",
                (key_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_api_keys(self, owner: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,name,scopes,created_at,expires_at,last_used_at,status FROM api_keys WHERE owner=? AND status!='DELETED' ORDER BY created_at DESC",
                (owner,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_api_key_status(self, owner: str, key_id: str, status: str) -> None:
        if status not in {"DISABLED", "DELETED"}:
            raise ValueError("invalid api key status")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE api_keys SET status=? WHERE owner=? AND id=? AND status!='DELETED'",
                (status, owner, key_id),
            ).rowcount
        if changed != 1:
            raise KeyError("api key unavailable")

    def touch_api_key(self, key_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE api_keys SET last_used_at=? WHERE id=? AND status='ACTIVE'", (utc_now(), key_id))

    def cancel_pending_api_key(self, key_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE api_keys SET status='DELETED' WHERE id=? AND status='PENDING'", (key_id,))

    def create_pending_webhook(self, webhook_id: str, owner: str, url: str, events: list[str]) -> None:
        self.ensure_user(owner)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO webhooks(id,owner,url,events,secret_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,'PENDING',?,?)",
                (webhook_id, owner, url[:500], json.dumps(sorted(set(events))), "", now, now),
            )
        self._secure_database()

    def attach_webhook_approval(self, webhook_id: str, approval_id: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE webhooks SET approval_id=?,updated_at=? WHERE id=? AND status!='DELETED'",
                (approval_id, utc_now(), webhook_id),
            ).rowcount
        if changed != 1:
            raise KeyError("webhook request unavailable")

    def activate_webhook(self, webhook_id: str, secret_hash: str) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE webhooks SET secret_hash=?,status='ACTIVE',failure_count=0,updated_at=? WHERE id=? AND status='PENDING'",
                (secret_hash, utc_now(), webhook_id),
            ).rowcount
        if changed != 1:
            raise KeyError("webhook request unavailable")
        self._secure_database()

    def get_webhook_record(self, webhook_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,owner,url,events,secret_hash,status,failure_count,approval_id,created_at,updated_at FROM webhooks WHERE id=?",
                (webhook_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_webhooks(self, owner: str, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id,url,events,status,failure_count,created_at,updated_at FROM webhooks WHERE owner=? AND status!='DELETED'"
        if active_only:
            query += " AND status='ACTIVE'"
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, (owner,)).fetchall()
        return [dict(row) for row in rows]

    def set_webhook_status(self, owner: str, webhook_id: str, status: str) -> None:
        if status not in {"DISABLED", "DELETED"}:
            raise ValueError("invalid webhook status")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE webhooks SET status=?,updated_at=? WHERE owner=? AND id=? AND status!='DELETED'",
                (status, utc_now(), owner, webhook_id),
            ).rowcount
        if changed != 1:
            raise KeyError("webhook unavailable")

    def cancel_pending_webhook(self, webhook_id: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE webhooks SET status='DELETED',updated_at=? WHERE id=? AND status='PENDING'", (utc_now(), webhook_id))

    def record_webhook_result(self, webhook_id: str, *, success: bool, disable_after: int) -> None:
        with self._connect() as connection:
            if success:
                connection.execute(
                    "UPDATE webhooks SET failure_count=0,updated_at=? WHERE id=? AND status='ACTIVE'",
                    (utc_now(), webhook_id),
                )
            else:
                connection.execute(
                    "UPDATE webhooks SET failure_count=failure_count+1,updated_at=? WHERE id=? AND status='ACTIVE'",
                    (utc_now(), webhook_id),
                )
                connection.execute(
                    "UPDATE webhooks SET status='DISABLED',updated_at=? WHERE id=? AND failure_count>=?",
                    (utc_now(), webhook_id, disable_after),
                )

    def insert_webhook_delivery(self, delivery: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO webhook_deliveries(id,webhook_id,event,request_id,attempt,status,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    delivery["id"], delivery["webhook_id"], delivery["event"],
                    delivery["request_id"], int(delivery["attempt"]), delivery["status"], utc_now(),
                ),
            )

    def record_metric(self, metric_type: str, value: float, *, owner: str | None = None, labels: dict[str, Any] | None = None) -> None:
        safe_labels = {str(key)[:40]: str(item)[:100] for key, item in (labels or {}).items() if str(key) not in {"token", "secret", "authorization"}}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO metrics(owner,type,value,labels,created_at) VALUES(?,?,?,?,?)",
                (owner, str(metric_type)[:100], float(value), json.dumps(safe_labels, separators=(",", ":")), utc_now()),
            )
        self._secure_database()

    def metrics_summary(self, owner: str) -> dict[str, Any]:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as connection:
            task_row = connection.execute(
                "SELECT COUNT(*) total, SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) completed, "
                "SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) failed, "
                "AVG(CASE WHEN completed_at IS NOT NULL THEN (julianday(completed_at)-julianday(created_at))*86400 END) average_seconds "
                "FROM tasks WHERE owner=? AND substr(created_at,1,10)=?",
                (owner, today),
            ).fetchone()
            skills = connection.execute(
                "SELECT labels,COUNT(*) calls,SUM(CASE WHEN value=0 THEN 1 ELSE 0 END) errors FROM metrics WHERE owner=? AND type='skill_call' GROUP BY labels ORDER BY calls DESC LIMIT 10",
                (owner,),
            ).fetchall()
            agents = connection.execute(
                "SELECT agent,COUNT(*) uses,SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) errors FROM tasks WHERE owner=? GROUP BY agent ORDER BY uses DESC",
                (owner,),
            ).fetchall()
        completed = int(task_row["completed"] or 0)
        failed = int(task_row["failed"] or 0)
        finished = completed + failed
        return {
            "tasks_today": int(task_row["total"] or 0),
            "success_percent": round((completed / finished) * 100, 1) if finished else 0.0,
            "average_seconds": round(float(task_row["average_seconds"] or 0.0), 1),
            "agents": [dict(row) for row in agents],
            "skills": [dict(row) for row in skills],
        }
