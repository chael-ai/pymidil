"""Telemetry sink port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from pymidil.event.observability.envelope import TelemetryEnvelope


class TelemetrySink(ABC):
    """Destination for telemetry envelopes.

    Implementations must never raise into the caller's hot path — the dispatch
    hook guards emit() — but should fail closed (drop + log) rather than block.
    """

    @abstractmethod
    async def emit(self, envelope: TelemetryEnvelope) -> None:
        """
        Ship a single envelope to the sink destination.

        This method should handle transmission, persistence, or forwarding of
        one telemetry envelope to the backend or output port implemented by the sink,
        such as logging, HTTP API, queue, or other transport. The call must not block,
        must not raise exceptions into the caller, and must handle all errors internally
        (e.g. by logging, dropping the envelope, or implementing best-effort delivery).

        Args:
            envelope (TelemetryEnvelope): The telemetry envelope to be shipped.
        """

    async def emit_many(self, envelopes: Sequence[TelemetryEnvelope]) -> None:
        """
        Ship a batch of telemetry envelopes.

        By default, this implementation fans out to :meth:`emit` for each envelope
        in sequence. Override this method to provide more efficient batch handling
        if the sink supports it (e.g. bulk HTTP POST, batched writes, or transactional delivery).

        Args:
            envelopes (Sequence[TelemetryEnvelope]): A sequence of envelopes to be shipped as a batch.
        """
        for envelope in envelopes:
            await self.emit(envelope)

    async def aclose(self) -> None:
        """
        Release any resources held by the sink.

        This may close network connections, flush buffers, release files, or perform
        other cleanup related to the sink implementation. By default, it is a no-op,
        but override it in subclasses that allocate external resources.

        Returns:
            None
        """
        return None
