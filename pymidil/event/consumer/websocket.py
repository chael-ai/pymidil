from fastapi import APIRouter, WebSocket
from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from pymidil.event.message import Message
from loguru import logger
from typing import List


class WebSocketPushConsumerEventConfig(PushEventConsumerConfig):
    type: str = "websocket"
    endpoint: str = "/events/ws"


class WebSocketPushConsumer(PushEventConsumer):
    def __init__(self, config: WebSocketPushConsumerEventConfig):
        super().__init__(config)
        self._config: WebSocketPushConsumerEventConfig = config
        self._router = APIRouter()
        self.connections: List[WebSocket] = []

    @property
    def entrypoint(self) -> APIRouter:
        return self._router

    async def _handler(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)
        try:
            while True:
                data: Message = await websocket.receive_json()
                await self.dispatch(data)
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

    async def ack(self, message: Message) -> None:
        logger.debug(f"Acked WebSocket event {message.id}")

    async def nack(self, message: Message, requeue: bool = True) -> None:
        logger.warning(f"Nacked WebSocket event {message.id}, requeue={requeue}")
