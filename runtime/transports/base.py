from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class TransportError(RuntimeError):
    pass


class Transport(ABC):
    @abstractmethod
    def send(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        raise NotImplementedError
