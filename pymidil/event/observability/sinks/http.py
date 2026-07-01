"""HTTP sink — posts envelopes to the Observatory ingestion API.

``httpx`` is imported lazily so this module loads without the ``auth``/``http``
extra installed; it is only required when the sink is actually used.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from loguru import logger

from pymidil.event.observability.envelope import TelemetryEnvelope
from pymidil.event.observability.sinks.base import TelemetrySink


class HttpTelemetrySink(TelemetrySink):
    """POSTs envelopes to ``{base_url}{path}`` on the Observatory API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        timeout: float = 10.0,
        single_path: str = "/v1/telemetry/events",
        batch_path: str = "/v1/telemetry/events/batch",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._single_path = single_path
        self._batch_path = batch_path
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            headers = {"X-Api-Key": self._api_key} if self._api_key else {}
            self._client = httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, headers=headers
            )
        return self._client

    async def emit(self, envelope: TelemetryEnvelope) -> None:
        client = self._get_client()
        response = await client.post(
            self._single_path, json=envelope.model_dump(mode="json")
        )
        response.raise_for_status()

    async def emit_many(self, envelopes: Sequence[TelemetryEnvelope]) -> None:
        if not envelopes:
            return
        client = self._get_client()
        body = {"events": [e.model_dump(mode="json") for e in envelopes]}
        response = await client.post(self._batch_path, json=body)
        response.raise_for_status()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.debug("HttpTelemetrySink client closed")
