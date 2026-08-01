"""Producers emit a producer-kind telemetry envelope per publish (A2 produce-side)."""

import pytest

from pymidil.event import (
    Event,
    EventKind,
    EventStatus,
    SQSProducer,
    SQSProducerEventConfig,
    TelemetryProducerHook,
)
from pymidil.event.observability.sinks.base import TelemetrySink

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


SOURCE = "arn:aws:sqs:us-east-1:123456789012:orders"


class _ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.envelopes: list = []

    async def emit(self, envelope) -> None:
        self.envelopes.append(envelope)


class _FakeSqsClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    async def send_message(self, **kw):
        if self.fail:
            raise RuntimeError("AWS.SimpleQueueService.NonExistentQueue")
        return {"MessageId": "MID-123"}


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


def _producer(client, sink):
    producer = SQSProducer(
        SQSProducerEventConfig(queue_url=SOURCE), session=_FakeSession(client)
    )
    producer.add_hook(
        TelemetryProducerHook(sink, source_service="booking-svc", broker="sqs")
    )
    return producer


async def test_publish_emits_produced_envelope_with_message_id():
    sink = _ListSink()
    producer = _producer(_FakeSqsClient(), sink)

    await producer.publish(
        Event(
            id="BK-1",
            source="booking-svc",
            type="BookingCreated",
            data={"booking_id": "BK-1"},
            idempotency_key="BK-1:BookingCreated",
        )
    )

    assert len(sink.envelopes) == 1
    env = sink.envelopes[0]
    assert env.kind == EventKind.PRODUCER
    assert env.status == EventStatus.SUCCESS
    assert env.message_id == "MID-123"  # the SQS-assigned id the consumer will see
    assert env.event_type == "BookingCreated"
    assert env.idempotency_key == "BK-1:BookingCreated"
    assert env.source_service == "booking-svc"
    assert env.broker == "sqs"
    assert env.consumer is None
    assert env.processing_time_ms is not None  # publish latency recorded


async def test_failed_publish_emits_failed_producer_envelope_and_reraises():
    sink = _ListSink()
    producer = _producer(_FakeSqsClient(fail=True), sink)

    with pytest.raises(RuntimeError):
        await producer.publish(
            Event(id="x", source="booking-svc", type="BookingCreated", data={"x": 1})
        )

    assert len(sink.envelopes) == 1
    env = sink.envelopes[0]
    assert env.kind == EventKind.PRODUCER
    assert env.status == EventStatus.FAILED
    assert env.failure_reason and "NonExistentQueue" in env.failure_reason


async def test_publish_without_hooks_is_a_noop():
    producer = SQSProducer(
        SQSProducerEventConfig(queue_url=SOURCE), session=_FakeSession(_FakeSqsClient())
    )
    # no hooks attached → no telemetry, no error
    await producer.publish(Event(id="x", source="s", type="t", data={"x": 1}))
