from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from pymidil.event.observability.protocols import MessageProtocol


@dataclass(slots=True)
class PublishRecord:
    """Context for one publish, handed to :class:`ProducerHook` observers.

    Mirrors the ``message`` a :class:`DispatchHook` receives, but for the produce
    side: the transport delivery id (known only after the send), the destination,
    the payload and the headers (event_type / idempotency_key / traceparent ride
    in ``metadata``), plus how long the publish took.
    """

    destination: str
    payload: Any
    metadata: Mapping[str, Any] = field(default_factory=dict)
    message_id: Optional[str] = None
    duration_ms: Optional[float] = None


class ProducerHook:
    """Extension point for observing the publish lifecycle — the produce-side
    twin of :class:`DispatchHook`. Attach via ``EventProducer.add_hook``.

    No-ops by default; override only the stages you care about. Hook failures
    must never break a publish (the producer guards each call).
    """

    async def on_publish(self, record: PublishRecord, producer_name: str) -> None:
        """
        Called after a message is durably accepted by the broker.

        Args:
            record (PublishRecord): The publish record.
            producer_name (str): The name of the producer.
        """
        pass

    async def on_publish_error(
        self, record: PublishRecord, producer_name: str, error: Exception
    ) -> None:
        """
        Called when the publish itself failed (the broker never accepted it).

        Args:
            record (PublishRecord): The publish record.
            producer_name (str): The name of the producer.
            error (Exception): The error that occurred.
        """
        pass


class DispatchHook:
    """
    Extension point for observing the full event dispatch lifecycle.

    Attach hooks to an EventConsumer via add_hook() to instrument
    message flow without modifying consumer or subscriber code —
    a clean application of the Open/Closed Principle.

    All methods are no-ops by default. Override only the stages you care
    about. Multiple hooks may be attached; they are called in order.
    """

    async def on_receive(self, message: MessageProtocol, consumer_name: str) -> None:
        """Called immediately when a message arrives at the consumer."""
        pass

    async def on_complete(
        self,
        message: MessageProtocol,
        consumer_name: str,
        duration_ms: float,
    ) -> None:
        """Called after all subscribers handled the message without error."""
        pass

    async def on_failure(
        self,
        message: MessageProtocol,
        consumer_name: str,
        error: Exception,
    ) -> None:
        """Called when one or more subscribers raised a non-retryable error."""
        pass

    async def on_retry(
        self,
        message: MessageProtocol,
        consumer_name: str,
        errors: list,
    ) -> None:
        """Called when the message is being requeued due to a RetryableEventError."""
        pass

    async def on_dead_letter(
        self,
        message: MessageProtocol,
        consumer_name: str,
        error: Exception | None = None,
    ) -> None:
        """Called when a message is moved to a dead-letter queue."""
        pass

    async def on_duplicate(
        self,
        message: MessageProtocol,
        consumer_name: str,
    ) -> None:
        """Called when a duplicate delivery is short-circuited by idempotency."""
        pass
