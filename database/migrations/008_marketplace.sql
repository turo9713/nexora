PRAGMA foreign_keys = ON;

CREATE TABLE publishers (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING','VERIFIED','SUSPENDED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
    UNIQUE(user_id,display_name)
);

CREATE TABLE marketplace_items (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('AGENT','SKILL','TEMPLATE','INTEGRATION')),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    current_version TEXT NOT NULL,
    author_id TEXT NOT NULL,
    category TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH')),
    status TEXT NOT NULL CHECK (status IN ('DRAFT','SUBMITTED','VALIDATING','APPROVED','PUBLISHED','DISABLED','REMOVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(author_id) REFERENCES publishers(id) ON DELETE RESTRICT
);

CREATE TABLE packages (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest TEXT NOT NULL,
    checksum TEXT NOT NULL,
    signature TEXT,
    signature_status TEXT NOT NULL CHECK (signature_status IN ('UNSIGNED','CHECKSUM_ATTESTED','INVALID')),
    validation_status TEXT NOT NULL CHECK (validation_status IN ('APPROVED','REJECTED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    UNIQUE(item_id,version)
);

CREATE TABLE marketplace_installations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    version TEXT NOT NULL,
    installed_by INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','ROLLED_BACK','FAILED')),
    approval_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(package_id) REFERENCES packages(id) ON DELETE RESTRICT,
    FOREIGN KEY(installed_by) REFERENCES users(id) ON DELETE RESTRICT,
    UNIQUE(workspace_id,item_id,version)
);

CREATE TABLE reviews (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(package_id) REFERENCES packages(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
    UNIQUE(package_id,user_id)
);

CREATE TABLE licenses (
    id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('COMMUNITY','INTERNAL','EVALUATION')),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','REVOKED','EXPIRED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(package_id) REFERENCES packages(id) ON DELETE RESTRICT
);

CREATE TABLE marketplace_events (
    id TEXT PRIMARY KEY,
    item_id TEXT,
    publisher_id TEXT,
    event TEXT NOT NULL,
    result TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES marketplace_items(id) ON DELETE RESTRICT,
    FOREIGN KEY(publisher_id) REFERENCES publishers(id) ON DELETE RESTRICT
);

CREATE TRIGGER packages_immutable_update BEFORE UPDATE ON packages BEGIN SELECT RAISE(ABORT,'marketplace packages are immutable'); END;
CREATE TRIGGER packages_immutable_delete BEFORE DELETE ON packages BEGIN SELECT RAISE(ABORT,'marketplace packages are immutable'); END;
CREATE TRIGGER marketplace_events_immutable_update BEFORE UPDATE ON marketplace_events BEGIN SELECT RAISE(ABORT,'marketplace events are immutable'); END;
CREATE TRIGGER marketplace_events_immutable_delete BEFORE DELETE ON marketplace_events BEGIN SELECT RAISE(ABORT,'marketplace events are immutable'); END;

CREATE INDEX idx_marketplace_catalog ON marketplace_items(status,type,category,name);
CREATE INDEX idx_marketplace_author ON marketplace_items(author_id,status);
CREATE INDEX idx_marketplace_packages ON packages(item_id,version);
CREATE INDEX idx_marketplace_installations_workspace ON marketplace_installations(workspace_id,status,updated_at);
CREATE INDEX idx_marketplace_reviews_item ON reviews(item_id,created_at);
CREATE INDEX idx_marketplace_events_item ON marketplace_events(item_id,created_at);
