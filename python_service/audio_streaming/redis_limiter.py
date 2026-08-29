"""Redis-backed rate limiter for multi-replica deployments.

The default ``RequestRateLimiter`` in ``cache.py`` is in-memory and only protects a single
process. Behind a load balancer with N replicas, each replica counts only its own traffic, so the
effective limit is N times the intended one. This limiter uses a Redis sliding-window counter
(``ZADD`` + ``ZREMRANGEBYSCORE`` + ``ZCARD`` in a pipeline) so the limit is enforced cluster-wide.

It is a drop-in: same ``allow(source) -> (bool, retry_after)`` contract. When Redis is not
configured, callers should fall back to the in-memory limiter (see ``app.py``).
"""

from __future__ import annotations

import time
from typing import Sequence


class RedisRateLimiter:
    """Cluster-wide rolling-window limiter backed by Redis sorted sets."""

    def __init__(self, url: str, max_requests: int, window_seconds: float = 60.0, max_keys: int = 10_000):
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(url, decode_responses=True)
        self._max_requests = max_requests
        self._window = window_seconds
        self._max_keys = max_keys

    @staticmethod
    def opaque_key(value: str) -> str:
        import hashlib
        return "ratelimit:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]

    async def allow(self, source: str) -> tuple[bool, int]:
        key = self.opaque_key(source)
        now = time.time()
        pipe = self._client.pipeline()
        pipe.zremrangebyscore(key, 0, now - self._window)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, int(self._window) + 1)
        _, _, count, _ = await pipe.execute()
        if count > self._max_requests:
            oldest = await self._client.zrange(key, 0, 0, withscores=True)
            retry = int(self._window - (now - oldest[0][1])) + 1 if oldest else 1
            return False, max(1, retry)
        return True, 0

    async def close(self) -> None:
        await self._client.aclose()
