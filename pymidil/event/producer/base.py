from __future__ import annotations

from abc import abstractmethod, ABC
from typing import Any, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

from pymidil.event.message import MessageBody
from pymidil.event.observability.hooks import ProducerHook, PublishRecord


class BaseProducerConfig(BaseModel):
    type: str = Field(..., description="Type of the producer configuration")


class EventProducer(ABC):
    """
    Abstract base for all event producers.

    An EventProducer is a DESTINATION Connector — it accepts event payloads
    and routes them to an external backend (SQS, Redis, etc.).

    Publish observability is layered on through :class:`ProducerHook`s — the
    produce-side twin of the consumer's ``DispatchHook`` (an Observer wiring that
    keeps telemetry out of transport code, per the Open/Closed Principle).
    Subclasses call ``_notify_published`` / ``_notify_publish_error`` around their
    send. Subclasses must implement publish() and close().
    """

    def __init__(self, config: BaseProducerConfig) -> None:
        self._config = config
        self._producer_hooks: List[ProducerHook] = []

    @property
    def name(self) -> str:
        return self._config.type

    def add_hook(self, hook: ProducerHook) -> None:
        """Attach a :class:`ProducerHook` to observe this producer's publishes."""
        self._producer_hooks.append(hook)

    def remove_hook(self, hook: ProducerHook) -> None:
        self._producer_hooks = [h for h in self._producer_hooks if h is not hook]

    async def _notify_published(self, record: PublishRecord) -> None:
        """Notify hooks of a successful publish; a hook failure never propagates."""
        for hook in self._producer_hooks:
            try:
                await hook.on_publish(record, self.name)
            except Exception as exc:
                logger.warning(
                    f"[{self.name}] ProducerHook {hook.__class__.__name__}.on_publish "
                    f"raised: {exc}"
                )

    async def _notify_publish_error(
        self, record: PublishRecord, error: Exception
    ) -> None:
        for hook in self._producer_hooks:
            try:
                await hook.on_publish_error(record, self.name, error)
            except Exception as exc:
                logger.warning(
                    f"[{self.name}] ProducerHook {hook.__class__.__name__}."
                    f"on_publish_error raised: {exc}"
                )

    @abstractmethod
    async def publish(
        self, payload: MessageBody, metadata: Optional[Dict[str, Any]] = None, **kwargs
    ) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...
