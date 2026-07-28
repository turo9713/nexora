PRAGMA foreign_keys = ON;

CREATE TABLE marketplace_metadata (
    item_id TEXT PRIMARY KEY,
    listing_kind TEXT NOT NULL CHECK (listing_kind IN ('EMPLOYEE','SKILL','WORKFLOW','INTEGRATION')),
    tags TEXT NOT NULL DEFAULT '[]',
    price_cents INTEGER NOT NULL DEFAULT 0 CHECK (price_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'USD' CHECK (length(currency) = 3),
    changelog TEXT NOT NULL DEFAULT '',
    compatibility TEXT NOT NULL DEFAULT '{}',
    screenshots TEXT NOT NULL DEFAULT '[]',
    documentation TEXT NOT NULL DEFAULT '',
    auto_update INTEGER NOT NULL DEFAULT 0 CHECK (auto_update IN (0,1)),
    visibility TEXT NOT NULL DEFAULT 'PUBLIC' CHECK (visibility IN ('PUBLIC','PRIVATE','ORGANIZATION')),
    organization_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
);

CREATE TABLE workforce_installations (
    id TEXT PRIMARY KEY,
    marketplace_installation_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    version TEXT NOT NULL,
    employee_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','UPDATING','UNINSTALLED','FAILED')),
    auto_update INTEGER NOT NULL DEFAULT 0 CHECK (auto_update IN (0,1)),
    configuration TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(marketplace_installation_id) REFERENCES marketplace_installations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    UNIQUE(workspace_id,item_id)
);

CREATE TABLE workforce_resources (
    id TEXT PRIMARY KEY,
    installation_id TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (resource_type IN ('WORKSPACE_BINDING','MEMORY_PROFILE','PERMISSIONS','WORKFLOW','PROMPT','SETTINGS')),
    resource_key TEXT NOT NULL,
    configuration TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(installation_id) REFERENCES workforce_installations(id) ON DELETE RESTRICT,
    UNIQUE(installation_id,resource_type,resource_key)
);

CREATE TABLE integration_wizards (
    id TEXT PRIMARY KEY,
    installation_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('TELEGRAM','EMAIL','GOOGLE','SLACK','GITHUB','WEBHOOK','API_KEY')),
    secret_reference TEXT,
    configuration TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('PENDING','ACTIVE','DISABLED','FAILED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(installation_id) REFERENCES workforce_installations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    UNIQUE(installation_id,provider)
);

CREATE TABLE marketplace_earnings (
    id TEXT PRIMARY KEY,
    publisher_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    installation_id TEXT,
    gross_cents INTEGER NOT NULL CHECK (gross_cents >= 0),
    commission_cents INTEGER NOT NULL CHECK (commission_cents >= 0),
    creator_cents INTEGER NOT NULL CHECK (creator_cents >= 0),
    currency TEXT NOT NULL DEFAULT 'USD' CHECK (length(currency) = 3),
    status TEXT NOT NULL CHECK (status IN ('ESTIMATED','VOID')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(publisher_id) REFERENCES publishers(id) ON DELETE RESTRICT,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(installation_id) REFERENCES workforce_installations(id) ON DELETE RESTRICT
);

CREATE TRIGGER marketplace_earnings_immutable_update BEFORE UPDATE ON marketplace_earnings
BEGIN SELECT RAISE(ABORT,'marketplace earnings are immutable'); END;
CREATE TRIGGER marketplace_earnings_immutable_delete BEFORE DELETE ON marketplace_earnings
BEGIN SELECT RAISE(ABORT,'marketplace earnings are immutable'); END;

CREATE INDEX idx_marketplace_metadata_catalog ON marketplace_metadata(listing_kind,visibility,price_cents);
CREATE INDEX idx_workforce_installations_workspace ON workforce_installations(workspace_id,status,updated_at);
CREATE INDEX idx_workforce_resources_installation ON workforce_resources(installation_id,resource_type);
CREATE INDEX idx_integration_wizards_workspace ON integration_wizards(workspace_id,status);
CREATE INDEX idx_marketplace_earnings_publisher ON marketplace_earnings(publisher_id,created_at);

INSERT OR IGNORE INTO plans(id,name,tier,limits,features,status,created_at) VALUES
('starter','Starter',15,'{"workspace_limit":3,"members_limit":3,"agents_limit":8,"tasks_monthly":750,"storage_bytes":10737418240}','{"marketplace":true,"private_marketplace":false,"audit":false}','ACTIVE',datetime('now')),
('business','Business',35,'{"workspace_limit":50,"members_limit":50,"agents_limit":null,"tasks_monthly":25000,"storage_bytes":536870912000}','{"marketplace":true,"private_marketplace":true,"audit":true,"knowledge_base":true}','ACTIVE',datetime('now'));
