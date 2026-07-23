"""Idempotency (A3) — dedup store + consumer-level policy.

Idempotency is applied at the dispatch boundary (see ``EventConsumer``), not as a
subscriber middleware, so it dedups the *delivery* once for every subscriber.
"""

from pymidil.event.idempotency.policy import (
    IdempotencyPolicy,
    KeyFn,
    default_idempotency_key,
)
from pymidil.event.idempotency.redis import RedisIdempotencyStore
from pymidil.event.idempotency.store import IdempotencyStore, InMemoryIdempotencyStore

__all__ = [
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "IdempotencyPolicy",
    "KeyFn",
    "default_idempotency_key",
]
