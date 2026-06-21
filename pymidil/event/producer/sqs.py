from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.base import BaseProducerConfig
import aioboto3
from typing import Literal
import json
from pydantic import Field
from pymidil.event.message import MessageBody
from botocore.utils import ArnParser


class SQSProducerEventConfig(BaseProducerConfig):
    type: Literal["sqs"] = "sqs"
    queue_url: str = Field(..., description="URL of the queue")

    @property
    def region(self) -> str:
        arn_parser = ArnParser()
        arn = arn_parser.parse(self.queue_url)
        return arn["region"]


class SQSProducer(EventProducer):
    def __init__(self, config: SQSProducerEventConfig) -> None:
        super().__init__(config)
        self._config: SQSProducerEventConfig = config
        self._session = aioboto3.Session()

    async def publish(self, payload: MessageBody, **kwargs) -> None:
        message = json.dumps(payload)
        async with self._session.client("sqs", region_name=self._config.region) as sqs:
            await sqs.send_message(QueueUrl=self._config.queue_url, MessageBody=message)

    async def close(self) -> None:
        pass
