from typing import Optional

import pytest

from pymidil.event.core import Delivery, Event
from pymidil.event.observability import EventStatus, TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.otel import current_span_ids, get_tracer

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, envelope) -> None:
        self.events.append(envelope)


class FakeDelivery(Delivery):
    """A minimal transport double for the emitter.

    Exposes ``transport_id`` (the physical delivery id, distinct from the
    logical ``event.id``) and ``retry_count`` so envelope assertions can prove
    the emitter reads them off the *delivery*, not the event.
    """

    def __init__(
        self,
        event: Event,
        *,
        transport_id: Optional[str] = None,
        retry_count: int = 1,
    ) -> None:
        super().__init__(event)
        self._transport_id = transport_id if transport_id is not None else event.id
        self._retry_count = retry_count

    @property
    def transport_id(self) -> str:
        return self._transport_id

    @property
    def retry_count(self) -> int:
        return self._retry_count

    async def _ack(self) -> None:
        ...

    async def _retry(self) -> None:
        ...

    async def _dlq(self, error: Optional[Exception] = None) -> None:
        ...


def _event(**overrides) -> Event:
    base = dict(
        id="EVT-1",
        source="booking-svc",
        type="BookingCreated",
        data={"booking_id": "BK-1"},
    )
    base.update(overrides)
    return Event(**base)


def _delivery(
    *, transport_id: str = "SQS-MSG-1", retry_count: int = 3, **event_overrides
) -> FakeDelivery:
    return FakeDelivery(
        _event(**event_overrides),
        transport_id=transport_id,
        retry_count=retry_count,
    )


async def test_on_complete_emits_success_with_trace():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="booking-svc")

    # Nested spans so the envelope can be checked for trace/span/parent ids.
    with get_tracer().start_as_current_span("parent"):
        _, parent_span_id, _ = current_span_ids()
        with get_tracer().start_as_current_span("child"):
            trace_id, span_id, _ = current_span_ids()
            await hook.on_complete(_delivery(), "sqs", duration_ms=12.5)

    assert len(sink.events) == 1
    env = sink.events[0]
    assert env.status == EventStatus.SUCCESS
    # Money-path: envelope fields map off the delivery, not the event id.
    assert env.message_id == "SQS-MSG-1"  # delivery.transport_id
    assert env.event_type == "BookingCreated"  # delivery.event.type
    assert env.attempts == 3  # delivery.retry_count
    assert env.payload == {"booking_id": "BK-1"}  # delivery.event.data
    assert env.broker == "sqs"
    assert env.consumer == "booking-svc"
    assert env.source_service == "booking-svc"
    assert env.processing_time_ms == 12.5
    assert env.trace_id == trace_id
    assert env.span_id == span_id
    assert env.parent_span_id == parent_span_id


async def test_on_failure_emits_failed_with_reason():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="settlement-svc")
    await hook.on_failure(_delivery(), "sqs", error=ValueError("pool exhausted"))
    env = sink.events[0]
    assert env.status == EventStatus.FAILED
    assert env.failure_reason == "pool exhausted"
    assert env.failure_class == "ValueError"


async def test_on_retry_emits_retrying():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    await hook.on_retry(_delivery(), "sqs", errors=[RuntimeError("timeout")])
    env = sink.events[0]
    assert env.status == EventStatus.RETRYING
    assert env.failure_class == "RuntimeError"


async def test_broker_override_and_payload_suppression():
    sink = ListSink()
    hook = TelemetryDispatchHook(
        sink, source_service="svc", broker="kafka", include_payload=False
    )
    await hook.on_complete(_delivery(), "sqs", duration_ms=1.0)
    env = sink.events[0]
    assert env.broker == "kafka"
    assert env.payload is None


async def test_event_type_falls_back_to_consumer_name():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    # An event with no type falls back to the transport/consumer name.
    await hook.on_complete(_delivery(id="m", type="", data={}), "sqs", duration_ms=1.0)
    assert sink.events[0].event_type == "sqs"


async def test_idempotency_key_from_event():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    # idempotency_key on the event surfaces as the envelope's dedup key.
    await hook.on_complete(
        _delivery(idempotency_key="BK-1:Created"), "sqs", duration_ms=1.0
    )
    assert sink.events[0].idempotency_key == "BK-1:Created"


async def test_sink_failure_never_breaks_dispatch():
    class BoomSink(TelemetrySink):
        async def emit(self, envelope) -> None:
            raise RuntimeError("sink down")

    hook = TelemetryDispatchHook(BoomSink(), source_service="svc")
    await hook.on_complete(_delivery(), "sqs", duration_ms=1.0)  # must not raise
