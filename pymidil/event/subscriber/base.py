import inspect
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional, Union

from loguru import logger

from pymidil.event.core import Event

FilterFn = Callable[[Event], Union[Awaitable[bool], bool]]
ErrorFn = Callable[[Event, Exception], Union[Awaitable[None], None]]


async def _maybe_await(value: Any) -> Any:
    """Normalize a sync-or-async call result to its value (handlers, filters,
    and error hooks may be either; ``isawaitable`` also covers futures)."""
    if inspect.isawaitable(value):
        return await value
    return value


class EventSubscriber(ABC):
    """
    Abstract base class for event subscribers.

    This class defines the contract that all event subscribers must follow.
    Subclasses should implement the `handle` method to process incoming events.
    Optionally, subclasses can override the `authenticate` method if authentication
    or authorization logic is required before handling an event.

    Methods:
        handle(event: Any) -> None:
            Abstract method that must be implemented by subclasses to handle the event.

        authenticate(event: Any) -> None:
            Optional asynchronous hook for performing authentication or authorization
            before processing the event. By default, this method does nothing and can
            be overridden as needed.
    """

    @abstractmethod
    async def handle(self, event: Event) -> None:
        """
        Handle an incoming event.

        Args:
            event (Any): The event object to be processed.

        """
        ...

    async def authorize(self, event: Event) -> bool:
        """
        Authorize the event.
        """
        return True

    async def should_handle(self, event: Event) -> bool:
        """
        Check if the event should be handled. e.g Validate the event payload.
        """
        return True

    async def on_error(self, event: Any, error: Exception) -> None:
        """
        Handle an error that occurred while handling the event.
        """
        pass

    async def on_success(self, event: Event) -> None:
        """
        Handle a successful event.
        """
        pass

    async def __call__(self, event: Event) -> None:
        """
        Invoke the subscriber for the given event.

        Orchestrates the lifecycle — ``should_handle`` → ``authorize`` →
        ``handle`` → ``on_success``/``on_error``. Handlers receive the event
        and nothing else; they drive the delivery's outcome by what they
        return or raise (return → ack, ``RetryableEventError`` → retry, any
        other exception → dead-letter). Settlement belongs to the dispatcher.
        """
        try:
            should_handle = await self.should_handle(event)
            if not should_handle:
                return

            authorized = await self.authorize(event)
            if not authorized:
                return

            await self.handle(event)
        except Exception as exc:
            # on_error is a subscriber-local observation hook (logging/cleanup).
            # Re-raise so the dispatch lifecycle can resolve the outcome
            # (retry / dead-letter): the consumer's gather(return_exceptions=True)
            # captures this exception to drive ack/retry/dlq + telemetry.
            await self.on_error(event, exc)
            raise
        else:
            await self.on_success(event)


class SubscriberMiddleware(ABC):
    """
    Abstract base class for subscriber middlewares.

    A `SubscriberMiddleware` allows you to intercept, modify, or augment the processing
    of events by an event subscriber. Middlewares are designed to be composed in a chain,
    where each middleware receives a `call_next` function (representing the next handler
    or middleware in the chain) and the event to process.

    Subclasses must implement the asynchronous `__call__` method, which should invoke
    `call_next(event)` to continue the chain, or perform additional logic before or after
    calling the next handler.

    Example usage:

        class LoggingMiddleware(SubscriberMiddleware):
            async def __call__(self, event: Event, call_next: Callable[[Event], Awaitable[Any]]):
                print(f"Processing event: {event}")
                result = await call_next(event)
                print(f"Finished event: {event}")
                return result

    Args:
        event (Message): The event object to be processed.
        call_next (Callable[[Event], Awaitable[Any]]): The next handler or middleware in the chain.

    Returns:
        Any: The result of processing the event, as returned by the handler or next middleware.

    Raises:
        Exception: Any exception raised during event processing may be propagated.
    """

    @abstractmethod
    async def __call__(
        self, event: Event, call_next: Callable[[Event], Awaitable[Any]]
    ) -> Any:
        ...


class FunctionSubscriber(EventSubscriber):
    """
    A subscriber that wraps a function handler with a chain of middlewares.

    This class allows you to compose a handler function with one or more
    `SubscriberMiddleware` instances, which are applied in a decorator-like
    fashion (the first middleware in the list is the outermost).

    Each middleware can intercept, modify, or augment the handling of an event,
    for example by adding retry logic, authentication, logging, etc.

    Example usage:

        subscriber = FunctionSubscriber(
            handler=lambda event: print(event),
            middlewares=[LoggingMiddleware()],
        )

        await subscriber.handle(event)

    Args:
        handler: The function to handle the event. Can be sync or async.
        middlewares: An optional list of `SubscriberMiddleware` instances to
            wrap the handler. Middlewares are applied in the order provided.

    Method:
        handle(event): Invokes the handler with all middlewares applied.
    """

    def __init__(
        self,
        handler: Callable[..., Any],
        middlewares: Optional[list[SubscriberMiddleware]] = None,
        filter: Optional[FilterFn] = None,
        on_error: Optional[ErrorFn] = None,
    ):
        self.handler = handler
        self.middlewares = middlewares or []
        self._filter = filter
        self._on_error = on_error

    async def should_handle(self, event: Event) -> bool:
        """
        Check if the event should be handled.
        """
        if self._filter is None:
            return True
        return await _maybe_await(self._filter(event))

    async def handle(self, event: Event) -> None:
        """
        Handle an event by applying all middlewares to the handler.

        The leaf handler may be sync or async; middlewares operate on the
        event only.
        """

        async def next_handler(e):
            return await _maybe_await(self.handler(e))

        # Apply middlewares in reverse order (so the first is the outermost)
        for mw in reversed(self.middlewares):

            async def wrapped(e, h=next_handler, m=mw):
                return await m(e, h)

            next_handler = wrapped
        await next_handler(event)

    async def on_error(self, event: Event, error: Exception) -> None:
        """
        Handle an error that occurred while handling the event.
        """
        if self._on_error is not None:
            await _maybe_await(self._on_error(event, error))
        else:
            logger.error(f"[subscriber] Unhandled error for event {event.id}: {error}")
