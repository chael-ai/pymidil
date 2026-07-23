"""DLQ redrive primitive (A4) — the executor behind a replay.

Re-drives dead-lettered messages back to their source queue so they get
re-processed. This is the data-plane action the Observatory's replay command
maps onto: an owning service runs ``redrive()`` (or wires it to a replay-command
consumer) to move messages from the DLQ back to the source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Mapping, Optional

import aioboto3
from loguru import logger

from pymidil.event.otel import inject_headers, replay_span
from pymidil.event.producer.sqs import build_sqs_message_attributes

REPLAYED_FROM_HEADER = "replayed_from"


def _flatten_attributes(attributes: Mapping[str, Any]) -> Dict[str, str]:
    """SQS MessageAttributes ({"k": {"StringValue": ...}}) → flat string carrier."""
    flat: Dict[str, str] = {}
    for key, value in (attributes or {}).items():
        if isinstance(value, Mapping):
            string_value = value.get("StringValue") or value.get("Value")
            if string_value is not None:
                flat[str(key)] = str(string_value)
        elif isinstance(value, str):
            flat[str(key)] = value
    return flat


class DlqRedriver(ABC):
    """Re-drives messages from a dead-letter queue back to the source."""

    @abstractmethod
    async def redrive(self, max_messages: int = 10) -> int:
        """Move up to ``max_messages`` from the DLQ to the source; return the count."""


class SQSDlqRedriver(DlqRedriver):
    """SQS redrive: receive from the DLQ, re-send to the source, delete from the DLQ."""

    def __init__(
        self,
        source_queue_url: str,
        dlq_url: str,
        region: str,
        *,
        session: Optional[Any] = None,
    ) -> None:
        self._source = source_queue_url
        self._dlq = dlq_url
        self._region = region
        self._session = session or aioboto3.Session()

    async def redrive(self, max_messages: int = 10) -> int:
        count = 0
        async with self._session.client("sqs", region_name=self._region) as sqs:  # type: ignore[attr-defined]
            response = await sqs.receive_message(
                QueueUrl=self._dlq,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=0,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
            for message in response.get("Messages", []):
                original_carrier = _flatten_attributes(
                    message.get("MessageAttributes", {})
                )
                # New trace for the replay, linked back to the original span.
                with replay_span(original_carrier, self._source) as (
                    _span,
                    original_sc,
                ):
                    carrier: Dict[str, str] = {}
                    inject_headers(carrier)  # the replay span's (new) trace
                    if original_sc.is_valid:
                        carrier[REPLAYED_FROM_HEADER] = format(
                            original_sc.trace_id, "032x"
                        )

                    params: Dict[str, Any] = {
                        "QueueUrl": self._source,
                        "MessageBody": message["Body"],
                    }
                    attributes = build_sqs_message_attributes(carrier)
                    if attributes:
                        params["MessageAttributes"] = attributes
                    await sqs.send_message(**params)
                    await sqs.delete_message(
                        QueueUrl=self._dlq, ReceiptHandle=message["ReceiptHandle"]
                    )
                count += 1
        if count:
            logger.info(
                f"Redrove {count} message(s) from {self._dlq} to {self._source}"
            )
        return count
