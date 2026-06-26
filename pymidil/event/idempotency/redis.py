"""Redis-backed idempotency store — shared dedup across service instances.

Uses ``SET key 1 NX EX ttl`` which is atomic, so concurrent consumers on
different instances cannot both claim the same key. ``redis`` is imported lazily
so the package loads without the ``redis`` extra installed.
"""

from __future__ import annotations

from typing import Any, Optional

from pymidil.event.idempotency.store import IdempotencyStore


class RedisIdempotencyStore(IdempotencyStore):
    def __init__(
        self,
        redis_client: Any = None,
        *,
        url: Optional[str] = None,
        prefix: str = "idem:",
    ) -> None:
        if redis_client is None:
            if url is None:
                raise ValueError("RedisIdempotencyStore requires a redis_client or url")
            from redis.asyncio import Redis

            redis_client = Redis.from_url(url)
        self._redis = redis_client
        self._prefix = prefix

    async def claim(self, key: str, ttl_seconds: Optional[float] = None) -> bool:
        ttl = int(ttl_seconds) if ttl_seconds else None
        result = await self._redis.set(f"{self._prefix}{key}", "1", nx=True, ex=ttl)
        return bool(result)

    async def release(self, key: str) -> None:
        await self._redis.delete(f"{self._prefix}{key}")

    async def aclose(self) -> None:
        await self._redis.close()
