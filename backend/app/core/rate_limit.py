import time
from collections import deque
from threading import Lock

from app.core.errors import DomainError


class LoginLimiter:
    """Bounded per-process limiter; use a shared gateway limit in multi-worker deployments."""

    def __init__(self, limit: int, window_seconds: int, *, action: str = "login") -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.action = action
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(self, client: str) -> None:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            if len(self._events) >= 10000:
                self._events = {
                    key: values
                    for key, values in self._events.items()
                    if values and values[-1] > cutoff
                }
                if len(self._events) >= 10000 and client not in self._events:
                    raise DomainError(
                        429, "rate_limited", f"Too many {self.action} requests; try again later"
                    )
            events = self._events.setdefault(client, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                raise DomainError(
                    429, "rate_limited", f"Too many {self.action} requests; try again later"
                )
            events.append(now)
