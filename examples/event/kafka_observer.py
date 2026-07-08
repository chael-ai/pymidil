"""Observe an EXISTING Kafka consumer with Midil — zero refactor.

This is the integration story for a team that already runs its own consumers
and will not rewrite them onto pymidil's ``EventConsumer``. Their aiokafka
loop stays exactly as it is; Midil is added by wrapping the handler:

    observe = ConsumerObserver(
        observatory_url=OBSERVATORY_URL, consumer="orders-worker", broker="kafka",
    )
    ...
    async with observe(delivery_id, "OrderPlaced", headers=record.headers):
        await handle_order(record)          # ← their code, untouched

Those three lines buy, per delivery: a telemetry envelope (success / retrying /
failed / dlq) identical to what a pymidil-managed consumer emits, wall-clock
processing time, W3C trace continuity from the Kafka headers (the lineage
graph's cross-service edges), and — via ``observe.control`` — pause / throttle
/ drain from the Observatory console.

``broker="kafka"`` is *data*, not code: pointing the same observer at a
RabbitMQ or Pulsar loop is a one-string change.

The seeder shows the produce-side twin, ``ProducerObserver`` — three more lines
around their ``send_and_wait`` that emit the *produced* leg, so the trace graph
gets its ingress node (checkout-gateway → orders-worker) and publish failures
become observable/alertable.

Run:
    # 1. Kafka (Redpanda is the quickest single-node broker):
    #    docker run -d -p 9092:9092 redpandadata/redpanda:latest \
    #        redpanda start --overprovisioned --smp 1 --memory 512M \
    #        --kafka-addr PLAINTEXT://0.0.0.0:9092 \
    #        --advertise-kafka-addr PLAINTEXT://127.0.0.1:9092
    # 2. Observatory:  uvicorn observatory.asgi:app --port 8080
    # 3. pip install aiokafka
    # 4. python examples/event/kafka_observer.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import signal
import uuid

from loguru import logger
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pymidil.event import ConsumerObserver, EventStatus, ProducerObserver
from pymidil.event.otel import configure_tracing

try:  # aiokafka is the team's dependency, not pymidil's
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
except ImportError:  # pragma: no cover
    AIOKafkaConsumer = AIOKafkaProducer = TopicPartition = None

KAFKA = os.getenv("KAFKA_BOOTSTRAP", "127.0.0.1:9092")
OBSERVATORY_URL = os.getenv("OBSERVATORY_URL", "http://127.0.0.1:8080")
TOPIC = os.getenv("DEMO_TOPIC", "orders")


# ---------------------------------------------------------------------------
# The team's EXISTING code — nothing below this banner knows about Midil.
# ---------------------------------------------------------------------------


class TransientBackendError(Exception):
    """The team's own retryable failure (their backend was busy)."""


async def handle_order(record) -> None:
    """Their existing business logic, verbatim — including their own parsing,
    so a poison (non-JSON) message fails *inside* the observed block and is
    recorded instead of silently vanishing."""
    order = json.loads(record.value)
    await asyncio.sleep(random.uniform(0.02, 0.1))
    if order and random.random() < 0.15:
        raise TransientBackendError("inventory backend busy")


# ---------------------------------------------------------------------------
# The Midil integration — everything the team actually adds.
# ---------------------------------------------------------------------------


def classify(exc: BaseException) -> EventStatus:
    """Their exception vocabulary → Midil statuses. Optional: without it, any
    exception records the honest default, ``failed``. The mapping must tell the
    truth about what the loop below actually does: transient errors really are
    redelivered (seek-based retry), so ``retrying`` is accurate."""
    if isinstance(exc, TransientBackendError):
        return EventStatus.RETRYING
    return EventStatus.FAILED


