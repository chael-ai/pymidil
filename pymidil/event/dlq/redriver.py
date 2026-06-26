"""DLQ redrive primitive (A4) — the executor behind a replay.

Re-drives dead-lettered messages back to their source queue so they get
re-processed. This is the data-plane action the Observatory's replay command
maps onto: an owning service runs ``redrive()`` (or wires it to a replay-command
consumer) to move messages from the DLQ back to the source.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import aioboto3
from loguru import logger


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
        async with self._session.client("sqs", region_name=self._region) as sqs:
            response = await sqs.receive_message(
                QueueUrl=self._dlq,
                MaxNumberOfMessages=min(max_messages, 10),
                WaitTimeSeconds=0,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
            for message in response.get("Messages", []):
                params: dict[str, Any] = {
                    "QueueUrl": self._source,
                    "MessageBody": message["Body"],
                }
                attributes = message.get("MessageAttributes")
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
