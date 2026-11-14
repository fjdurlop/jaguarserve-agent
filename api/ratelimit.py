"""Sliding-window rate limits in memory (single replica). Swap for Redis when scaling agent-api out."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: float) -> float:
        """Record a hit. Returns 0 if allowed, else seconds to wait."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            return max(1.0, q[0] + window_s - now)
        q.append(now)
        if len(self._hits) > 50_000:  # crude memory bound
            self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
        return 0.0
