import pytest

from pymidil.event.idempotency import InMemoryIdempotencyStore, default_idempotency_key
from pymidil.event.message import Message


@pytest.mark.anyio
async def test_store_claim_is_atomic_and_releasable():
    store = InMemoryIdempotencyStore()
    assert await store.claim("K") is True
    assert await store.claim("K") is False  # already claimed
    await store.release("K")
    assert await store.claim("K") is True  # reclaimable after release


@pytest.mark.anyio
async def test_ttl_zero_expires_immediately():
    store = InMemoryIdempotencyStore()
    assert await store.claim("K", ttl_seconds=0) is True
    assert await store.claim("K", ttl_seconds=0) is True  # ttl=0 -> reclaimable


def test_evict_expired_prunes_only_stale_entries():
    store = InMemoryIdempotencyStore()
    store._claims = {"stale": 1.0, "live": 1e18}
    store._evict_expired(now=2.0)
    assert "stale" not in store._claims
    assert "live" in store._claims


def test_default_key_prefers_typed_field_then_id():
    # No reliance on metadata: typed idempotency_key, else the message id.
    assert default_idempotency_key(Message(id="m1", body={})) == "m1"
    assert (
        default_idempotency_key(
            Message(id="m1", body={}, idempotency_key="BK-1:Created")
        )
        == "BK-1:Created"
    )
