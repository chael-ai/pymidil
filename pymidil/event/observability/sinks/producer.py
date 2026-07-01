"""Producer sink — re-publishes envelopes through an EventProducer.

Dogfoods the event bus: telemetry is shipped to a queue/stream (SQS, Redis) that
the Observatory ingestion pipeline consumes, decoupling emitters from the API's
availability.
"""

from __future__ import annotations

from pymidil.event.observability.envelope import TelemetryEnvelope
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.producer.base import EventProducer


class ProducerTelemetrySink(TelemetrySink):
    def __init__(
        self, producer: EventProducer, *, close_producer: bool = False
    ) -> None:
        self._producer = producer
        self._close_producer = close_producer

    async def emit(self, envelope: TelemetryEnvelope) -> None:
        """
        Ship a single envelope to the producer sink destination.

        This method publishes the envelope to the producer.

        Args:
            envelope (TelemetryEnvelope): The telemetry envelope to be shipped.
        """
        await self._producer.publish(envelope.model_dump(mode="json"))

    async def aclose(self) -> None:
        """
        Release any resources held by the producer sink.

        This method closes the producer if the close_producer flag is set.

        Returns:
            None
        """
        if self._close_producer:
            await self._producer.close()
