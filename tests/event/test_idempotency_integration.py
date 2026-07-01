"""Consumer-level idempotency over the real dispatch path.

Proves the refactor: dedup is applied at the dispatch boundary, so it covers
every subscriber type (not just FunctionSubscriber) and never cross-blocks
sibling subscribers on the first delivery. The duplicate signal travels via the
on_duplicate hook — no message mutation.
"""

import pytest

from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.idempotency import IdempotencyPolicy, InMemoryIdempotencyStore
from pymidil.event.message import Message
from pymidil.event.observability import EventStatus, TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.subscriber.base import EventSubscriber, FunctionSubscriber

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # dispatch() is asyncio-native


class _MemConfig(BaseConsumerConfig):
    type: str = "booking-svc"


class _MemConsumer(EventConsumer):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def ack(self, message) -> None:
        ...

    async def nack(self, message, requeue: bool = False) -> None:
        ...


class ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, envelope) -> None:
        self.events.append(envelope)


class CountingSubscriber(EventSubscriber):
    """A class-based subscriber — has no middleware support of its own."""

    def __init__(self) -> None:
        self.count = 0

    async def handle(self, event) -> None:
        self.count += 1


def _msg(message_id: str, key: str = "K") -> Message:
    return Message(
        id=message_id,
        body={"v": message_id},
        idempotency_key=key,
        metadata={"event_type": "BookingCreated"},
    )


async def test_dedups_delivery_and_emits_duplicate_via_hook():
    store = InMemoryIdempotencyStore()
    sink = ListSink()
    handled: list = []

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(FunctionSubscriber(handler=lambda e: handled.append(e.id)))
    consumer.add_hook(TelemetryDispatchHook(sink, source_service="booking-svc"))
    consumer.use_idempotency(IdempotencyPolicy(store))

    await consumer.dispatch(_msg("EVT-1"))
    await consumer.dispatch(_msg("EVT-2"))  # same key -> duplicate

    assert handled == ["EVT-1"]  # second delivery short-circuited
    assert [e.status for e in sink.events] == [
        EventStatus.SUCCESS,
        EventStatus.DUPLICATE,
    ]


async def test_dedup_covers_class_based_subscriber():
    store = InMemoryIdempotencyStore()
    subscriber = CountingSubscriber()  # NOT a FunctionSubscriber, no middleware

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(subscriber)
    consumer.use_idempotency(IdempotencyPolicy(store))

    await consumer.dispatch(_msg("EVT-1"))
    await consumer.dispatch(_msg("EVT-2"))  # same key

    assert subscriber.count == 1  # deduped even without middleware support


async def test_first_delivery_runs_all_subscribers_then_dedups():
    store = InMemoryIdempotencyStore()
    a, b = CountingSubscriber(), CountingSubscriber()

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(a)
    consumer.subscribe(b)
    consumer.use_idempotency(IdempotencyPolicy(store))

    await consumer.dispatch(_msg("EVT-1"))  # both run — no cross-block
    assert (a.count, b.count) == (1, 1)

    await consumer.dispatch(_msg("EVT-2"))  # same key — neither runs
    assert (a.count, b.count) == (1, 1)


async def test_claim_released_on_non_success_outcome():
    store = InMemoryIdempotencyStore()

    class Retrying(EventSubscriber):
        async def handle(self, event) -> None:
            ...

        async def __call__(self, event):  # propagate so the outcome is a retry
            raise RetryableEventError("transient")

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(Retrying())
    consumer.use_idempotency(IdempotencyPolicy(store))

    await consumer.dispatch(_msg("EVT-1", key="K"))
    # retry outcome -> claim released -> a redelivery can be re-processed
    assert await store.claim("K") is True
