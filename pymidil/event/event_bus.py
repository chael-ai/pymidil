from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from pydantic_settings import BaseSettings

from pymidil.event.consumer.strategies.pull import PullEventConsumer
from pymidil.event.consumer.strategies.push import PushEventConsumer
from pymidil.event.producer.base import EventProducer
from pymidil.event.producer.redis import RedisProducer, RedisProducerEventConfig
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.producer.sqs import SQSProducer, SQSProducerEventConfig
from pymidil.event.consumer.sqs import SQSConsumer, SQSConsumerEventConfig
from pymidil.event.consumer.webhook import WebhookConsumer, WebhookConsumerEventConfig
from pymidil.event.subscriber.base import (
    ErrorFn,
    EventSubscriber,
    FilterFn,
    FunctionSubscriber,
    SubscriberMiddleware,
)
from pymidil.event.exceptions import (
    ConsumerError,
    ConsumerNotImplementedError,
    ProducerError,
    ProducerNotImplementedError,
    TransportNotImplementedError,
)
from pymidil.event.config import (
    ConsumerConfig,
    EventConfig,
    EventConsumerType,
    EventProducerType,
    ProducerConfig,
)


class EventBusFactory:
    """
    Factory for creating producers, consumers, and their configurations.

    Decoupled from EventBus so new connector types can be registered here
    without touching the bus orchestration logic — Single Responsibility.
    """

    _PRODUCER_MAP = {
        "redis": RedisProducer,
        "sqs": SQSProducer,
    }
    _CONSUMER_MAP = {
        "sqs": SQSConsumer,
        "webhook": WebhookConsumer,
    }
    _CONFIG_MAP = {
        "sqs": {"producer": SQSProducerEventConfig, "consumer": SQSConsumerEventConfig},
        "webhook": {"consumer": WebhookConsumerEventConfig},
        "redis": {"producer": RedisProducerEventConfig},
    }

    @classmethod
    def create_producer(cls, config: ProducerConfig) -> EventProducer:
        """
        Create an event producer instance based on the provided configuration.

        Args:
            config: The configuration object for the producer.

        Returns:
         An instance of EventProducer.

        Raises:
            ValueError: If the producer type is not supported.
        """
        producer_cls = cls._PRODUCER_MAP.get(config.type)
        if not producer_cls:
            raise ProducerNotImplementedError(config.type)
        return producer_cls(config)

    @classmethod
    def create_consumer(
        cls, config: ConsumerConfig
    ) -> PullEventConsumer | PushEventConsumer:
        """
        Create an event consumer instance (pull or push) based on the provided configuration.

        Args:
            config: The configuration object for the consumer.

        Returns:
            An instance of PullEventConsumer or PushEventConsumer.

        Raises:
            ValueError: If the consumer type is not supported.
        """

        consumer_cls = cls._CONSUMER_MAP.get(config.type)
        if not consumer_cls:
            raise ConsumerNotImplementedError(config.type)
        return consumer_cls(config)

    @classmethod
    def create_config(
        cls, transport: EventProducerType | EventConsumerType, **kwargs: Any
    ) -> BaseSettings:
        """
        Create a configuration object for the specified transport type.

        Args:
            transport: The transport type (e.g., "redis", "sqs", "webhook").
            **kwargs: Additional keyword arguments to pass to the config class.

        Returns:
            An instance of a configuration class derived from BaseSettings.

        Raises:
            ValueError: If the transport type is not supported.
        """
        config_map = cls._CONFIG_MAP.get(transport)
        if not isinstance(config_map, dict):
            raise TransportNotImplementedError(transport)
        config_cls = config_map.get("producer") or config_map.get("consumer")
        if not config_cls:
            raise TransportNotImplementedError(transport)
        return config_cls(**kwargs)


