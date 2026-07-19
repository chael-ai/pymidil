"""Wiring — the demo's composition root.

Turns configuration + subscribers into *running services*. Each consumer is
assembled from four independent concerns, kept separate on purpose:

    transport   — an SQSConsumer bound to a queue
    telemetry   — a TelemetryDispatchHook streaming lifecycle to the Observatory
    idempotency — an IdempotencyPolicy so redeliveries don't double-process
    behaviour   — the EventSubscriber that actually handles the event

Producers get the transport + a TelemetryProducerHook (the "emitted" leg of the
trace). This module knows nothing about *how* events are handled — that's the
subscribers' job — only how the pieces snap together.
"""

from __future__ import annotations

from typing import Sequence

from pymidil.event import (
    SQSConsumer,
    SQSConsumerEventConfig,
    SQSProducer,
    SQSProducerEventConfig,
    TelemetryDispatchHook,
    TelemetryProducerHook,
)
from pymidil.event.idempotency import IdempotencyPolicy, InMemoryIdempotencyStore
from pymidil.event.observability.sinks.http import HttpTelemetrySink

from .messages import idempotency_key
from .settings import BRANCHES, LOYALTY_DLQ, ORDER_SERVICE, SOURCE_QUEUE, Settings
from .subscribers import FlakyLoyaltySubscriber, LeafSubscriber, OrderSubscriber


def _consumer_config(
    s: Settings, queue_url: str, *, dlq_url: str | None = None
) -> SQSConsumerEventConfig:
    return SQSConsumerEventConfig(
        type="sqs",
        queue_url=queue_url,
        dlq_url=dlq_url,
        endpoint_url=s.endpoint_url,
        aws_region=s.region,
        wait_time_seconds=1,
        visibility_timeout=8,
        max_number_of_messages=10,
        poll_interval=0.2,
        backoff_base_delay=1,
        backoff_max_delay=6,
    )


def _sink(s: Settings) -> HttpTelemetrySink:
    return HttpTelemetrySink(s.observatory_url, api_key=s.observatory_api_key)


def dispatch_telemetry(s: Settings, service: str) -> TelemetryDispatchHook:
    """The consumer-side telemetry leg — one row per dispatch outcome."""
    return TelemetryDispatchHook(_sink(s), source_service=service, broker="sqs")


def producer_telemetry(s: Settings, service: str) -> TelemetryProducerHook:
    """The producer-side telemetry leg — the "emitted" step of the trace."""
    return TelemetryProducerHook(_sink(s), source_service=service, broker="sqs")


def _idempotency() -> IdempotencyPolicy:
    return IdempotencyPolicy(InMemoryIdempotencyStore(), key_fn=idempotency_key)


def build_branch_producers(
    s: Settings, session, urls: dict[str, str]
) -> list[tuple[str, SQSProducer]]:
    """order-svc's outbound side: one producer per branch, each emitting producer
    telemetry *as* order-svc (so the fan-out edges are attributed to it)."""
    producers: list[tuple[str, SQSProducer]] = []
    for branch in BRANCHES:
        producer = SQSProducer(
            SQSProducerEventConfig(
                type="sqs",
                queue_url=urls[branch.queue],
                endpoint_url=s.endpoint_url,
                aws_region=s.region,
            ),
            session=session,
        )
        producer.add_hook(producer_telemetry(s, ORDER_SERVICE))
        producers.append((branch.event_type, producer))
    return producers


def build_order_consumer(
    s: Settings,
    session,
    urls: dict[str, str],
    branch_producers: Sequence[tuple[str, SQSProducer]],
) -> SQSConsumer:
    """order-svc: consumes OrderPaid and fans it out through ``branch_producers``."""
    consumer = SQSConsumer(_consumer_config(s, urls[SOURCE_QUEUE]), session=session)
    consumer.add_hook(dispatch_telemetry(s, ORDER_SERVICE))
    consumer.use_idempotency(_idempotency())
    consumer.subscribe(OrderSubscriber(branch_producers))
    return consumer


def build_leaf_consumers(
    s: Settings, session, urls: dict[str, str]
) -> list[SQSConsumer]:
    """The four downstream branch consumers. The flaky one gets a DLQ + the
    ``FlakyLoyaltySubscriber``; the rest are plain ``LeafSubscriber``s."""
    consumers: list[SQSConsumer] = []
    for branch in BRANCHES:
        dlq_url = urls[LOYALTY_DLQ] if branch.flaky else None
        consumer = SQSConsumer(
            _consumer_config(s, urls[branch.queue], dlq_url=dlq_url), session=session
        )
        consumer.add_hook(dispatch_telemetry(s, branch.service))
        consumer.use_idempotency(_idempotency())
        subscriber = (
            FlakyLoyaltySubscriber(branch.service)
            if branch.flaky
            else LeafSubscriber(branch.service)
        )
        consumer.subscribe(subscriber)
        consumers.append(consumer)
    return consumers
