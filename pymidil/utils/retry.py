from __future__ import annotations

from abc import ABC, abstractmethod
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    ParamSpec,
    Type,
    TypeVar,
)

from loguru import logger

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)
from tenacity.wait import wait_base

P = ParamSpec("P")
R = TypeVar("R")

SyncCallable = Callable[P, R]
CoroutineCallable = Callable[P, Coroutine[Any, Any, R]]

_DEFAULT_MAX_ATTEMPTS = 3


class BaseAsyncRetryPolicy(ABC):
    @abstractmethod
    async def __call__(
        self, func: Callable[..., Awaitable[Any]], *args, **kwargs
    ) -> Any:
        ...

    def retry(
        self, func: Callable[..., Awaitable[Any]]
    ) -> Callable[..., Awaitable[Any]]:
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support decorating"
        )


class AsyncRetry(BaseAsyncRetryPolicy):
    def __init__(
        self,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        wait: wait_base | None = None,
        retry_on_exceptions: tuple[Type[BaseException], ...] = (Exception,),
    ) -> None:
        """
        Args:
            max_attempts: Maximum number of retry attempts.
            wait: Any tenacity wait strategy (e.g. wait_exponential, wait_fixed, wait_random_exponential).
                  Defaults to exponential backoff.
            retry_on_exceptions: Which exceptions should trigger a retry.
        """
        self.max_attempts = max_attempts
        self.wait = wait or wait_exponential_jitter()
        self.retry_on_exceptions = retry_on_exceptions

    async def __call__(
        self, func: Callable[..., Awaitable[Any]], *args, **kwargs
    ) -> Any:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=self.wait,
            retry=retry_if_exception_type(*self.retry_on_exceptions),
            reraise=True,
        ):
            with attempt:
                attempt_number = attempt.retry_state.attempt_number
                logger.debug(
                    f"Attempt {attempt_number}: Executing function '{func.__name__}' with arguments {args} and keyword arguments {kwargs}."
                )

                return await func(*args, **kwargs)

    def retry(self, func: Callable[..., Awaitable[Any]]) -> CoroutineCallable[P, R]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self(func, *args, **kwargs)

        return wrapper
