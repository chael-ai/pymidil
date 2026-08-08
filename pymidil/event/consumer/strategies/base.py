from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from threading import Lock
from typing import Annotated, Any, List, Optional, Set

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from dataclasses import dataclass

from pymidil.event.core import Delivery, Event
from pymidil.exceptions import ConsumerError, RetryableEventError
from pymidil.event.idempotency.policy import IdempotencyPolicy
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.otel import consumer_span
from pymidil.event.retry import RetryConfig, TransportCapabilities, validate_policy
from pymidil.event.subscriber.base import EventSubscriber, ManualSubscriber


class BaseConsumerConfig(BaseModel):
    # Unknown keys refuse loudly: a stale config (e.g. the pre-retry-policy
    # backoff_base_delay) must fail at parse, not be silently dropped.
    model_config = ConfigDict(extra="forbid")

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
        # Single-authority mode: when set, this subscriber owns settlement and
        # the aggregation path is bypassed entirely (see subscribe()).
        self._manual: Optional[ManualSubscriber] = None
        self._subscription_lock = Lock()
        self._dispatch_hooks: List[DispatchHook] = []
        self._idempotency: Optional[IdempotencyPolicy] = idempotency
        # The retry policy, when the config carries one (pull transports).
        # The dispatcher DECIDES from it (budget + delay); transports enact.
        retry: Optional[RetryConfig] = getattr(config, "retry", None)
        if retry is not None:
            # Validate where the policy is ARMED, not one level below — any
            # config that carries a retry policy gets checked against what
            # this transport can physically do.
            validate_policy(retry, self.capabilities, config.type)
        self._retry_config = retry
        self._retry_backoff = retry.build_backoff() if retry is not None else None

    @property
    def capabilities(self) -> TransportCapabilities:
        """What this consumer's transport can physically do. Conservative by
        default; transports override to claim more (and are validated on it)."""
        return TransportCapabilities()

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

    def subscribe(self, subscriber: EventSubscriber | ManualSubscriber) -> None:
        """Register a subscriber, enforcing the settlement-authority topology.

        A consumer runs in exactly one of two modes, decided by what you
        subscribe: AGGREGATION (any number of ``EventSubscriber``s; the
        dispatcher merges their outcomes and settles) or SINGLE-AUTHORITY
        (exactly one ``ManualSubscriber``, which settles the delivery itself).
        Mixing the two would reintroduce the settlement race the modes exist
        to prevent, so it refuses loudly at wiring time.
        """
        with self._subscription_lock:
            if isinstance(subscriber, ManualSubscriber):
                if self._manual is not None:
                    raise ConsumerError(
                        f"{self.name} already has a settlement authority "
                        f"({type(self._manual).__name__}) — single-authority "
                        f"mode is exclusive: one ManualSubscriber per consumer."
                    )
                if self._subscribers:
                    raise ConsumerError(
                        f"{self.name} has {len(self._subscribers)} aggregation "
                        f"subscriber(s) — a ManualSubscriber cannot share a "
                        f"consumer: its whole contract is being the SOLE "
                        f"settlement authority. Use a dedicated consumer."
                    )
                self._manual = subscriber
                return
            if self._manual is not None:
                raise ConsumerError(
                    f"{self.name} is in single-authority mode "
                    f"({type(self._manual).__name__} owns settlement) — "
                    f"aggregation subscribers cannot join it. Use a dedicated "
                    f"consumer."
                )
            self._subscribers.add(subscriber)

    def unsubscribe(self, subscriber: EventSubscriber | ManualSubscriber) -> None:
        """
        Discard a handler (subscriber).

        Args:
            subscriber (EventSubscriber): The subscriber to remove.
        """
        with self._subscription_lock:
            if subscriber is self._manual:
                self._manual = None
                return
            if isinstance(subscriber, EventSubscriber):
                self._subscribers.discard(subscriber)

    @property
    def has_subscribers(self) -> bool:
        """Whether anything will process deliveries — either mode."""
        return bool(self._subscribers) or self._manual is not None

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

        if self._manual is not None:
            await self._dispatch_manual(delivery)
            return

        event = delivery.event
        key = self._dedup_key(event)
        start = time.monotonic()

        try:
            if key is not None and not await self._claim_delivery(key, delivery):
                return

            await self._safe_notify_hooks("on_receive", delivery)

            if not self._subscribers:
                # NEVER ack here: acking would DELETE a message nobody
                # processed. A consumer polling with zero subscribers is a
                # wiring bug — leave the delivery unsettled (it redelivers)
                # and say so loudly.
                logger.error(
                    f"{self.name}: no subscribers registered — leaving event "
                    f"{event.id} unsettled for redelivery. Subscribe before "
                    f"start(), or stop this consumer."
                )
                return

            subscriber_results = await self._execute_subscribers(event)

            duration_ms = (time.monotonic() - start) * 1000

            outcome = self._determine_outcome(subscriber_results, duration_ms, event)
            outcome = self._bound_retries(outcome, delivery)

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

    async def _claim_delivery(self, key: str, delivery: Delivery) -> bool:
        """Take the idempotency claim; short-circuit (report + ack) a duplicate.

        Returns True when the delivery is claimed and should proceed. Shared by
        both dispatch modes — dedup is a consumer-level policy, orthogonal to
        who owns settlement.
        """
        policy = self._idempotency
        assert policy is not None  # key resolves only with a policy
        if await policy.store.claim(key, policy.ttl_seconds):
            return True
        logger.debug(
            f"{self.name} duplicate {delivery.event.id} (key={key}) short-circuited"
        )
        await self._safe_notify_hooks("on_duplicate", delivery)
        await delivery.ack()
        return False

    async def _dispatch_manual(self, delivery: Delivery) -> None:
        """Single-authority dispatch: the ManualSubscriber owns settlement.

        The dispatcher's remaining jobs here are the ones a handler cannot
        perform for itself:

        * dedup (consumer-level policy, same as aggregation mode);
        * TRUTHFUL REPORTING — after the handler returns, the latch
          (``delivery.disposition``) is the record of what physically
          happened, and the matching lifecycle hook is emitted from it, so
          manual settlement never bypasses the Observatory;
        * the exception backstop — an unsettled raise is still an outcome and
          routes through the normal machinery (retry budget, declared fate);
        * the deferral rule — an unsettled clean return is a DECISION, not a
          bug: the delivery is left for the transport to redeliver (this is
          what makes settle-later-on-callback and checkpoint patterns safe —
          a forgotten ack costs a redelivery, never a lost message).
        """
        manual = self._manual
        assert manual is not None
        event = delivery.event
        key = self._dedup_key(event)
        start = time.monotonic()

        try:
            if key is not None and not await self._claim_delivery(key, delivery):
                return

            await self._safe_notify_hooks("on_receive", delivery)

            try:
                await manual.handle(delivery)
            except Exception as exc:
                if delivery.settled:
                    # The latch is the truth; the exception is post-settlement
                    # noise — report the settlement, surface the error loudly.
                    logger.error(
                        f"{self.name}: {type(manual).__name__} settled event "
                        f"{event.id} as '{delivery.disposition}' and then "
                        f"raised: {exc!r}"
                    )
                    await self._report_settlement(delivery, start)
                else:
                    outcome = self._determine_outcome(
                        {type(manual).__name__: exc},
                        (time.monotonic() - start) * 1000,
                        event,
                    )
                    outcome = self._bound_retries(outcome, delivery)
                    await self._handle_outcome(outcome, delivery)
                if key is not None and delivery.disposition != "ack":
                    await self._release_claim(key)
                return

            if delivery.settled:
                await self._report_settlement(delivery, start)
            else:
                logger.debug(
                    f"{self.name}: {type(manual).__name__} deferred event "
                    f"{event.id} (returned unsettled) — the transport will "
                    f"redeliver"
                )
            if key is not None and delivery.disposition != "ack":
                # Deferred or non-terminal: a redelivery must be free to
                # re-process; only a completed (acked) delivery keeps its claim.
                await self._release_claim(key)

        except Exception:
            if key is not None:
                await self._release_claim(key)
            logger.exception(
                f"Dispatcher failed unexpectedly for {self.name} event {event.id}"
            )
            raise

    async def _report_settlement(self, delivery: Delivery, start: float) -> None:
        """Emit the lifecycle hook matching what the latch says PHYSICALLY
        happened — reporting-from-the-record, the manual-mode counterpart of
        ``_handle_outcome``'s decide-then-act."""
        duration_ms = (time.monotonic() - start) * 1000
        match delivery.disposition:
            case "ack":
                await self._safe_notify_hooks(
                    "on_complete", delivery, duration_ms=duration_ms
                )
            case "retry":
                await self._safe_notify_hooks("on_retry", delivery, errors=[])
            case "dlq":
                await self._safe_notify_hooks(
                    "on_dead_letter", delivery, error=delivery.disposition_error
                )

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

    def _bound_retries(
        self, outcome: DispatchOutcome, delivery: Delivery
    ) -> DispatchOutcome:
        """Enforce the retry budget: a retryable outcome whose attempts are
        spent becomes terminal, with a reason that says so. Attempt counting is
        the transport's (SQS: ApproximateReceiveCount — a ceiling on
        *deliveries*, not handler runs)."""
        if not isinstance(outcome, RetryOutcome) or self._retry_config is None:
            return outcome
        budget = self._retry_config.max_attempts
        if budget is None or delivery.retry_count < budget:
            return outcome
        return FailureOutcome(
            exception_group=ExceptionGroup(
                f"retry budget exhausted after {delivery.retry_count} "
                f"attempts (max_attempts={budget})",
                outcome.errors,
            )
        )

    def _retry_delay(self, delivery: Delivery) -> float:
        """The policy-decided redelivery delay for this attempt (0.0 without a
        policy — transports that cannot delay ignore it anyway)."""
        if self._retry_backoff is None:
            return 0.0
        return self._retry_backoff.next_delay(delivery.retry_count)

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
                await delivery.retry(self._retry_delay(delivery))

            case FailureOutcome(exception_group=group):
                # Terminal failure → the consumer's DECLARED fate, with
                # telemetry that matches the physical action (never a DLQ
                # status for a message that is not physically diverted).
                match delivery.terminal_action:
                    case "dlq":
                        logger.error(f"{self.name} event {event.id} failed: {group}")
                        await self._safe_notify_hooks(
                            "on_dead_letter", delivery, error=group
                        )
                        await delivery.dlq(group)
                    case "requeue":
                        logger.error(
                            f"{self.name} event {event.id} failed terminally; "
                            f"requeueing per declared fate (broker redrive owns "
                            f"termination): {group}"
                        )
                        await self._safe_notify_hooks(
                            "on_retry", delivery, errors=[group]
                        )
                        await delivery.retry(self._retry_delay(delivery))
                    case "drop":
                        logger.error(
                            f"{self.name} event {event.id} failed terminally; "
                            f"dropping per declared fate (explicit data "
                            f"loss): {group}"
                        )
                        await self._safe_notify_hooks(
                            "on_failure", delivery, error=group
                        )
                        await delivery.ack()

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
