"""Telemetry configuration + one-call wiring.

    from pymidil.event.event_bus import EventBus
    from pymidil.event.observability.config import attach_telemetry

    bus = EventBus(...)
    hook = attach_telemetry(bus)   # reads MIDIL_TELEMETRY_* env

Producer-backed sinks need a producer instance, so build those explicitly with
``ProducerTelemetrySink`` and pass ``sink=`` to :func:`attach_telemetry`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from pymidil.event.observability.emitter import TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.observability.sinks.null import NullTelemetrySink
from pymidil.event.observability.sinks.stdout import StdoutTelemetrySink

if TYPE_CHECKING:
    from pymidil.event.event_bus import EventBus

SinkKind = Literal["stdout", "http", "null"]


class ObservabilityConfig(BaseSettings):
    """The Midil Observatory connection contract (env prefix ``MIDIL_``).

    This is *data* — the platform credentials and attribution, read from the
    environment (or ``.env``) by default and overridable by construction. It
    holds no behavior; :class:`~pymidil.event.observability.platform.Observability`
    turns it into a sink and instruments components with it. The API key lives
    here and is passed to exactly one sink, never onto a transport config.

        MIDIL_OBSERVATORY_URL   base URL of the Observatory API
        MIDIL_API_KEY           org-scoped key (``mo_…``); optional in dev
        MIDIL_SERVICE           default service name telemetry is attributed to
        MIDIL_TELEMETRY         set ``false`` to disable
    """

    model_config = SettingsConfigDict(env_prefix="MIDIL_", extra="ignore")

    observatory_url: Optional[str] = None
    api_key: Optional[str] = None
    service: Optional[str] = None
    telemetry: bool = True

    @property
    def active(self) -> bool:
        """Telemetry needs a destination AND an attribution to be meaningful.

        A URL without a service name would fill the Observatory with
        ``unknown-service`` rows, so both are required to activate.
        """
        return self.telemetry and bool(self.observatory_url) and bool(self.service)


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
