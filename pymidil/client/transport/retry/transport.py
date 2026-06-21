import asyncio
import time
from typing import Any, Callable, Coroutine, Optional, Union

import httpx

from pymidil.client.transport.retry.protocols import (
    RetryObserver,
    RetryStrategy,
    BackoffStrategy,
)
from pymidil.client.transport.retry.strategies import DefaultRetryStrategy
from pymidil.client.transport.retry.backoff import ExponentialBackoffAdaptor
from loguru import logger


class RetryTransport(httpx.AsyncBaseTransport, httpx.BaseTransport):
    def __init__(
        self,
        wrapped: Union[httpx.BaseTransport, httpx.AsyncBaseTransport],
        max_attempts: int = 5,
        retry_strategy: RetryStrategy = DefaultRetryStrategy(),
        backoff_strategy: BackoffStrategy = ExponentialBackoffAdaptor(),
        observer: Optional[RetryObserver] = None,
    ) -> None:
        """
        A custom HTTP transport for httpx that automatically retries requests using a configurable
        retry and backoff strategy.

        Args:
            wrapped (Union[httpx.BaseTransport, httpx.AsyncBaseTransport]):
                The underlying transport to wrap and delegate requests to.
            max_attempts (int, optional):
                The maximum number of attempts for a request (including the initial attempt).
                Defaults to 5.
            retry_strategy (RetryStrategy, optional):
                The strategy to determine whether a request should be retried based on the request,
                response, and error. Defaults to DefaultRetryStrategy().
            backoff_strategy (BackoffStrategy, optional):
                The strategy to determine how long to wait between retries. Defaults to ExponentialBackoffWithJitter().
            observer (Optional[RetryObserver], optional):
                An optional observer that can mutate the request before each retry (e.g., to refresh auth).
        """
        self._wrapped = wrapped
        self._max_attempts = max_attempts
        self._retry_strategy = retry_strategy
        self._backoff_strategy = backoff_strategy
        self._observer = observer

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self._sync_retry_loop(request, self._wrapped.handle_request)  # type: ignore

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._async_retry_loop(request, self._wrapped.handle_async_request)  # type: ignore

    def _sync_retry_loop(
        self, request: httpx.Request, send: Callable[..., httpx.Response]
    ) -> httpx.Response:
        response = None
        for attempt in range(1, self._max_attempts + 1):
            error = None
            try:
                response = send(request)
                if not self._retry_strategy.should_retry(request, response, None):
                    return response
                response.close()
            except Exception as exc:
                error = exc
                if not self._retry_strategy.should_retry(request, None, exc):
                    raise
            msg = f"Retry {attempt} for {request.method} {request.url}"
            if error:
                logger.warning(f"{msg} due to error: {error}")
            elif response:
                logger.warning(f"{msg} with status: {response.status_code}")
            time.sleep(
                self._backoff_strategy.calculate_sleep(
                    attempt, response.headers if response else {}
                )
            )
            request = self._observer.on_retry(request) if self._observer else request
        return response  # type: ignore # May be failed last attempt

    async def _async_retry_loop(
        self,
        request: httpx.Request,
        send: Callable[..., Coroutine[Any, Any, httpx.Response]],
    ) -> httpx.Response:
        response = None
        for attempt in range(1, self._max_attempts + 1):
            error = None
            try:
                response = await send(request)
                if not self._retry_strategy.should_retry(request, response, None):
                    return response
                await response.aclose()
            except Exception as exc:
                error = exc
                if not self._retry_strategy.should_retry(request, None, exc):
                    raise
            msg = f"Retry {attempt} for {request.method} {request.url}"
            if error:
                logger.warning(f"{msg} due to error: {error}")
            elif response:
                logger.warning(f"{msg} with status: {response.status_code}")
            await asyncio.sleep(
                self._backoff_strategy.calculate_sleep(
                    attempt, response.headers if response else {}
                )
            )
            request = self._observer.on_retry(request) if self._observer else request
        return response  # type: ignore # Final failed attempt

    async def aclose(self) -> None:
        await self._wrapped.aclose()  # type: ignore

    def close(self) -> None:
        self._wrapped.close()  # type: ignore
