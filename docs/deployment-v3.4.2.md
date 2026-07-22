# Nexora 3.4.2 deployment notes

This patch changes private state writing, Telegram workspace binding, and the
Dashboard task SSE consumer. It does not change the database schema, Gateway,
secrets, firewall, or host networking.

Before deployment, record container IDs and restart counts, verify SQLite
integrity, create a configuration/data backup and Git bundle, and record current
task/state modes. Run the permission utility in `--check` mode before changing
anything.

Deploy only the affected Telegram, Dashboard, and API services. Do not restart
OpenClaw Gateway and do not reboot the VPS. After deployment, run `/status`, then
create one Telegram task and verify its new files are `0600` before any repair.
Confirm that the task and its progress/timeline arrive on the authenticated SSE
stream for the same workspace and not for another workspace.

Rollback restores the pre-deployment application bundle and state/configuration
backup, then restarts only the same affected services. There is no migration to
reverse.
