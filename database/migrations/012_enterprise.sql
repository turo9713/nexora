PRAGMA foreign_keys = ON;

CREATE TABLE enterprise_policies (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('AGENT_POLICY','DATA_POLICY','ACCESS_POLICY','WORKFLOW_POLICY','SECURITY_POLICY')),
    rules TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','ACTIVE','DISABLED','ARCHIVED')),
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
);

CREATE TABLE policy_versions (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    rules TEXT NOT NULL,
    changelog TEXT NOT NULL,
    approval_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(policy_id, version),
    FOREIGN KEY(policy_id) REFERENCES enterprise_policies(id) ON DELETE RESTRICT
);

CREATE TABLE security_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    actor_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    result TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    previous_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
);

CREATE TRIGGER security_events_immutable_update
BEFORE UPDATE ON security_events BEGIN
    SELECT RAISE(ABORT, 'security events are immutable');
END;

CREATE TRIGGER security_events_immutable_delete
BEFORE DELETE ON security_events BEGIN
    SELECT RAISE(ABORT, 'security events are immutable');
END;

CREATE TABLE sla_metrics (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE storage_checks (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT,
    database_status TEXT NOT NULL,
    permissions_status TEXT NOT NULL,
    backup_status TEXT NOT NULL,
    disk_percent REAL NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE deployment_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    resources TEXT NOT NULL,
    security_settings TEXT NOT NULL,
    enabled_features TEXT NOT NULL,
    limits TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED')),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_enterprise_policies_org_status ON enterprise_policies(organization_id,status,created_at DESC);
CREATE INDEX idx_policy_versions_policy_version ON policy_versions(policy_id,version DESC);
CREATE INDEX idx_security_events_org_created ON security_events(organization_id,created_at DESC);
CREATE INDEX idx_sla_metrics_org_workspace ON sla_metrics(organization_id,workspace_id,created_at DESC);
CREATE INDEX idx_storage_checks_org_workspace ON storage_checks(organization_id,workspace_id,created_at DESC);

INSERT INTO deployment_profiles(id,name,resources,security_settings,enabled_features,limits,status,created_at) VALUES
('DPL-DEVELOPMENT','Development','{"cpu":"shared","memory":"small"}','{"deny_by_default":true,"sandbox":true,"approvals":true}','["runtime","dashboard","api"]','{"tasks":100}','ACTIVE',strftime('%Y-%m-%dT%H:%M:%fZ','now')),
('DPL-STAGING','Staging','{"cpu":"dedicated","memory":"medium"}','{"deny_by_default":true,"sandbox":true,"approvals":true}','["runtime","dashboard","api","audit"]','{"tasks":1000}','ACTIVE',strftime('%Y-%m-%dT%H:%M:%fZ','now')),
('DPL-PRODUCTION','Production','{"cpu":"dedicated","memory":"large"}','{"deny_by_default":true,"sandbox":true,"approvals":true,"immutable_audit":true}','["runtime","dashboard","api","audit","sla"]','{"tasks":5000}','ACTIVE',strftime('%Y-%m-%dT%H:%M:%fZ','now')),
('DPL-ENTERPRISE','Enterprise','{"cpu":"isolated","memory":"custom"}','{"deny_by_default":true,"sandbox":true,"approvals":true,"immutable_audit":true,"tenant_isolation":true}','["runtime","dashboard","api","audit","sla","compliance","sso_foundation"]','{"tasks":null}','ACTIVE',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
