# Nexora Core

The open-source core is intentionally mapped onto the established package
layout to avoid duplicate modules or import conflicts:

- `runtime/`, `workflows/`, and `storage/`: task and workflow engine.
- `agents/`: manifests and Agent Registry.
- `skills/`: declarative Skill Registry and validators.
- `api/`: scoped versioned API facade.
- `dashboard/`: authenticated control panel.
- `security/`: policies, redaction, and audit controls.
- `database/`: SQLite models, repository, and reversible migrations.

This directory documents the boundary; it does not copy or wrap those packages.
Production configuration and proprietary extensions are not part of Core.
