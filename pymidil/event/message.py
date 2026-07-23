from typing import Union, Optional, Sequence, Mapping, Any
from pymidil.jsonapi.config import AllowExtraFieldsModel
from datetime import datetime
from pydantic import Field
from pymidil.utils.time import utcnow

MessageBody = Sequence[Any] | Mapping[Any, Any] | str


class Message(AllowExtraFieldsModel):
    """The thin, transport-agnostic core of an event: identity + payload.

    Deliberately minimal — ``id`` and ``body`` are the essence, with
    ``idempotency_key`` (the logical-event thread) and ``timestamp`` as the only
    other first-class identity fields. Transport delivery context (broker headers,
    SQS attributes, HTTP headers, ack handles) lives on the inbound subclasses
    (``ConsumerMessage.metadata``, ``WebhookMessage.headers``), never on the base —
    so generic dispatch never reaches into a transport-specific field. Trace
    propagation rides the consumer's ``carrier()`` adapter, not a base field.
    """

    id: Union[str, int] = Field(
        ...,
        description="Unique identifier for the message or its position, You can rely on the message Id for idempotent",
    )
    body: MessageBody = Field(..., description="The actual message payload")
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Business key for deduplication; falls back to id when unset",
    )
    timestamp: Optional[datetime] = Field(
        default_factory=utcnow, description="When the message was published or received"
    )
