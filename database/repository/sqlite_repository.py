from __future__ import annotations

import json
import hashlib
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
            (5, self.migrations_root / "005_community.sql"),
            (6, self.migrations_root / "006_teams.sql"),
            (7, self.migrations_root / "007_cloud_billing.sql"),
            (8, self.migrations_root / "008_marketplace.sql"),
            (9, self.migrations_root / "009_creator_economy.sql"),
            (10, self.migrations_root / "010_agent_ecosystem.sql"),
            (11, self.migrations_root / "011_operations.sql"),
        )
        with self._connect() as connection:
            for version, path in scripts:
                try:
                    applied = connection.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone()
                except sqlite3.OperationalError:
                    applied = None
                if applied is not None:
                    continue
                current_version = connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0] if version in {6, 7, 8, 9, 10, 11} else None
                if version in {6, 7, 8, 9, 10, 11} and current_version == version - 1:
                    connection.commit()
                    self._backup_before_version(connection, version)
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                    (version, utc_now()),
                )
                if version in {6, 7, 8, 9, 10, 11} and connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError(f"migration {version:03d} integrity check failed")
        self._secure_database()
        return self.schema_version()

    def _backup_before_v6(self, source: sqlite3.Connection) -> None:
        self._backup_before_version(source, 6)

    def _backup_before_version(self, source: sqlite3.Connection, version: int) -> None:
        backup = self.path.with_suffix(self.path.suffix + f".pre-v{version}.backup")
        temporary = backup.with_suffix(backup.suffix + ".tmp")
        if backup.is_symlink() or temporary.is_symlink():
            raise RuntimeError("unsafe database backup path")
        temporary.unlink(missing_ok=True)
        try:
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("database backup integrity check failed")
                target.commit()
            finally:
                target.close()
            os.chmod(temporary, 0o600)
            os.replace(temporary, backup)
            os.chmod(backup, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    def rollback(self, version: int = 11) -> None:
        if version not in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}:
            raise ValueError("unsupported migration rollback")
        current = self.schema_version()
        if current > version:
            raise RuntimeError(f"rollback migration {current} first")
        names = {1: "platform", 2: "dashboard", 3: "skills", 4: "public_api", 5: "community", 6: "teams", 7: "cloud_billing", 8: "marketplace", 9: "creator_economy", 10: "agent_ecosystem", 11: "operations"}
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

    def ensure_user(self, external_hash: str) -> int:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO users(external_hash, created_at, status) VALUES(?, ?, 'ACTIVE')",
                (external_hash, utc_now()),
            )
            row = connection.execute("SELECT id FROM users WHERE external_hash=?", (external_hash,)).fetchone()
        self._secure_database()
        if row is None:
            raise RuntimeError("user unavailable")
        return int(row["id"])

    def ensure_team_user(self, external_hash: str, *, email_hash: str | None = None, display_name: str | None = None) -> int:
        user_id = self.ensure_user(external_hash)
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET email_hash=COALESCE(email_hash,?),display_name=COALESCE(display_name,?) WHERE id=?",
                (email_hash, display_name, user_id),
            )
        self._secure_database()
        return user_id

    def upsert_task(self, task: dict[str, Any]) -> None:
        owner = str(task["owner_namespace"])
        self.ensure_user(owner)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks(id, owner, title, status, progress, agent, created_at, updated_at,
                                  completed_at, result_summary, error_code, organization_id,
                                  workspace_id, creator_id, assignee_id)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    owner=excluded.owner, title=excluded.title, status=excluded.status,
                    progress=excluded.progress, agent=excluded.agent, updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at, result_summary=excluded.result_summary,
                    error_code=excluded.error_code,
                    organization_id=COALESCE(excluded.organization_id,tasks.organization_id),
                    workspace_id=COALESCE(excluded.workspace_id,tasks.workspace_id),
                    creator_id=COALESCE(excluded.creator_id,tasks.creator_id),
                    assignee_id=COALESCE(excluded.assignee_id,tasks.assignee_id)
                """,
                (
                    str(task["task_id"]), owner, str(task.get("title") or "")[:200],
                    str(task.get("status") or "NEW"), max(0, min(100, int(task.get("progress", 0)))),
                    str(task.get("assigned_agent") or "unknown")[:100], str(task.get("created_at") or utc_now()),
                    str(task.get("updated_at") or utc_now()), task.get("completed_at"),
                    str(task.get("result_summary") or "")[:1500], task.get("error_code"),
                    task.get("organization_id"), task.get("workspace_id"),
                    task.get("creator_id"), task.get("assignee_id"),
                ),
            )
        self._secure_database()

    def insert_task_event(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            inserted = connection.execute(
                "INSERT OR IGNORE INTO task_events(id, task_id, event_type, payload, created_at) VALUES(?, ?, ?, ?, ?)",
                (
                    str(event["event_id"]), event.get("task_id"), str(event["type"]),
                    json.dumps(event.get("metadata", {}), ensure_ascii=False, separators=(",", ":")),
                    str(event["timestamp"]),
                ),
            ).rowcount
            if inserted:
                self._project_operations_event(connection, event)
        self._secure_database()

    def _project_operations_event(self, connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        """Build v3.4 read projections without exposing raw event metadata."""
        event_type = str(event.get("type") or "").upper()
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        if event_type == "TASK_UPDATED" and str(metadata.get("status") or "").upper() == "FAILED":
            event_type = "TASK_FAILED"
        task_id = str(event.get("task_id") or "")
        if not task_id:
            return
        task = connection.execute(
            "SELECT t.id,t.owner,t.workspace_id,t.agent,t.error_code,u.id user_id "
            "FROM tasks t JOIN users u ON u.external_hash=t.owner WHERE t.id=?",
            (task_id,),
        ).fetchone()
        if task is None or not task["workspace_id"]:
            return
        workspace_id = str(task["workspace_id"])
        timestamp = str(event.get("timestamp") or utc_now())
        event_id = str(event.get("event_id") or "")
        notification_type = {
            "TASK_COMPLETED": "TASK_COMPLETED",
            "TASK_FAILED": "TASK_FAILED",
            "APPROVAL_CREATED": "APPROVAL_REQUIRED",
            "AGENT_ERROR": "AGENT_ERROR",
            "SECURITY_DENIED": "SECURITY_ALERT",
        }.get(event_type)
        if notification_type:
            messages = {
                "TASK_COMPLETED": f"Задача {task_id[:100]} завершена.",
                "TASK_FAILED": f"Задача {task_id[:100]} завершилась с безопасной ошибкой.",
                "APPROVAL_REQUIRED": f"Для задачи {task_id[:100]} требуется подтверждение.",
                "AGENT_ERROR": f"Агент сообщил об ошибке в задаче {task_id[:100]}.",
                "SECURITY_ALERT": "Операция заблокирована политикой безопасности.",
            }
            notification_id = "NTF-" + hashlib.sha256(event_id.encode()).hexdigest()[:16].upper()
            connection.execute(
                "INSERT OR IGNORE INTO notifications(id,user_id,workspace_id,type,message,status,created_at) "
                "VALUES(?,?,?,?,?,'UNREAD',?)",
                (notification_id, int(task["user_id"]), workspace_id, notification_type, messages[notification_type], timestamp),
            )
        status_map = {
            "AGENT_STARTED": ("RUNNING", "GOOD"),
            "AGENT_FINISHED": ("IDLE", "GOOD"),
            "AGENT_ERROR": ("ERROR", "DEGRADED"),
            "TASK_FAILED": ("ERROR", "DEGRADED"),
        }
        if event_type in status_map:
            status, health = status_map[event_type]
            connection.execute(
                "INSERT OR IGNORE INTO agent_status_history(id,workspace_id,agent_id,task_id,status,health,error_code,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    "ASH-" + hashlib.sha256(event_id.encode()).hexdigest()[:16].upper(),
                    workspace_id, str(task["agent"] or "unknown")[:100], task_id, status, health,
                    str(task["error_code"] or "")[:100] or None, timestamp,
                ),
            )
        connection.execute(
            "INSERT OR IGNORE INTO dashboard_metrics(id,workspace_id,metric,value,period,created_at) VALUES(?,?,?,?,?,?)",
            (
                "DMT-" + hashlib.sha256(event_id.encode()).hexdigest()[:16].upper(),
                workspace_id, event_type[:100], 1.0, timestamp[:10], timestamp,
            ),
        )

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
            return row is not None and str(row[0]).lower() == "ok" and self.schema_version() == 11
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
            "SELECT id, owner, title, status, progress, agent, created_at, updated_at, completed_at, "
            "result_summary, error_code, organization_id, workspace_id, creator_id, assignee_id "
            "FROM tasks WHERE " + " AND ".join(clauses) +
            " ORDER BY updated_at DESC LIMIT ?"
        )
        with self._connect() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def get_task_details(self, owner: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            task = connection.execute(
                "SELECT id, owner, title, status, progress, agent, created_at, updated_at, completed_at, "
                "result_summary, error_code, organization_id, workspace_id, creator_id, assignee_id "
                "FROM tasks WHERE owner=? AND id=?",
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

    def get_task_scope(self, task_id: str) -> dict[str, Any] | None:
        """Return only the internal fields required to authorize a task read."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner, workspace_id FROM tasks WHERE id=?",
                (task_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_task_events(self, owner: str, task_id: str) -> list[dict[str, Any]]:
        """Return task events only after an owner-scoped task match.

        The join intentionally keeps task ownership in the same SQL statement as
        the event lookup.  This prevents a caller from using a known task ID to
        enumerate another owner's timeline.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.id, e.event_type, e.payload, e.created_at "
                "FROM task_events e JOIN tasks t ON t.id=e.task_id "
                "WHERE t.owner=? AND t.id=? "
                "ORDER BY e.created_at ASC, e.id ASC",
                (owner, task_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_workspace_task_events(self, workspace_id: str, task_id: str) -> list[dict[str, Any]]:
        """Return events only for a task in an already-authorized workspace."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.id, e.event_type, e.payload, e.created_at "
                "FROM task_events e JOIN tasks t ON t.id=e.task_id "
                "WHERE t.workspace_id=? AND t.id=? "
                "ORDER BY e.created_at ASC, e.id ASC",
                (workspace_id, task_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_agent_tasks(self, owner: str, agent: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, title, status, progress, created_at, updated_at FROM tasks "
                "WHERE owner=? AND lower(agent)=lower(?) ORDER BY updated_at DESC LIMIT ?",
                (owner, agent, max(1, min(50, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def agent_task_summary(self, owner: str, agent: str, workspace_id: str | None = None) -> dict[str, Any]:
        clauses = ["owner=?", "lower(agent)=lower(?)"]
        values: list[Any] = [owner, agent]
        if workspace_id:
            clauses.append("workspace_id=?")
            values.append(workspace_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT "
                "COUNT(CASE WHEN status='COMPLETED' THEN 1 END) AS completed_tasks, "
                "COUNT(CASE WHEN status IN ('NEW','CLARIFYING','QUEUED','PLANNING','IN_PROGRESS','WAITING_APPROVAL') THEN 1 END) AS active_tasks, "
                "MAX(updated_at) AS last_activity "
                "FROM tasks WHERE " + " AND ".join(clauses),
                tuple(values),
            ).fetchone()
        return {
            "completed_tasks": int(row["completed_tasks"] or 0),
            "active_tasks": int(row["active_tasks"] or 0),
            "last_activity": row["last_activity"],
        }

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

    def consume_team_approval(self, owner: str, approval_id: str, action_type: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status,action_type,expires_at FROM approvals WHERE owner=? AND id=?",
                (owner, approval_id),
            ).fetchone()
            if row is None or row["status"] != "APPROVED" or row["action_type"] != action_type:
                return False
            try:
                expires = datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                return False
            if expires <= datetime.now(timezone.utc):
                return False
            changed = connection.execute(
                "UPDATE approvals SET status='CONSUMED' WHERE owner=? AND id=? AND status='APPROVED'",
                (owner, approval_id),
            ).rowcount
        self._secure_database()
        return changed == 1

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

    def create_organization(self, organization_id: str, owner_external_hash: str, name: str) -> dict[str, Any]:
        owner_id = self.ensure_team_user(owner_external_hash)
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO organizations(id,name,owner_id,status,created_at,updated_at) VALUES(?,?,?,'ACTIVE',?,?)",
                (organization_id, name[:120], owner_id, now, now),
            )
        self._secure_database()
        return {"id": organization_id, "name": name[:120], "status": "ACTIVE", "created_at": now, "updated_at": now}

    def list_organizations_for_user(self, external_hash: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT o.id,o.name,o.status,o.created_at,o.updated_at,CASE WHEN o.owner_id=u.id THEN 'OWNER' ELSE NULL END owner_role "
                "FROM organizations o JOIN users u ON u.external_hash=? LEFT JOIN workspaces w ON w.organization_id=o.id "
                "LEFT JOIN workspace_members m ON m.workspace_id=w.id AND m.user_id=u.id AND m.status='ACTIVE' "
                "WHERE o.owner_id=u.id OR m.id IS NOT NULL ORDER BY o.created_at",
                (external_hash,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_organization(self, organization_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id,name,owner_id,status,created_at,updated_at FROM organizations WHERE id=?", (organization_id,)).fetchone()
        return None if row is None else dict(row)

    def user_id(self, external_hash: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id FROM users WHERE external_hash=? AND status='ACTIVE'", (external_hash,)).fetchone()
        return None if row is None else int(row["id"])

    def organization_role(self, external_hash: str, organization_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT CASE WHEN o.owner_id=u.id THEN 'OWNER' ELSE (SELECT m.role FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id JOIN roles r ON r.id=m.role WHERE m.user_id=u.id AND m.status='ACTIVE' AND w.organization_id=o.id ORDER BY r.rank DESC LIMIT 1) END role "
                "FROM organizations o JOIN users u ON u.external_hash=? WHERE o.id=? AND o.status='ACTIVE'",
                (external_hash, organization_id),
            ).fetchone()
        return None if row is None or row["role"] is None else str(row["role"])

    def set_organization_status(self, organization_id: str, status: str) -> None:
        if status not in {"ACTIVE", "SUSPENDED", "ARCHIVED"}:
            raise ValueError("invalid organization status")
        with self._connect() as connection:
            changed = connection.execute("UPDATE organizations SET status=?,updated_at=? WHERE id=?", (status, utc_now(), organization_id)).rowcount
        if changed != 1:
            raise KeyError("organization unavailable")

    def create_workspace(self, workspace_id: str, organization_id: str, creator_external_hash: str, name: str, description: str, creator_role: str = "OWNER") -> dict[str, Any]:
        if creator_role not in {"OWNER", "ADMIN", "MANAGER", "OPERATOR", "VIEWER"}:
            raise ValueError("invalid workspace role")
        user_id = self.ensure_team_user(creator_external_hash)
        now = utc_now()
        member_id = "MEM-" + hashlib.sha256(f"{workspace_id}:{user_id}".encode()).hexdigest()[:12].upper()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO workspaces(id,organization_id,name,description,status,created_at) VALUES(?,?,?,?, 'ACTIVE',?)",
                (workspace_id, organization_id, name[:120], description[:1000], now),
            )
            connection.execute(
                "INSERT INTO workspace_members(id,workspace_id,user_id,role,status,created_at) VALUES(?,?,?,?, 'ACTIVE',?)",
                (member_id, workspace_id, user_id, creator_role, now),
            )
        self._secure_database()
        return {"id": workspace_id, "organization_id": organization_id, "name": name[:120], "description": description[:1000], "status": "ACTIVE", "created_at": now}

    def get_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,organization_id,name,description,status,created_at FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def membership(self, external_hash: str, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT m.id,m.role,m.status,m.user_id,w.organization_id,w.status workspace_status,o.status organization_status "
                "FROM workspace_members m JOIN users u ON u.id=m.user_id JOIN workspaces w ON w.id=m.workspace_id "
                "JOIN organizations o ON o.id=w.organization_id WHERE u.external_hash=? AND m.workspace_id=? AND m.status='ACTIVE'",
                (external_hash, workspace_id),
            ).fetchone()
        return None if row is None else dict(row)

    def list_workspaces_for_user(self, external_hash: str, organization_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT w.id,w.organization_id,w.name,w.description,w.status,w.created_at,m.role,"
            "(SELECT COUNT(*) FROM workspace_members x WHERE x.workspace_id=w.id AND x.status='ACTIVE') members,"
            "(SELECT COUNT(*) FROM tasks t WHERE t.workspace_id=w.id) tasks,"
            "(SELECT COUNT(*) FROM workspace_agents a WHERE a.workspace_id=w.id AND a.enabled=1) agents,"
            "(SELECT COUNT(*) FROM workspace_skills s WHERE s.workspace_id=w.id AND s.enabled=1) skills "
            "FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id JOIN users u ON u.id=m.user_id "
            "WHERE u.external_hash=? AND m.status='ACTIVE'"
        )
        values: list[Any] = [external_hash]
        if organization_id:
            query += " AND w.organization_id=?"
            values.append(organization_id)
        query += " ORDER BY w.created_at"
        with self._connect() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def set_workspace_component(self, workspace_id: str, component_type: str, component_id: str, enabled: bool) -> None:
        if component_type not in {"agent", "skill"}:
            raise ValueError("invalid workspace component")
        table = "workspace_agents" if component_type == "agent" else "workspace_skills"
        column = "agent_id" if component_type == "agent" else "skill_id"
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO {table}(workspace_id,{column},enabled) VALUES(?,?,?) ON CONFLICT(workspace_id,{column}) DO UPDATE SET enabled=excluded.enabled",
                (workspace_id, component_id, int(enabled)),
            )
        self._secure_database()

    def list_workspace_components(self, workspace_id: str, component_type: str) -> list[str]:
        if component_type not in {"agent", "skill"}:
            raise ValueError("invalid workspace component")
        table = "workspace_agents" if component_type == "agent" else "workspace_skills"
        column = "agent_id" if component_type == "agent" else "skill_id"
        with self._connect() as connection:
            rows = connection.execute(f"SELECT {column} value FROM {table} WHERE workspace_id=? AND enabled=1 ORDER BY {column}", (workspace_id,)).fetchall()
        return [str(row["value"]) for row in rows]

    def upsert_workspace_member(self, member_id: str, workspace_id: str, user_id: int, role: str) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO workspace_members(id,workspace_id,user_id,role,status,created_at) VALUES(?,?,?,?, 'ACTIVE',?) "
                "ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role,status='ACTIVE'",
                (member_id, workspace_id, user_id, role, now),
            )
            row = connection.execute("SELECT id,workspace_id,user_id,role,status,created_at FROM workspace_members WHERE workspace_id=? AND user_id=?", (workspace_id, user_id)).fetchone()
        self._secure_database()
        return dict(row)

    def set_workspace_member(self, workspace_id: str, user_id: int, *, role: str | None = None, status: str | None = None) -> None:
        if role is None and status is None:
            return
        clauses: list[str] = []
        values: list[Any] = []
        if role is not None:
            clauses.append("role=?")
            values.append(role)
        if status is not None:
            clauses.append("status=?")
            values.append(status)
        values.extend((workspace_id, user_id))
        with self._connect() as connection:
            changed = connection.execute(f"UPDATE workspace_members SET {','.join(clauses)} WHERE workspace_id=? AND user_id=?", tuple(values)).rowcount
        if changed != 1:
            raise KeyError("member unavailable")

    def list_workspace_members(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.id,m.user_id,m.role,m.status,m.created_at,COALESCE(u.display_name,'Member') display_name "
                "FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=? ORDER BY m.created_at",
                (workspace_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_knowledge_document(self, document: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_documents(id,workspace_id,name,type,access_level,content,content_hash,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (document["id"], document["workspace_id"], document["name"], document["type"], document["access_level"], document["content"], document["content_hash"], document["created_by"], document["created_at"]),
            )
        self._secure_database()

    def list_knowledge_documents(self, workspace_id: str, allowed_levels: tuple[str, ...]) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in allowed_levels)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT id,name,type,access_level,content,content_hash,created_at FROM knowledge_documents WHERE workspace_id=? AND access_level IN ({placeholders}) ORDER BY created_at",
                (workspace_id, *allowed_levels),
            ).fetchall()
        return [dict(row) for row in rows]

    def attach_task_workspace(self, task_id: str, organization_id: str, workspace_id: str, creator_id: int, assignee_id: int | None = None) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE tasks SET organization_id=?,workspace_id=?,creator_id=?,assignee_id=? WHERE id=?",
                (organization_id, workspace_id, creator_id, assignee_id, task_id),
            ).rowcount
        if changed != 1:
            raise KeyError("task unavailable")

    def get_team_task(self, workspace_id: str, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,title,status,progress,agent,created_at,updated_at,completed_at,result_summary,error_code,organization_id,workspace_id,creator_id,assignee_id FROM tasks WHERE workspace_id=? AND id=?",
                (workspace_id, task_id),
            ).fetchone()
        return None if row is None else dict(row)

    def list_team_tasks(self, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,title,status,progress,agent,created_at,updated_at,completed_at,result_summary,error_code,organization_id,workspace_id,creator_id,assignee_id FROM tasks WHERE workspace_id=? ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_task_comment(self, comment: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO task_comments(id,task_id,workspace_id,author_id,message,created_at) VALUES(?,?,?,?,?,?)",
                (comment["id"], comment["task_id"], comment["workspace_id"], comment["author_id"], comment["message"], comment["created_at"]),
            )
        self._secure_database()

    def list_task_comments(self, workspace_id: str, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.id,c.task_id,c.message,c.created_at,COALESCE(u.display_name,'Member') author FROM task_comments c JOIN users u ON u.id=c.author_id WHERE c.workspace_id=? AND c.task_id=? ORDER BY c.created_at",
                (workspace_id, task_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_activity(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO activity_events(id,organization_id,workspace_id,event,actor_id,resource_id,payload,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (event["id"], event["organization_id"], event.get("workspace_id"), event["event"], event.get("actor_id"), event.get("resource_id"), json.dumps(event.get("payload", {}), separators=(",", ":")), event["created_at"]),
            )
        self._secure_database()

    def list_activity(self, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,event,resource_id,payload,created_at FROM activity_events WHERE workspace_id=? ORDER BY created_at DESC LIMIT ?",
                (workspace_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_notification(
        self,
        notification_id: str,
        owner: str,
        workspace_id: str,
        notification_type: str,
        message: str,
        *,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        user_id = self.ensure_user(owner)
        now = created_at or utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO notifications(id,user_id,workspace_id,type,message,status,created_at) VALUES(?,?,?,?,?,'UNREAD',?)",
                (notification_id, user_id, workspace_id, notification_type, str(message)[:500], now),
            )
        self._secure_database()
        return {
            "id": notification_id, "workspace_id": workspace_id, "type": notification_type,
            "message": str(message)[:500], "status": "UNREAD", "created_at": now, "read_at": None,
        }

    def list_notifications(
        self,
        owner: str,
        workspace_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT n.id,n.workspace_id,n.type,n.message,n.status,n.created_at,n.read_at "
            "FROM notifications n JOIN users u ON u.id=n.user_id "
            "WHERE u.external_hash=? AND n.workspace_id=?"
        )
        values: list[Any] = [owner, workspace_id]
        if status:
            query += " AND n.status=?"
            values.append(status)
        query += " ORDER BY n.created_at DESC,n.id DESC LIMIT ?"
        values.append(max(1, min(200, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(query, tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def mark_notification_read(self, owner: str, workspace_id: str, notification_id: str) -> bool:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE notifications SET status='READ',read_at=COALESCE(read_at,?) "
                "WHERE id=? AND workspace_id=? AND user_id=(SELECT id FROM users WHERE external_hash=?)",
                (utc_now(), notification_id, workspace_id, owner),
            ).rowcount
        self._secure_database()
        return changed == 1

    def operations_dashboard(self, owner: str, workspace_id: str) -> dict[str, int | str | None]:
        with self._connect() as connection:
            workspace = connection.execute(
                "SELECT id,name,organization_id FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
            counts = connection.execute(
                "SELECT COUNT(*) total,"
                "COUNT(CASE WHEN status IN ('NEW','CLARIFYING','QUEUED','PLANNING','IN_PROGRESS','WAITING_APPROVAL') THEN 1 END) active,"
                "COUNT(CASE WHEN status='COMPLETED' THEN 1 END) completed,"
                "COUNT(CASE WHEN status='FAILED' THEN 1 END) failed,"
                "COUNT(DISTINCT CASE WHEN status IN ('NEW','CLARIFYING','QUEUED','PLANNING','IN_PROGRESS','WAITING_APPROVAL') THEN lower(agent) END) running_agents "
                "FROM tasks WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            pending = connection.execute(
                "SELECT COUNT(*) FROM approvals a JOIN tasks t ON t.id=a.task_id "
                "WHERE t.workspace_id=? AND a.owner=? AND a.status='PENDING'",
                (workspace_id, owner),
            ).fetchone()[0]
            members = connection.execute(
                "SELECT COUNT(*) FROM workspace_members WHERE workspace_id=? AND status='ACTIVE'",
                (workspace_id,),
            ).fetchone()[0]
            agents = connection.execute(
                "SELECT COUNT(*) FROM workspace_agents WHERE workspace_id=? AND enabled=1",
                (workspace_id,),
            ).fetchone()[0]
            skills = connection.execute(
                "SELECT COUNT(*) FROM workspace_skills WHERE workspace_id=? AND enabled=1",
                (workspace_id,),
            ).fetchone()[0]
            unread = connection.execute(
                "SELECT COUNT(*) FROM notifications n JOIN users u ON u.id=n.user_id "
                "WHERE n.workspace_id=? AND u.external_hash=? AND n.status='UNREAD'",
                (workspace_id, owner),
            ).fetchone()[0]
            cursor = connection.execute(
                "SELECT e.id FROM task_events e JOIN tasks t ON t.id=e.task_id "
                "WHERE t.workspace_id=? ORDER BY e.created_at DESC,e.id DESC LIMIT 1",
                (workspace_id,),
            ).fetchone()
        return {
            "workspace_id": workspace_id,
            "workspace_name": None if workspace is None else str(workspace["name"]),
            "organization_id": None if workspace is None else str(workspace["organization_id"]),
            "tasks_total": int(counts["total"] or 0),
            "active_tasks": int(counts["active"] or 0),
            "completed_tasks": int(counts["completed"] or 0),
            "failed_tasks": int(counts["failed"] or 0),
            "running_agents": int(counts["running_agents"] or 0),
            "pending_approvals": int(pending or 0),
            "members": int(members or 0),
            "agents": int(agents or 0),
            "skills": int(skills or 0),
            "unread_notifications": int(unread or 0),
            "realtime_cursor": None if cursor is None else str(cursor["id"]),
        }

    def list_operations_activity(self, workspace_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,event,resource_id,payload,created_at,source FROM ("
                " SELECT e.id id,e.event_type event,e.task_id resource_id,e.payload payload,e.created_at created_at,'runtime' source"
                " FROM task_events e JOIN tasks t ON t.id=e.task_id WHERE t.workspace_id=?"
                " UNION ALL"
                " SELECT a.id id,a.event event,a.resource_id resource_id,a.payload payload,a.created_at created_at,'workspace' source"
                " FROM activity_events a WHERE a.workspace_id=?"
                ") ORDER BY created_at DESC,id DESC LIMIT ?",
                (workspace_id, workspace_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_realtime_task_events(
        self,
        workspace_id: str,
        *,
        after_event_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        selected_limit = max(1, min(100, int(limit)))
        with self._connect() as connection:
            cursor = None
            if after_event_id:
                cursor = connection.execute(
                    "SELECT e.created_at,e.id FROM task_events e JOIN tasks t ON t.id=e.task_id "
                    "WHERE t.workspace_id=? AND e.id=?",
                    (workspace_id, after_event_id),
                ).fetchone()
            if cursor is not None:
                rows = connection.execute(
                    "SELECT e.id,e.task_id,e.event_type,e.payload,e.created_at,t.status,t.progress,t.agent,t.error_code "
                    "FROM task_events e JOIN tasks t ON t.id=e.task_id WHERE t.workspace_id=? "
                    "AND (e.created_at>? OR (e.created_at=? AND e.id>?)) "
                    "ORDER BY e.created_at ASC,e.id ASC LIMIT ?",
                    (workspace_id, cursor["created_at"], cursor["created_at"], cursor["id"], selected_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM (SELECT e.id,e.task_id,e.event_type,e.payload,e.created_at,t.status,t.progress,t.agent,t.error_code "
                    "FROM task_events e JOIN tasks t ON t.id=e.task_id WHERE t.workspace_id=? "
                    "ORDER BY e.created_at DESC,e.id DESC LIMIT ?) ORDER BY created_at ASC,id ASC",
                    (workspace_id, selected_limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def agent_operational_summary(self, workspace_id: str, agent_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            active = connection.execute(
                "SELECT id,title,status,updated_at,error_code FROM tasks WHERE workspace_id=? AND lower(agent)=lower(?) "
                "AND status IN ('NEW','CLARIFYING','QUEUED','PLANNING','IN_PROGRESS','WAITING_APPROVAL') "
                "ORDER BY updated_at DESC LIMIT 1",
                (workspace_id, agent_id),
            ).fetchone()
            latest = connection.execute(
                "SELECT id,title,status,updated_at,error_code FROM tasks WHERE workspace_id=? AND lower(agent)=lower(?) "
                "ORDER BY updated_at DESC LIMIT 1",
                (workspace_id, agent_id),
            ).fetchone()
            history = connection.execute(
                "SELECT status,health,error_code,created_at FROM agent_status_history "
                "WHERE workspace_id=? AND lower(agent_id)=lower(?) ORDER BY created_at DESC LIMIT 1",
                (workspace_id, agent_id),
            ).fetchone()
        return {
            "active_task": None if active is None else dict(active),
            "latest_task": None if latest is None else dict(latest),
            "history": None if history is None else dict(history),
        }

    def operations_analytics(self, workspace_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            totals = connection.execute(
                "SELECT COUNT(*) created,COUNT(CASE WHEN status='COMPLETED' THEN 1 END) completed,"
                "COUNT(CASE WHEN status='FAILED' THEN 1 END) failed,"
                "AVG(CASE WHEN completed_at IS NOT NULL THEN (julianday(completed_at)-julianday(created_at))*86400 END) average_seconds "
                "FROM tasks WHERE workspace_id=?",
                (workspace_id,),
            ).fetchone()
            agents = connection.execute(
                "SELECT agent,COUNT(*) executions,COUNT(CASE WHEN status='COMPLETED' THEN 1 END) completed,"
                "COUNT(CASE WHEN status='FAILED' THEN 1 END) errors FROM tasks WHERE workspace_id=? "
                "GROUP BY agent ORDER BY executions DESC,agent",
                (workspace_id,),
            ).fetchall()
            workflow_events = connection.execute(
                "SELECT t.id task_id,t.status,e.payload,e.created_at FROM tasks t "
                "JOIN task_events e ON e.task_id=t.id WHERE t.workspace_id=? "
                "ORDER BY t.id,e.created_at,e.id",
                (workspace_id,),
            ).fetchall()
        return {
            "tasks": dict(totals),
            "agents": [dict(row) for row in agents],
            "workflow_events": [dict(row) for row in workflow_events],
        }

    def record_metric(self, metric_type: str, value: float, *, owner: str | None = None, labels: dict[str, Any] | None = None) -> None:
        safe_labels = {str(key)[:40]: str(item)[:100] for key, item in (labels or {}).items() if str(key) not in {"token", "secret", "authorization"}}
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO metrics(owner,type,value,labels,created_at) VALUES(?,?,?,?,?)",
                (owner, str(metric_type)[:100], float(value), json.dumps(safe_labels, separators=(",", ":")), utc_now()),
            )
        self._secure_database()

    def register_template(self, manifest: Any, *, initial_status: str) -> bool:
        now = utc_now()
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM templates WHERE id=?", (manifest.id,)).fetchone() is not None
            if exists:
                connection.execute(
                    "UPDATE templates SET name=?,version=?,permission_level=?,approval_required=?,manifest_hash=?,updated_at=? WHERE id=?",
                    (manifest.name, manifest.version, manifest.risk, int(manifest.approval_required), manifest.manifest_hash, now, manifest.id),
                )
            else:
                connection.execute(
                    "INSERT INTO templates(id,name,version,status,permission_level,approval_required,manifest_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (manifest.id, manifest.name, manifest.version, initial_status, manifest.risk, int(manifest.approval_required), manifest.manifest_hash, now, now),
                )
        self._secure_database()
        return not exists

    def insert_template_event(self, template_id: str, event: str, result: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO template_events(template_id,event,result,created_at) VALUES(?,?,?,?)",
                (template_id, str(event)[:80], str(result)[:80], utc_now()),
            )
        self._secure_database()

    def set_template_status(self, template_id: str, status: str) -> None:
        if status not in {"DISCOVERED", "VALIDATED", "ACTIVE", "DISABLED", "FAILED"}:
            raise ValueError("invalid template status")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE templates SET status=?,updated_at=? WHERE id=?",
                (status, utc_now(), template_id),
            ).rowcount
        if changed != 1:
            raise KeyError("template unavailable")
        self._secure_database()

    def get_template_status(self, template_id: str) -> str | None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT status FROM templates WHERE id=?", (template_id,)).fetchone()
        except sqlite3.OperationalError:
            return None
        return None if row is None else str(row["status"])

    def template_exists(self, template_id: str) -> bool:
        return self.get_template_status(template_id) is not None

    def list_templates(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,name,version,status,permission_level,approval_required,created_at,updated_at FROM templates ORDER BY id"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_template_details(self, template_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,name,version,status,permission_level,approval_required,created_at,updated_at FROM templates WHERE id=?",
                (template_id,),
            ).fetchone()
            if row is None:
                return None
            events = connection.execute(
                "SELECT event,result,created_at FROM template_events WHERE template_id=? ORDER BY created_at",
                (template_id,),
            ).fetchall()
        result = dict(row)
        result["events"] = [dict(item) for item in events]
        return result

    @staticmethod
    def _installation_id(owner: str, template_id: str) -> str:
        digest = hashlib.sha256(f"{owner}:{template_id}".encode("utf-8")).hexdigest()[:12].upper()
        return f"INS-{digest}"

    def install_template(self, owner: str, template_id: str, *, approval_id: str | None = None) -> dict[str, Any]:
        now = utc_now()
        installation_id = self._installation_id(owner, template_id)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO installations(id,template_id,owner,status,approval_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(template_id,owner) DO UPDATE SET status='ACTIVE',approval_id=excluded.approval_id,updated_at=excluded.updated_at",
                (installation_id, template_id, owner, "ACTIVE", approval_id, now, now),
            )
            row = connection.execute(
                "SELECT id,template_id,status,created_at,updated_at FROM installations WHERE owner=? AND template_id=?",
                (owner, template_id),
            ).fetchone()
        self._secure_database()
        return dict(row)

    def rollback_template_installation(self, owner: str, template_id: str, approval_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE installations SET status='ROLLED_BACK',approval_id=?,updated_at=? WHERE owner=? AND template_id=? AND status='ACTIVE'",
                (approval_id, utc_now(), owner, template_id),
            ).rowcount
            row = connection.execute(
                "SELECT id,template_id,status,created_at,updated_at FROM installations WHERE owner=? AND template_id=?",
                (owner, template_id),
            ).fetchone()
        if changed != 1 or row is None:
            raise KeyError("installation unavailable")
        self._secure_database()
        return dict(row)

    def list_template_installations(self, owner: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,template_id,status,created_at,updated_at FROM installations WHERE owner=? ORDER BY updated_at DESC",
                (owner,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_template_installation(self, owner: str, template_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,template_id,status,created_at,updated_at FROM installations WHERE owner=? AND template_id=?",
                (owner, template_id),
            ).fetchone()
        return None if row is None else dict(row)

    def community_metrics(self, owner: str) -> dict[str, int]:
        with self._connect() as connection:
            installed = connection.execute(
                "SELECT COUNT(*) FROM installations WHERE owner=? AND status='ACTIVE'", (owner,)
            ).fetchone()[0]
            active_skills = connection.execute("SELECT COUNT(*) FROM skills WHERE status='ACTIVE'").fetchone()[0]
            demos = connection.execute(
                "SELECT COALESCE(SUM(value),0) FROM metrics WHERE owner=? AND type='demo_completed'", (owner,)
            ).fetchone()[0]
        return {"installed_templates": int(installed), "active_skills": int(active_skills), "completed_demos": int(demos)}

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

    # Cloud and billing foundation (v2.3). Public callers use the service layer;
    # these methods intentionally expose no client-controlled usage mutation.
    def list_plans(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT id,name,tier,limits,features,status,created_at FROM plans"
        if active_only:
            query += " WHERE status='ACTIVE'"
        query += " ORDER BY tier"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id,name,tier,limits,features,status,created_at FROM plans WHERE id=?",
                (plan_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def ensure_subscription(self, organization_id: str, plan_id: str = "free") -> dict[str, Any]:
        now = utc_now()
        subscription_id = "SUB-" + hashlib.sha256(organization_id.encode()).hexdigest()[:12].upper()
        with self._connect() as connection:
            created = connection.execute(
                "INSERT OR IGNORE INTO subscriptions(id,organization_id,plan_id,status,started_at,expires_at,created_at,updated_at) "
                "VALUES(?,?,?,'ACTIVE',?,NULL,?,?)",
                (subscription_id, organization_id, plan_id, now, now, now),
            ).rowcount == 1
            row = connection.execute(
                "SELECT s.id,s.organization_id,s.plan_id,s.status,s.started_at,s.expires_at,s.created_at,s.updated_at,p.name plan_name "
                "FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.organization_id=?",
                (organization_id,),
            ).fetchone()
        self._secure_database()
        if row is None:
            raise RuntimeError("subscription unavailable")
        result = dict(row)
        result["_created"] = created
        return result

    def get_subscription(self, organization_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT s.id,s.organization_id,s.plan_id,s.status,s.started_at,s.expires_at,s.created_at,s.updated_at,p.name plan_name "
                "FROM subscriptions s JOIN plans p ON p.id=s.plan_id WHERE s.organization_id=?",
                (organization_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def set_subscription(self, organization_id: str, plan_id: str, status: str = "ACTIVE", expires_at: str | None = None) -> dict[str, Any]:
        if status not in {"TRIAL", "ACTIVE", "PAUSED", "CANCELLED", "EXPIRED"}:
            raise ValueError("invalid subscription status")
        self.ensure_subscription(organization_id)
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE subscriptions SET plan_id=?,status=?,expires_at=?,updated_at=? WHERE organization_id=?",
                (plan_id, status, expires_at, utc_now(), organization_id),
            ).rowcount
        if changed != 1:
            raise KeyError("subscription unavailable")
        self._secure_database()
        result = self.get_subscription(organization_id)
        if result is None:
            raise RuntimeError("subscription unavailable")
        return result

    def set_subscription_status(self, organization_id: str, status: str) -> None:
        if status not in {"TRIAL", "ACTIVE", "PAUSED", "CANCELLED", "EXPIRED"}:
            raise ValueError("invalid subscription status")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE subscriptions SET status=?,updated_at=? WHERE organization_id=?",
                (status, utc_now(), organization_id),
            ).rowcount
        if changed != 1:
            raise KeyError("subscription unavailable")

    def insert_usage_event(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO usage_events(id,organization_id,workspace_id,metric,value,source,timestamp) VALUES(?,?,?,?,?,?,?)",
                (event["id"], event["organization_id"], event.get("workspace_id"), event["metric"], int(event["value"]), event["source"], event["timestamp"]),
            )
        self._secure_database()

    def usage_summary(self, organization_id: str, month: str) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT metric,COALESCE(SUM(value),0) total FROM usage_events WHERE organization_id=? AND substr(timestamp,1,7)=? GROUP BY metric",
                (organization_id, month),
            ).fetchall()
        return {str(row["metric"]): int(row["total"]) for row in rows}

    def organization_resource_usage(self, organization_id: str, month: str) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM workspaces WHERE organization_id=? AND status='ACTIVE') workspaces,"
                "(SELECT COUNT(DISTINCT m.user_id) FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE w.organization_id=? AND m.status='ACTIVE') members,"
                "(SELECT COUNT(DISTINCT a.agent_id) FROM workspace_agents a JOIN workspaces w ON w.id=a.workspace_id WHERE w.organization_id=? AND a.enabled=1) agents,"
                "(SELECT COUNT(*) FROM tasks WHERE organization_id=? AND substr(created_at,1,7)=?) tasks_monthly,"
                "(SELECT COALESCE(SUM(length(k.content)),0) FROM knowledge_documents k JOIN workspaces w ON w.id=k.workspace_id WHERE w.organization_id=?) storage_bytes",
                (organization_id, organization_id, organization_id, organization_id, month, organization_id),
            ).fetchone()
        return {
            "workspace_limit": int(row["workspaces"]),
            "members_limit": int(row["members"]),
            "agents_limit": int(row["agents"]),
            "tasks_monthly": int(row["tasks_monthly"]),
            "storage_bytes": int(row["storage_bytes"]),
        }

    def get_limit_overrides(self, organization_id: str) -> dict[str, int | None]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT metric,value FROM limits WHERE organization_id=? AND source='CUSTOM'",
                (organization_id,),
            ).fetchall()
        return {str(row["metric"]): (None if row["value"] is None else int(row["value"])) for row in rows}

    def insert_billing_event(self, event: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO billing_events(id,organization_id,event,result,metadata,created_at) VALUES(?,?,?,?,?,?)",
                (event["id"], event["organization_id"], event["event"], event["result"], json.dumps(event.get("metadata", {}), separators=(",", ":"), ensure_ascii=False), event["created_at"]),
            )
        self._secure_database()

    def list_billing_events(self, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,event,result,metadata,created_at FROM billing_events WHERE organization_id=? ORDER BY created_at DESC LIMIT ?",
                (organization_id, max(1, min(200, int(limit)))),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_cloud_organizations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT o.id,o.name,o.status,o.created_at,o.updated_at,s.plan_id,s.status subscription_status "
                "FROM organizations o LEFT JOIN subscriptions s ON s.organization_id=o.id ORDER BY o.created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_cloud_resource(self, resource: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO cloud_resources(id,organization_id,workspace_id,resource_type,status,metadata,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (resource["id"], resource["organization_id"], resource.get("workspace_id"), resource["resource_type"], resource["status"], json.dumps(resource.get("metadata", {}), separators=(",", ":"), ensure_ascii=False), resource["created_at"], resource["updated_at"]),
            )
        self._secure_database()

    def list_cloud_resources(self, organization_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,workspace_id,resource_type,status,created_at,updated_at FROM cloud_resources WHERE organization_id=? ORDER BY created_at",
                (organization_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # Marketplace v2.4 repositories. Package content is declarative JSON only.
    def create_publisher(self, value: dict[str, Any]) -> dict[str, Any]:
        user_id = self.ensure_user(str(value["owner"]))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO publishers(id,user_id,display_name,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (value["id"], user_id, value["display_name"], value["status"], value["created_at"], value["updated_at"]),
            )
        self._secure_database()
        return self.get_publisher(str(value["id"])) or {}

    def get_publisher(self, publisher_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT p.id,p.display_name,p.status,p.created_at,p.updated_at,u.external_hash owner FROM publishers p JOIN users u ON u.id=p.user_id WHERE p.id=?",
                (publisher_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def list_publishers(self, owner: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT p.id,p.display_name,p.status,p.created_at,p.updated_at FROM publishers p"
        values: tuple[Any, ...] = ()
        if owner is not None:
            sql += " JOIN users u ON u.id=p.user_id WHERE u.external_hash=?"
            values = (owner,)
        sql += " ORDER BY p.created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [dict(row) for row in rows]

    def set_publisher_status(self, publisher_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE publishers SET status=?,updated_at=? WHERE id=?", (status, utc_now(), publisher_id))
        self._secure_database()

    def insert_marketplace_item(self, item: dict[str, Any], package: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO marketplace_items(id,type,name,description,current_version,author_id,category,risk_level,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (item["id"], item["type"], item["name"], item["description"], item["current_version"], item["author_id"], item["category"], item["risk_level"], item["status"], item["created_at"], item["updated_at"]),
            )
            connection.execute(
                "INSERT INTO packages(id,item_id,version,manifest,checksum,signature,signature_status,validation_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (package["id"], package["item_id"], package["version"], package["manifest"], package["checksum"], package.get("signature"), package["signature_status"], package["validation_status"], package["created_at"]),
            )
        self._secure_database()

    def add_marketplace_package_version(self, item: dict[str, Any], package: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO packages(id,item_id,version,manifest,checksum,signature,signature_status,validation_status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (package["id"], package["item_id"], package["version"], package["manifest"], package["checksum"], package.get("signature"), package["signature_status"], package["validation_status"], package["created_at"]),
            )
            connection.execute(
                "UPDATE marketplace_items SET name=?,description=?,current_version=?,category=?,risk_level=?,status='PUBLISHED',updated_at=? WHERE id=? AND author_id=?",
                (item["name"], item["description"], item["current_version"], item["category"], item["risk_level"], item["updated_at"], item["id"], item["author_id"]),
            )
        self._secure_database()

    def list_marketplace_versions(self, item_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,version,checksum,signature_status,validation_status,created_at FROM packages WHERE item_id=? ORDER BY created_at DESC", (item_id,)).fetchall()
        return [dict(row) for row in rows]

    def set_marketplace_item_status(self, item_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE marketplace_items SET status=?,updated_at=? WHERE id=?", (status, utc_now(), item_id))
        self._secure_database()

    def list_marketplace_items(self, *, search: str | None = None, category: str | None = None, item_type: str | None = None, author_id: str | None = None, published_only: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if published_only:
            clauses.append("m.status='PUBLISHED'")
        if search:
            clauses.append("(lower(m.name) LIKE ? OR lower(m.description) LIKE ?)")
            term = f"%{search.casefold()[:100]}%"
            values.extend((term, term))
        if category:
            clauses.append("m.category=?")
            values.append(category[:64])
        if item_type:
            clauses.append("m.type=?")
            values.append(item_type.upper())
        if author_id:
            clauses.append("m.author_id=?")
            values.append(author_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(max(1, min(200, int(limit))))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.id,m.type,m.name,m.description,m.current_version version,m.author_id,p.display_name author,m.category,m.risk_level,m.status,m.created_at,m.updated_at,"
                "(SELECT COUNT(*) FROM marketplace_installations i WHERE i.item_id=m.id AND i.status='ACTIVE') downloads "
                "FROM marketplace_items m JOIN publishers p ON p.id=m.author_id" + where + " ORDER BY m.name LIMIT ?",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_marketplace_item(self, item_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT m.id,m.type,m.name,m.description,m.current_version version,m.author_id,p.display_name author,m.category,m.risk_level,m.status,m.created_at,m.updated_at,"
                "(SELECT COUNT(*) FROM marketplace_installations i WHERE i.item_id=m.id AND i.status='ACTIVE') downloads "
                "FROM marketplace_items m JOIN publishers p ON p.id=m.author_id WHERE m.id=?",
                (item_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_marketplace_package(self, item_id: str, version: str | None = None) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT p.* FROM packages p JOIN marketplace_items m ON m.id=p.item_id WHERE p.item_id=? AND p.version=COALESCE(?,m.current_version)",
                (item_id, version),
            ).fetchone()
        return None if row is None else dict(row)

    def add_marketplace_installation(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO marketplace_installations(id,workspace_id,item_id,package_id,version,installed_by,status,approval_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (value["id"], value["workspace_id"], value["item_id"], value["package_id"], value["version"], value["installed_by"], value["status"], value.get("approval_id"), value["created_at"], value["updated_at"]),
            )
        self._secure_database()
        return self.get_marketplace_installation(value["workspace_id"], value["item_id"], value["version"]) or {}

    def get_marketplace_installation(self, workspace_id: str, item_id: str, version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id,workspace_id,item_id,package_id,version,status,approval_id,created_at,updated_at FROM marketplace_installations WHERE workspace_id=? AND item_id=? AND version=?", (workspace_id,item_id,version)).fetchone()
        return None if row is None else dict(row)

    def list_marketplace_installations(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,item_id,version,status,created_at,updated_at FROM marketplace_installations WHERE workspace_id=? ORDER BY updated_at DESC", (workspace_id,)).fetchall()
        return [dict(row) for row in rows]

    def rollback_marketplace_installation(self, workspace_id: str, item_id: str, version: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE marketplace_installations SET status='ROLLED_BACK',updated_at=? WHERE workspace_id=? AND item_id=? AND version=? AND status='ACTIVE'", (utc_now(),workspace_id,item_id,version))
        self._secure_database()
        return cursor.rowcount == 1

    def add_marketplace_review(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO reviews(id,item_id,package_id,workspace_id,user_id,rating,comment,created_at) VALUES(?,?,?,?,?,?,?,?)", (value["id"],value["item_id"],value["package_id"],value["workspace_id"],value["user_id"],value["rating"],value["comment"],value["created_at"]))
        self._secure_database()

    def list_marketplace_reviews(self, item_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT r.id,r.rating,r.comment,r.created_at,p.version FROM reviews r JOIN packages p ON p.id=r.package_id WHERE r.item_id=? ORDER BY r.created_at DESC", (item_id,)).fetchall()
        return [dict(row) for row in rows]

    def add_marketplace_license(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO licenses(id,item_id,package_id,owner,type,status,created_at) VALUES(?,?,?,?,?,?,?)", (value["id"],value["item_id"],value["package_id"],value["owner"],value["type"],value["status"],value["created_at"]))
        self._secure_database()

    def add_marketplace_event(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO marketplace_events(id,item_id,publisher_id,event,result,metadata,created_at) VALUES(?,?,?,?,?,?,?)", (value["id"],value.get("item_id"),value.get("publisher_id"),value["event"],value["result"],json.dumps(value.get("metadata",{}),ensure_ascii=False,separators=(",",":")),value["created_at"]))
        self._secure_database()

    def list_marketplace_events(self, item_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,event,result,metadata,created_at FROM marketplace_events WHERE item_id=? ORDER BY created_at DESC LIMIT ?", (item_id,max(1,min(200,int(limit))))).fetchall()
        return [dict(row) for row in rows]

    # Creator Economy v2.5 repositories.
    def create_creator_profile(self, value: dict[str, Any]) -> dict[str, Any]:
        user_id = self.ensure_user(str(value["owner"]))
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO creator_profiles(id,user_id,publisher_id,display_name,bio,avatar_reference,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (value["id"],user_id,value["publisher_id"],value["display_name"],value["bio"],value.get("avatar_reference"),value["status"],value["created_at"],value["updated_at"]),
            )
            connection.execute(
                "INSERT INTO creator_verification(creator_id,level,status,verified_at,updated_at) VALUES(?,'NEW_CREATOR','PENDING',NULL,?)",
                (value["id"],value["updated_at"]),
            )
        self._secure_database()
        return self.get_creator_profile(str(value["id"])) or {}

    def get_creator_profile(self, creator_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT c.id,c.publisher_id,c.display_name,c.bio,c.avatar_reference,c.status,c.created_at,c.updated_at,v.level,v.status verification_status,v.verified_at "
                "FROM creator_profiles c JOIN creator_verification v ON v.creator_id=c.id WHERE c.id=?",
                (creator_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def get_creator_for_owner(self, owner: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT c.id,c.publisher_id,c.display_name,c.bio,c.avatar_reference,c.status,c.created_at,c.updated_at,v.level,v.status verification_status,v.verified_at "
                "FROM creator_profiles c JOIN users u ON u.id=c.user_id JOIN creator_verification v ON v.creator_id=c.id WHERE u.external_hash=?",
                (owner,),
            ).fetchone()
        return None if row is None else dict(row)

    def update_creator_profile(self, creator_id: str, *, display_name: str | None = None, bio: str | None = None, avatar_reference: str | None = None, status: str | None = None) -> None:
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (("display_name",display_name),("bio",bio),("avatar_reference",avatar_reference),("status",status)):
            if value is not None:
                fields.append(f"{column}=?")
                values.append(value)
        if not fields:
            return
        fields.append("updated_at=?")
        values.extend((utc_now(),creator_id))
        with self._connect() as connection:
            connection.execute(f"UPDATE creator_profiles SET {','.join(fields)} WHERE id=?", tuple(values))
        self._secure_database()

    def set_creator_verification(self, creator_id: str, level: str, status: str, verified_at: str | None) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE creator_verification SET level=?,status=?,verified_at=?,updated_at=? WHERE creator_id=?", (level,status,verified_at,utc_now(),creator_id))
        self._secure_database()

    def insert_creator_package_version(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO package_versions(id,package_id,creator_id,version,manifest,checksum,changelog,compatibility,status,created_at,updated_at,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (value["id"],value["package_id"],value["creator_id"],value["version"],value["manifest"],value["checksum"],value["changelog"],value["compatibility"],value["status"],value["created_at"],value["updated_at"],value.get("published_at")),
            )
        self._secure_database()

    def update_creator_package_version(self, creator_id: str, package_id: str, version: str, *, manifest: str | None = None, checksum: str | None = None, changelog: str | None = None, compatibility: str | None = None, status: str | None = None, published_at: str | None = None) -> bool:
        fields: list[str] = []
        values: list[Any] = []
        for column, value in (("manifest",manifest),("checksum",checksum),("changelog",changelog),("compatibility",compatibility),("status",status),("published_at",published_at)):
            if value is not None:
                fields.append(f"{column}=?")
                values.append(value)
        fields.append("updated_at=?")
        values.extend((utc_now(),creator_id,package_id,version))
        with self._connect() as connection:
            changed = connection.execute(f"UPDATE package_versions SET {','.join(fields)} WHERE creator_id=? AND package_id=? AND version=?", tuple(values)).rowcount
        self._secure_database()
        return changed == 1

    def get_creator_package_version(self, creator_id: str, package_id: str, version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT id,package_id,creator_id,version,manifest,checksum,changelog,compatibility,status,created_at,updated_at,published_at FROM package_versions WHERE creator_id=? AND package_id=? AND version=?", (creator_id,package_id,version)).fetchone()
        return None if row is None else dict(row)

    def list_creator_package_versions(self, creator_id: str, package_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT id,package_id,version,checksum,changelog,compatibility,status,created_at,updated_at,published_at FROM package_versions WHERE creator_id=?"
        values: list[Any] = [creator_id]
        if package_id is not None:
            sql += " AND package_id=?"
            values.append(package_id)
        sql += " ORDER BY package_id,created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(sql,tuple(values)).fetchall()
        return [dict(row) for row in rows]

    def set_marketplace_current_version(self, item_id: str, version: str) -> bool:
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM packages WHERE item_id=? AND version=? AND validation_status='APPROVED'", (item_id,version)).fetchone()
            if exists is None:
                return False
            changed = connection.execute("UPDATE marketplace_items SET current_version=?,updated_at=? WHERE id=?", (version,utc_now(),item_id)).rowcount
        self._secure_database()
        return changed == 1

    def record_creator_metric(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO creator_metrics(id,creator_id,package_id,metric,value,result,created_at) VALUES(?,?,?,?,?,?,?)", (value["id"],value["creator_id"],value.get("package_id"),value["metric"],int(value["value"]),value["result"],value["created_at"]))
        self._secure_database()

    def creator_analytics(self, creator_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM marketplace_items m JOIN creator_profiles c ON c.publisher_id=m.author_id WHERE c.id=?) packages,"
                "(SELECT COUNT(*) FROM marketplace_installations i JOIN marketplace_items m ON m.id=i.item_id JOIN creator_profiles c ON c.publisher_id=m.author_id WHERE c.id=?) total_installs,"
                "(SELECT COUNT(*) FROM marketplace_installations i JOIN marketplace_items m ON m.id=i.item_id JOIN creator_profiles c ON c.publisher_id=m.author_id WHERE c.id=? AND i.status='ACTIVE') active_installations,"
                "(SELECT COALESCE(SUM(value),0) FROM creator_metrics WHERE creator_id=? AND metric='EXECUTION') executions,"
                "(SELECT COALESCE(SUM(value),0) FROM creator_metrics WHERE creator_id=? AND metric='SUCCESS') successes,"
                "(SELECT COALESCE(SUM(value),0) FROM creator_metrics WHERE creator_id=? AND metric='ERROR') errors,"
                "(SELECT COUNT(*) FROM reviews r JOIN marketplace_items m ON m.id=r.item_id JOIN creator_profiles c ON c.publisher_id=m.author_id WHERE c.id=?) reviews,"
                "(SELECT COALESCE(AVG(r.rating),0) FROM reviews r JOIN marketplace_items m ON m.id=r.item_id JOIN creator_profiles c ON c.publisher_id=m.author_id WHERE c.id=?) rating",
                (creator_id,creator_id,creator_id,creator_id,creator_id,creator_id,creator_id,creator_id),
            ).fetchone()
        executions = int(row["executions"])
        successes = int(row["successes"])
        return {"packages":int(row["packages"]),"total_installs":int(row["total_installs"]),"active_installations":int(row["active_installations"]),"executions":executions,"successes":successes,"errors":int(row["errors"]),"reviews":int(row["reviews"]),"rating":round(float(row["rating"]),2),"success_rate":round((successes / executions * 100) if executions else 100.0,2)}

    def creator_package_analytics(self, creator_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.id,m.name,m.current_version version,"
                "COUNT(DISTINCT i.id) total_installs,COUNT(DISTINCT CASE WHEN i.status='ACTIVE' THEN i.id END) active_installations,"
                "COALESCE((SELECT SUM(value) FROM creator_metrics cm WHERE cm.creator_id=? AND cm.package_id=m.id AND cm.metric='EXECUTION'),0) executions,"
                "COALESCE((SELECT SUM(value) FROM creator_metrics cm WHERE cm.creator_id=? AND cm.package_id=m.id AND cm.metric='SUCCESS'),0) successes,"
                "COALESCE((SELECT SUM(value) FROM creator_metrics cm WHERE cm.creator_id=? AND cm.package_id=m.id AND cm.metric='ERROR'),0) errors,"
                "COALESCE(AVG(r.rating),0) rating FROM marketplace_items m JOIN creator_profiles c ON c.publisher_id=m.author_id "
                "LEFT JOIN marketplace_installations i ON i.item_id=m.id LEFT JOIN reviews r ON r.item_id=m.id WHERE c.id=? GROUP BY m.id ORDER BY m.name",
                (creator_id,creator_id,creator_id,creator_id),
            ).fetchall()
        result=[]
        for row in rows:
            value=dict(row); executions=int(value["executions"]); successes=int(value["successes"]); value["success_rate"]=round((successes/executions*100) if executions else 100.0,2); value["rating"]=round(float(value["rating"]),2); result.append(value)
        return result

    def upsert_quality_score(self, value: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO quality_scores(package_id,version,security_score,compatibility_score,reliability_score,user_rating,score,grade,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(package_id,version) DO UPDATE SET security_score=excluded.security_score,compatibility_score=excluded.compatibility_score,reliability_score=excluded.reliability_score,user_rating=excluded.user_rating,score=excluded.score,grade=excluded.grade,updated_at=excluded.updated_at", (value["package_id"],value["version"],value["security_score"],value["compatibility_score"],value["reliability_score"],value["user_rating"],value["score"],value["grade"],value["updated_at"]))
        self._secure_database()

    def get_quality_score(self, package_id: str, version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row=connection.execute("SELECT * FROM quality_scores WHERE package_id=? AND version=?",(package_id,version)).fetchone()
        return None if row is None else dict(row)

    def add_review_vote(self, review_id: str, user_id: int, vote: int) -> None:
        with self._connect() as connection:
            connection.execute("INSERT INTO review_votes(review_id,user_id,vote,created_at) VALUES(?,?,?,?) ON CONFLICT(review_id,user_id) DO UPDATE SET vote=excluded.vote,created_at=excluded.created_at",(review_id,user_id,int(vote),utc_now()))
        self._secure_database()

    def review_for_vote(self, review_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row=connection.execute("SELECT r.id,r.item_id,r.package_id,r.workspace_id,r.user_id,p.version,(SELECT COALESCE(SUM(v.vote),0) FROM review_votes v WHERE v.review_id=r.id) helpful FROM reviews r JOIN packages p ON p.id=r.package_id WHERE r.id=?",(review_id,)).fetchone()
        return None if row is None else dict(row)
