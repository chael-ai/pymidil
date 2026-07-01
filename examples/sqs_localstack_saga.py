"""Live booking-saga demo on LocalStack SQS, feeding the Midil Observatory.

A real, multi-service event flow — no seeding. Each service is a pymidil
``SQSConsumer`` with its own queue (+ DLQ), wired to:

  * the telemetry emitter  -> POSTs envelopes to the Observatory ingestion API
  * OpenTelemetry tracing  -> traceparent rides SQS attributes, so one booking
                              produces ONE trace spanning every hop
  * idempotency            -> duplicate deliveries are short-circuited

Flow:  BookingCreated -> PaymentAuthorized -> ShipmentCreated -> EmailSent
The terminal ``email-worker`` throttles (SMTP 421): some bookings retry a few
times and then dead-letter, the rest succeed — so the console shows live
success / retrying / dlq / duplicate, real traces, and a populated DLQ.

Run:
    # 1. LocalStack:   docker run -d -p 127.0.0.1:4566:4566 -e SERVICES=sqs localstack/localstack:3
    # 2. Observatory:  OBSERVATORY_STORAGE_BACKEND=mongodb uvicorn observatory.asgi:app --port 8080
    # 3. this:         python examples/sqs_localstack_saga.py
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

# service, source-queue, incoming-type, next-type, next-queue
FLOW = [
    (
        "booking-svc",
        "q-booking-created",
        "BookingCreated",
        "PaymentAuthorized",
        "q-payment-authorized",
    ),
    (
        "payment-svc",
        "q-payment-authorized",
        "PaymentAuthorized",
        "ShipmentCreated",
        "q-shipment-created",
    ),
    (
        "shipment-svc",
        "q-shipment-created",
        "ShipmentCreated",
        "EmailSent",
        "q-email-sent",
    ),
    ("email-worker", "q-email-sent", "EmailSent", None, None),
]
EMAIL_DLQ = "q-email-sent-dlq"


def _attr(value):
    """Coerce an SQS MessageAttribute / plain value to a flat string."""
    if isinstance(value, dict):
        return value.get("StringValue") or value.get("stringValue")
    return value if value is None else str(value)


def idempotency_key(message):
    """Dedup on the logical key carried in the message, not the per-delivery id."""
    md = getattr(message, "metadata", {}) or {}
    key = _attr(md.get("idempotency_key"))
    return key or str(getattr(message, "id", ""))


def create_queues() -> dict[str, str]:
    """Create every queue (idempotent) and return name -> URL."""
    sqs = boto3.client(
        "sqs",
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    names = [src for _, src, *_ in FLOW] + [EMAIL_DLQ]
    urls = {name: sqs.create_queue(QueueName=name)["QueueUrl"] for name in names}
    logger.info("Created {} SQS queues on LocalStack", len(urls))
    return urls


def make_handler(name, next_type, next_producer):
    async def handler(message):
        body = message.body if isinstance(message.body, dict) else {}
        booking = body.get("booking_id", "BK-?")
        await asyncio.sleep(random.uniform(0.02, 0.18))  # simulate work

        # Terminal hop: the mail provider throttles (SMTP 421).
        if name == "email-worker":
            doomed = (hash(booking) % 100) < 35  # ~35% of bookings are throttled
            if doomed:
                received = int(
                    _attr((message.metadata or {}).get("ApproximateReceiveCount"))
                    or "1"
                )
                if received < 4:
                    raise RetryableEventError(
                        f"SMTP 421 — upstream throttled (attempt {received})"
                    )
                raise RuntimeError("SMTP 421 — max retries exhausted, dead-lettering")
            return  # delivered

        # Otherwise advance the saga to the next service.
        nxt = f"{booking}:{next_type}"
        await next_producer.publish(
            {"booking_id": booking, "event_type": next_type},
            metadata={"event_type": next_type, "idempotency_key": nxt},
        )

    return handler


def build_services(session, urls):
    consumers = []
    for name, src, _in_type, next_type, next_queue in FLOW:
        cfg = SQSConsumerEventConfig(
            type="sqs",
            queue_url=urls[src],
            dlq_url=urls[EMAIL_DLQ] if name == "email-worker" else None,
            endpoint_url=ENDPOINT,
            aws_region=REGION,
            wait_time_seconds=1,
            visibility_timeout=10,
            max_number_of_messages=10,
            poll_interval=0.2,
            backoff_base_delay=1,
            backoff_max_delay=8,
        )
        consumer = SQSConsumer(cfg, session=session)
        consumer.add_hook(
            TelemetryDispatchHook(
                HttpTelemetrySink(OBSERVATORY_URL), source_service=name, broker="sqs"
            )
        )
        consumer.use_idempotency(
            IdempotencyPolicy(InMemoryIdempotencyStore(), key_fn=idempotency_key)
        )
        next_producer = None
        if next_queue:
            next_producer = SQSProducer(
                SQSProducerEventConfig(
                    type="sqs",
                    queue_url=urls[next_queue],
                    endpoint_url=ENDPOINT,
                    aws_region=REGION,
                ),
                session=session,
            )
            # Producer telemetry: this service's publish of the next event is
            # recorded as a `producer`-kind observation, so a message's lifecycle
            # reads produced → consumed → … in the Event Detail view.
            next_producer.add_hook(
                TelemetryProducerHook(
                    HttpTelemetrySink(OBSERVATORY_URL),
                    source_service=name,
                    broker="sqs",
                )
            )
        consumer.subscribe(
            FunctionSubscriber(handler=make_handler(name, next_type, next_producer))
        )
        consumers.append(consumer)
    return consumers


async def driver(session, booking_queue_url, stop: asyncio.Event):
    """Continuously emit BookingCreated, occasionally a duplicate."""
    producer = SQSProducer(
        SQSProducerEventConfig(
            type="sqs",
            queue_url=booking_queue_url,
            endpoint_url=ENDPOINT,
            aws_region=REGION,
        ),
        session=session,
    )
    producer.add_hook(
        TelemetryProducerHook(
            HttpTelemetrySink(OBSERVATORY_URL),
            source_service="booking-gateway",
            broker="sqs",
        )
    )
    n = 0
    while not stop.is_set():
        booking = f"BK-{uuid.uuid4().hex[:6].upper()}"
        key = f"{booking}:BookingCreated"
        payload = {"booking_id": booking, "event_type": "BookingCreated"}
        meta = {"event_type": "BookingCreated", "idempotency_key": key}
        await producer.publish(payload, metadata=meta)
        n += 1
        if random.random() < 0.2:  # ~20% re-delivered (idempotency should catch it)
            await producer.publish(payload, metadata=meta)
        if n % 10 == 0:
            logger.info("driver: emitted {} bookings", n)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0 / RATE_PER_SEC)
        except asyncio.TimeoutError:
            pass


async def main():
    configure_tracing(service_name="midil-demo", exporter=InMemorySpanExporter())
    session = aioboto3.Session(
        aws_access_key_id="test", aws_secret_access_key="test", region_name=REGION
    )
    urls = create_queues()
    consumers = build_services(session, urls)

    for c in consumers:
        await c.start()
    logger.info(
        "Started {} consumers — saga is live. Telemetry -> {}",
        len(consumers),
        OBSERVATORY_URL,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    drive = asyncio.create_task(driver(session, urls["q-booking-created"], stop))
    await stop.wait()

    logger.info("Shutting down…")
    drive.cancel()
    for c in consumers:
        await c.stop()


if __name__ == "__main__":
    asyncio.run(main())
