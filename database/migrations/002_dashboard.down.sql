DROP INDEX IF EXISTS idx_agent_overrides_enabled;
DROP TABLE IF EXISTS agent_overrides;
DELETE FROM schema_migrations WHERE version = 2;
