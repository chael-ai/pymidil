import asyncio
from functools import wraps
from typing import Callable, Coroutine, Any, Optional, Protocol

from loguru import logger
from starlette.concurrency import run_in_threadpool
from traceback import format_exception

import redis.asyncio as redis


AsyncFunc = Callable[[], Coroutine[Any, Any, None]]
SyncFunc = Callable[[], None]
TaskFunc = AsyncFunc | SyncFunc
Decorator = Callable[[TaskFunc], AsyncFunc]


class RedisLockManager:
    def __init__(self, client: redis.Redis, key: str, ttl: int):
        self.client = client
        self.key = key
        self.ttl = ttl

    async def acquire(self) -> bool:
        return await self.client.set(
            name=self.key, value="1", nx=True, ex=self.ttl  # Set if not exists  # TTL
        )


class TaskLauncher:
    @staticmethod
    def launch(coro: Coroutine[Any, Any, None]) -> None:
        asyncio.ensure_future(coro)


class ExecutionStrategy(Protocol):
    async def run(self, func: TaskFunc) -> None:
        ...


class AsyncExecutionStrategy:
    async def run(self, func: TaskFunc) -> None:
        await func()  # type: ignore


class SyncExecutionStrategy:
    async def run(self, func: TaskFunc) -> None:
        await run_in_threadpool(func)


def get_execution_strategy(func: TaskFunc) -> ExecutionStrategy:
    return (
        AsyncExecutionStrategy()
        if asyncio.iscoroutinefunction(func)
        else SyncExecutionStrategy()
    )


class PeriodicTask:
    def __init__(
        self,
        func: TaskFunc,
        seconds: float,
        wait_first: bool = False,
        raise_exceptions: bool = False,
        max_repetitions: Optional[int] = None,
        lock_manager: Optional[RedisLockManager] = None,
    ):
        self.func = func
        self.seconds = seconds
        self.wait_first = wait_first
        self.raise_exceptions = raise_exceptions
        self.max_repetitions = max_repetitions
        self.lock_manager = lock_manager
        self.strategy = get_execution_strategy(func)

    def start(self) -> None:
        TaskLauncher.launch(self._loop())

    async def _loop(self) -> None:
        if self.wait_first:
            await asyncio.sleep(self.seconds)

        repetitions = 0
        while self.max_repetitions is None or repetitions < self.max_repetitions:
            repetitions += 1
            try:
                if self.lock_manager:
                    acquired = await self.lock_manager.acquire()
                    if not acquired:
                        logger.debug(
                            f"Lock `{self.lock_manager.key}` held, skipping run."
                        )
                        await asyncio.sleep(self.seconds)
                        continue
                    logger.info(
                        f"Lock `{self.lock_manager.key}` acquired, executing task."
                    )

                await self.strategy.run(self.func)
            except Exception as exc:
                logger.error(
                    "".join(format_exception(type(exc), exc, exc.__traceback__))
                )
                if self.raise_exceptions:
                    raise
            await asyncio.sleep(self.seconds)


def repeat_every(
    seconds: float,
    wait_first: bool = False,
    raise_exceptions: bool = False,
    max_repetitions: Optional[int] = None,
) -> Decorator:
    def decorator(func: TaskFunc) -> AsyncFunc:
        task = PeriodicTask(
            func=func,
            seconds=seconds,
            wait_first=wait_first,
            raise_exceptions=raise_exceptions,
            max_repetitions=max_repetitions,
        )

        @wraps(func)
        async def wrapper() -> None:
            task.start()

        return wrapper

    return decorator


def repeat_every_distributed(
    *,
    seconds: float,
    lock_key: str,
    redis_client: redis.Redis,
    wait_first: bool = False,
    raise_exceptions: bool = False,
    max_repetitions: Optional[int] = None,
    lock_ttl: Optional[int] = None,
) -> Decorator:
    ttl = lock_ttl or int(seconds)

    def decorator(func: TaskFunc) -> AsyncFunc:
        task = PeriodicTask(
            func=func,
            seconds=seconds,
            wait_first=wait_first,
            raise_exceptions=raise_exceptions,
            max_repetitions=max_repetitions,
            lock_manager=RedisLockManager(redis_client, lock_key, ttl),
        )

        @wraps(func)
        async def wrapper() -> None:
            task.start()

        return wrapper

    return decorator
