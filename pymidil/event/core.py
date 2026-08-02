"""The core event model for pymidil — defines Event and Delivery primitives.

- Event: an immutable, transport-agnostic business fact, designed to be serializable and to represent state changes in a system (CloudEvents-inspired).
- Delivery: represents a single attempt to deliver an Event over some transport, intentionally not serializable and may contain transport-specific metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Literal, Mapping, Optional

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
    specversion: str = Field(default="1.0", description="Specification version")

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


class Settlement(ABC):
    """The single abstract write contract: physical settlement operations for
    one delivery attempt, plus the declared fate of terminal failures.

    The split of responsibilities: the *Delivery* reads (identity, attempt
    count, trace carrier) and owns the settle-once latch; the *Settlement*
    writes (the broker calls) and declares where terminal failures go. The
    name follows the industry vocabulary — AMQP's *disposition* is the
    settlement outcome/state (which is what ``Delivery.disposition`` records);
    the object that performs the physical operations is the settlement.
    """

    @property
    @abstractmethod
    def terminal_action(self) -> Literal["dlq", "requeue", "drop"]:
        """Where terminal failures go — declared, never guessed.

        The dispatcher consults this to route a failure outcome (a
        non-retryable error, or a spent retry budget) AND to emit telemetry
        that matches the physical action: ``dlq`` diverts, ``requeue`` leaves
        the event to redeliver (the broker's own redrive owns termination),
        ``drop`` removes it (explicit data loss). Abstract so every settlement
        must declare its fate at write time — no silent inheritance.
        """

    @abstractmethod
    async def ack(self) -> None:
        """Physically acknowledge (remove) the delivery at the broker."""

    @abstractmethod
    async def retry(self, delay: float) -> None:
        """Physically schedule redelivery after ``delay`` seconds (policy-decided)."""

    @abstractmethod
    async def dlq(
        self,
        event: Event,
        carrier: Mapping[str, str],
        error: Optional[Exception] = None,
    ) -> None:
        """Physically divert to the dead-letter destination, preserving the
        wire carrier so a later replay links back."""


class NoSettlement(Settlement):
    """The settlement of transports with no broker-side settlement (push,
    observed): every write is a no-op, and the truthful fate of a terminal
    failure is ``drop`` — the event is simply gone from this consumer's
    perspective."""

    @property
    def terminal_action(self) -> Literal["dlq", "requeue", "drop"]:
        return "drop"

    async def ack(self) -> None:
        return None

    async def retry(self, delay: float) -> None:
        return None

    async def dlq(
        self,
        event: Event,
        carrier: Mapping[str, str],
        error: Optional[Exception] = None,
    ) -> None:
        return None


class Delivery:
    """
    Represents a single attempt to deliver an Event over a transport.

    A Delivery READS: the event it carries, when it arrived, the transport's
    id for this attempt, the attempt count, and the trace carrier — transports
    subclass to override those reads. It never WRITES: the physical settlement
    operations live on the :class:`Settlement` it composes, so there is exactly
    one abstract write contract in the model.

    A delivery settles exactly once: the public verbs latch the first
    disposition and refuse later ones loudly (error log, no-op) — the physical
    disposition already happened, so a second one is always a bug. Settlement
    is called by the dispatcher, which aggregates every subscriber's outcome.

    Attributes:
        event: The Event this delivery carries.
        received_at: The datetime when this delivery attempt was received/created.
    """

    event: Event
    received_at: datetime

    def __init__(
        self,
        event: Event,
        settlement: Optional[Settlement] = None,
        *,
        received_at: Optional[datetime] = None,
    ) -> None:
        self.event = event
        self.received_at = received_at or utcnow()
        self._settlement: Settlement = settlement or NoSettlement()
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
            await self._settlement.ack()

    async def retry(self, delay: float = 0.0) -> None:
        """Make this event available for redelivery (first-wins latch).

        ``delay`` is decided by the dispatcher's retry policy; the settlement
        enacts it (SQS: visibility timeout) or ignores it if the transport
        cannot delay.
        """
        if self._claim("retry"):
            await self._settlement.retry(delay)

    async def dlq(self, error: Optional[Exception] = None) -> None:
        """Divert this event to a dead-letter destination (first-wins latch)."""
        if self._claim("dlq"):
            await self._settlement.dlq(self.event, self.carrier(), error)

    @property
    def terminal_action(self) -> Literal["dlq", "requeue", "drop"]:
        """Where terminal failures go — forwarded from the settlement, which
        declares it."""
        return self._settlement.terminal_action

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

    def carrier(self) -> Mapping[str, str]:
        """
        Returns a mapping of trace context headers for OpenTelemetry extraction.

        Override in transports carrying distributed tracing metadata.
        """
        return {}


class NoAckDelivery(Delivery):
    """A semantic name for push/observed deliveries — a plain :class:`Delivery`
    with the default :class:`NoSettlement` (all writes no-op, fate ``drop``)."""
