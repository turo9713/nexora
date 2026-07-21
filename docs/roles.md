# Roles and permissions

RBAC is deny-by-default. Missing roles, unknown roles, and unknown permissions
are denied.

| Role | Intended capabilities |
| --- | --- |
| OWNER | Organization, members, billing preparation, security, and all workspace administration |
| ADMIN | Workspaces, members, agents, skills, tasks, knowledge, and workspace audit |
| MANAGER | Workflow/task management, comments, knowledge, and workspace audit |
| OPERATOR | Create/read permitted tasks, comments, and team knowledge |
| VIEWER | Read permitted tasks and team-level knowledge |

Only OWNER may assign any role. ADMIN may assign roles strictly below ADMIN and
cannot create another ADMIN or OWNER. Role changes and invitations require a
matching one-time approval. A role never bypasses agent policies, skill
permissions, sandbox restrictions, or resource ownership.
