from fastapi import APIRouter, Request, HTTPException
from loguru import logger
from pymidil.event.message import Message
from pymidil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from typing import Literal, Dict, Any, Mapping
import hashlib
import json
from pydantic import Field


class WebhookMessage(Message):
    headers: Dict[str, Any] = Field(
        default_factory=dict, description="Additional message properties or headers"
    )


class WebhookConsumerEventConfig(PushEventConsumerConfig):
    type: Literal["webhook"] = "webhook"
    endpoint: str = "/events"


class WebhookConsumer(PushEventConsumer):
    def __init__(self, config: WebhookConsumerEventConfig):
        super().__init__(config)
        self._config: WebhookConsumerEventConfig = config
        self._router = APIRouter()

        logger.info("Starting webhook consumer")

        # Create the route statically so it's available for FastAPI's OpenAPI schema.
        # FastAPI needs to know about all routes at startup time to include them in the OpenAPI schema that powers the Swagger UI
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

    def carrier(self, message: Message) -> Mapping[str, str]:
        """HTTP request headers carry the trace context (W3C traceparent)."""
        headers = getattr(message, "headers", {}) or {}
        return {str(k): str(v) for k, v in headers.items()}

    async def _handler(
        self,
        request: Request,
    ) -> Dict[str, Any]:
        try:
            data = await request.json()
            headers = dict(request.headers)
            message_id = self._hash_body(data)
            message = WebhookMessage(body=data, id=message_id, headers=headers)
            await self.dispatch(message)
            return {"status": "ok"}
        except Exception as e:
            logger.exception("Webhook event handling failed")
            raise HTTPException(status_code=400, detail=str(e))

    def _hash_body(self, body: Any) -> str:
        body_str = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body_str.encode("utf-8")).hexdigest()

    async def start(self) -> None:
        """
        Setup the webhook consumer routes to receive events.
        """
        logger.info(f"Webhook consumer ready at {self._config.endpoint}")

    async def stop(self) -> None:
        self._subscribers.clear()
        logger.info("Webhook consumer stopped")

    # Push transport: ack/retry/dlq inherit Acknowledger's no-op defaults — the
    # HTTP response is the acknowledgement.
