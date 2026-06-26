"""Idempotency store (A3) — the dedup backbone.

A store records which idempotency keys have already been processed so re-deliveries
can be short-circuited. ``claim`` is an atomic check-and-set: it returns True for
the first caller and False for any duplicate. ``release`` undoes a claim so a
*failed* first attempt can be retried.
"""

from __future__ import annotations

import asyncio
import math
import time
from abc import ABC, abstractmethod
from typing import Optional


class IdempotencyStore(ABC):
    """Atomic claim/release store for idempotency keys."""

    @abstractmethod
    async def claim(self, key: str, ttl_seconds: Optional[float] = None) -> bool:
        """Atomically claim ``key``. True if newly claimed, False if already seen."""

    @abstractmethod
    async def release(self, key: str) -> None:
        """Release a claim so the key can be re-processed (e.g. after a failure).

        Releases are not fenced: after a TTL-expiry-and-reclaim race a late
        release can drop a *newer* claim. Keep the TTL comfortably above the
        handler's worst-case runtime to avoid that window.
        """

    async def aclose(self) -> None:
        """Release any resources. No-op by default."""
        return None


class InMemoryIdempotencyStore(IdempotencyStore):
    """Process-local store with optional TTL. Single-instance / testing.

    Expired entries are swept lazily once the store grows past ``max_entries``,
    so TTL'd workloads stay bounded. Claims made *without* a TTL are retained for
    the process lifetime — that is the dedup guarantee, not a leak; use a TTL (or
    ``RedisIdempotencyStore``) for an unbounded, long-running keyspace.
    """

    def __init__(self, *, max_entries: int = 10_000) -> None:
        self._claims: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries

    async def claim(self, key: str, ttl_seconds: Optional[float] = None) -> bool:
        async with self._lock:
            now = time.monotonic()
            expiry = self._claims.get(key)
            if expiry is not None and expiry > now:
                return False
            if len(self._claims) >= self._max_entries:
                self._evict_expired(now)
            # ttl_seconds=0 means "expire immediately"; only None means "never".
            self._claims[key] = (
                now + ttl_seconds if ttl_seconds is not None else math.inf
            )
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            self._claims.pop(key, None)

    def _evict_expired(self, now: float) -> None:
        self._claims = {k: exp for k, exp in self._claims.items() if exp > now}
