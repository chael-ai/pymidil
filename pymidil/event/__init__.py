"""Event package public API.

Heavy optional transports (SQS, Redis, webhook/FastAPI) are loaded lazily so
``import pymidil.event.observability`` works without installing every extra.
"""

from __future__ import annotations

from typing import Any

# Eager: small, always-useful surfaces with no optional deps.
from pymidil.event.exceptions import (
    BaseEventError,
    ConsumerCrashError,
    ConsumerError,
    ConsumerNotImplementedError,
    ConsumerStartError,
    NonRetryableEventError,
    ProducerError,
    ProducerNotImplementedError,
    RetryableEventError,
    TransportNotImplementedError,
)
from pymidil.event.context import EventContext, event_context, get_current_event
from pymidil.event.message import Message
from pymidil.event.acknowledgement import Acknowledger

__all__ = [
    # event bus
    "EventBus",
    # message
    "Message",
    # Producers
    "SQSProducer",
    "SQSProducerEventConfig",
    "BaseProducerConfig",
    "RedisProducer",
    "RedisProducerEventConfig",
    # Consumers
    "EventConsumer",
    "BaseConsumerConfig",
    "PullEventConsumer",
    "PullEventConsumerConfig",
    "PushEventConsumer",
    "PushEventConsumerConfig",
    "SQSConsumer",
    "SQSConsumerEventConfig",
    "ConsumerMessage",
    # Subscribers and Middlewares
    "EventSubscriber",
    "FunctionSubscriber",
    "SubscriberMiddleware",
    "GroupMiddleware",
    "RetryMiddleware",
    # Context
    "EventContext",
    "get_current_event",
    "event_context",
    # Exceptions
    "ConsumerNotImplementedError",
    "ProducerNotImplementedError",
    "TransportNotImplementedError",
    "BaseEventError",
    "RetryableEventError",
    "NonRetryableEventError",
    "ConsumerStartError",
    "ConsumerCrashError",
    "ConsumerError",
    "ProducerError",
    # Observability extension points + telemetry (A2)
    "DispatchHook",
    "ProducerHook",
    "PublishRecord",
    "MessageProtocol",
    "TelemetryEnvelope",
    "EventStatus",
    "EventKind",
    "TelemetryDispatchHook",
    "ConsumerObserver",
    "ProducerObserver",
    "TelemetryProducerHook",
    "TelemetrySink",
    "TelemetrySettings",
    "attach_telemetry",
    "create_producer_observer",
    "create_consumer_observer",
    "observe_publish",
    "observe_consume",
    "clear_observer_caches",
    # Idempotency (A3)
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "IdempotencyPolicy",
    # Dead-letter operations (A4)
    "DlqRedriver",
    "SQSDlqRedriver",
    # Acknowledgement
    "Acknowledger",
]

_LAZY: dict[str, tuple[str, str]] = {
    "EventBus": ("pymidil.event.event_bus", "EventBus"),
    "SQSProducer": ("pymidil.event.producer.sqs", "SQSProducer"),
    "SQSProducerEventConfig": ("pymidil.event.producer.sqs", "SQSProducerEventConfig"),
    "BaseProducerConfig": ("pymidil.event.producer.base", "BaseProducerConfig"),
    "RedisProducer": ("pymidil.event.producer.redis", "RedisProducer"),
    "RedisProducerEventConfig": (
        "pymidil.event.producer.redis",
        "RedisProducerEventConfig",
    ),
    "EventConsumer": ("pymidil.event.consumer.strategies.base", "EventConsumer"),
    "BaseConsumerConfig": (
        "pymidil.event.consumer.strategies.base",
        "BaseConsumerConfig",
    ),
    "ConsumerMessage": ("pymidil.event.consumer.strategies.base", "ConsumerMessage"),
    "PullEventConsumer": (
        "pymidil.event.consumer.strategies.pull",
        "PullEventConsumer",
    ),
    "PullEventConsumerConfig": (
        "pymidil.event.consumer.strategies.pull",
        "PullEventConsumerConfig",
    ),
    "PushEventConsumer": (
        "pymidil.event.consumer.strategies.push",
        "PushEventConsumer",
    ),
    "PushEventConsumerConfig": (
        "pymidil.event.consumer.strategies.push",
        "PushEventConsumerConfig",
    ),
    "SQSConsumer": ("pymidil.event.consumer.sqs", "SQSConsumer"),
    "SQSConsumerEventConfig": (
        "pymidil.event.consumer.sqs",
        "SQSConsumerEventConfig",
    ),
    "EventSubscriber": ("pymidil.event.subscriber.base", "EventSubscriber"),
    "FunctionSubscriber": ("pymidil.event.subscriber.base", "FunctionSubscriber"),
    "SubscriberMiddleware": ("pymidil.event.subscriber.base", "SubscriberMiddleware"),
    "GroupMiddleware": ("pymidil.event.subscriber.middleware", "GroupMiddleware"),
    "RetryMiddleware": ("pymidil.event.subscriber.middleware", "RetryMiddleware"),
    "DispatchHook": ("pymidil.event.observability", "DispatchHook"),
    "ProducerHook": ("pymidil.event.observability", "ProducerHook"),
    "PublishRecord": ("pymidil.event.observability", "PublishRecord"),
    "MessageProtocol": ("pymidil.event.observability", "MessageProtocol"),
    "TelemetryEnvelope": ("pymidil.event.observability", "TelemetryEnvelope"),
    "EventStatus": ("pymidil.event.observability", "EventStatus"),
    "EventKind": ("pymidil.event.observability", "EventKind"),
    "TelemetryDispatchHook": ("pymidil.event.observability", "TelemetryDispatchHook"),
    "ConsumerObserver": ("pymidil.event.observability", "ConsumerObserver"),
    "ProducerObserver": ("pymidil.event.observability", "ProducerObserver"),
    "TelemetryProducerHook": ("pymidil.event.observability", "TelemetryProducerHook"),
    "TelemetrySink": ("pymidil.event.observability", "TelemetrySink"),
    "TelemetrySettings": ("pymidil.event.observability", "TelemetrySettings"),
    "attach_telemetry": ("pymidil.event.observability", "attach_telemetry"),
    "create_producer_observer": (
        "pymidil.event.observability",
        "create_producer_observer",
    ),
    "create_consumer_observer": (
        "pymidil.event.observability",
        "create_consumer_observer",
    ),
    "observe_publish": ("pymidil.event.observability", "observe_publish"),
    "observe_consume": ("pymidil.event.observability", "observe_consume"),
    "clear_observer_caches": (
        "pymidil.event.observability",
        "clear_observer_caches",
    ),
    "IdempotencyStore": ("pymidil.event.idempotency", "IdempotencyStore"),
    "InMemoryIdempotencyStore": (
        "pymidil.event.idempotency",
        "InMemoryIdempotencyStore",
    ),
    "RedisIdempotencyStore": ("pymidil.event.idempotency", "RedisIdempotencyStore"),
    "IdempotencyPolicy": ("pymidil.event.idempotency", "IdempotencyPolicy"),
    "DlqRedriver": ("pymidil.event.dlq", "DlqRedriver"),
    "SQSDlqRedriver": ("pymidil.event.dlq", "SQSDlqRedriver"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    from importlib import import_module

    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value
