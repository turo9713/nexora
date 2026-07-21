PRAGMA foreign_keys = ON;

CREATE TABLE plans (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tier INTEGER NOT NULL UNIQUE,
    limits TEXT NOT NULL,
    features TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','DISABLED')),
    created_at TEXT NOT NULL
);

INSERT INTO plans(id,name,tier,limits,features,status,created_at) VALUES
 ('free','Free',10,'{"workspace_limit":1,"members_limit":1,"agents_limit":3,"tasks_monthly":100,"storage_bytes":1073741824}','{"audit":false,"knowledge_base":false,"sso":false,"private_deployment":false,"custom_limits":false}','ACTIVE',datetime('now')),
 ('pro','Pro',20,'{"workspace_limit":10,"members_limit":10,"agents_limit":null,"tasks_monthly":5000,"storage_bytes":53687091200}','{"audit":true,"knowledge_base":true,"sso":false,"private_deployment":false,"custom_limits":false}','ACTIVE',datetime('now')),
 ('team','Team',30,'{"workspace_limit":null,"members_limit":100,"agents_limit":null,"tasks_monthly":20000,"storage_bytes":214748364800}','{"audit":true,"knowledge_base":true,"sso":false,"private_deployment":false,"custom_limits":false}','ACTIVE',datetime('now')),
 ('enterprise','Enterprise',40,'{"workspace_limit":null,"members_limit":null,"agents_limit":null,"tasks_monthly":null,"storage_bytes":null}','{"audit":true,"knowledge_base":true,"sso":true,"private_deployment":true,"custom_limits":true}','ACTIVE',datetime('now'));

CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL UNIQUE,
    plan_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('TRIAL','ACTIVE','PAUSED','CANCELLED','EXPIRED')),
    started_at TEXT NOT NULL,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE RESTRICT
);

CREATE TABLE usage_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT,
    metric TEXT NOT NULL,
    value INTEGER NOT NULL CHECK (value >= 0),
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value INTEGER,
    source TEXT NOT NULL CHECK (source IN ('PLAN','CUSTOM')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    UNIQUE(organization_id,metric)
);

CREATE TABLE billing_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    event TEXT NOT NULL,
    result TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
);

CREATE TABLE cloud_resources (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT,
    resource_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ALLOCATED','READY','SUSPENDED','RELEASED')),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TRIGGER usage_events_immutable_update BEFORE UPDATE ON usage_events BEGIN SELECT RAISE(ABORT,'usage events are immutable'); END;
CREATE TRIGGER usage_events_immutable_delete BEFORE DELETE ON usage_events BEGIN SELECT RAISE(ABORT,'usage events are immutable'); END;
CREATE TRIGGER billing_events_immutable_update BEFORE UPDATE ON billing_events BEGIN SELECT RAISE(ABORT,'billing events are immutable'); END;
CREATE TRIGGER billing_events_immutable_delete BEFORE DELETE ON billing_events BEGIN SELECT RAISE(ABORT,'billing events are immutable'); END;

CREATE INDEX idx_subscriptions_org_status ON subscriptions(organization_id,status);
CREATE INDEX idx_usage_org_metric_time ON usage_events(organization_id,metric,timestamp);
CREATE INDEX idx_usage_workspace_time ON usage_events(workspace_id,timestamp);
CREATE INDEX idx_billing_org_time ON billing_events(organization_id,created_at);
CREATE INDEX idx_cloud_org_status ON cloud_resources(organization_id,status);
