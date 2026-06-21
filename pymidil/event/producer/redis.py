from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.base import BaseProducerConfig
from pydantic import Field
from typing import Literal
import json
from redis.asyncio import Redis
from pymidil.event.message import MessageBody


class RedisProducerEventConfig(BaseProducerConfig):
    type: Literal["redis"] = Field(
        "redis", description="Type of the producer configuration"
    )
    channel: str = Field(..., description="Channel to publish the event to")
    url: str = Field(..., description="Endpoint of the Redis server")


class RedisProducer(EventProducer):
    def __init__(self, config: RedisProducerEventConfig) -> None:
        super().__init__(config)
        self._config: RedisProducerEventConfig = config
        self._redis = Redis.from_url(config.url)

    async def publish(self, payload: MessageBody, **kwargs) -> None:
        message = json.dumps(payload)
        await self._redis.publish(self._config.channel, message)

    async def close(self) -> None:
        await self._redis.close()
