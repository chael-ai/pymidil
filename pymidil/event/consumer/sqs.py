from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
import aioboto3
import asyncio
from loguru import logger
from pymidil.event.consumer.strategies.base import ConsumerMessage
from pydantic import Field
from botocore.exceptions import ClientError
from typing import Dict, Any, Mapping, Optional, Literal, cast
import json
from datetime import datetime
from pymidil.utils.retry import AsyncRetry
from pymidil.utils.backoff import ExponentialBackoff
from pymidil.event.message import Message
from pymidil.event.producer.sqs import build_sqs_message_attributes, region_from_arn

retry_policy = AsyncRetry(retry_on_exceptions=(ClientError,))

_DEFAULT_REGION = "us-east-1"


class SQSConsumerEventConfig(PullEventConsumerConfig):
    type: Literal["sqs"] = "sqs"
    queue_url: str = Field(..., description="URL of the queue")
    dlq_url: Optional[str] = Field(
        default=None, description="URL of the dead-letter queue"
    )
    visibility_timeout: int = Field(
        default=30, description="Visibility timeout in seconds", ge=0
    )
    max_number_of_messages: int = Field(
        default=10, description="Max messages to receive per poll (1-10)", ge=1, le=10
    )
    wait_time_seconds: int = Field(
        default=20, description="Wait time for long polling (0-20)", ge=0, le=20
    )
    poll_interval: float = Field(
        default=0.1, description="Interval between polls if no messages", ge=0.0
    )
    backoff_base_delay: float = Field(
        default=5, description="Base delay for backoff in seconds", ge=0
    )
    backoff_max_delay: float = Field(
        default=300, description="Max delay for backoff in seconds", ge=0
    )
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

    @property
    def dlq_region(self) -> str:
        return self.aws_region or region_from_arn(self.dlq_url) or self.region


