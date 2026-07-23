import pytest

from pymidil.event.message import Message
from pymidil.event.observability import EventStatus, TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.otel import current_span_ids, get_tracer

pytestmark = pytest.mark.anyio


class ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, envelope) -> None:
        self.events.append(envelope)


def _msg(**overrides) -> Message:
    base = dict(
        id="EVT-1",
        body={"booking_id": "BK-1"},
        metadata={"event_type": "BookingCreated"},
    )
    base.update(overrides)
    return Message(**base)


async def test_on_complete_emits_success_with_trace():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="booking-svc")

    # Nested spans so the envelope can be checked for trace/span/parent ids.
    with get_tracer().start_as_current_span("parent"):
        _, parent_span_id, _ = current_span_ids()
        with get_tracer().start_as_current_span("child"):
            trace_id, span_id, _ = current_span_ids()
            await hook.on_complete(_msg(), "sqs", duration_ms=12.5)

    assert len(sink.events) == 1
    env = sink.events[0]
    assert env.status == EventStatus.SUCCESS
    assert env.message_id == "EVT-1"
    assert env.event_type == "BookingCreated"
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
    await hook.on_failure(_msg(), "sqs", error=ValueError("pool exhausted"))
    env = sink.events[0]
    assert env.status == EventStatus.FAILED
    assert env.failure_reason == "pool exhausted"
    assert env.failure_class == "ValueError"


async def test_on_retry_emits_retrying():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    await hook.on_retry(_msg(), "sqs", errors=[RuntimeError("timeout")])
    env = sink.events[0]
    assert env.status == EventStatus.RETRYING
    assert env.failure_class == "RuntimeError"


async def test_broker_override_and_payload_suppression():
    sink = ListSink()
    hook = TelemetryDispatchHook(
        sink, source_service="svc", broker="kafka", include_payload=False
    )
    await hook.on_complete(_msg(), "sqs", duration_ms=1.0)
    env = sink.events[0]
    assert env.broker == "kafka"
    assert env.payload is None


async def test_event_type_falls_back_to_consumer_name():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    await hook.on_complete(Message(id="m", body={}), "sqs", duration_ms=1.0)
    assert sink.events[0].event_type == "sqs"


async def test_idempotency_key_from_metadata():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    await hook.on_complete(
        _msg(metadata={"idempotency_key": "BK-1:Created"}), "sqs", duration_ms=1.0
    )
    assert sink.events[0].idempotency_key == "BK-1:Created"


async def test_sink_failure_never_breaks_dispatch():
    class BoomSink(TelemetrySink):
        async def emit(self, envelope) -> None:
            raise RuntimeError("sink down")

    hook = TelemetryDispatchHook(BoomSink(), source_service="svc")
    await hook.on_complete(_msg(), "sqs", duration_ms=1.0)  # must not raise
