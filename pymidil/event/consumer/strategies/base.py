from __future__ import annotations

import asyncio
import time
from abc import abstractmethod, ABC
from threading import Lock
from typing import Annotated, Any, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field
from dataclasses import dataclass

from pymidil.event.exceptions import RetryableEventError
from pymidil.event.message import Message
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.subscriber.base import EventSubscriber


class ConsumerMessage(Message):
    ack_handle: Optional[str] = Field(
        default=None,
        description="Token or handle required to ack/nack/delete this message",
    )


class BaseConsumerConfig(BaseModel):
    type: Annotated[
        str,
        Field(
            description="Type of the consumer configuration",
            pattern=r"^[a-zA-Z0-9_-]+$",
        ),
    ]


@dataclass(slots=True)
class SuccessOutcome:
    duration_ms: float


@dataclass(slots=True)
class RetryOutcome:
    errors: List[RetryableEventError]


@dataclass(slots=True)
class FailureOutcome:
    exception_group: ExceptionGroup


DispatchOutcome = SuccessOutcome | RetryOutcome | FailureOutcome


class EventConsumer(ABC):
    """
    Abstract base for all event consumers.

    An EventConsumer is a SOURCE Connector — it receives messages from an
    external backend and dispatches them to registered EventSubscribers.

    The dispatch lifecycle is instrumented through DispatchHooks, which
    observe each stage (receive → handled/failed/retried) without modifying
    this class — Open/Closed Principle applied. Attach hooks via add_hook()
    before calling connect().

    Subclasses implement start(), stop(), ack(), and nack().
    """

    def __init__(self, config: BaseConsumerConfig) -> None:
        self._config = config
        self._subscribers: Set[EventSubscriber] = set()
        self._subscription_lock = Lock()
        self._dispatch_hooks: List[DispatchHook] = []

    @property
    def name(self) -> str:
        return self._config.type

    def add_hook(self, hook: DispatchHook) -> None:
        """Attach a DispatchHook to observe this consumer's dispatch lifecycle."""
        self._dispatch_hooks.append(hook)

    def remove_hook(self, hook: DispatchHook) -> None:
        self._dispatch_hooks = [h for h in self._dispatch_hooks if h is not hook]

    def subscribe(self, subscriber: EventSubscriber) -> None:
        with self._subscription_lock:
            self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber) -> None:
        """
        Discard a handler (subscriber).

        Args:
            subscriber (EventSubscriber): The subscriber to remove.
        """
        with self._subscription_lock:
            self._subscribers.discard(subscriber)

    async def dispatch(self, message: Message) -> None:
        """
        Dispatch a message to all subscribers.

        Lifecycle:

            on_receive
                  ▼
            subscribers
                  ▼
         determine outcome
                  ▼
            hooks + ack/nack
        """

        start = time.monotonic()

        try:
            await self._safe_notify_hooks(
                "on_receive",
                message,
            )

            if not self._subscribers:
                logger.warning(
                    f"No subscribers registered for " f"{self.name} event {message.id}"
                )

                await self.ack(message)
                return

            subscriber_results = await self._execute_subscribers(message)

            duration_ms = (time.monotonic() - start) * 1000

            outcome = self._determine_outcome(
                subscriber_results,
                duration_ms,
                message,
            )

            await self._handle_outcome(
                outcome,
                message,
            )

        except Exception:
            logger.exception(
                f"Dispatcher failed unexpectedly for " f"{self.name} event {message.id}"
            )

            raise

    async def _execute_subscribers(
        self,
        message: Message,
    ) -> dict[str, Any]:
        """
        Execute all subscribers concurrently and
        preserve subscriber identity.
        """

        results = await asyncio.gather(
            *(subscriber(message) for subscriber in self._subscribers),
            return_exceptions=True,
        )

        return {
            self._subscriber_name(subscriber): result
            for subscriber, result in zip(
                self._subscribers,
                results,
                strict=True,
            )
        }

    def _determine_outcome(
        self,
        results: dict[str, Any],
        duration_ms: float,
        message: Message,
    ) -> DispatchOutcome:
        """
        Resolve subscriber results into a single
        dispatch outcome.
        """

        retryable_errors: List[RetryableEventError] = []
        exceptions: List[Exception] = []

        for subscriber_name, result in results.items():
            if isinstance(
                result,
                RetryableEventError,
            ):
                logger.warning(
                    f"Subscriber '{subscriber_name}' "
                    f"requested retry for "
                    f"{self.name} event {message.id}"
                )
                retryable_errors.append(result)
                continue

            if isinstance(result, Exception):
                logger.error(
                    f"Subscriber '{subscriber_name}' "
                    f"failed for "
                    f"{self.name} event {message.id}: "
                    f"{result}"
                )

                exceptions.append(result)

        if retryable_errors:
            return RetryOutcome(
                errors=retryable_errors,
            )

        if exceptions:
            return FailureOutcome(
                exception_group=ExceptionGroup(
                    f"{self.name} event " f"{message.id} failed",
                    exceptions,
                )
            )

        return SuccessOutcome(
            duration_ms=duration_ms,
        )

    async def _handle_outcome(
        self,
        outcome: DispatchOutcome,
        message: Message,
    ) -> None:
        match outcome:
            case RetryOutcome(errors=errors):
                logger.debug(f"{self.name} event " f"{message.id} " f"will be retried")

                await self._safe_notify_hooks(
                    "on_retry",
                    message,
                    errors=errors,
                )

                await self.nack(
                    message,
                    requeue=True,
                )

            case FailureOutcome(exception_group=group):
                logger.error(f"{self.name} event " f"{message.id} failed: " f"{group}")

                await self._safe_notify_hooks(
                    "on_failure",
                    message,
                    error=group,
                )

                await self.ack(message)

            case SuccessOutcome(duration_ms=duration_ms):
                await self._safe_notify_hooks(
                    "on_complete",
                    message,
                    duration_ms=duration_ms,
                )

                await self.ack(message)

    async def _safe_notify_hooks(
        self,
        event: str,
        message: Message,
        **kwargs: Any,
    ) -> None:
        """
        Hook failures should never affect
        message acknowledgement.
        """

        try:
            await self._notify_hooks(
                event,
                message,
                **kwargs,
            )

        except Exception:
            logger.exception(
                f"Hook '{event}' failed for " f"{self.name} event " f"{message.id}"
            )

    @staticmethod
    def _subscriber_name(
        subscriber: Any,
    ) -> str:
        return getattr(
            subscriber,
            "__qualname__",
            repr(subscriber),
        )

    async def _notify_hooks(self, stage: str, message: Message, **kwargs: Any) -> None:
        """
        Notify all dispatch hooks of the event lifecycle stage.

        Args:
            stage: The stage of the event lifecycle.
            message: The message to notify the hooks about.
            **kwargs: Additional keyword arguments to pass to the hook.
        """
        for hook in self._dispatch_hooks:
            try:
                await getattr(hook, stage)(message, self.name, **kwargs)
            except Exception as exc:
                logger.warning(
                    f"[{self.name}] Hook {hook.__class__.__name__}.{stage} raised: {exc}"
                )

    @abstractmethod
    async def start(self) -> None:
        """
        Begin consuming events from the event source.

        This method should be implemented to start the event loop or background
        process that listens for incoming events and dispatches them to the
        registered subscribers.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Stop consuming events and perform any necessary cleanup.

        This method should be implemented to halt event processing, release
        resources, and ensure that no further events are delivered to subscribers.
        """
        ...

    @abstractmethod
    async def ack(self, message: Message) -> None:
        """
        Acknowledge the receipt of an event.

        This method should be implemented to acknowledge the receipt of an event,
        such as confirming that the event has been processed successfully.

        Args:
            message: The message to ack.
        """
        pass

    @abstractmethod
    async def nack(self, message: Message, requeue: bool = False) -> None:
        """
        Negative acknowledge the receipt of an event.

        This method should be implemented to negatively acknowledge the receipt of an event,
        such as indicating that the event was not processed successfully. If requeue is True,
        the message will be requeued for re-processing.

        Args:
            message: The message to nack.
            requeue: Whether to requeue the message.
        """
        pass
