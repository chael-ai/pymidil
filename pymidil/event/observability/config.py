"""Telemetry configuration + one-call wiring.

    from pymidil.event.event_bus import EventBus
    from pymidil.event.observability.config import attach_telemetry

    bus = EventBus(...)
    hook = attach_telemetry(bus)   # reads MIDIL_TELEMETRY_* env

For broker-agnostic observers (existing Django / Kafka / … loops)::

    from pymidil.event.observability.config import (
        create_consumer_observer,
        create_producer_observer,
    )

    publish = create_producer_observer()          # MIDIL_TELEMETRY_* env
    observe = create_consumer_observer("worker")

Producer-backed sinks need a producer instance, so build those explicitly with
``ProducerTelemetrySink`` and pass ``sink=`` to :func:`attach_telemetry`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from pymidil.event.observability.emitter import TelemetryDispatchHook
from pymidil.event.observability.observer import ConsumerObserver, ProducerObserver
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.observability.sinks.null import NullTelemetrySink
from pymidil.event.observability.sinks.stdout import StdoutTelemetrySink

if TYPE_CHECKING:
    from pymidil.event.event_bus import EventBus

SinkKind = Literal["stdout", "http", "null"]


class TelemetrySettings(BaseSettings):
    """Env-driven telemetry config (prefix ``MIDIL_TELEMETRY_``)."""

    model_config = SettingsConfigDict(env_prefix="MIDIL_TELEMETRY_", extra="ignore")

    enabled: bool = True
    sink: SinkKind = "stdout"
    source_service: str = "unknown-service"
    broker: Optional[str] = None
    include_payload: bool = True

    http_endpoint: Optional[str] = None
    http_api_key: Optional[str] = None


def create_sink(settings: TelemetrySettings) -> TelemetrySink:
    """Build a sink from settings (Factory)."""
    if not settings.enabled or settings.sink == "null":
        return NullTelemetrySink()
    if settings.sink == "stdout":
        return StdoutTelemetrySink()
    if settings.sink == "http":
        if not settings.http_endpoint:
            raise ValueError(
                "MIDIL_TELEMETRY_HTTP_ENDPOINT is required for the http sink"
            )
        from pymidil.event.observability.sinks.http import HttpTelemetrySink

        return HttpTelemetrySink(settings.http_endpoint, api_key=settings.http_api_key)
    raise ValueError(f"Unknown telemetry sink: {settings.sink!r}")


def create_telemetry_hook(
    settings: Optional[TelemetrySettings] = None,
    *,
    sink: Optional[TelemetrySink] = None,
) -> TelemetryDispatchHook:
    settings = settings or TelemetrySettings()
    return TelemetryDispatchHook(
        sink or create_sink(settings),
        source_service=settings.source_service,
        broker=settings.broker,
        include_payload=settings.include_payload,
    )


def create_producer_observer(
    settings: Optional[TelemetrySettings] = None,
    *,
    sink: Optional[TelemetrySink] = None,
) -> ProducerObserver:
    """Build a :class:`ProducerObserver` from ``MIDIL_TELEMETRY_*`` settings."""
    settings = settings or TelemetrySettings()
    return ProducerObserver(
        source_service=settings.source_service,
        broker=settings.broker or "unknown",
        sink=sink or create_sink(settings),
        include_payload=settings.include_payload,
    )


def create_consumer_observer(
    consumer: str,
    settings: Optional[TelemetrySettings] = None,
    *,
    sink: Optional[TelemetrySink] = None,
) -> ConsumerObserver:
    """Build a :class:`ConsumerObserver` from ``MIDIL_TELEMETRY_*`` settings."""
    settings = settings or TelemetrySettings()
    return ConsumerObserver(
        consumer=consumer,
        broker=settings.broker or "unknown",
        sink=sink or create_sink(settings),
        source_service=settings.source_service,
        include_payload=settings.include_payload,
    )


def attach_telemetry(
    bus: "EventBus",
    settings: Optional[TelemetrySettings] = None,
    *,
    sink: Optional[TelemetrySink] = None,
    target: Optional[str] = None,
) -> TelemetryDispatchHook:
    """Build a telemetry hook and attach it to the bus's consumers.

    Returns the hook so the caller can ``await hook_sink.aclose()`` on shutdown
    (access the sink via ``hook`` if needed).
    """
    hook = create_telemetry_hook(settings, sink=sink)
    bus.add_dispatch_hook(hook, target=target)
    return hook
