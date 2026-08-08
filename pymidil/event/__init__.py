"""pymidil.event — the event platform: model, dispatch, transports, telemetry.

One-stop imports: ``from pymidil.event import Event, EventBus, SQSConsumer, …``.

The barrel is LAZY (PEP 562) for anything that needs an optional dependency:
``import pymidil.event`` costs only the core model and dispatch machinery
(stdlib + base deps). Transport/bus/observability names import on first
access — and a missing optional dependency raises an ImportError that names
the extra to install, instead of an opaque ModuleNotFoundError at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# ---- Eager: core model + policy + dispatch machinery (base deps only) --------
from pymidil.event.core import (
    Delivery,
    Event,
    NoAckDelivery,
    NoSettlement,
    Settlement,
)
from pymidil.event.retry import RetryConfig, RetryPolicyError, TransportCapabilities
from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from pymidil.event.producer.base import BaseProducerConfig, EventProducer
from pymidil.event.subscriber.base import (
    EventSubscriber,
    FunctionSubscriber,
    ManualSubscriber,
    SubscriberMiddleware,
)
from pymidil.event.subscriber.middleware import GroupMiddleware, LoggingMiddleware

# Event errors are defined once, at the package root (they subclass MidilError
# alongside the other domains' errors); re-exported here for handler ergonomics.
from pymidil.exceptions import (
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

# ---- Lazy: names that pull optional dependencies ------------------------------
#: name -> (module, extra that provides its dependencies, or None)
_LAZY: dict[str, tuple[str, str | None]] = {
    # bus (its factory wires every transport, so it needs their deps)
    "EventBus": ("pymidil.event.event_bus", "full"),
    # transports
    "SQSConsumer": ("pymidil.event.transports.sqs", "aws"),
    "SQSConsumerEventConfig": ("pymidil.event.transports.sqs", "aws"),
    "SQSDelivery": ("pymidil.event.transports.sqs", "aws"),
    "SQSSettlement": ("pymidil.event.transports.sqs", "aws"),
    "SQSProducer": ("pymidil.event.transports.sqs", "aws"),
    "SQSProducerEventConfig": ("pymidil.event.transports.sqs", "aws"),
    "RedisProducer": ("pymidil.event.transports.redis", "redis"),
    "RedisProducerEventConfig": ("pymidil.event.transports.redis", "redis"),
    "WebhookConsumer": ("pymidil.event.transports.webhook", "web"),
    "WebhookConsumerEventConfig": ("pymidil.event.transports.webhook", "web"),
    "WebhookDelivery": ("pymidil.event.transports.webhook", "web"),
    # observability (HTTP sink needs httpx)
    "ConsumerObserver": ("pymidil.event.observability", None),
    "ProducerObserver": ("pymidil.event.observability", None),
    "DispatchHook": ("pymidil.event.observability", None),
    "ProducerHook": ("pymidil.event.observability", None),
    "PublishRecord": ("pymidil.event.observability", None),
    "TelemetryDispatchHook": ("pymidil.event.observability", None),
    "TelemetryProducerHook": ("pymidil.event.observability", None),
    "TelemetryEnvelope": ("pymidil.event.observability", None),
    "EventKind": ("pymidil.event.observability", None),
    "EventStatus": ("pymidil.event.observability", None),
    "TelemetrySink": ("pymidil.event.observability", None),
    "HttpTelemetrySink": ("pymidil.event.observability", None),
    "TelemetrySettings": ("pymidil.event.observability", None),
    "attach_telemetry": ("pymidil.event.observability", None),
    # idempotency (Redis store needs redis)
    "IdempotencyPolicy": ("pymidil.event.idempotency", "redis"),
    "IdempotencyStore": ("pymidil.event.idempotency", "redis"),
    "InMemoryIdempotencyStore": ("pymidil.event.idempotency", "redis"),
    "RedisIdempotencyStore": ("pymidil.event.idempotency", "redis"),
}

if TYPE_CHECKING:  # static analyzers see the real symbols
    from pymidil.event.event_bus import EventBus
    from pymidil.event.idempotency import (
        IdempotencyPolicy,
        IdempotencyStore,
        InMemoryIdempotencyStore,
        RedisIdempotencyStore,
    )
    from pymidil.event.observability import (
        ConsumerObserver,
        DispatchHook,
        EventKind,
        EventStatus,
        ProducerHook,
        ProducerObserver,
        PublishRecord,
        TelemetryDispatchHook,
        TelemetryEnvelope,
        TelemetryProducerHook,
        TelemetrySettings,
        TelemetrySink,
        attach_telemetry,
    )
    from pymidil.event.transports.redis import (
        RedisProducer,
        RedisProducerEventConfig,
    )
    from pymidil.event.transports.sqs import (
        SQSConsumer,
        SQSConsumerEventConfig,
        SQSDelivery,
        SQSProducer,
        SQSProducerEventConfig,
        SQSSettlement,
    )
    from pymidil.event.transports.webhook import (
        WebhookConsumer,
        WebhookConsumerEventConfig,
        WebhookDelivery,
    )


def __getattr__(name: str):
    try:
        module_path, extra = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module 'pymidil.event' has no attribute {name!r}")
    import importlib

    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        hint = f" — install the extra: pip install 'pymidil[{extra}]'" if extra else ""
        raise ImportError(
            f"{name} needs an optional dependency that is not installed "
            f"({exc.name or exc}){hint}"
        ) from exc
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY.keys()))


__all__ = [
    # bus
    "EventBus",
    # core model (Event + Delivery + Settlement)
    "Event",
    "Delivery",
    "Settlement",
    "NoSettlement",
    "NoAckDelivery",
    # retry policy
    "RetryConfig",
    "RetryPolicyError",
    "TransportCapabilities",
    # producers
    "EventProducer",
    "BaseProducerConfig",
    "SQSProducer",
    "SQSProducerEventConfig",
    "RedisProducer",
    "RedisProducerEventConfig",
    # consumers
    "EventConsumer",
    "BaseConsumerConfig",
    "PullEventConsumer",
    "PullEventConsumerConfig",
    "PushEventConsumer",
    "PushEventConsumerConfig",
    "SQSConsumer",
    "SQSConsumerEventConfig",
    "SQSDelivery",
    "SQSSettlement",
    "WebhookConsumer",
    "WebhookConsumerEventConfig",
    "WebhookDelivery",
    # subscribers + middleware
    "EventSubscriber",
    "FunctionSubscriber",
    "ManualSubscriber",
    "SubscriberMiddleware",
    "GroupMiddleware",
    "LoggingMiddleware",
    # exceptions
    "BaseEventError",
    "ConsumerCrashError",
    "ConsumerError",
    "ConsumerNotImplementedError",
    "ConsumerStartError",
    "NonRetryableEventError",
    "ProducerError",
    "ProducerNotImplementedError",
    "RetryableEventError",
    "TransportNotImplementedError",
    # observability
    "DispatchHook",
    "ProducerHook",
    "PublishRecord",
    "TelemetryEnvelope",
    "EventStatus",
    "EventKind",
    "TelemetryDispatchHook",
    "TelemetryProducerHook",
    "ConsumerObserver",
    "ProducerObserver",
    "TelemetrySink",
    "HttpTelemetrySink",
    "TelemetrySettings",
    "attach_telemetry",
    # idempotency
    "IdempotencyPolicy",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
]
