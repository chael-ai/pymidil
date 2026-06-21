from typing import Mapping, Optional, Protocol
import httpx


class RetryObserver(Protocol):
    def on_retry(self, request: httpx.Request) -> httpx.Request:
        ...


class RetryStrategy(Protocol):
    def should_retry(
        self,
        request: httpx.Request,
        response: Optional[httpx.Response],
        error: Optional[Exception],
    ) -> bool:
        ...


class BackoffStrategy(Protocol):
    def calculate_sleep(self, attempt: int, headers: Mapping[str, str]) -> float:
        ...
