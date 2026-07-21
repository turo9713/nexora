PRAGMA foreign_keys = ON;

ALTER TABLE users ADD COLUMN email_hash TEXT;
ALTER TABLE users ADD COLUMN display_name TEXT;

CREATE UNIQUE INDEX idx_users_email_hash ON users(email_hash) WHERE email_hash IS NOT NULL;

CREATE TABLE organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','ARCHIVED')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE roles (
    id TEXT PRIMARY KEY CHECK (id IN ('OWNER','ADMIN','MANAGER','OPERATOR','VIEWER')),
    rank INTEGER NOT NULL UNIQUE,
    description TEXT NOT NULL
);

INSERT INTO roles(id,rank,description) VALUES
 ('OWNER',50,'Organization, members, billing preparation, and security'),
 ('ADMIN',40,'Workspace, agents, and skills administration'),
 ('MANAGER',30,'Workflow and task management'),
 ('OPERATOR',20,'Execution of permitted tasks'),
 ('VIEWER',10,'Read-only access');

CREATE TABLE workspaces (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUSPENDED','ARCHIVED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    UNIQUE(organization_id,name)
);

CREATE TABLE workspace_members (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE','INVITED','REMOVED')),
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT,
    FOREIGN KEY(role) REFERENCES roles(id) ON DELETE RESTRICT,
    UNIQUE(workspace_id,user_id)
);

CREATE TABLE workspace_agents (
    workspace_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
    PRIMARY KEY(workspace_id,agent_id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE workspace_skills (
    workspace_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK (enabled IN (0,1)),
    PRIMARY KEY(workspace_id,skill_id),
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT
);

CREATE TABLE knowledge_documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    access_level TEXT NOT NULL CHECK (access_level IN ('TEAM','MANAGERS','ADMINS')),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE task_comments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE RESTRICT
);

CREATE TABLE activity_events (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    workspace_id TEXT,
    event TEXT NOT NULL,
    actor_id INTEGER,
    resource_id TEXT,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(id) ON DELETE RESTRICT,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY(actor_id) REFERENCES users(id) ON DELETE RESTRICT
);

ALTER TABLE tasks ADD COLUMN organization_id TEXT REFERENCES organizations(id);
ALTER TABLE tasks ADD COLUMN workspace_id TEXT REFERENCES workspaces(id);
ALTER TABLE tasks ADD COLUMN creator_id INTEGER REFERENCES users(id);
ALTER TABLE tasks ADD COLUMN assignee_id INTEGER REFERENCES users(id);

CREATE INDEX idx_organizations_owner_status ON organizations(owner_id,status);
CREATE INDEX idx_workspaces_org_status ON workspaces(organization_id,status);
CREATE INDEX idx_workspace_members_user_status ON workspace_members(user_id,status);
CREATE INDEX idx_knowledge_workspace_created ON knowledge_documents(workspace_id,created_at);
CREATE INDEX idx_comments_workspace_task ON task_comments(workspace_id,task_id,created_at);
CREATE INDEX idx_activity_workspace_created ON activity_events(workspace_id,created_at);
CREATE INDEX idx_tasks_workspace_updated ON tasks(workspace_id,updated_at);
