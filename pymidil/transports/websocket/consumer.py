"""WebSocket consumer — adapts a received JSON frame into an ``Event``.

A push transport with no broker settlement (``WebSocketDelivery`` inherits the
no-op dispositions). Each frame becomes a real ``Event`` — the model is
enforced at the boundary rather than dispatching a raw dict.
"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, WebSocket
from loguru import logger

from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from pymidil.event.core import Event, NoAckDelivery


class WebSocketDelivery(NoAckDelivery):
    """One WebSocket frame delivery — no ack, no trace carrier."""


class WebSocketConsumerEventConfig(PushEventConsumerConfig):
    type: str = "websocket"
    endpoint: str = "/events/ws"


class WebSocketConsumer(PushEventConsumer):
    def __init__(self, config: WebSocketConsumerEventConfig):
        super().__init__(config)
        self._config: WebSocketConsumerEventConfig = config
        self._router = APIRouter()
        self.connections: List[WebSocket] = []

    @property
    def entrypoint(self) -> APIRouter:
        return self._router

    @staticmethod
    def _to_event(frame: Any) -> Event:
        if isinstance(frame, dict) and "type" in frame and "data" in frame:
            return Event(
                id=str(frame.get("id") or frame.get("idempotency_key") or ""),
                source=str(frame.get("source") or "websocket"),
                type=str(frame["type"]),
                data=frame["data"],
                idempotency_key=frame.get("idempotency_key"),
            )
        # A bare payload frame — wrap it as a generic event.
        return Event(id="", source="websocket", type="unknown", data=frame)

    async def _handler(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.append(websocket)
        try:
            while True:
                frame = await websocket.receive_json()
                await self.dispatch(WebSocketDelivery(self._to_event(frame)))
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            self.connections.remove(websocket)

    async def start(self) -> None:
        @self._router.websocket(self._config.endpoint)
        async def websocket_endpoint(websocket: WebSocket) -> None:
            return await self._handler(websocket)

        logger.info(f"WebSocket consumer ready at {self._config.endpoint}")

    async def stop(self) -> None:
        self.connections.clear()