class EventBus:
    """
    Central orchestrator for event-driven communication.

    Manages the lifecycle of all producers and consumers.

    Usage:
        bus = EventBus()
        bus.subscribe(OrderHandler())
        async with lifespan(app):
            await bus.start()
    """

    def __init__(
        self,
        config: Optional[EventConfig] = None,
    ) -> None:
        if config is None:
            config = self._config_from_settings()

        self.producers: Mapping[str, EventProducer] = {}
        if config.producers:
            for name, producer_config in config.producers.items():
                producer = EventBusFactory.create_producer(producer_config)
                self.producers[name] = producer  # type: ignore[index]

        self.consumers: Mapping[str, PullEventConsumer | PushEventConsumer] = {}
        if config.consumers:
            for name, consumer_config in config.consumers.items():
                consumer = EventBusFactory.create_consumer(consumer_config)
                self.consumers[name] = consumer  # type: ignore[index]

    def add_dispatch_hook(
        self, hook: DispatchHook, target: Optional[str] = None
    ) -> None:
        """
        Add a dispatch hook to a specific consumer or all consumers.

        Args:
            hook: The dispatch hook to add.
            target: Optional name of the specific consumer to add the hook to.
                If None, adds the hook to all consumers.
        """

        if target:
            if target not in self.consumers:
                raise ConsumerError(f"Consumer '{target}' not found")
            self.consumers[target].add_hook(hook)
        else:
            for consumer in self.consumers.values():
                consumer.add_hook(hook)

    async def publish(
        self,
        payload: Dict[str, Any],
        target: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Publish an event to a specific producer or all producers.

        Args:
            payload: The event payload as a dictionary.
            target: Optional name of the specific producer to publish to.
                         If None, publishes to all producers.
            metadata: Optional metadata to include with the event.

        Raises:
            ValueError: If no producers are configured or if the specified producer is not found.
        """
        if not self.producers:
            raise ProducerError("No producers configured")

        if target:
            if target not in self.producers:
                raise ProducerError(
                    f"Producer '{target}' not found. "
                    f"Available: {list(self.producers.keys())}"
                )
            await self.producers[target].publish(payload, metadata=metadata)
        else:
            for producer in self.producers.values():
                await producer.publish(payload, metadata=metadata)

    def subscribe(self, handler: EventSubscriber, target: Optional[str] = None) -> None:
        """
        Register an event subscriber/handler to receive events from one or all consumers.

        Args:
            handler: An instance of EventSubscriber.
            target: Optional name of the specific consumer to subscribe to.
                         If None, subscribes to all consumers.

        Raises:
            ValueError: If no consumers are configured or if the specified consumer is not found.
        """
        if not self.consumers:
            raise ConsumerError("No consumers configured")

        if target:
            if target not in self.consumers:
                raise ConsumerError(
                    f"Consumer '{target}' not found. "
                    f"Available: {list(self.consumers.keys())}"
                )
            self.consumers[target].subscribe(handler)
        else:
            for consumer in self.consumers.values():
                consumer.subscribe(handler)

    def subscriber(
        self,
        target: Optional[str] = None,
        middlewares: Optional[list[SubscriberMiddleware]] = None,
        filter: Optional[FilterFn] = None,
        on_error: Optional[ErrorFn] = None,
    ):
        """Decorator that registers a plain async function as a subscriber."""

        def decorator(func):
            self.subscribe(
                FunctionSubscriber(
                    handler=func,
                    middlewares=middlewares,
                    filter=filter,
                    on_error=on_error,
                ),
                target=target,
            )
            return func

        return decorator

    async def start(self) -> None:
        """
        Start all event consumers to begin receiving and dispatching events.

        Raises:
            ValueError: If no consumers are configured.
        """
        if not self.consumers:
            raise ConsumerError("No consumers configured")
        for consumer in self.consumers.values():
            await consumer.start()

    async def stop(self) -> None:
        """
        Stop all event consumers and producers to stop receiving and dispatching events.
        """
        for consumer in self.consumers.values():
            await consumer.stop()
        for producer in self.producers.values():
            await producer.close()

    @staticmethod
    def _config_from_settings() -> EventConfig:
        from pymidil.settings import get_settings

        settings = get_settings()
        consumers = settings.list_consumers()
        producers = settings.list_producers()
        return EventConfig(
            consumers={name: settings.get_consumer(name) for name in consumers},
            producers={name: settings.get_producer(name) for name in producers},
        )
