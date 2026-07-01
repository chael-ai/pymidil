"""No-op sink — disables telemetry while keeping the wiring in place."""

from __future__ import annotations

from pymidil.event.observability.envelope import TelemetryEnvelope
from pymidil.event.observability.sinks.base import TelemetrySink


class NullTelemetrySink(TelemetrySink):
    """No-op sink — disables telemetry while keeping the wiring in place."""

    async def emit(self, envelope: TelemetryEnvelope) -> None:
        """
        Ship a single envelope to the null sink destination.

        This method does nothing.

        Args:
            envelope (TelemetryEnvelope): The telemetry envelope to be shipped.
        """
        return None
