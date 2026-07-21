# Agents

The registry requires exactly these enabled manifests:

- orchestrator — routing and coordination;
- developer — workspace-only implementation;
- content — drafts without publication;
- research — analysis without unrestricted network access;
- analytics — workspace analysis without financial access;
- qa — quality and safety review;
- devops — infrastructure planning without host administration;
- sales — drafts without external outreach.

Each manifest declares an ID, system role, permissions, allowed and denied
tools, restrictions, risk, approval requirements, and enabled status. Unknown,
missing, malformed, disabled, or internally contradictory manifests make the
registry fail closed.
