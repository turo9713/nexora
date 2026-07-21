from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HealthSummary:
    active_tasks: int
    completed_today: int
    failed_access: int
    pending_approvals: int
