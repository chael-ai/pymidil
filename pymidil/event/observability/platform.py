"""The platform instrumenter — turns the connection contract into telemetry.

:class:`Observability` owns the process's telemetry sink and knows how to
attach the right hook to a consumer or a producer. It is the *behavior* half of
the platform integration (:class:`ObservabilityConfig` is the data half), and
the single place the API key lives — inside one sink's HTTP client, never on a
transport.

The bus holds one of these and calls :meth:`instrument_consumer` /
:meth:`instrument_producer` at registration time. When the contract isn't
satisfied (no URL/service, or telemetry disabled) every method is a clean
no-op, so a service developed without an Observatory just runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from pymidil.event.observability.config import ObservabilityConfig

if TYPE_CHECKING:
    from pymidil.event.consumer.strategies.base import EventConsumer
    from pymidil.event.observability.sinks.base import TelemetrySink
    from pymidil.event.producer.base import EventProducer

#: What a bus accepts for its ``observability`` argument:
#: ``None`` → resolve from the environment · ``False`` → disabled ·
#: an :class:`ObservabilityConfig` → explicit · an :class:`Observability` → as-is.
ObservabilitySpec = Union["Observability", ObservabilityConfig, bool, None]


class Observability:
    """Owns the telemetry sink and instruments components with it."""

    def __init__(self, config: ObservabilityConfig) -> None:
        self._config = config
        self._sink: Optional["TelemetrySink"] = None

    @classmethod
    def resolve(cls, spec: ObservabilitySpec) -> "Observability":
        """Normalize a bus's ``observability`` argument into an instance.

        ``None`` reads the environment contract (default-on); ``False``
        disables; an :class:`ObservabilityConfig` is wrapped; an existing
        :class:`Observability` passes through.
        """
        if isinstance(spec, Observability):
            return spec
        if spec is False:
            return cls(ObservabilityConfig(telemetry=False))
        if isinstance(spec, ObservabilityConfig):
            return cls(spec)
        # None (or True) → the environment contract
        return cls(ObservabilityConfig())

    @property
    def active(self) -> bool:
        return self._config.active

    def _sink_for(self) -> "TelemetrySink":
        if self._sink is None:
            from pymidil.event.observability.sinks.http import HttpTelemetrySink

            self._sink = HttpTelemetrySink(
                self._config.observatory_url,  # type: ignore[arg-type]
                api_key=self._config.api_key,
            )
        return self._sink

    def instrument_consumer(
        self, consumer: "EventConsumer", *, service: Optional[str] = None
    ) -> None:
        """Attach the consumer-side telemetry hook (no-op when inactive)."""
        if not self.active:
            return
        from pymidil.event.observability.emitter import TelemetryDispatchHook

        source = service or self._config.service
        consumer.add_hook(
            TelemetryDispatchHook(self._sink_for(), source_service=source)  # type: ignore[arg-type]
        )

    def instrument_producer(
        self, producer: "EventProducer", *, service: Optional[str] = None
    ) -> None:
        """Attach the producer-side telemetry hook (no-op when inactive)."""
        if not self.active:
            return
        from pymidil.event.observability.emitter import TelemetryProducerHook

        source = service or self._config.service
        producer.add_hook(
            TelemetryProducerHook(self._sink_for(), source_service=source)  # type: ignore[arg-type]
        )

    async def aclose(self) -> None:
        """Release the sink's resources (its HTTP client)."""
        if self._sink is not None:
            aclose = getattr(self._sink, "aclose", None)
            if aclose is not None:
                await aclose()
            self._sink = None
