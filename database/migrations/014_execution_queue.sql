PRAGMA foreign_keys = ON;

CREATE TABLE execution_jobs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    owner TEXT NOT NULL,
    session_id TEXT NOT NULL,
    worker_group TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 5 CHECK (priority BETWEEN 0 AND 9),
    status TEXT NOT NULL CHECK (status IN (
        'QUEUED','RUNNING','RETRY_WAIT','SUCCEEDED','FAILED','CANCELLED'
    )),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts BETWEEN 1 AND 5),
    available_at TEXT NOT NULL,
    lease_owner TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL,
    last_error_code TEXT,
    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE RESTRICT,
    FOREIGN KEY(owner) REFERENCES users(external_hash) ON DELETE RESTRICT,
    UNIQUE(worker_group,idempotency_key)
);

CREATE TABLE execution_job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES execution_jobs(id) ON DELETE RESTRICT
);

CREATE INDEX idx_execution_jobs_claim
    ON execution_jobs(worker_group,owner,status,available_at,priority DESC,created_at);
CREATE INDEX idx_execution_jobs_task
    ON execution_jobs(task_id,created_at DESC);
CREATE INDEX idx_execution_job_events_job
    ON execution_job_events(job_id,created_at);

CREATE TRIGGER execution_job_events_immutable_update
BEFORE UPDATE ON execution_job_events
BEGIN SELECT RAISE(ABORT,'execution job events are immutable'); END;

CREATE TRIGGER execution_job_events_immutable_delete
BEFORE DELETE ON execution_job_events
BEGIN SELECT RAISE(ABORT,'execution job events are immutable'); END;
