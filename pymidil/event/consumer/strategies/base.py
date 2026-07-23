from __future__ import annotations

import asyncio
import time
from abc import abstractmethod
from threading import Lock
from typing import Annotated, Any, Dict, List, Mapping, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field
from dataclasses import dataclass

from pymidil.event.acknowledgement import Acknowledger
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.idempotency.policy import IdempotencyPolicy
from pymidil.event.message import Message
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.otel import consumer_span
from pymidil.event.subscriber.base import EventSubscriber


class ConsumerMessage(Message):
    """An inbound message as received from a pull transport.

    Adds the delivery context the base :class:`Message` deliberately omits: the
    ``ack_handle`` needed to acknowledge/redeliver, and ``metadata`` — the broker's
    delivery attributes/headers (SQS message+system attributes, etc.). Consumers
    read trace context out of ``metadata`` via their ``carrier()`` adapter.
    """

    ack_handle: Optional[str] = Field(
        default=None,
        description="Token or handle required to ack/nack/delete this message",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Broker delivery attributes/headers (e.g. SQS message attributes)",
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


class EventConsumer(Acknowledger):
    """
    Abstract base for all event consumers.

    An EventConsumer is a SOURCE Connector — it receives messages from an
    external backend and dispatches them to registered EventSubscribers.

    A consumer *is* an :class:`Acknowledger`: dispatch resolves each outcome into
    a disposition (``ack`` / ``retry`` / ``dlq``) and calls it on the consumer's
    acknowledger, which defaults to ``self``. Inject a different one with
    ``use_acknowledger`` when a disposition (typically ``dlq``) must vary
    independently of the ingress transport.

    The dispatch lifecycle is instrumented through DispatchHooks, which observe
    each stage without modifying this class — Open/Closed Principle. Subclasses
    implement start(), stop(), and (for pull transports) ack()/retry()/dlq().
    """

    def __init__(
        self,
        config: BaseConsumerConfig,
        *,
        idempotency: Optional[IdempotencyPolicy] = None,
        acknowledger: Optional[Acknowledger] = None,
    ) -> None:
        self._config = config
        self._subscribers: Set[EventSubscriber] = set()
        self._subscription_lock = Lock()
        self._dispatch_hooks: List[DispatchHook] = []
        self._idempotency: Optional[IdempotencyPolicy] = idempotency
        self._acknowledger: Acknowledger = acknowledger or self

    @property
    def name(self) -> str:
        return self._config.type

    def add_hook(self, hook: DispatchHook) -> None:
        """Attach a DispatchHook to observe this consumer's dispatch lifecycle."""
        self._dispatch_hooks.append(hook)

    def remove_hook(self, hook: DispatchHook) -> None:
        self._dispatch_hooks = [h for h in self._dispatch_hooks if h is not hook]

    def use_idempotency(self, policy: IdempotencyPolicy) -> None:
        """Enable consumer-level deduplication for every subscriber via ``policy``."""
        self._idempotency = policy

    def use_acknowledger(self, acknowledger: Acknowledger) -> None:
        """Override how dispositions are applied (e.g. dead-letter to a store)."""
        self._acknowledger = acknowledger

    def carrier(self, message: Message) -> Mapping[str, str]:
        """The trace-propagation carrier for this message.

        Transports override this to expose their native header mechanism (SQS
        message attributes, HTTP headers, …). The default is empty — no
        propagation — so generic dispatch never reaches into a transport-specific
        ``Message`` field.
        """
        return {}

    def _idempotency_key(self, message: Message) -> Optional[str]:
        """The dedup key for this message, or None when idempotency is disabled."""
        if self._idempotency is None:
            return None
        return self._idempotency.key_fn(message)

    async def _release_claim(self, key: str) -> None:
        if self._idempotency is not None:
            await self._idempotency.store.release(key)

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
        """Continue the incoming trace, then run the dispatch lifecycle (A1).

        The trace is extracted from the transport's carrier (``carrier()``) and a
        child CONSUMER span is bound for the whole lifecycle, so subscribers and
        dispatch hooks observe a coherent, correlated trace across broker hops.
        A missing upstream context is flagged as a discontinuity rather than
        silently rooting a new trace.
        """
        with consumer_span(self.carrier(message), self.name):
            await self._dispatch(message)

    async def _dispatch(self, message: Message) -> None:
        """
        Dispatch a message to all subscribers.

        Lifecycle:

            idempotency claim
                  ▼
            on_receive
                  ▼
            subscribers
                  ▼
         determine outcome
                  ▼
            hooks + ack/nack

        Deduplication is applied here, at the dispatch boundary, so it covers
        every subscriber regardless of type. A duplicate delivery is acked and
        reported via the on_duplicate hook without running any subscriber; the
        claim is released if processing does not succeed, so a redelivery can
        be re-processed.
        """

        key = self._idempotency_key(message)
        if key is not None:
            policy = self._idempotency
            assert policy is not None  # key only resolves when a policy is configured
            if not await policy.store.claim(key, policy.ttl_seconds):
                logger.debug(
                    f"{self.name} duplicate {message.id} (key={key}) short-circuited"
                )
                await self._safe_notify_hooks("on_duplicate", message)
                await self._acknowledger.ack(message)
                return

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

                await self._acknowledger.ack(message)
                return

            subscriber_results = await self._execute_subscribers(message)

            duration_ms = (time.monotonic() - start) * 1000

            outcome = self._determine_outcome(
                subscriber_results,
                duration_ms,
                message,
            )

            # Keep the claim only for a successful outcome; release on
            # retry/failure so a redelivery is free to re-process.
            if key is not None and not isinstance(outcome, SuccessOutcome):
                await self._release_claim(key)

            await self._handle_outcome(
                outcome,
                message,
            )

        except Exception:
            if key is not None:
                await self._release_claim(key)
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

                await self._acknowledger.retry(message)

            case FailureOutcome(exception_group=group):
                logger.error(f"{self.name} event " f"{message.id} failed: " f"{group}")

                # Non-retryable failure → dead-letter (diverted for inspection),
                # reported once via on_dead_letter. The DLQ envelope carries the
                # failure reason/class.
                await self._safe_notify_hooks(
                    "on_dead_letter",
                    message,
                    error=group,
                )

                await self._acknowledger.dlq(message, error=group)

            case SuccessOutcome(duration_ms=duration_ms):
                await self._safe_notify_hooks(
                    "on_complete",
                    message,
                    duration_ms=duration_ms,
                )

                await self._acknowledger.ack(message)

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
