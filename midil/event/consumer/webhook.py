from fastapi import APIRouter, Request, HTTPException, Depends
from loguru import logger
from midil.event.message import Message
from midil.event.consumer.strategies.push import (
    PushEventConsumer,
    PushEventConsumerConfig,
)
from typing import Literal, Dict, Any
import hashlib
import json
from pydantic import Field


class WebhookMessage(Message):
    headers: Dict[str, Any] = Field(
        default_factory=dict, description="Additional message properties or headers"
    )
    path_params: Dict[str, Any] = Field(
        default_factory=dict, description="The path parameters"
    )


class WebhookConsumerEventConfig(PushEventConsumerConfig):
    type: Literal["webhook"] = "webhook"
    endpoint: str = "/events"


class WebhookConsumer(PushEventConsumer):
    """A FastAPI-based webhook consumer for processing incoming events.

    This class sets up a webhook endpoint to receive and process events, dispatching
    them to subscribers. It includes authorization and error handling mechanisms.
    """

    def __init__(self, config: WebhookConsumerEventConfig):
        """Initialize the webhook consumer with the provided configuration."""
        super().__init__(config)
        self._config: WebhookConsumerEventConfig = config
        self._router = APIRouter()
        self._setup_routes()
        logger.info(
            f"Webhook consumer initialized at endpoint: {self._config.endpoint}"
        )

    def _setup_routes(self) -> None:
        """Configure FastAPI routes for the webhook consumer."""

        @self._router.post(
            self._config.endpoint,
            summary="Receive Webhook Events",
            description="Endpoint to receive and process webhook events. Requires authorization.",
            response_description="Returns {'status': 'ok'} on successful processing.",
        )
        async def receive_webhook(
            request: Request, authorized: bool = Depends(self.authorize)
        ) -> Dict[str, Any]:
            """Handle incoming webhook requests."""
            if not authorized:
                logger.warning("Unauthorized webhook request received")
                raise HTTPException(status_code=401, detail="Unauthorized access")

            return await self._handle_request(request)

    @property
    def entrypoint(self) -> APIRouter:
        """Expose the FastAPI router for integration with the application."""
        return self._router

    async def _handle_request(self, request: Request) -> Dict[str, Any]:
        """Process the incoming webhook request and dispatch the event.

        Args:
            request: The FastAPI request object containing the webhook payload.

        Returns:
            A dictionary indicating successful processing.

        Raises:
            HTTPException: If the request is invalid or processing fails.
        """
        try:
            data = await request.json()
            message = self._create_message(data, request)
            await self.dispatch(message)
            logger.debug(f"Successfully processed webhook event: {message.id}")
            return {"status": "ok"}

        except json.JSONDecodeError:
            logger.error("Invalid JSON payload received")
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        except Exception as e:
            logger.exception(f"Failed to process webhook event: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

    def _create_message(self, data: Dict[str, Any], request: Request) -> WebhookMessage:
        """Create a WebhookMessage from the request data.

        Args:
            data: The parsed JSON payload from the request.
            request: The FastAPI request object.

        Returns:
            A WebhookMessage instance with a unique ID, body, headers, and path parameters.
        """
        message_id = self._generate_message_id(data)
        return WebhookMessage(
            body=data,
            id=message_id,
            headers=dict(request.headers),
            path_params=dict(request.path_params),
        )

    def _generate_message_id(self, data: Any) -> str:
        """Generate a unique SHA-256 hash for the message body.

        Args:
            data: The message payload to hash.

        Returns:
            A hexadecimal string representing the SHA-256 hash.
        """
        body_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body_str.encode("utf-8")).hexdigest()

    async def start(self) -> None:
        """Start the webhook consumer and log readiness."""
        logger.info(f"Webhook consumer started at {self._config.endpoint}")

    async def stop(self) -> None:
        """Stop the webhook consumer and clear subscribers."""
        self._subscribers.clear()
        logger.info("Webhook consumer stopped")

    async def ack(self, message: Message) -> None:
        """Acknowledge successful processing of a message.

        Args:
            message: The message to acknowledge.
        """
        logger.debug(f"Acked event: {message.model_dump_json()}")

    async def nack(self, message: Message, requeue: bool = True) -> None:
        """Reject a message with an option to requeue.

        Args:
            message: The message to reject.
            requeue: Whether to requeue the message for reprocessing.
        """
        logger.warning(f"Nacked event, requeue={requeue}: {message.model_dump_json()}")

    async def authorize(self, message: Message) -> bool:
        """Authorize the incoming message.

        Args:
            message: The message to authorize.

        Returns:
            True if authorized, False otherwise.

        Note:
            This is a placeholder implementation. Replace with actual authorization logic.
        """
        return True
