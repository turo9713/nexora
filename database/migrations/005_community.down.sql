PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_installations_owner_status;
DROP INDEX IF EXISTS idx_template_events_template;
DROP INDEX IF EXISTS idx_templates_status;
DROP TABLE IF EXISTS installations;
DROP TABLE IF EXISTS template_events;
DROP TABLE IF EXISTS templates;
DELETE FROM schema_migrations WHERE version = 5;
PRAGMA foreign_keys = ON;
