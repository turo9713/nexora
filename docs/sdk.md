# SDK Foundation

The Python SDK in `sdk/python/nexora_sdk` is an in-process facade over authenticated, workspace-scoped services. It supports agent declaration, declared-skill binding checks, team declaration, safe workflow planning, and result handles. `start_workflow` returns a policy-validated plan and deliberately does not execute it autonomously. It has no network client, arbitrary code loader, shell bridge, Docker access, or Gateway credential.

Agent/team creation accepts an approval ID and consumes it through the existing approval service. See `sdk/python/examples/safe_agent.py`.
