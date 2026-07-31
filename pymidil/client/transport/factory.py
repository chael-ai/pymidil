from typing import Any, Optional, TypedDict

import httpx

from pymidil.client.transport.retry.protocols import (
    BackoffStrategy,
    RetryObserver,
    RetryStrategy,
)
from pymidil.client.transport.retry.transport import AsyncRetryTransport


class RetryConfig(TypedDict, total=False):
    max_attempts: int
    retry_strategy: RetryStrategy
    backoff_strategy: BackoffStrategy
    observer: Optional[RetryObserver]


class RetryableAsyncClient(httpx.AsyncClient):
    """
    An httpx.AsyncClient whose transport automatically retries requests
    (via AsyncRetryTransport). Accepts every regular httpx.AsyncClient keyword
    argument unchanged, plus an optional `retry_config` to tune retry behavior.
    """

    def __init__(
        self,
        retry_config: Optional[RetryConfig] = None,
        **kwargs: Any,
    ) -> None:
        self._retry_config: RetryConfig = retry_config or {}
        super().__init__(**kwargs)

    def _init_transport(  # type: ignore[override]
        self,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        **kwargs: Any,
    ) -> httpx.AsyncBaseTransport:
        if transport is not None:
            return super()._init_transport(transport=transport, **kwargs)

        return AsyncRetryTransport(
            wrapped=httpx.AsyncHTTPTransport(**kwargs),
            **self._retry_config,
        )

    def _init_proxy_transport(  # type: ignore[override]
        self, proxy: httpx.Proxy, **kwargs: Any
    ) -> httpx.AsyncBaseTransport:
        return AsyncRetryTransport(
            wrapped=httpx.AsyncHTTPTransport(proxy=proxy, **kwargs),
            **self._retry_config,
        )
