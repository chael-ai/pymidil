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
from typing import Dict, Any, Optional, Literal, cast
import json
from datetime import datetime
from pymidil.utils.retry import AsyncRetry
from pymidil.utils.backoff import ExponentialBackoff
from pymidil.event.message import Message
from botocore.utils import ArnParser

retry_policy = AsyncRetry(retry_on_exceptions=(ClientError,))


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

    @property
    def region(self) -> str:
        arn_parser = ArnParser()
        arn = arn_parser.parse_arn(self.queue_url)
        return arn["region"]

    @property
    def dlq_region(self) -> Optional[str]:
        arn_parser = ArnParser()
        arn = arn_parser.parse_arn(self.dlq_url)
        return arn["region"] if arn else None


class SQSConsumer(PullEventConsumer):
    def __init__(
        self,
        config: SQSConsumerEventConfig,
    ):
        super().__init__(config)
        self._config: SQSConsumerEventConfig = config
        self._session: aioboto3.Session = aioboto3.Session()
        self.backoff = ExponentialBackoff(
            base_delay=self._config.backoff_base_delay,
            max_delay=self._config.backoff_max_delay,
        )

    async def ack(self, message: Message) -> None:
        """
        Acknowledge (delete) the message from the SQS queue.

        Args:
            message (EventContext): The SQS message dictionary, expected to contain 'ReceiptHandle'.
        """
        message = cast(ConsumerMessage, message)
        try:
            async with self._session.client(
                "sqs", region_name=self._config.region
            ) as sqs:  # type: ignore[attr-defined]
                await sqs.delete_message(
                    QueueUrl=self._config.queue_url,
                    ReceiptHandle=message.ack_handle,
                )
                logger.debug(f"Acknowledged message {message.id}")
        except ClientError as e:
            logger.error(f"Error acknowledging message {message.id}: {e}")

    async def nack(self, message: Message, requeue: bool = True) -> None:
        """
        Negative acknowledge the message.

        Behavior:
        - If `requeue` is True and a DLQ is configured, the message is explicitly
            sent to the DLQ and then removed from the source queue to avoid duplicates.
        - If `requeue` is False, the message visibility timeout is reset to 0,
            making it immediately available again in the source queue.
        - If no DLQ is configured but the source queue has an SQS redrive policy,
            repeated nacks will eventually cause SQS to move the message to the DLQ
            automatically once `maxReceiveCount` is exceeded.

        Args:
            message (Message): The SQS message object (with ReceiptHandle, Body, etc.).
            requeue (bool): Whether to send the message to the DLQ (if configured).
        """
        message = cast(ConsumerMessage, message)
        try:
            if requeue and self._config.dlq_url:
                # move to dead letter queue
                async with self._session.client(
                    "sqs", region_name=self._config.dlq_region
                ) as sqs:  # type: ignore
                    params = {
                        "QueueUrl": self._config.dlq_url,
                        "MessageBody": message.model_dump_json(),
                    }
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
                    await self.ack(message)  # Remove from source queue
                    logger.debug(f"Sent message {message.id} to DLQ")

            else:
                async with self._session.client(
                    "sqs", region_name=self._config.region
                ) as sqs:  # type: ignore
                    receive_count = int(
                        message.metadata.get("ApproximateReceiveCount", "1")
                    )
                    delay = self.backoff.next_delay(receive_count)
                    await sqs.change_message_visibility(
                        QueueUrl=self._config.queue_url,
                        ReceiptHandle=message.ack_handle,
                        VisibilityTimeout=delay,
                    )
                    logger.debug(
                        f"Requeued message {message.id} with backoff delay={delay}s (attempt {receive_count})"
                    )

        except ClientError as e:
            logger.error(f"Error nacking message {message.id}: {e}")

    @retry_policy.retry
    async def _poll_loop(self) -> None:
        """
        Main loop for polling SQS and processing messages.
        """
        async with self._session.client("sqs", region_name=self._config.region) as sqs:  # type: ignore[attr-defined]
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
                    f"Nacking message {message.get('MessageId')} due to error: {e}"
                )
                await self.nack(event, requeue=True)
            logger.warning(
                f"Skipping nack message {message.get('MessageId')} because no event was found: {e}"
            )
            raise e