async def consume(stop: asyncio.Event) -> None:
    observe = ConsumerObserver(
        observatory_url=OBSERVATORY_URL,
        consumer="orders-worker",
        broker="kafka",
        classify=classify,
    )
    # Manual commits: at-least-once. With auto-commit a failed record's offset
    # would be committed behind our back and the "retry" would never happen.
    consumer = AIOKafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA,
        group_id="orders-worker",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    logger.info("orders-worker consuming '{}' — telemetry → {}", TOPIC, OBSERVATORY_URL)

    attempts: dict[str, int] = {}  # delivery id → attempt number (for telemetry)

    async def process(record) -> bool:
        """One delivery. Returns True when the loop must rewind to this record
        (transient failure → Kafka-native retry via seek)."""
        delivery_id = f"{record.topic}/{record.partition}/{record.offset}"
        attempt = attempts.get(delivery_id, 0) + 1
        attempts[delivery_id] = attempt
        try:
            # ---- the Midil integration: three lines ------------------------
            async with observe(
                delivery_id,
                "OrderPlaced",
                headers=record.headers,  # traceparent rides in here
                payload=record.value.decode("utf-8", "replace"),
                attempts=attempt,
            ):
                await handle_order(record)  # their code, untouched
            # -----------------------------------------------------------------
        except TransientBackendError:
            # Genuine redelivery: rewind to the failed record and don't commit —
            # Kafka re-serves it, so the RETRYING envelope above is the truth.
            consumer.seek(TopicPartition(record.topic, record.partition), record.offset)
            return True
        except Exception:
            # Terminal (e.g. poison message) — the observer already recorded the
            # failure; park/skip per your own policy and move on.
            logger.warning("terminal failure for {} — recorded, skipping", delivery_id)
        attempts.pop(delivery_id, None)
        return False

    try:
        while not stop.is_set():
            # Honour the console: Pause/Throttle/Drain on the Consumers page.
            control = await observe.control.get()
            if not control.state.should_pull:
                await asyncio.sleep(1.0)
                continue

            batches = await consumer.getmany(timeout_ms=1000, max_records=10)
            rewound = False
            for records in batches.values():
                for record in records:
                    if await process(record):
                        rewound = True
                        break
                if rewound:
                    break
            if batches and not rewound:
                await consumer.commit()
    finally:
        # Close independently — a failing consumer.stop() must not leak the
        # observer's HTTP client.
        try:
            await consumer.stop()
        finally:
            await observe.aclose()


async def seed_orders(stop: asyncio.Event) -> None:
    """Stand-in for the team's upstream producer — observed with the produce-side
    twin. ``pub.headers`` carries the trace context onto the wire; ``pub.sent``
    records the delivery id so the produced record groups with the consumer's
    records and the trace graph draws the ingress edge (checkout-gateway →
    orders-worker) instead of a floating node."""
    publish = ProducerObserver(
        observatory_url=OBSERVATORY_URL,
        source_service="checkout-gateway",
        broker="kafka",
    )
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA)
    await producer.start()
    try:
        while not stop.is_set():
            order = {"order_id": f"OD-{uuid.uuid4().hex[:6].upper()}"}
            # ---- the Midil integration: three lines, produce side ----------
            async with publish(
                "OrderPlaced",
                destination=TOPIC,
                payload=order,
                idempotency_key=f"{order['order_id']}:OrderPlaced",
            ) as pub:
                md = await producer.send_and_wait(  # their producer, untouched
                    TOPIC,
                    json.dumps(order).encode(),
                    headers=[(k, v.encode()) for k, v in pub.headers.items()],
                )
                pub.sent(f"{TOPIC}/{md.partition}/{md.offset}")
            # -----------------------------------------------------------------
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.7)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await producer.stop()
        finally:
            await publish.aclose()


async def main() -> None:
    if AIOKafkaConsumer is None:
        raise SystemExit("this example needs aiokafka:  pip install aiokafka")
    configure_tracing(
        service_name="kafka-observer-demo", exporter=InMemorySpanExporter()
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await asyncio.gather(seed_orders(stop), consume(stop))
    logger.info("Shut down cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
