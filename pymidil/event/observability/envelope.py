"""Telemetry envelope (M0.1 contract).

The wire shape an emitter produces and the Observatory API ingests. Kept aligned
with ``midil-observatory-api``'s ``TelemetryEnvelopeIn``; ``model_dump(mode="json")``
yields exactly that payload.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from pymidil.utils.time import utcnow


class EventStatus(str, Enum):
    """Terminal outcome of a single observation (publish or dispatch)."""

    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    DLQ = "dlq"
    DUPLICATE = "duplicate"


class EventKind(str, Enum):
    """Which side of the wire produced the observation.

    ``status`` answers *what happened*; ``kind`` answers *who observed it* — a
    producer recording a publish versus a consumer recording a dispatch outcome.
    Keeping them orthogonal lets consumer-centric rollups stay unpolluted while
    the producer leg still contributes to a single event's lifecycle.
    """

    PRODUCER = "producer"
    CONSUMER = "consumer"


class TelemetryEnvelope(BaseModel):
    """One observation of an event as it flowed through one consumer.

    Four identifiers tell the story of an event, each with a distinct scope:

    - ``id`` — this *observation* (one emitted envelope); new every emit.
    - ``message_id`` — this *transport delivery* (SQS ``MessageId``, webhook body
      hash). Stable across a delivery's own retries; new per hop and per replay.
    - ``idempotency_key`` — the *logical step*; stable across retries, redeliveries
      and replays of one hop, but a new key at each downstream hop.
    - ``trace_id`` — the *distributed transaction*; shared across hops, and on a
      DLQ replay a new trace linked to the original via ``replayed_from``.
    """

    message_id: str = Field(
        ...,
        description="Transport delivery id (SQS MessageId / webhook body hash) — this delivery, not the logical event",
    )
    event_type: str = Field(..., description="e.g. BookingCreated, PaymentAuthorized")
    status: EventStatus
    kind: EventKind = Field(
        default=EventKind.CONSUMER,
        description="Producer (publish) vs consumer (dispatch) observation",
    )
    broker: str = Field(
        ..., description="Transport: sqs, sns, kafka, rabbitmq, redis, …"
    )

    id: Optional[str] = Field(
        default=None, description="Stable observation id; generated if omitted"
    )
    occurred_at: datetime = Field(default_factory=utcnow)
    consumer: Optional[str] = None
    source_service: Optional[str] = None
    attempts: int = 1
    processing_time_ms: Optional[float] = None
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Logical step id; stable across retries/redeliveries/replays of one hop",
    )
    replayed_from: Optional[str] = Field(
        default=None, description="Original trace id when this run is a DLQ replay"
    )
    failure_reason: Optional[str] = None
    failure_class: Optional[str] = None
    payload: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
