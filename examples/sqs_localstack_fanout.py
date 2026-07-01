"""Fan-out demo on LocalStack SQS, feeding the Midil Observatory.

A practical event-driven pattern: once an order is paid, several *independent*
things must happen in parallel. ``order-svc`` consumes one ``OrderPaid`` event
and **fans it out** into four events, each handled by its own service:

    OrderPaid ─┬─▶ ShipmentRequested  → shipping-svc
               ├─▶ InvoiceIssued      → billing-svc
               ├─▶ PointsAwarded      → loyalty-svc   (flaky: sometimes dead-letters)
               └─▶ ReceiptEmailed     → receipt-svc

One order = one trace whose graph branches one-into-four — the shape a lineage
graph shows at a glance and a flat list can't. The loyalty branch throttles now
and then, so some traces show three green branches and one red — "paid and
shipped, but loyalty points failed," visible in a single picture.

Run:
    # 1. LocalStack:   docker run -d -p 127.0.0.1:4566:4566 -e SERVICES=sqs localstack/localstack:3
    # 2. Observatory:  uvicorn observatory.asgi:app --port 8080
    # 3. this:         python examples/sqs_localstack_fanout.py
"""

from __future__ import annotations

import asyncio
import os
import random
import signal
import uuid

import aioboto3
import boto3
from loguru import logger
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pymidil.event import (
    FunctionSubscriber,
    SQSConsumer,
    SQSConsumerEventConfig,
    SQSProducer,
    SQSProducerEventConfig,
    TelemetryDispatchHook,
    TelemetryProducerHook,
)
from pymidil.event.idempotency import IdempotencyPolicy, InMemoryIdempotencyStore
from pymidil.event.observability.sinks.http import HttpTelemetrySink
from pymidil.event.otel import configure_tracing
from pymidil.exceptions import RetryableEventError

ENDPOINT = os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
OBSERVATORY_URL = os.getenv("OBSERVATORY_URL", "http://127.0.0.1:8080")
RATE_PER_SEC = float(os.getenv("DEMO_RATE", "1.5"))

SOURCE_QUEUE = "q-order-paid"
# event_type, queue, consuming service, flaky?
FANOUT = [
    ("ShipmentRequested", "q-ship", "shipping-svc", False),
    ("InvoiceIssued", "q-invoice", "billing-svc", False),
    ("PointsAwarded", "q-loyalty", "loyalty-svc", True),
    ("ReceiptEmailed", "q-receipt", "receipt-svc", False),
]
LOYALTY_DLQ = "q-loyalty-dlq"


def _attr(value):
    if isinstance(value, dict):
        return value.get("StringValue") or value.get("stringValue")
    return value if value is None else str(value)


def idempotency_key(message):
    md = getattr(message, "metadata", {}) or {}
    return _attr(md.get("idempotency_key")) or str(getattr(message, "id", ""))


