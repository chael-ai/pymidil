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


class AsyncHTTPClientTelemetrySink(TelemetrySink):
    """POSTs envelopes to ``{base_url}{path}`` via ``pymidil.client.AsyncHTTPClient``.

    Experimental variant of :class:`HttpTelemetrySink` that routes through
    pymidil's own request module instead of a private ``httpx.AsyncClient``,
    to test whether ``AsyncHTTPClient`` holds up as the sole request path for
    a real caller. ``pymidil.client`` is imported lazily (same reason as
    ``httpx`` above: this module must stay loadable without the ``auth``/
    ``http`` extra) — only constructing this class pulls it in.

    Known gaps found by writing this variant, kept rather than papered over:

    - No per-instance ``timeout``: ``AsyncHTTPClient`` has no constructor arg
      for it, so unlike ``HttpTelemetrySink`` this class can't honor one —
      every request uses ``get_http_async_client()``'s default (60s).
    - No real ``aclose()``: ``AsyncHTTPClient`` never owns its transport
      exclusively (it always shares the process-wide cached client from
      ``get_http_async_client()``), so there is nothing this sink can safely
      close on its own — ``aclose()`` here only drops its own reference.
    - Retries turned out to be a non-issue in practice, but only by luck of
      defaults: ``DefaultRetryStrategy.RETRYABLE_METHODS`` excludes POST, and
      every call this sink makes is a POST — verified empirically (a mocked
      503 response was attempted exactly once, no backoff sleep). Nothing
      about *this* call site enforces that, though; if ``AsyncHTTPClient``'s
      default retry strategy ever changed to include POST, this sink would
      silently start retrying against ``TelemetrySink.emit()``'s "must not
      block" contract with no way to opt out from here.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        single_path: str = "/v1/telemetry/events",
        batch_path: str = "/v1/telemetry/events/batch",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._single_path = single_path
        self._batch_path = batch_path
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            from pymidil.client.http import AsyncHTTPClient

            headers = {"X-Api-Key": self._api_key} if self._api_key else None
            self._client = AsyncHTTPClient(base_url=self._base_url, headers=headers)
        return self._client

    async def emit(self, envelope: TelemetryEnvelope) -> None:
        client = self._get_client()
        await client.send_request(
            "POST", self._single_path, json=envelope.model_dump(mode="json")
        )

    async def emit_many(self, envelopes: Sequence[TelemetryEnvelope]) -> None:
        if not envelopes:
            return
        client = self._get_client()
        body = {"events": [e.model_dump(mode="json") for e in envelopes]}
        await client.send_request("POST", self._batch_path, json=body)
