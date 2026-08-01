"""SQS consumer — adapts the SQS wire into an ``Event`` + ``SqsDelivery``.

Everything SQS-shaped is quarantined in this module: the ``{"StringValue": …}``
attribute envelope, ``ApproximateReceiveCount``, receipt handles, region-from-ARN.
The rest of pymidil sees only a transport-neutral :class:`Event` and a
:class:`~pymidil.event.core.Delivery` whose disposition it can call.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Dict, Literal, Mapping, Optional

import aioboto3
from botocore.exceptions import ClientError
from loguru import logger
from pydantic import Field

from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
from pymidil.event.control import ControlSource, ControlState
from pymidil.event.core import Delivery, Event
from pymidil.event.wire import wire_to_event
from pymidil.event.producer.sqs import build_sqs_message_attributes, region_from_arn
from pymidil.utils.backoff import ExponentialBackoff
from pymidil.utils.retry import AsyncRetry
from pymidil.utils.time import utcnow

retry_policy = AsyncRetry(retry_on_exceptions=(ClientError,))

_DEFAULT_REGION = "us-east-1"


def _unwrap(value: Any) -> Optional[str]:
    """Peel an SQS attribute value (``{"StringValue": …}``) to a plain string."""
    if isinstance(value, dict):
        value = (
            value.get("StringValue") or value.get("stringValue") or value.get("Value")
        )
    return None if value is None else str(value)


class SQSConsumerEventConfig(PullEventConsumerConfig):
    type: Literal["sqs"] = "sqs"
    queue_url: str = Field(..., description="URL of the queue")
    dlq_url: Optional[str] = Field(
        default=None, description="URL of the dead-letter queue"
    )
    visibility_timeout: int = Field(
        default=30, description="Visibility timeout (s)", ge=0
    )
    max_number_of_messages: int = Field(default=10, ge=1, le=10)
    wait_time_seconds: int = Field(default=20, ge=0, le=20)
    poll_interval: float = Field(default=0.1, ge=0.0)
    backoff_base_delay: float = Field(default=5, ge=0)
    backoff_max_delay: float = Field(default=300, ge=0)
    aws_region: Optional[str] = Field(default=None)
    endpoint_url: Optional[str] = Field(default=None)

    @property
    def region(self) -> str:
        return self.aws_region or region_from_arn(self.queue_url) or _DEFAULT_REGION

    @property
    def dlq_region(self) -> str:
        return self.aws_region or region_from_arn(self.dlq_url) or self.region


class SqsDelivery(Delivery):
    """One SQS delivery attempt — owns the receipt handle and the disposition."""

    def __init__(
        self,
        event: Event,
        *,
        session: Any,
        config: SQSConsumerEventConfig,
        backoff: ExponentialBackoff,
        message_id: str,
        receipt_handle: str,
        raw_attributes: Mapping[str, Any],
    ) -> None:
        super().__init__(event)
        self._session = session
        self._config = config
        self._backoff = backoff
        self._message_id = message_id
        self._receipt_handle = receipt_handle
        self._raw = dict(raw_attributes)

    @property
    def transport_id(self) -> str:
        return self._message_id

    @property
    def retry_count(self) -> int:
        return int(_unwrap(self._raw.get("ApproximateReceiveCount")) or 1)

    def carrier(self) -> Mapping[str, str]:
        """W3C trace context from the SQS attribute bag (unwrapped)."""
        flat: Dict[str, str] = {}
        for key, value in self._raw.items():
            text = _unwrap(value)
            if text is not None:
                flat[str(key)] = text
        return flat

    def _client(self, region: str):
        return self._session.client(
            "sqs", region_name=region, endpoint_url=self._config.endpoint_url
        )

    async def _ack(self) -> None:
        try:
            async with self._client(self._config.region) as sqs:
                await sqs.delete_message(
                    QueueUrl=self._config.queue_url, ReceiptHandle=self._receipt_handle
                )
                logger.debug(f"Acknowledged message {self._message_id}")
        except ClientError as e:
            logger.error(f"Error acknowledging message {self._message_id}: {e}")

    async def _retry(self) -> None:
        delay = self._backoff.next_delay(self.retry_count)
        try:
            async with self._client(self._config.region) as sqs:
                await sqs.change_message_visibility(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=self._receipt_handle,
                    VisibilityTimeout=int(delay),
                )
                logger.debug(
                    f"Requeued message {self._message_id} with backoff delay={delay}s "
                    f"(attempt {self.retry_count})"
                )
        except ClientError as e:
            logger.error(f"Error retrying message {self._message_id}: {e}")

    async def _dlq(self, error: Optional[Exception] = None) -> None:
        if not self._config.dlq_url:
            await self._retry()  # no DLQ configured → redeliver rather than drop
            return
        try:
            async with self._client(self._config.dlq_region) as sqs:
                params: Dict[str, Any] = {
                    "QueueUrl": self._config.dlq_url,
                    "MessageBody": json.dumps(self.event.data),
                }
                # Preserve the trace carrier so a later replay links back.
                attributes = build_sqs_message_attributes(dict(self.carrier()))
                if attributes:
                    params["MessageAttributes"] = attributes
                if self._config.dlq_url.endswith(".fifo"):
                    params.update(
                        {
                            "MessageGroupId": _unwrap(self._raw.get("MessageGroupId"))
                            or "default",
                            "MessageDeduplicationId": _unwrap(
                                self._raw.get("MessageDeduplicationId")
                            )
                            or self._message_id,
                        }
                    )
                await sqs.send_message(**params)
                logger.debug(f"Sent message {self._message_id} to DLQ")
        except ClientError as e:
            logger.error(f"Error dead-lettering message {self._message_id}: {e}")
            return
        await self._ack()  # remove from source after diverting


class SQSConsumer(PullEventConsumer):
    def __init__(
        self,
        config: SQSConsumerEventConfig,
        *,
        session: Optional[Any] = None,
        control: Optional[ControlSource] = None,
    ):
        super().__init__(config, control=control)
        self._config: SQSConsumerEventConfig = config
        self.session = session or aioboto3.Session()
        self.backoff = ExponentialBackoff(
            base_delay=self._config.backoff_base_delay,
            max_delay=self._config.backoff_max_delay,
        )

    def _to_event(self, message: Dict[str, Any], metadata: Dict[str, Any]) -> Event:
        try:
            data = json.loads(message["Body"])
        except json.JSONDecodeError:
            data = message["Body"]

        sent = metadata.get("SentTimestamp")
        occurred = datetime.fromtimestamp(int(sent) / 1000) if sent else utcnow()

        # Flatten the SQS attribute bag to plain strings, then reconstruct the
        # event through the one wire contract (with the transport's own id/time
        # as fallbacks for foreign producers).
        flat = {
            str(key): text
            for key, value in metadata.items()
            if (text := _unwrap(value)) is not None
        }
        return wire_to_event(
            flat,
            data=data,
            fallback_id=message["MessageId"],
            fallback_time=occurred,
        )

    async def _process_message(self, message: Dict[str, Any]) -> None:
        delivery: Optional[SqsDelivery] = None
        try:
            metadata = {
                **message.get("Attributes", {}),
                **message.get("MessageAttributes", {}),
            }
            delivery = SqsDelivery(
                self._to_event(message, metadata),
                session=self.session,
                config=self._config,
                backoff=self.backoff,
                message_id=message["MessageId"],
                receipt_handle=message["ReceiptHandle"],
                raw_attributes=metadata,
            )
            await self.dispatch(delivery)
        except Exception as e:
            mid = message.get("MessageId")
            if delivery is not None:
                logger.error(f"Dead-lettering message {mid} due to error: {e}")
                await delivery.dlq(e)
            else:
                logger.warning(f"Skipping malformed SQS message {mid}: {e}")
            raise e

    @retry_policy.retry
    async def _poll_loop(self) -> None:
        async with self.session.client(
            "sqs",
            region_name=self._config.region,
            endpoint_url=self._config.endpoint_url,
        ) as sqs:  # type: ignore[attr-defined]
            while self._running:
                control = await self._control_gate()
                if control is None:
                    continue
                throttled = control.state is ControlState.THROTTLED

                logger.debug(f"Polling SQS from queue: {self._config.queue_url}")
                try:
                    response = await sqs.receive_message(
                        QueueUrl=self._config.queue_url,
                        MaxNumberOfMessages=(
                            1 if throttled else self._config.max_number_of_messages
                        ),
                        VisibilityTimeout=self._config.visibility_timeout,
                        WaitTimeSeconds=self._config.wait_time_seconds,
                        AttributeNames=["All"],
                        MessageAttributeNames=["All"],
                    )
                    messages = response.get("Messages", [])
                    if messages:
                        logger.debug(
                            f"Found {len(messages)} message(s), dispatching..."
                        )
                        async with asyncio.TaskGroup() as tg:
                            for msg in messages:
                                tg.create_task(self._process_message(msg))
                        await self._throttle_pace(control)
                    else:
                        await asyncio.sleep(self._config.poll_interval)
                except ClientError as e:
                    logger.warning(f"Error polling SQS: {e}, retrying...")
                    raise e
