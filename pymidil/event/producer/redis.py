from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.base import BaseProducerConfig
from pydantic import Field
from typing import Any, Dict, Literal, Optional
import json
from redis.asyncio import Redis
from pymidil.event.message import MessageBody
from pymidil.event.otel import inject_headers, producer_span


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

    async def publish(
        self, payload: MessageBody, metadata: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        # Redis pub/sub has no header side-channel, so trace context rides in a
        # wire envelope: {"data": <payload>, "metadata": {"traceparent": ...}}.
        with producer_span(self._config.channel):
            headers = dict(metadata or {})
            inject_headers(headers)
            envelope = {"data": payload, "metadata": headers}
            await self._redis.publish(self._config.channel, json.dumps(envelope))

    async def close(self) -> None:
        await self._redis.close()