class SQSConsumer(PullEventConsumer):
    def __init__(
        self,
        config: SQSConsumerEventConfig,
        *,
        session: Optional[Any] = None,
    ):
        super().__init__(config)
        self._config: SQSConsumerEventConfig = config
        self.session = session or aioboto3.Session()
        self.backoff = ExponentialBackoff(
            base_delay=self._config.backoff_base_delay,
            max_delay=self._config.backoff_max_delay,
        )

    def carrier(self, message: Message) -> Mapping[str, str]:
        """Flatten SQS attributes (incl. message attributes) to a string carrier."""
        flat: Dict[str, str] = {}
        for key, value in (getattr(message, "metadata", {}) or {}).items():
            if isinstance(value, Mapping):
                string_value = (
                    value.get("StringValue")
                    or value.get("stringValue")
                    or value.get("Value")
                )
                if string_value is not None:
                    flat[str(key)] = str(string_value)
            elif isinstance(value, (str, int, float, bool)):
                flat[str(key)] = str(value)
        return flat

    async def ack(self, message: Message) -> None:
        """Acknowledge (delete) the message from the source queue."""
        message = cast(ConsumerMessage, message)
        try:
            async with self.session.client(
                "sqs",
                region_name=self._config.region,
                endpoint_url=self._config.endpoint_url,
            ) as sqs:  # type: ignore[attr-defined]
                await sqs.delete_message(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=message.ack_handle,
                )
                logger.debug(f"Acknowledged message {message.id}")
        except ClientError as e:
            logger.error(f"Error acknowledging message {message.id}: {e}")

    async def retry(self, message: Message) -> None:
        """Make the message available again by resetting visibility (with backoff)."""
        message = cast(ConsumerMessage, message)
        receive_count = int(message.metadata.get("ApproximateReceiveCount", "1"))
        delay = self.backoff.next_delay(receive_count)
        try:
            async with self.session.client(
                "sqs",
                region_name=self._config.region,
                endpoint_url=self._config.endpoint_url,
            ) as sqs:  # type: ignore[attr-defined]
                await sqs.change_message_visibility(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=message.ack_handle,
                    VisibilityTimeout=int(delay),
                )
                logger.debug(
                    f"Requeued message {message.id} with backoff delay={delay}s "
                    f"(attempt {receive_count})"
                )
        except ClientError as e:
            logger.error(f"Error retrying message {message.id}: {e}")

    async def dlq(self, message: Message, error: Optional[Exception] = None) -> None:
        """Divert the message to the DLQ, then remove it from the source queue.

        Falls back to redelivery when no DLQ is configured, rather than dropping.
        """
        message = cast(ConsumerMessage, message)
        if not self._config.dlq_url:
            await self.retry(message)
            return
        try:
            async with self.session.client(
                "sqs",
                region_name=self._config.dlq_region,
                endpoint_url=self._config.endpoint_url,
            ) as sqs:  # type: ignore[attr-defined]
                params: Dict[str, Any] = {
                    "QueueUrl": self._config.dlq_url,
                    "MessageBody": message.model_dump_json(),
                }
                # Preserve the trace carrier on the DLQ message so a later replay
                # can link back to the original span.
                attributes = build_sqs_message_attributes(dict(self.carrier(message)))
                if attributes:
                    params["MessageAttributes"] = attributes
                if self._config.dlq_url.endswith(".fifo"):
                    params.update(
                        {
                            "MessageGroupId": message.metadata.get(
                                "MessageGroupId", "default"
                            ),
                            "MessageDeduplicationId": message.metadata.get(
                                "MessageDeduplicationId", str(message.id)
                            ),
                        }
                    )
                await sqs.send_message(**params)
                logger.debug(f"Sent message {message.id} to DLQ")
        except ClientError as e:
            logger.error(f"Error dead-lettering message {message.id}: {e}")
            return
        await self.ack(message)  # remove from source after diverting

    @retry_policy.retry
    async def _poll_loop(self) -> None:
        """
        Main loop for polling SQS and processing messages.
        """
        async with self.session.client(
            "sqs",
            region_name=self._config.region,
            endpoint_url=self._config.endpoint_url,
        ) as sqs:  # type: ignore[attr-defined]
            while self._running:
                logger.debug(
                    f"Polling SQS for new messages from queue: {self._config.queue_url}"
                )
                try:
                    response = await sqs.receive_message(
                        QueueUrl=self._config.queue_url,
                        MaxNumberOfMessages=self._config.max_number_of_messages,
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
                    else:
                        await asyncio.sleep(self._config.poll_interval)
                except ClientError as e:
                    logger.warning(
                        f"Error polling SQS: {e} ({getattr(e, 'response', None)}), retrying..."
                    )
                    raise e

    async def _process_message(self, message: Dict[str, Any]) -> None:
        """
        Parse and dispatch a single message to subscribers.
        """
        try:
            event = None
            try:
                body = json.loads(message["Body"])
            except json.JSONDecodeError:
                body = message["Body"]

            # Convert SentTimestamp to datetime
            sent_timestamp = message.get("Attributes", {}).get("SentTimestamp")
            timestamp = (
                datetime.fromtimestamp(int(sent_timestamp) / 1000)
                if sent_timestamp
                else None
            )

            # Combine Attributes and MessageAttributes for metadata
            metadata = {
                **message.get("Attributes", {}),
                **message.get("MessageAttributes", {}),
            }

            event = ConsumerMessage(
                id=message["MessageId"],
                body=body,
                timestamp=timestamp,
                ack_handle=message["ReceiptHandle"],
                metadata=metadata,
            )
            await self.dispatch(event)

        except Exception as e:
            if event:
                logger.error(
                    f"Dead-lettering message {message.get('MessageId')} due to error: {e}"
                )
                await self.dlq(event, error=e)
            logger.warning(
                f"Skipping message {message.get('MessageId')} because no event was found: {e}"
            )
            raise e
