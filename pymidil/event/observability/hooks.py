from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pymidil.event.core import Delivery, Event


@dataclass(slots=True)
class PublishRecord:
    """Context for one publish, handed to :class:`ProducerHook` observers.

    The produce-side counterpart to a :class:`~pymidil.event.core.Delivery`: it
    carries the typed :class:`~pymidil.event.core.Event` being published (so an
    observer reads ``record.event.type`` / ``.time`` / ``.dedup_key`` off typed
    fields, symmetric with the consumer's ``delivery.event``), the destination,
    the transport delivery id (known only after the send), and how long the
    publish took.
    """

    destination: str
    event: "Event"
    message_id: Optional[str] = None
    duration_ms: Optional[float] = None


class ProducerHook:
    """Extension point for observing the publish lifecycle — the produce-side
    twin of :class:`DispatchHook`. Attach via ``EventProducer.add_hook``.

    No-ops by default; override only the stages you care about. Hook failures
    must never break a publish (the producer guards each call).
    """

    async def on_publish(self, record: PublishRecord, producer_name: str) -> None:
        """Called after a message is durably accepted by the broker."""
        pass

    async def on_publish_error(
        self, record: PublishRecord, producer_name: str, error: Exception
    ) -> None:
        """Called when the publish itself failed (the broker never accepted it)."""
        pass


class DispatchHook:
    """Extension point for observing the full dispatch lifecycle.

    Attach hooks to an ``EventConsumer`` via ``add_hook()`` to instrument event
    flow without modifying consumer or subscriber code — the Open/Closed
    Principle. Every stage receives the :class:`~pymidil.event.core.Delivery`
    (which carries the ``event`` and the transport context), so a hook reads
    one well-typed shape — never a loose message bag.

    All methods are no-ops by default; override only the stages you care about.
    """

    async def on_receive(self, delivery: "Delivery", consumer_name: str) -> None:
        """Called immediately when a delivery arrives at the consumer."""
        pass

    async def on_complete(
        self, delivery: "Delivery", consumer_name: str, duration_ms: float
    ) -> None:
        """Called after all subscribers handled the event without error."""
        pass

    async def on_failure(
        self, delivery: "Delivery", consumer_name: str, error: Exception
    ) -> None:
        """Called when one or more subscribers raised a non-retryable error."""
        pass

    async def on_retry(
        self, delivery: "Delivery", consumer_name: str, errors: list
    ) -> None:
        """Called when the event is being requeued due to a RetryableEventError."""
        pass

    async def on_dead_letter(
        self,
        delivery: "Delivery",
        consumer_name: str,
        error: Exception | None = None,
    ) -> None:
        """Called when an event is moved to a dead-letter queue."""
        pass

    async def on_duplicate(self, delivery: "Delivery", consumer_name: str) -> None:
        """Called when a duplicate delivery is short-circuited by idempotency."""
        pass
