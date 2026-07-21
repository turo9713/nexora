PRAGMA foreign_keys = OFF;
DROP INDEX IF EXISTS idx_skill_events_skill;
DROP INDEX IF EXISTS idx_skills_status;
DROP TABLE IF EXISTS skill_permissions;
DROP TABLE IF EXISTS skill_events;
DROP TABLE IF EXISTS skills;
DELETE FROM schema_migrations WHERE version = 3;
PRAGMA foreign_keys = ON;
