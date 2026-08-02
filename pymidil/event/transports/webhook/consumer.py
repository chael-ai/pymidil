"""Webhook consumer — adapts an HTTP POST into an ``Event`` + ``WebhookDelivery``.

A push transport: there is no broker to ack against, so the HTTP response is the
acknowledgement (``WebhookDelivery`` inherits the no-op dispositions). HTTP
headers carry the W3C trace context.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Mapping

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from pymidil.event.core import Event, NoAckDelivery
from pymidil.event.wire import EVENT_TYPE_FIELD, IDEMPOTENCY_KEY_FIELD


class WebhookDelivery(NoAckDelivery):
    """One HTTP webhook delivery — carries the request headers for tracing."""

    def __init__(self, event: Event, *, headers: Mapping[str, str]) -> None:
        super().__init__(event)
        self._headers = dict(headers)

    def carrier(self) -> Mapping[str, str]:
        return {str(k): str(v) for k, v in self._headers.items()}


class WebhookConsumerEventConfig(PushEventConsumerConfig):
    type: Literal["webhook"] = "webhook"
    endpoint: str = "/events"


class WebhookConsumer(PushEventConsumer):
    def __init__(self, config: WebhookConsumerEventConfig):
        super().__init__(config)
        self._config: WebhookConsumerEventConfig = config
        self._router = APIRouter()

        @self._router.post(
            self._config.endpoint,
            summary="Receive webhook events",
            description="Endpoint to receive webhook events",
        )
        async def receive_hook(request: Request) -> Dict[str, Any]:
            return await self._handler(request)

        logger.info(f"Webhook consumer ready at {self._config.endpoint}")

    @property
    def entrypoint(self) -> APIRouter:
        return self._router

    def _to_event(self, data: Any, headers: Mapping[str, str]) -> Event:
        return Event(
            id=headers[IDEMPOTENCY_KEY_FIELD],
            source=headers["source"] or "webhook",
            type=headers[EVENT_TYPE_FIELD],
            data=data,
            idempotency_key=headers[IDEMPOTENCY_KEY_FIELD],
        )

    async def _handler(self, request: Request) -> Dict[str, Any]:
        try:
            data = await request.json()
            headers = dict(request.headers)
            delivery = WebhookDelivery(self._to_event(data, headers), headers=headers)
            await self.dispatch(delivery)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Webhook event handling failed")
            raise HTTPException(status_code=400, detail=str(e))

    async def start(self) -> None:
        logger.info(f"Webhook consumer ready at {self._config.endpoint}")

    async def stop(self) -> None:
        self._subscribers.clear()
        logger.info("Webhook consumer stopped")
