from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceMember:
    id: str
    workspace_id: str
    user_id: int
    role: str
    status: str
    created_at: str
