"""The core event model for pymidil — defines Event and Delivery primitives.

- Event: an immutable, transport-agnostic business fact, designed to be serializable and to represent state changes in a system (CloudEvents-inspired).
- Delivery: represents a single attempt to deliver an Event over some transport, intentionally not serializable and may contain transport-specific metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping, Optional

from loguru import logger
from pydantic import BaseModel, Field

from pymidil.utils.time import utcnow


class Event(BaseModel):
    """
    Represents an immutable business fact, inspired by the CloudEvents specification.

    Event objects capture an occurrence in the system, with a unique identity,
    its source, type, and payload. Once created, an Event is not modified.
    This model is intended to be portable across transports and serializable
    for storage, routing, and replay.

    Attributes:
        id: A globally unique, transport-independent identifier for the event. Stable across all deliveries of this event.
        source: The system component or service that originated the event.
        type: The event's classification, e.g. 'order.created'.
        data: The payload of the event; arbitrary content associated with the event.
        subject: (Optional) Specific entity or resource in the source to which this event relates.
        time: Timestamp when the event occurred; set to the time of creation by default.
        datacontenttype: (Optional) MIME type of the payload, e.g. application/json.
        dataschema: (Optional) URI identifying the schema of the event's data.
        idempotency_key: (Optional) Secondary key for supporting de-duplication.
        extensions: (Optional) Extension fields for custom or transport-specific metadata.
    """

    id: str = Field(..., description="Logical identity — stable across every delivery")
    source: str = Field(
        ..., description="The context that produced the event (a service)"
    )
    type: str = Field(..., description="Event type, e.g. 'order.created'")
    data: Any = Field(default=None, description="The payload (CloudEvents 'data')")

    subject: Optional[str] = Field(
        default=None, description="The event's subject within its source (e.g. an id)"
    )
    time: datetime = Field(default_factory=utcnow, description="When the fact occurred")
    datacontenttype: Optional[str] = Field(
        default="application/json", description="Media type of ``data``"
    )
    dataschema: Optional[str] = Field(
        default=None, description="Schema URI for ``data``"
    )

    idempotency_key: Optional[str] = Field(default=None)
    extensions: dict[str, str] = Field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """
        Returns a deduplication key used by idempotent consumers.

        If an idempotency_key is present, it is used; otherwise the event's id is used.
        This allows consumers to safely deduplicate events even across delivery retries.
        """
        return self.idempotency_key or self.id


class Delivery(ABC):
    """
    Represents a single attempt to deliver an Event over a transport.

    The Delivery object encapsulates contextual metadata about a delivery attempt,
    such as when it was received and the Event being delivered. It provides
    transport-level settlement (ack/retry/dlq) semantics and trace carrier for
    distributed tracing.

    A delivery settles exactly once: the public verbs latch the first
    disposition and refuse later ones loudly (error log, no-op) — the physical
    disposition already happened, so a second one is always a bug. Settlement
    is called by the dispatcher, which aggregates every subscriber's outcome;
    transports implement the physical operations in ``_ack``/``_retry``/``_dlq``
    and may compose those primitives internally (e.g. SQS dead-lettering sends
    to the DLQ then deletes from the source).

    Attributes:
        event: The Event this delivery carries.
        received_at: The datetime when this delivery attempt was received/created.
    """

    event: Event
    received_at: datetime

    def __init__(self, event: Event, *, received_at: Optional[datetime] = None) -> None:
        self.event = event
        self.received_at = received_at or utcnow()
        self._disposition: Optional[str] = None

    @property
    def disposition(self) -> Optional[str]:
        """The disposition that settled this delivery (``"ack"`` | ``"retry"``
        | ``"dlq"``), or ``None`` while unsettled."""
        return self._disposition

    @property
    def settled(self) -> bool:
        """Whether a disposition has already been applied to this delivery."""
        return self._disposition is not None

    def _claim(self, disposition: str) -> bool:
        """Latch the first disposition; refuse (loudly) any later one."""
        if self._disposition is not None:
            logger.error(
                f"Delivery {self.transport_id} already settled as "
                f"'{self._disposition}' — refusing '{disposition}' "
                f"(one delivery settles exactly once)"
            )
            return False
        self._disposition = disposition
        return True

    async def ack(self) -> None:
        """Acknowledge successful handling of this delivery (first-wins latch)."""
        if self._claim("ack"):
            await self._ack()

    async def retry(self) -> None:
        """Make this event available for redelivery (first-wins latch)."""
        if self._claim("retry"):
            await self._retry()

    async def dlq(self, error: Optional[Exception] = None) -> None:
        """Divert this event to a dead-letter destination (first-wins latch)."""
        if self._claim("dlq"):
            await self._dlq(error)

    @property
    def transport_id(self) -> str:
        """
        Returns an identifier representing this physical delivery attempt.

        By default, this is the logical event id.
        Transport-specific implementations may override for per-attempt uniqueness.
        """
        return self.event.id

    @property
    def retry_count(self) -> int:
        """
        Returns the number of delivery attempts for this event.

        Defaults to 1 for stateless transports. Override in transports with attempt tracking.
        """
        return 1

    @abstractmethod
    async def _ack(self) -> None:
        """
        Physical acknowledgment — transport-specific.

        Never called directly; the latched :meth:`ack` is the entrypoint.
        Transports may call this primitive when composing dispositions.
        """

    @abstractmethod
    async def _retry(self) -> None:
        """
        Physical redelivery request — transport-specific.

        Never called directly; the latched :meth:`retry` is the entrypoint.
        """

    @abstractmethod
    async def _dlq(self, error: Optional[Exception] = None) -> None:
        """
        Physical dead-lettering — transport-specific.

        Never called directly; the latched :meth:`dlq` is the entrypoint.
        """

    def carrier(self) -> Mapping[str, str]:
        """
        Returns a mapping of trace context headers for OpenTelemetry extraction.

        Override in transports carrying distributed tracing metadata.
        """
        return {}


class NoAckDelivery(Delivery):
    """
    Delivery for transports that do not support broker-side settlement.

    This delivery implementation is for push transports or simple brokerless
    integrations (e.g., webhooks, WebSocket) where ack/retry/dlq operations are no-ops.
    """

    async def _ack(self) -> None:
        """No-op: No acknowledgment necessary for this delivery type."""
        return None

    async def _retry(self) -> None:
        """No-op: Retry is not supported for this delivery type."""
        return None

    async def _dlq(self, error: Optional[Exception] = None) -> None:
        """No-op: No dead-letter queue for this delivery type."""
        return None
