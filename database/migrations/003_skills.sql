PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('DISCOVERED','VALIDATED','INSTALLED','ACTIVE','DISABLED','FAILED','REMOVED')),
    risk TEXT NOT NULL,
    agent TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id TEXT NOT NULL,
    event TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS skill_permissions (
    skill_id TEXT NOT NULL,
    permission TEXT NOT NULL,
    scope TEXT NOT NULL,
    PRIMARY KEY(skill_id, permission, scope),
    FOREIGN KEY(skill_id) REFERENCES skills(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status);
CREATE INDEX IF NOT EXISTS idx_skill_events_skill ON skill_events(skill_id, created_at);
