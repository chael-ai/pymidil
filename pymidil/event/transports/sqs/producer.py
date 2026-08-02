from __future__ import annotations

from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.base import BaseProducerConfig
import aioboto3
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional
import json
from pydantic import Field
from pymidil.event.otel import inject_headers, producer_span
from pymidil.event.wire import event_to_wire
from botocore.utils import ArnParser

if TYPE_CHECKING:
    from pymidil.event.core import Event

_MAX_SQS_ATTRIBUTES = 10
_DEFAULT_REGION = "us-east-1"


def region_from_arn(value: Optional[str]) -> Optional[str]:
    """Best-effort region from an SQS ARN; None for plain URLs (never raises)."""
    if not value:
        return None
    try:
        return ArnParser().parse_arn(value).get("region") or None
    except Exception:
        return None


def build_sqs_message_attributes(headers: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Map flat string-ish headers (incl. traceparent) to SQS MessageAttributes."""
    attributes: Dict[str, Dict[str, str]] = {}
    for key, value in headers.items():
        if value is None or not isinstance(value, (str, int, float, bool)):
            continue
        attributes[str(key)] = {"DataType": "String", "StringValue": str(value)}
        if len(attributes) >= _MAX_SQS_ATTRIBUTES:
            break
    return attributes


class SQSProducerEventConfig(BaseProducerConfig):
    type: Literal["sqs"] = "sqs"
    queue_url: str = Field(..., description="URL of the queue")
    aws_region: Optional[str] = Field(
        default=None, description="Explicit region; overrides any ARN-derived value"
    )
    endpoint_url: Optional[str] = Field(
        default=None,
        description="Custom SQS endpoint (e.g. LocalStack http://localhost:4566)",
    )

    @property
    def region(self) -> str:
        return self.aws_region or region_from_arn(self.queue_url) or _DEFAULT_REGION


class SQSProducer(EventProducer):
    def __init__(
        self, config: SQSProducerEventConfig, *, session: Optional[Any] = None
    ) -> None:
        super().__init__(config)
        self._config: SQSProducerEventConfig = config
        self._session = session or aioboto3.Session()

    async def _publish(self, event: "Event") -> None:
        body = json.dumps(event.data)
        # The event's identity/metadata attributes ride the SQS attribute
        # side-channel. Inject the *enclosing* trace context (the consumer span
        # when publishing from within a handler's dispatch, or none for a root
        # publish) *before* opening the producer span, so a downstream consumer
        # is parented directly to the upstream consumer — a clean consumer→
        # consumer chain. Injecting the producer span instead would insert an
        # unobserved hop between every pair of consumer spans. The producer span
        # below still records the publish for local trace observability (it just
        # isn't the propagated parent).
        headers = dict(event_to_wire(event))
        inject_headers(headers)
        with producer_span(self._config.queue_url):
            params: Dict[str, Any] = {
                "QueueUrl": self._config.queue_url,
                "MessageBody": body,
            }
            attributes = build_sqs_message_attributes(headers)
            if attributes:
                params["MessageAttributes"] = attributes

            async def _send() -> Optional[str]:
                async with self._session.client(
                    "sqs",
                    region_name=self._config.region,
                    endpoint_url=self._config.endpoint_url,
                ) as sqs:  # type: ignore[attr-defined]
                    response = await sqs.send_message(**params)
                # SQS returns the same MessageId the consumer will later receive,
                # so the produced record groups with that delivery's records.
                return (response or {}).get("MessageId")

            await self._send_and_notify(event, self._config.queue_url, _send)

    async def close(self) -> None:
        pass
