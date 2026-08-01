from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from threading import Lock
from typing import Annotated, Any, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, Field
from dataclasses import dataclass

from pymidil.event.core import Delivery, Event
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.idempotency.policy import IdempotencyPolicy
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.otel import consumer_span
from pymidil.event.subscriber.base import EventSubscriber


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

    An EventConsumer is a SOURCE Connector — it receives a transport
    :class:`~pymidil.event.core.Delivery` (which carries the ``Event``) and
    dispatches the event to registered EventSubscribers.

    Disposition (``ack`` / ``retry`` / ``dlq``) lives on the ``Delivery`` — the
    transport attempt owns how it is settled — so dispatch resolves an outcome
    and calls it on the delivery, no per-consumer acknowledger casting.

    The dispatch lifecycle is instrumented through DispatchHooks, which observe
    each stage without modifying this class — Open/Closed Principle. Subclasses
    implement start() and stop(), and construct Deliveries from their transport.
    """

    def __init__(
        self,
        config: BaseConsumerConfig,
        *,
        idempotency: Optional[IdempotencyPolicy] = None,
    ) -> None:
        self._config = config
        self._subscribers: Set[EventSubscriber] = set()
        self._subscription_lock = Lock()
        self._dispatch_hooks: List[DispatchHook] = []
        self._idempotency: Optional[IdempotencyPolicy] = idempotency

    @property
    def name(self) -> str:
        return self._config.type

    def add_hook(self, hook: DispatchHook) -> None:
        """Attach a DispatchHook to observe this consumer's dispatch lifecycle."""
        self._dispatch_hooks.append(hook)

    def remove_hook(self, hook: DispatchHook) -> None:
        self._dispatch_hooks = [h for h in self._dispatch_hooks if h is not hook]

    def use_idempotency(self, policy: Optional[IdempotencyPolicy] = None) -> None:
        """Enable consumer-level deduplication for every subscriber.

        Zero-arg is the sensible default: an in-memory store keyed on the
        message's typed ``idempotency_key`` (falling back to its id). Pass a
        policy for a durable store (Redis) or a custom key function.
        """
        if policy is None:
            from pymidil.event.idempotency import (
                IdempotencyPolicy as _Policy,
                InMemoryIdempotencyStore,
            )

            policy = _Policy(InMemoryIdempotencyStore())
        self._idempotency = policy

    def _dedup_key(self, event: Event) -> Optional[str]:
        """The dedup key for this event, or None when idempotency is disabled.

        Honors a custom ``key_fn`` if the policy sets one; the default resolves
        to ``event.dedup_key`` (the override, else the logical id).
        """
        if self._idempotency is None:
            return None
        return self._idempotency.key_fn(event)

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

    async def dispatch(self, delivery: Delivery) -> None:
        """Continue the incoming trace, then run the dispatch lifecycle.

        The trace is extracted from the delivery's ``carrier()`` and a child
        CONSUMER span is bound for the whole lifecycle, so subscribers and
        dispatch hooks observe a coherent, correlated trace across broker hops.
        """
        with consumer_span(delivery.carrier(), self.name):
            await self._dispatch(delivery)

    async def _dispatch(self, delivery: Delivery) -> None:
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

        event = delivery.event
        key = self._dedup_key(event)
        if key is not None:
            policy = self._idempotency
            assert policy is not None  # key only resolves when a policy is configured
            if not await policy.store.claim(key, policy.ttl_seconds):
                logger.debug(
                    f"{self.name} duplicate {event.id} (key={key}) short-circuited"
                )
                await self._safe_notify_hooks("on_duplicate", delivery)
                await delivery.ack()
                return

        start = time.monotonic()

        try:
            await self._safe_notify_hooks("on_receive", delivery)

            if not self._subscribers:
                logger.warning(
                    f"No subscribers registered for {self.name} event {event.id}"
                )
                await delivery.ack()
                return

            subscriber_results = await self._execute_subscribers(event)

            duration_ms = (time.monotonic() - start) * 1000

            outcome = self._determine_outcome(subscriber_results, duration_ms, event)

            # Keep the claim only for a successful outcome; release on
            # retry/failure so a redelivery is free to re-process.
            if key is not None and not isinstance(outcome, SuccessOutcome):
                await self._release_claim(key)

            await self._handle_outcome(outcome, delivery)

        except Exception:
            if key is not None:
                await self._release_claim(key)
            logger.exception(
                f"Dispatcher failed unexpectedly for {self.name} event {event.id}"
            )
            raise

    async def _execute_subscribers(self, event: Event) -> dict[str, Any]:
        """Execute all subscribers concurrently, preserving subscriber identity.

        Each subscriber receives the event — nothing else; the outcome of a
        dispatch is decided by what subscribers return or raise.
        """
        # Snapshot once: the set may be mutated by subscribe()/unsubscribe()
        # while we await, and iterating it twice across that await would
        # mispair (or strict-zip-error) results against subscribers.
        subscribers = list(self._subscribers)
        results = await asyncio.gather(
            *(subscriber(event) for subscriber in subscribers),
            return_exceptions=True,
        )

        return {
            self._subscriber_name(subscriber): result
            for subscriber, result in zip(subscribers, results, strict=True)
        }

    def _determine_outcome(
        self,
        results: dict[str, Any],
        duration_ms: float,
        event: Event,
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
                    f"{self.name} event {event.id}"
                )
                retryable_errors.append(result)
                continue

            if isinstance(result, Exception):
                logger.error(
                    f"Subscriber '{subscriber_name}' "
                    f"failed for "
                    f"{self.name} event {event.id}: "
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
                    f"{self.name} event {event.id} failed",
                    exceptions,
                )
            )

        return SuccessOutcome(
            duration_ms=duration_ms,
        )

    async def _handle_outcome(
        self,
        outcome: DispatchOutcome,
        delivery: Delivery,
    ) -> None:
        event = delivery.event
        match outcome:
            case RetryOutcome(errors=errors):
                logger.debug(f"{self.name} event {event.id} will be retried")
                await self._safe_notify_hooks("on_retry", delivery, errors=errors)
                await delivery.retry()

            case FailureOutcome(exception_group=group):
                logger.error(f"{self.name} event {event.id} failed: {group}")
                # Non-retryable failure → dead-letter (diverted for inspection),
                # reported once via on_dead_letter.
                await self._safe_notify_hooks("on_dead_letter", delivery, error=group)
                await delivery.dlq(group)

            case SuccessOutcome(duration_ms=duration_ms):
                await self._safe_notify_hooks(
                    "on_complete", delivery, duration_ms=duration_ms
                )
                await delivery.ack()

    async def _safe_notify_hooks(
        self, stage: str, delivery: Delivery, **kwargs: Any
    ) -> None:
        """Hook failures never affect settlement of the delivery."""
        try:
            await self._notify_hooks(stage, delivery, **kwargs)
        except Exception:
            logger.exception(
                f"Hook '{stage}' failed for {self.name} event {delivery.event.id}"
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

    async def _notify_hooks(
        self, stage: str, delivery: Delivery, **kwargs: Any
    ) -> None:
        """Notify all dispatch hooks of the lifecycle ``stage`` with the delivery."""
        for hook in self._dispatch_hooks:
            try:
                await getattr(hook, stage)(delivery, self.name, **kwargs)
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
