# Agent Teams

Agent Teams are workspace-scoped groups of declarative agents with one leader, member roles, and an ordered workflow. Team membership never grants new tools or permissions. Create/add/remove operations require RBAC, Policy Engine, one-time approval, and audit; reads always verify workspace membership.

Roles are `LEADER`, `SPECIALIST`, and `REVIEWER`. A team cannot contain an unknown or disabled custom agent and cannot reference another workspace.