def create_queues() -> dict[str, str]:
    sqs = boto3.client(
        "sqs",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    names = [SOURCE_QUEUE, LOYALTY_DLQ] + [q for _, q, _, _ in FANOUT]
    urls = {n: sqs.create_queue(QueueName=n)["QueueUrl"] for n in names}
    logger.info("Created {} SQS queues on LocalStack", len(urls))
    return urls


def order_handler(fanout_producers):
    """order-svc: one OrderPaid in → four events out (the fan-out)."""

    async def handler(message):
        body = message.body if isinstance(message.body, dict) else {}
        order = body.get("order_id", "OD-?")
        await asyncio.sleep(random.uniform(0.02, 0.12))
        for event_type, producer in fanout_producers:
            await producer.publish(
                {"order_id": order, "event_type": event_type},
                metadata={
                    "event_type": event_type,
                    "idempotency_key": f"{order}:{event_type}",
                },
            )

    return handler


def leaf_handler(service: str, flaky: bool):
    """A downstream branch: do the work; the flaky one throttles then dead-letters."""

    async def handler(message):
        body = message.body if isinstance(message.body, dict) else {}
        order = body.get("order_id", "OD-?")
        await asyncio.sleep(random.uniform(0.02, 0.15))
        if flaky and (hash(order) % 100) < 30:
            received = int(
                _attr((message.metadata or {}).get("ApproximateReceiveCount")) or "1"
            )
            if received < 3:
                raise RetryableEventError(f"loyalty backend busy (attempt {received})")
            raise RuntimeError("loyalty backend unavailable — giving up")

    return handler


def build_services(session, urls):
    consumers = []

    # Downstream branch consumers.
    for event_type, queue, service, flaky in FANOUT:
        cfg = SQSConsumerEventConfig(
            type="sqs",
            queue_url=urls[queue],
            dlq_url=urls[LOYALTY_DLQ] if flaky else None,
            endpoint_url=ENDPOINT,
            aws_region=REGION,
            wait_time_seconds=1,
            visibility_timeout=8,
            max_number_of_messages=10,
            poll_interval=0.2,
            backoff_base_delay=1,
            backoff_max_delay=6,
        )
        consumer = SQSConsumer(cfg, session=session)
        consumer.add_hook(
            TelemetryDispatchHook(
                HttpTelemetrySink(OBSERVATORY_URL), source_service=service, broker="sqs"
            )
        )
        consumer.use_idempotency(
            IdempotencyPolicy(InMemoryIdempotencyStore(), key_fn=idempotency_key)
        )
        consumer.subscribe(FunctionSubscriber(handler=leaf_handler(service, flaky)))
        consumers.append(consumer)

    # order-svc: one producer per fan-out branch, each emitting producer telemetry.
    fanout_producers = []
    for event_type, queue, _service, _flaky in FANOUT:
        producer = SQSProducer(
            SQSProducerEventConfig(
                type="sqs",
                queue_url=urls[queue],
                endpoint_url=ENDPOINT,
                aws_region=REGION,
            ),
            session=session,
        )
        producer.add_hook(
            TelemetryProducerHook(
                HttpTelemetrySink(OBSERVATORY_URL),
                source_service="order-svc",
                broker="sqs",
            )
        )
        fanout_producers.append((event_type, producer))

    order_cfg = SQSConsumerEventConfig(
        type="sqs",
        queue_url=urls[SOURCE_QUEUE],
        endpoint_url=ENDPOINT,
        aws_region=REGION,
        wait_time_seconds=1,
        visibility_timeout=8,
        max_number_of_messages=10,
        poll_interval=0.2,
    )
    order_svc = SQSConsumer(order_cfg, session=session)
    order_svc.add_hook(
        TelemetryDispatchHook(
            HttpTelemetrySink(OBSERVATORY_URL), source_service="order-svc", broker="sqs"
        )
    )
    order_svc.use_idempotency(
        IdempotencyPolicy(InMemoryIdempotencyStore(), key_fn=idempotency_key)
    )
    order_svc.subscribe(FunctionSubscriber(handler=order_handler(fanout_producers)))
    consumers.append(order_svc)
    return consumers


async def driver(session, source_url, stop: asyncio.Event):
    """The ingress: emit OrderPaid (booking-gateway-style origin)."""
    producer = SQSProducer(
        SQSProducerEventConfig(
            type="sqs", queue_url=source_url, endpoint_url=ENDPOINT, aws_region=REGION
        ),
        session=session,
    )
    producer.add_hook(
        TelemetryProducerHook(
            HttpTelemetrySink(OBSERVATORY_URL),
            source_service="checkout-gateway",
            broker="sqs",
        )
    )
    n = 0
    while not stop.is_set():
        order = f"OD-{uuid.uuid4().hex[:6].upper()}"
        await producer.publish(
            {"order_id": order, "event_type": "OrderPaid"},
            metadata={
                "event_type": "OrderPaid",
                "idempotency_key": f"{order}:OrderPaid",
            },
        )
        n += 1
        if n % 10 == 0:
            logger.info("driver: emitted {} orders", n)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0 / RATE_PER_SEC)
        except asyncio.TimeoutError:
            pass


async def main():
    configure_tracing(service_name="midil-fanout", exporter=InMemorySpanExporter())
    session = aioboto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name=REGION
    )
    urls = create_queues()
    consumers = build_services(session, urls)
    for c in consumers:
        await c.start()
    logger.info(
        "Fan-out demo live — OrderPaid → 4 branches. Telemetry → {}", OBSERVATORY_URL
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    drive = asyncio.create_task(driver(session, urls[SOURCE_QUEUE], stop))
    await stop.wait()

    logger.info("Shutting down…")
    drive.cancel()
    for c in consumers:
        await c.stop()


if __name__ == "__main__":
    asyncio.run(main())
