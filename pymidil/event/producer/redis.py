from __future__ import annotations

from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.base import BaseProducerConfig
from pydantic import Field
from typing import TYPE_CHECKING, Literal, Optional
import json
from redis.asyncio import Redis
from pymidil.event.otel import inject_headers, producer_span
from pymidil.event.wire import event_to_wire

if TYPE_CHECKING:
    from pymidil.event.core import Event


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

    async def _publish(self, event: "Event") -> None:
        # Redis pub/sub has no header side-channel, so the event's attributes and
        # trace context ride in a wire envelope: {"data": <payload>, "metadata":
        # {event_id, event_type, …, traceparent}}. Inject the *enclosing* trace
        # context before the producer span (see the SQS producer for why), so a
        # downstream consumer parents to the upstream consumer.
        headers = dict(event_to_wire(event))
        inject_headers(headers)
        with producer_span(self._config.channel):
            envelope = {"data": event.data, "metadata": headers}

            async def _send() -> Optional[str]:
                await self._redis.publish(self._config.channel, json.dumps(envelope))
                return None  # pub/sub has no per-message delivery id

            await self._send_and_notify(event, self._config.channel, _send)

    async def close(self) -> None:
        await self._redis.close()
