from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable


class APIRateLimiter:
    """In-memory per-key, per-owner, per-endpoint fixed-window limiter."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._values: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key_id: str, owner: str, endpoint: str, *, limit: int, window_seconds: int = 60) -> bool:
        now = self.clock()
        identities = ((f"key:{key_id}", endpoint), (f"owner:{owner}", endpoint))
        with self._lock:
            for identity in identities:
                values = self._values[identity]
                while values and values[0] <= now - window_seconds:
                    values.popleft()
                if len(values) >= limit:
                    return False
            for identity in identities:
                self._values[identity].append(now)
        return True
