# User Dashboard

Nexora 3.4 adds `/home` as a single operations entry point. It shows the
authorized workspace name, active and completed tasks, running agents, pending
approvals, unread notifications, and a bounded usage percentage.

## Pages

- `/home` — summary, recent activity, notifications, and realtime state.
- `/activity` — sanitized workspace event timeline.
- `/notifications` — owner/workspace-scoped notifications and read state.
- `/workspace` — members, agents, tasks, skills, role, and usage.
- `/agents/status` — current task, health, last execution, and safe error code.
- `/analytics` — task, agent, workflow success, duration, and bottleneck-stage aggregates.
- `/onboarding` — links through workspace, template, first task, and result.

The UI is not an execution console. It cannot run tools, change task state,
restart services, or contact OpenClaw directly. Task creation and risky actions
remain on existing authorized surfaces and continue to use Policy and Approval.

## API

Dashboard session endpoints are same-origin under `/api/*`. Public clients use:

- `GET /api/v1/dashboard` with `operations:read`;
- `GET /api/v1/activity` with `operations:read`;
- `GET /api/v1/notifications` with `notifications:read`;
- `GET /api/v1/agents/status` with `agents:read`.

An optional `workspace_id` must belong to the authenticated principal. Omitted
workspace IDs resolve to the first active membership. Unknown and inaccessible
workspaces return the same safe not-found response.
