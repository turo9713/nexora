PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agent_overrides (
    agent_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    approval_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_overrides_enabled ON agent_overrides(enabled);
