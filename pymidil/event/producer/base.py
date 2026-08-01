from __future__ import annotations

import time
from abc import abstractmethod, ABC
from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional

from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from pymidil.event.core import Event
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

    async def publish(self, event: "Event") -> None:
        """Publish an :class:`Event`.

        The event's ``data`` becomes the message body; its identity/metadata
        attributes (id, source, type, subject, time, idempotency_key,
        extensions) ride in the transport's attribute side-channel via
        :func:`~pymidil.event.wire.event_to_wire`, so a consumer reconstructs
        the same event on the other side. Transports implement :meth:`_publish`
        (framing + trace injection + send) and settle observability through
        :meth:`_send_and_notify`.
        """
        return await self._publish(event)

    async def _send_and_notify(
        self,
        event: "Event",
        destination: str,
        send: Callable[[], Awaitable[Optional[str]]],
    ) -> None:
        """Time the ``send``, then notify producer hooks (success or error).

        Transports call this from *inside* their producer span so the produced
        telemetry records that span. ``send`` performs the broker call and
        returns the transport delivery id (or ``None`` for id-less transports).
        A hook failure never breaks the publish; a broker failure re-raises
        after the error hook fires.
        """
        record = PublishRecord(destination=destination, event=event)
        start = time.monotonic()
        try:
            record.message_id = await send()
        except Exception as error:
            record.duration_ms = (time.monotonic() - start) * 1000
            await self._notify_publish_error(record, error)
            raise
        record.duration_ms = (time.monotonic() - start) * 1000
        await self._notify_published(record)

    @abstractmethod
    async def _publish(self, event: "Event") -> None:
        """Transport-specific framing + send. Never called directly — use
        :meth:`publish`. Implementations derive the body (``event.data``) and the
        wire attributes (:func:`~pymidil.event.wire.event_to_wire`), inject trace
        context, and settle through :meth:`_send_and_notify`."""

    @abstractmethod
    async def close(self) -> None:
        ...
