from typing import Any, Awaitable, Callable, List, cast
import asyncio

from loguru import logger
from pymidil.event.subscriber.base import SubscriberMiddleware
from pymidil.event.core import Event


class GroupMiddleware(SubscriberMiddleware):
    """
    A middleware that runs multiple middlewares in parallel.

    This middleware allows you to group several `SubscriberMiddleware` instances
    and execute them concurrently for a given event. This is useful for scenarios
    where you want to apply multiple, independent side effects or checks to an event
    without blocking on each one sequentially.

    Args:
        middlewares (List[SubscriberMiddleware]): The list of middlewares to run in parallel.
        fail_fast (bool): If True, the group will stop and raise as soon as any middleware fails,
            cancelling the remaining tasks. If False, all middlewares are run and errors are logged,
            but exceptions are not propagated.

    Usage:
        group = GroupMiddleware([LoggingMiddleware(), MetricsMiddleware()], fail_fast=True)
        await group(call_next, event)

    Note:
        - The order of execution is not guaranteed.
        - If `fail_fast` is True, the first exception will be raised and remaining middlewares cancelled.
        - If `fail_fast` is False, all exceptions are logged and execution continues.
    """

    def __init__(self, middlewares: List[SubscriberMiddleware], fail_fast: bool = True):
        self.middlewares = middlewares
        self.fail_fast = fail_fast

    async def __call__(
        self, event: Event, call_next: Callable[[Event], Awaitable[Any]]
    ) -> Any:
        async def run_middleware(mw: SubscriberMiddleware):
            await mw(event, call_next)

        tasks = [asyncio.create_task(run_middleware(mw)) for mw in self.middlewares]

        if self.fail_fast:
            # Cancel all if one fails
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in pending:
                task.cancel()
            # Reraise if there was an exception
            for task in done:
                if task.exception():
                    exc = cast(BaseException, task.exception())
                    raise exc
        else:
            # Run all, gather errors but don’t fail fast
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error(f"[GroupMiddleware] Middleware error: {r}")


class LoggingMiddleware(SubscriberMiddleware):
    async def __call__(
        self, event: Any, call_next: Callable[[Event], Awaitable[Any]]
    ) -> Any:
        logger.info(f"Event {event} processing started")
        try:
            result = await call_next(event)
            logger.info(f"Event {event} processed successfully")
            return result
        except Exception as e:
            logger.error(f"Event {event} processing failed: {e}")
            raise
