from __future__ import annotations

from abc import abstractmethod, ABC

from pydantic import BaseModel, Field

from pymidil.event.message import MessageBody


class BaseProducerConfig(BaseModel):
    type: str = Field(..., description="Type of the producer configuration")


class EventProducer(ABC):
    """
    Abstract base for all event producers.

    An EventProducer is a DESTINATION Connector — it accepts event payloads
    and routes them to an external backend (SQS, Redis, etc.).

    Subclasses must implement publish() and close(). The connect/disconnect/health
    methods have sensible defaults but can be overridden for richer lifecycle control.
    """

    def __init__(self, config: BaseProducerConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return self._config.type

    @abstractmethod
    async def publish(self, payload: MessageBody, **kwargs) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...
