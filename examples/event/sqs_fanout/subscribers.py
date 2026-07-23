"""The business logic, as :class:`EventSubscriber` classes.

A subscriber is *how you handle an event* in pymidil. Rather than passing a bare
function (``FunctionSubscriber``), each service here subclasses ``EventSubscriber``
and implements the lifecycle the base class orchestrates on every message:

    should_handle(event)   → skip events that don't apply (validation/filtering)
    authorize(event)       → (default True) gate on identity/permissions
    handle(event)          → do the work; raise to signal failure
    on_success / on_error  → observe the outcome (log, metrics, cleanup)

Raising from ``handle`` is meaningful: a :class:`RetryableEventError` tells the
consumer to leave the message on the queue for redelivery; any other exception
is a terminal failure and the consumer dead-letters the message. That single
rule is what turns the loyalty branch red while its siblings stay green.
"""

from __future__ import annotations

import asyncio
import random
from typing import Sequence

from loguru import logger

from pymidil.event import EventSubscriber, Message, SQSProducer
from pymidil.event.exceptions import NonRetryableEventError, RetryableEventError

from .messages import order_id, receive_count


async def _do_work() -> None:
    """Stand in for a real unit of work (a DB write, an API call, …)."""
    await asyncio.sleep(random.uniform(0.02, 0.15))


class OrderSubscriber(EventSubscriber):
    """``order-svc`` — consumes one ``OrderPaid`` and fans it out into N branches.

    This is the one-into-many step: a producer used *inside* a subscriber, so a
    single order becomes a branching trace instead of a straight line. Each
    branch keeps the order id and a per-branch idempotency key.
    """

    def __init__(self, branches: Sequence[tuple[str, SQSProducer]]) -> None:
        self._branches = branches

    async def should_handle(self, event: Message) -> bool:
        # Only fan out well-formed orders — anything without an id is ignored
        # before it ever reaches handle().
        return isinstance(event.body, dict) and "order_id" in event.body

    async def handle(self, event: Message) -> None:
        order = order_id(event)
        await _do_work()
        for event_type, producer in self._branches:
            await producer.publish(
                {"order_id": order, "event_type": event_type},
                metadata={
                    "event_type": event_type,
                    "idempotency_key": f"{order}:{event_type}",
                },
            )
        logger.debug("order-svc fanned {} into {} branches", order, len(self._branches))


class LeafSubscriber(EventSubscriber):
    """A downstream branch (shipping / billing / receipt).

    Does its unit of work and reports the outcome through the success/error
    hooks — the well-behaved baseline the flaky branch overrides.
    """

    def __init__(self, service: str) -> None:
        self.service = service

    async def handle(self, event: Message) -> None:
        await _do_work()

    async def on_success(self, event: Message) -> None:
        logger.debug("{} handled {}", self.service, order_id(event))

    async def on_error(self, event: Message, error: Exception) -> None:
        logger.warning("{} failed {}: {}", self.service, order_id(event), error)


class FlakyLoyaltySubscriber(LeafSubscriber):
    """``loyalty-svc`` — a realistic partial failure.

    About ``failure_rate``% of orders hit a "busy" backend. Those are retried a
    couple of times (``RetryableEventError`` → the message stays on the queue and
    SQS redelivers it), then given up on (``NonRetryableEventError`` → the
    consumer dead-letters it). The result is the single red branch in an
    otherwise-green fan-out trace: *paid and shipped, but loyalty points failed.*
    """

    def __init__(
        self, service: str, *, failure_rate: int = 30, max_attempts: int = 3
    ) -> None:
        super().__init__(service)
        self._failure_rate = failure_rate
        self._max_attempts = max_attempts

    def _order_is_cursed(self, order: str) -> bool:
        # Deterministic per order, so a given order fails consistently across
        # its retries (a flaky *backend*, not a flaky coin-flip per delivery).
        return hash(order) % 100 < self._failure_rate

    async def handle(self, event: Message) -> None:
        await _do_work()
        order = order_id(event)
        if not self._order_is_cursed(order):
            return  # sails through like any healthy branch

        attempt = receive_count(event)
        if attempt < self._max_attempts:
            raise RetryableEventError(f"loyalty backend busy (attempt {attempt})")
        raise NonRetryableEventError("loyalty backend unavailable — giving up")
