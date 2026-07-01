"""Stdout sink — logs envelopes as JSON. The zero-dependency default."""

from __future__ import annotations

from loguru import logger

from pymidil.event.observability.envelope import TelemetryEnvelope
from pymidil.event.observability.sinks.base import TelemetrySink


class StdoutTelemetrySink(TelemetrySink):
    async def emit(self, envelope: TelemetryEnvelope) -> None:
        """
        Ship a single envelope to the stdout sink destination.

        This method logs the envelope as a JSON string to the console.

        Args:
            envelope (TelemetryEnvelope): The telemetry envelope to be shipped.
        """
        logger.bind(telemetry=True).info(envelope.model_dump_json())
