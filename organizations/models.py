from dataclasses import dataclass


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
