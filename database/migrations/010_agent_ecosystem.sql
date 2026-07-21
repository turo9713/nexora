PRAGMA foreign_keys = ON;

CREATE TABLE agents (
    id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','VALIDATED','ACTIVE','DISABLED','ARCHIVED')),
    current_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id,id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE agent_versions (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    version TEXT NOT NULL,
    manifest TEXT NOT NULL,
    checksum TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','VALIDATED','ACTIVE','DISABLED','ARCHIVED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id,agent_id) REFERENCES agents(workspace_id,id) ON DELETE RESTRICT,
    UNIQUE(workspace_id,agent_id,version)
);

CREATE TABLE agent_teams (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    leader_agent_id TEXT NOT NULL,
    workflow TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','ACTIVE','DISABLED','ARCHIVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE team_members (
    id TEXT PRIMARY KEY,
    team_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    role TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY(team_id) REFERENCES agent_teams(id) ON DELETE RESTRICT,
    UNIQUE(team_id,agent_id)
);

CREATE TABLE agent_memory (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    agent_id TEXT,
    scope TEXT NOT NULL CHECK(scope IN ('PERSONAL','WORKSPACE','AGENT')),
    key_hash TEXT NOT NULL,
    value TEXT NOT NULL,
    classification TEXT NOT NULL CHECK(classification IN ('PUBLIC','INTERNAL')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT,
    UNIQUE(workspace_id,owner_id,agent_id,scope,key_hash)
);

CREATE TABLE agent_plans (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','VALIDATED','WAITING_APPROVAL','READY','RUNNING','COMPLETED','FAILED','CANCELLED')),
    risk TEXT NOT NULL CHECK(risk IN ('LOW','MEDIUM','HIGH')),
    steps TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE agent_evaluations (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    agent_id TEXT NOT NULL,
    task_id TEXT,
    accuracy INTEGER NOT NULL CHECK(accuracy BETWEEN 0 AND 100),
    reliability INTEGER NOT NULL CHECK(reliability BETWEEN 0 AND 100),
    safety INTEGER NOT NULL CHECK(safety BETWEEN 0 AND 100),
    speed INTEGER NOT NULL CHECK(speed BETWEEN 0 AND 100),
    cost INTEGER NOT NULL CHECK(cost BETWEEN 0 AND 100),
    score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
    grade TEXT NOT NULL CHECK(grade IN ('A+','A','B','C','D','F')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE sdk_apps (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    scopes TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ACTIVE','DISABLED','REVOKED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TRIGGER agent_versions_immutable_update BEFORE UPDATE ON agent_versions
BEGIN SELECT RAISE(ABORT,'agent versions are immutable'); END;
CREATE TRIGGER agent_versions_immutable_delete BEFORE DELETE ON agent_versions
BEGIN SELECT RAISE(ABORT,'agent versions are immutable'); END;
CREATE TRIGGER agent_evaluations_immutable_update BEFORE UPDATE ON agent_evaluations
BEGIN SELECT RAISE(ABORT,'agent evaluations are immutable'); END;
CREATE TRIGGER agent_evaluations_immutable_delete BEFORE DELETE ON agent_evaluations
BEGIN SELECT RAISE(ABORT,'agent evaluations are immutable'); END;

CREATE INDEX idx_agents_workspace_status ON agents(workspace_id,status,name);
CREATE INDEX idx_agent_versions_agent ON agent_versions(workspace_id,agent_id,created_at);
CREATE INDEX idx_agent_teams_workspace ON agent_teams(workspace_id,status,name);
CREATE INDEX idx_team_members_team ON team_members(team_id,position);
CREATE INDEX idx_agent_memory_scope ON agent_memory(workspace_id,owner_id,scope,updated_at);
CREATE INDEX idx_agent_plans_workspace ON agent_plans(workspace_id,status,updated_at);
CREATE INDEX idx_agent_evaluations_workspace ON agent_evaluations(workspace_id,agent_id,created_at);
CREATE INDEX idx_sdk_apps_workspace ON sdk_apps(workspace_id,status);
