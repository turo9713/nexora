PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    last_used_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','DISABLED','DELETED')),
    approval_id TEXT
);

CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    url TEXT NOT NULL,
    events TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','DISABLED','DELETED')),
    failure_count INTEGER NOT NULL DEFAULT 0,
    approval_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event TEXT NOT NULL,
    request_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(webhook_id) REFERENCES webhooks(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT,
    type TEXT NOT NULL,
    value REAL NOT NULL,
    labels TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_keys_owner_status ON api_keys(owner, status);
CREATE INDEX IF NOT EXISTS idx_webhooks_owner_status ON webhooks(owner, status);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_hook ON webhook_deliveries(webhook_id, created_at);
CREATE INDEX IF NOT EXISTS idx_metrics_type_created ON metrics(type, created_at);
