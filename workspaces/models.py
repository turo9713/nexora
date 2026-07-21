from dataclasses import dataclass


@dataclass(frozen=True)
class Workspace:
    id: str
    organization_id: str
    name: str
    description: str
    status: str
    created_at: str
