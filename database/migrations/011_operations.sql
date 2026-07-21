PRAGMA foreign_keys = ON;

CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    workspace_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('TASK_COMPLETED','TASK_FAILED','APPROVAL_REQUIRED','AGENT_ERROR','SECURITY_ALERT')),
    message TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('UNREAD','READ')),
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE agent_status_history (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('READY','IDLE','RUNNING','ERROR','DISABLED')),
    health TEXT NOT NULL CHECK(health IN ('GOOD','DEGRADED','UNKNOWN')),
    error_code TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE TABLE dashboard_metrics (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    period TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE INDEX idx_notifications_user_workspace_status
    ON notifications(user_id,workspace_id,status,created_at DESC);
CREATE INDEX idx_agent_status_workspace_agent_created
    ON agent_status_history(workspace_id,agent_id,created_at DESC);
CREATE INDEX idx_dashboard_metrics_workspace_period
    ON dashboard_metrics(workspace_id,period,metric);
CREATE INDEX idx_activity_workspace_event_created
    ON activity_events(workspace_id,event,created_at DESC);
CREATE INDEX idx_task_events_created_id
    ON task_events(created_at,id);
