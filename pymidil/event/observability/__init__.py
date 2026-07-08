from pymidil.event.observability.config import (
    TelemetrySettings,
    attach_telemetry,
    create_sink,
    create_telemetry_hook,
)
from pymidil.event.observability.emitter import (
    TelemetryDispatchHook,
    TelemetryProducerHook,
)
from pymidil.event.observability.envelope import (
    EventKind,
    EventStatus,
    TelemetryEnvelope,
)
from pymidil.event.observability.hooks import (
    DispatchHook,
    ProducerHook,
    PublishRecord,
)
from pymidil.event.observability.observer import (
    ConsumerObserver,
    Observation,
    ObservedMessage,
    ProducerObserver,
    PublishObservation,
    default_classification,
)
from pymidil.event.observability.protocols import MessageProtocol
from pymidil.event.observability.sinks import (
    NullTelemetrySink,
    StdoutTelemetrySink,
    TelemetrySink,
)

__all__ = [
    # extension points
    "DispatchHook",
    "ProducerHook",
    "PublishRecord",
    "MessageProtocol",
    # telemetry contract
    "TelemetryEnvelope",
    "EventStatus",
    "EventKind",
    # emitter (A2)
    "TelemetryDispatchHook",
    "TelemetryProducerHook",
    # broker-agnostic observation (A5)
    "ConsumerObserver",
    "Observation",
    "ObservedMessage",
    "ProducerObserver",
    "PublishObservation",
    "default_classification",
    # sinks
    "TelemetrySink",
    "StdoutTelemetrySink",
    "NullTelemetrySink",
    # config / wiring
    "TelemetrySettings",
    "create_sink",
    "create_telemetry_hook",
    "attach_telemetry",
]
