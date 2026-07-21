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
# Custom agents in v3

The reviewed eight-agent static registry remains the runtime trust anchor.
Custom agents are declarative Manifest v2 records, scoped to one workspace and
stored as immutable semantic versions. Their requested tools and permissions
are strict allowlists and can never extend the static Policy Engine.
