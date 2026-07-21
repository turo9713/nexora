# Workflow templates

Nexora 2.1 templates are declarative selections of existing agents and skills. They cannot contain commands, executable entrypoints, secrets, environment variables, Docker access, or production permissions.

The successful lifecycle is `DISCOVERED -> VALIDATED -> ACTIVE`. Installation runs validation, referenced component checks, Policy Engine evaluation, approval when required, persistence, and audit registration. Installations are owner-isolated, reversible, and idempotent.
