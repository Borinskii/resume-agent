from __future__ import annotations

import time
from collections import deque
from threading import Lock


class RateLimiter:
    """In-memory sliding-window rate limiter.

    Suitable for single-process dev/prototype. Replace with Redis-backed
    limiter when running multiple workers.
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self._max:
                return False
            bucket.append(now)
            return True
