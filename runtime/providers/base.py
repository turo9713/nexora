"""Base provider interface for Nexora runtime."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Raised when a provider cannot execute or validate a request."""


class AgentProvider(ABC):
    def __init__(self, base_path: str | None = None, config: dict | None = None):
        self.base_path = base_path
        self.config = config or {}

    @abstractmethod
    def execute_agent(self, agent_message: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_response(self, agent_result: dict) -> bool:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> dict:
        raise NotImplementedError
