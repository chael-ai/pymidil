from pymidil.event.consumer.strategies.base import BaseConsumerConfig
from pymidil.event.consumer.strategies.base import EventConsumer
from typing import Any


class PushEventConsumerConfig(BaseConsumerConfig):
    ...


class PushEventConsumer(EventConsumer):
    def __init__(self, config: PushEventConsumerConfig):
        super().__init__(config)

    @property
    def entrypoint(self) -> Any:
        """
        Return the framework-specific entrypoint object.
        Examples:
            - FastAPI app
            - WebSocket server instance
            - gRPC server
        """
        raise NotImplementedError(
            "Entrypoint not implemented for {self.__class__.__name__}"
        )
