"""Sliding-window rate limits: in memory (one replica) or in Redis (shared by all agent-api replicas)."""

import secrets
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def check(self, key: str, limit: int, window_s: float) -> float:
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


# Atomic sliding window on a sorted set: drop old hits, count, add if under the limit.
# Returns 0 when allowed, else milliseconds until the oldest hit leaves the window.
_SLIDING = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return math.max(1, tonumber(oldest[2]) + window - now)
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


class RedisRateLimiter:
    def __init__(self, client):
        self.r = client
        self._script = client.register_script(_SLIDING)

    async def check(self, key: str, limit: int, window_s: float) -> float:
        now_ms = int(time.time() * 1000)
        wait_ms = await self._script(
            keys=[f"rl:{key}"],
            args=[now_ms, int(window_s * 1000), limit, f"{now_ms}-{secrets.token_hex(4)}"],
        )
        return max(1.0, int(wait_ms) / 1000) if int(wait_ms) else 0.0
