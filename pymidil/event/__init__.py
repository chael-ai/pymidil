from pymidil.event.event_bus import EventBus

# Producers
from pymidil.brokers.sqs import SQSProducer, SQSProducerEventConfig
from pymidil.event.producer.base import BaseProducerConfig
from pymidil.event.producer.redis import RedisProducer, RedisProducerEventConfig

# Consumers (Base, Pull, Push, SQS)
from pymidil.event.consumer.strategies.base import (
    EventConsumer,
    BaseConsumerConfig,
)
from pymidil.event.core import Delivery, Event, NoAckDelivery, NoSettlement, Settlement
from pymidil.event.retry import RetryConfig, RetryPolicyError, TransportCapabilities
from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from pymidil.brokers.sqs import SQSConsumer, SQSConsumerEventConfig

# Subscribers and Middlewares
from pymidil.event.subscriber.base import (
    EventSubscriber,
    FunctionSubscriber,
    SubscriberMiddleware,
)
from pymidil.event.subscriber.middleware import (
    GroupMiddleware,
    RetryMiddleware,
)

# Exceptions
from pymidil.event.exceptions import (
    BaseEventError,
    ConsumerError,
    ConsumerCrashError,
    ConsumerNotImplementedError,
    ConsumerStartError,
    RetryableEventError,
    NonRetryableEventError,
    ProducerError,
    ProducerNotImplementedError,
    TransportNotImplementedError,
)

# Context
from pymidil.event.context import EventContext, get_current_event, event_context

# Observability extension points + telemetry (A2)
from pymidil.event.observability import (
    ConsumerObserver,
    DispatchHook,
    ProducerObserver,
    EventKind,
    EventStatus,
    ProducerHook,
    PublishRecord,
    TelemetryDispatchHook,
    TelemetryEnvelope,
    TelemetryProducerHook,
    TelemetrySettings,
    TelemetrySink,
    attach_telemetry,
)

# Idempotency (A3)
from pymidil.event.idempotency import (
    IdempotencyPolicy,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
)

# Dead-letter operations (A4)

# Acknowledgement (transport-agnostic dispositions: ack / retry / dlq)

__all__ = [
    # event bus
    "EventBus",
    # core model (Event + Delivery)
    "Event",
    "Delivery",
    "Settlement",
    "NoSettlement",
    "RetryConfig",
    "RetryPolicyError",
    "TransportCapabilities",
    "NoAckDelivery",
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
    # Idempotency (A3)
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "IdempotencyPolicy",
    # Dead-letter operations (A4)
    # Acknowledgement
]
