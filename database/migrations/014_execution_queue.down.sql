PRAGMA foreign_keys = OFF;
DROP TRIGGER IF EXISTS execution_job_events_immutable_delete;
DROP TRIGGER IF EXISTS execution_job_events_immutable_update;
DROP TABLE IF EXISTS execution_job_events;
DROP TABLE IF EXISTS execution_jobs;
DELETE FROM schema_migrations WHERE version=14;
PRAGMA foreign_keys = ON;
