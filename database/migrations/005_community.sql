PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('DISCOVERED','VALIDATED','ACTIVE','DISABLED','FAILED')),
    permission_level TEXT NOT NULL CHECK (permission_level IN ('LOW','MEDIUM')),
    approval_required INTEGER NOT NULL CHECK (approval_required IN (0,1)),
    manifest_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS template_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id TEXT NOT NULL,
    event TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(template_id) REFERENCES templates(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS installations (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','ROLLED_BACK','FAILED')),
    approval_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(template_id, owner),
    FOREIGN KEY(template_id) REFERENCES templates(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status);
CREATE INDEX IF NOT EXISTS idx_template_events_template ON template_events(template_id, created_at);
CREATE INDEX IF NOT EXISTS idx_installations_owner_status ON installations(owner, status);
