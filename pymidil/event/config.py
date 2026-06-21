from __future__ import annotations

from typing import Annotated, Optional, Union, TypeAlias, Mapping

from pydantic import BaseModel, Field
from pymidil.event.consumer.sqs import SQSConsumerEventConfig
from pymidil.event.consumer.webhook import WebhookConsumerEventConfig
from pymidil.event.producer.redis import RedisProducerEventConfig
from pymidil.event.producer.sqs import SQSProducerEventConfig
from enum import Enum


ProducerConfig = Annotated[
    Union[SQSProducerEventConfig, RedisProducerEventConfig], Field(discriminator="type")
]

ConsumerConfig = Annotated[
    Union[
        SQSConsumerEventConfig,
        WebhookConsumerEventConfig,
    ],
    Field(discriminator="type"),
]

NamedProducersConfig: TypeAlias = Mapping[str, ProducerConfig]
NamedConsumersConfig: TypeAlias = Mapping[str, ConsumerConfig]


class EventConfig(BaseModel):
    """
    Configuration model for the EventBus.

    Attributes:
        producers: Named configurations for event producers (optional).
        consumers: Named configurations for event consumers (optional).
    """

    consumers: Optional[NamedConsumersConfig] = Field(
        default=None, description="Named configurations for event consumers"
    )
    producers: Optional[NamedProducersConfig] = Field(
        default=None, description="Named configurations for event producers"
    )


class EventConsumerType(str, Enum):
    SQS = "sqs"
    WEBHOOK = "webhook"
    HTTP_POLLING = "http_polling"
    STRIPE_WEBHOOK = "stripe_webhook"


class EventProducerType(str, Enum):
    REDIS = "redis"
    SQS = "sqs"
