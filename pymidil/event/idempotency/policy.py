"""Idempotency policy + key extraction — what a consumer needs to dedup.

Bundles the store with the key-extraction function and an optional TTL. Attached
to a consumer (``consumer.use_idempotency(...)``); the consumer applies it at the
dispatch boundary, before fanning out to subscribers, so the guarantee holds for
*every* subscriber regardless of how it is authored.

Key extraction lives here (a policy concern), not in the store (a persistence
concern).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from pymidil.event.idempotency.store import IdempotencyStore

KeyFn = Callable[[Any], Optional[str]]


def default_idempotency_key(message: Any) -> Optional[str]:
    """Resolve the dedup key from the typed ``idempotency_key`` field, else the id.

    Both are first-class, typed attributes of the message — no reliance on the
    untyped, transport-populated metadata bag.
    """
    key = getattr(message, "idempotency_key", None)
    if key:
        return str(key)
    message_id = getattr(message, "id", None)
    return str(message_id) if message_id is not None else None


@dataclass
class IdempotencyPolicy:
    store: IdempotencyStore
    key_fn: KeyFn = default_idempotency_key
    ttl_seconds: Optional[float] = None
