"""Idempotency + DLQ telemetry (A3 + A4).

Run: python examples/event/idempotency_dlq.py

Shows, without any broker, how:
  * consumer-level idempotency short-circuits a re-delivery (A3) — for any
    subscriber type — and the emitter reports it as `duplicate` via on_duplicate,
  * the on_dead_letter hook produces `dlq` telemetry (A4).
"""

import asyncio

from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.idempotency import IdempotencyPolicy, InMemoryIdempotencyStore
from pymidil.event.message import Message
from pymidil.event.observability import StdoutTelemetrySink, TelemetryDispatchHook
from pymidil.event.subscriber.base import FunctionSubscriber


class InMemoryConsumer(EventConsumer):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def ack(self, message: Message) -> None:
        ...

    async def nack(self, message: Message, requeue: bool = False) -> None:
        ...


class _Config(BaseConsumerConfig):
    type: str = "booking-svc"


async def handle(event: Message) -> None:
    print(f"  handled {event.id}")


async def main() -> None:
    hook = TelemetryDispatchHook(
        StdoutTelemetrySink(), source_service="booking-svc", broker="sqs"
    )
    consumer = InMemoryConsumer(_Config())
    consumer.subscribe(FunctionSubscriber(handler=handle))
    consumer.add_hook(hook)
    consumer.use_idempotency(IdempotencyPolicy(InMemoryIdempotencyStore()))

    key = "BK-1:PaymentAuthorized"
    print("dispatch original:")
    await consumer.dispatch(
        Message(id="EVT-1", body={"amt": 50}, idempotency_key=key)
    )  # success
    print("dispatch re-delivery (same key):")
    await consumer.dispatch(
        Message(id="EVT-2", body={"amt": 50}, idempotency_key=key)
    )  # duplicate

    print("dead-letter:")
    await hook.on_dead_letter(
        Message(
            id="EVT-3",
            body={"tx": "TX-9"},
            metadata={"event_type": "SettlementInitiated"},
        ),
        "sqs",
        error=RuntimeError("retries exhausted"),
    )  # dlq


if __name__ == "__main__":
    asyncio.run(main())
