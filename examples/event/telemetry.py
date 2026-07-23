"""Telemetry + trace propagation (A1 + A2) over OpenTelemetry.

Run: python examples/event/telemetry.py

Shows, without any broker, how:
  * a producer injects the active OTel trace into a carrier,
  * a consumer continues it via carrier() + a CONSUMER span (no Message field),
  * the TelemetryDispatchHook emits a correlated envelope.
"""

import asyncio

from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.message import Message
from pymidil.event.observability import StdoutTelemetrySink, TelemetryDispatchHook
from pymidil.event.otel import (
    configure_tracing,
    current_span_ids,
    inject_headers,
    producer_span,
)
from pymidil.event.subscriber.base import FunctionSubscriber


class InMemoryConsumer(EventConsumer):
    """A trivial consumer; its carrier is the message metadata."""

    def carrier(self, message: Message):
        return getattr(message, "metadata", {}) or {}

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...


class _Config(BaseConsumerConfig):
    type: str = "memory"


async def handle(event: Message) -> None:
    trace_id, span_id, parent = current_span_ids()
    print(
        f"  handler sees trace={trace_id[:8] if trace_id else None} "
        f"span={span_id[:8] if span_id else None} "
        f"parent={parent[:8] if parent else None}"
    )


async def main() -> None:
    configure_tracing(service_name="booking-svc")  # opt-in OTel SDK

    # --- producer side: inject the active trace into the carrier ---
    outgoing: dict = {"event_type": "BookingCreated"}
    with producer_span("orders"):
        inject_headers(outgoing)
        trace_id, span_id, _ = current_span_ids()
    print(f"published trace={trace_id[:8]} span={span_id[:8]}")

    # --- consumer side: continue the trace + emit telemetry ---
    consumer = InMemoryConsumer(_Config())
    consumer.subscribe(FunctionSubscriber(handler=handle))
    consumer.add_hook(
        TelemetryDispatchHook(
            StdoutTelemetrySink(), source_service="booking-svc", broker="sqs"
        )
    )

    incoming = Message(id="EVT-1", body={"booking_id": "BK-44821"}, metadata=outgoing)
    await consumer.dispatch(incoming)


if __name__ == "__main__":
    asyncio.run(main())
