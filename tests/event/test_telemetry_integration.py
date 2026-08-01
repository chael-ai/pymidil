"""A1 + A2 over the real dispatch path with OTel propagation (no broker)."""

from typing import Optional

import pytest

from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.core import Event, NoAckDelivery
from pymidil.event.observability import EventStatus, TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.otel import current_span_ids, inject_headers, producer_span
from pymidil.event.producer.sqs import SQSProducer, SQSProducerEventConfig
from pymidil.event.subscriber.base import FunctionSubscriber

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # dispatch() is asyncio-native


class _MemConfig(BaseConsumerConfig):
    type: str = "memory"


class _MemConsumer(EventConsumer):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...


class _MemDelivery(NoAckDelivery):
    """A brokerless delivery whose ``carrier()`` carries upstream trace context.

    Disposition is a no-op (inherited from ``NoAckDelivery``); the trace carrier
    now lives on the delivery, not the consumer, so ``dispatch`` extracts it via
    ``delivery.carrier()``.
    """

    def __init__(self, event: Event, *, carrier: Optional[dict] = None) -> None:
        super().__init__(event)
        self._carrier = dict(carrier or {})

    def carrier(self):
        return self._carrier


class ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, envelope) -> None:
        self.events.append(envelope)


async def test_dispatch_continues_trace_and_emits_success():
    seen: dict = {}

    async def handler(event):
        seen["ids"] = current_span_ids()

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(FunctionSubscriber(handler=handler))
    sink = ListSink()
    consumer.add_hook(TelemetryDispatchHook(sink, source_service="booking-svc"))

    # Produce an upstream trace context into the carrier.
    carrier: dict = {}
    with producer_span("orders"):
        inject_headers(carrier)
        parent_trace, parent_span, _ = current_span_ids()

    event = Event(id="EVT-9", source="orders", type="BookingCreated", data={"x": 1})
    await consumer.dispatch(_MemDelivery(event, carrier=carrier))

    # A1: handler observed a child of the incoming trace
    trace_id, span_id, parent_span_id = seen["ids"]
    assert trace_id == parent_trace
    assert parent_span_id == parent_span
    assert span_id != parent_span

    # A2: a correlated success envelope was emitted
    assert len(sink.events) == 1
    env = sink.events[0]
    assert env.status == EventStatus.SUCCESS
    assert env.message_id == "EVT-9"
    assert env.event_type == "BookingCreated"
    assert env.trace_id == parent_trace
    assert env.parent_span_id == parent_span


async def test_dispatch_starts_root_when_no_incoming_trace():
    seen: dict = {}

    async def handler(event):
        seen["ids"] = current_span_ids()

    consumer = _MemConsumer(_MemConfig())
    consumer.subscribe(FunctionSubscriber(handler=handler))
    event = Event(id="m", source="orders", type="BookingCreated", data={})
    await consumer.dispatch(_MemDelivery(event))

    trace_id, span_id, parent_span_id = seen["ids"]
    assert trace_id is not None and span_id is not None  # SDK provider active
    assert parent_span_id is None  # root span — no upstream context


class _FakeSqsClient:
    def __init__(self) -> None:
        self.sent: list = []

    async def send_message(self, **kw):
        self.sent.append(kw)


class _FakeCtx:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, client):
        self._client = client

    def client(self, *_a, **_kw):
        return _FakeCtx(self._client)


async def test_handler_publish_continues_trace_across_hops():
    """A handler publishing downstream within dispatch continues the same trace."""
    client = _FakeSqsClient()
    producer = SQSProducer(
        SQSProducerEventConfig(queue_url="arn:aws:sqs:us-east-1:123456789012:next"),
        session=_FakeSession(client),
    )
    consumer = _MemConsumer(_MemConfig())
    seen: dict = {}

    async def handler(event):
        seen["consumer_trace"] = current_span_ids()[0]
        await producer.publish(
            Event(
                id="REQ-1",
                source="orders",
                type="PaymentRequested",
                data={"next": "PaymentRequested"},
            )
        )

    consumer.subscribe(FunctionSubscriber(handler=handler))
    event = Event(
        id="EVT-1", source="orders", type="BookingCreated", data={"booking": 1}
    )
    await consumer.dispatch(_MemDelivery(event))

    traceparent = client.sent[0]["MessageAttributes"]["traceparent"]["StringValue"]
    downstream_trace = traceparent.split("-")[1]
    assert seen["consumer_trace"] is not None
    assert downstream_trace == seen["consumer_trace"]  # same trace across the hop
