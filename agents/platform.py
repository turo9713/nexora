from __future__ import annotations

from typing import Any

from nexora.agents.builder import AgentBuilder
from nexora.agents.evaluation import AgentEvaluation
from nexora.agents.memory import AgentMemory
from nexora.agents.planning import PlanningEngine
from nexora.agents.security import AgentSecurityGuard
from nexora.agents.teams import AgentTeamService


class AgentEcosystem:
    def __init__(self, database: Any, teams: Any, policy: Any, audit: Any, *, memory_pepper: bytes) -> None:
        self.security = AgentSecurityGuard(teams, policy, audit)
        self.builder = AgentBuilder(database, self.security, audit)
        self.teams = AgentTeamService(database, self.security, audit)
        self.planning = PlanningEngine(database, self.security, audit)
        self.memory = AgentMemory(database, self.security, audit, memory_pepper)
        self.evaluation = AgentEvaluation(database, self.security, audit)


__all__ = ["AgentEcosystem"]
