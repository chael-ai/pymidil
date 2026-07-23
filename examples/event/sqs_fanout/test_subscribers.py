"""Unit tests for the fan-out subscribers — no LocalStack, no Observatory.

Because the handlers are ``EventSubscriber`` classes, their logic (fan-out,
validation, retry-then-give-up) is testable with a fake message and fake
producers. That testability is the point of the OOP approach.
"""

from types import SimpleNamespace

import pytest

from pymidil.event.exceptions import NonRetryableEventError, RetryableEventError

from .subscribers import FlakyLoyaltySubscriber, LeafSubscriber, OrderSubscriber

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    # The demo is asyncio-based (asyncio.sleep in the handlers), so pin the
    # anyio backend rather than also running the trio variant.
    return "asyncio"


def _message(order_id="OD-1", *, receive_count=1, body=None):
    """A minimal stand-in for a ConsumerMessage (body + SQS-style metadata)."""
    return SimpleNamespace(
        id=order_id,
        body={"order_id": order_id} if body is None else body,
        metadata={"ApproximateReceiveCount": str(receive_count)},
    )


class _RecordingProducer:
    def __init__(self):
        self.published: list[tuple[dict, dict]] = []

    async def publish(self, body, metadata=None):
        self.published.append((body, metadata or {}))


async def test_order_subscriber_fans_out_to_every_branch():
    ship, invoice = _RecordingProducer(), _RecordingProducer()
    subscriber = OrderSubscriber(
        [("ShipmentRequested", ship), ("InvoiceIssued", invoice)]
    )

    await subscriber(_message("OD-42"))

    assert [b["event_type"] for b, _ in ship.published] == ["ShipmentRequested"]
    assert [b["event_type"] for b, _ in invoice.published] == ["InvoiceIssued"]
    # each branch carries the order id and a per-branch idempotency key
    body, meta = ship.published[0]
    assert body["order_id"] == "OD-42"
    assert meta["idempotency_key"] == "OD-42:ShipmentRequested"


async def test_order_subscriber_ignores_malformed_events():
    ship = _RecordingProducer()
    subscriber = OrderSubscriber([("ShipmentRequested", ship)])

    # no order_id → should_handle() is False → handle() never runs
    await subscriber(_message(body={"nonsense": True}))

    assert ship.published == []


async def test_leaf_subscriber_handles_cleanly():
    # a well-behaved branch just does its work and doesn't raise
    await LeafSubscriber("shipping-svc")(_message("OD-7"))


async def test_flaky_subscriber_retries_then_gives_up():
    # failure_rate=100 → every order is "cursed", so we exercise the failure path
    loyalty = FlakyLoyaltySubscriber("loyalty-svc", failure_rate=100, max_attempts=3)

    # early attempts ask for redelivery…
    with pytest.raises(RetryableEventError):
        await loyalty(_message("OD-9", receive_count=1))
    with pytest.raises(RetryableEventError):
        await loyalty(_message("OD-9", receive_count=2))

    # …the final attempt gives up terminally → the consumer dead-letters it
    with pytest.raises(NonRetryableEventError):
        await loyalty(_message("OD-9", receive_count=3))


async def test_flaky_subscriber_lets_healthy_orders_through():
    # failure_rate=0 → nothing is cursed, so it behaves like any leaf
    loyalty = FlakyLoyaltySubscriber("loyalty-svc", failure_rate=0)
    await loyalty(_message("OD-11", receive_count=1))
