from __future__ import annotations

import asyncio
import signal
from typing import Any, Dict, Optional

from loguru import logger
from pydantic_settings import BaseSettings

from pymidil.event.consumer.strategies.pull import PullEventConsumer
from pymidil.event.consumer.strategies.push import PushEventConsumer
from pymidil.event.producer.base import EventProducer
from pymidil.event.transports.redis import RedisProducer, RedisProducerEventConfig
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.observability.platform import Observability, ObservabilitySpec
from pymidil.event.transports.sqs import SQSProducer, SQSProducerEventConfig
from pymidil.event.transports.sqs import SQSConsumer, SQSConsumerEventConfig
from pymidil.event.transports.webhook import WebhookConsumer, WebhookConsumerEventConfig
from pymidil.event.subscriber.base import (
    ErrorFn,
    EventSubscriber,
    FilterFn,
    FunctionSubscriber,
    SubscriberMiddleware,
)
from pymidil.exceptions import (
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

    A Midil bus is **observed by default**: it resolves the Observatory
    connection contract (``MIDIL_*`` env) at construction and instruments every
    producer/consumer it builds or that you register, so telemetry needs zero
    wiring. Turn it off with ``EventBus(observability=False)``, or supply an
    explicit :class:`ObservabilityConfig`. Raw components constructed outside a
    bus stay pure — telemetry is a property of the platform (the bus), not of
    the transport primitives, so unit tests never emit by accident.

    Usage:
        bus = EventBus()                              # observed
        bus.include_consumer("orders", my_consumer)   # pre-built, instrumented
        bus.subscribe(OrderHandler(), target="orders")
        await bus.run()                               # signals + lifecycle
    """

    def __init__(
        self,
        config: Optional[EventConfig] = None,
        *,
        observability: ObservabilitySpec = None,
    ) -> None:
        if config is None:
            config = self._config_from_settings()

        self._observability = Observability.resolve(observability)

        self.producers: Dict[str, EventProducer] = {}
        if config.producers:
            for name, producer_config in config.producers.items():
                self.include_producer(
                    name, EventBusFactory.create_producer(producer_config)
                )

        self.consumers: Dict[str, PullEventConsumer | PushEventConsumer] = {}
        if config.consumers:
            for name, consumer_config in config.consumers.items():
                self.include_consumer(
                    name, EventBusFactory.create_consumer(consumer_config)
                )

    def include_consumer(
        self,
        name: str,
        consumer: PullEventConsumer | PushEventConsumer,
        *,
        service: Optional[str] = None,
    ) -> PullEventConsumer | PushEventConsumer:
        """Register a pre-built consumer, instrumenting it at the same moment.

        This is where hand-assembled components (custom sessions, injected
        repositories) meet config-built ones — both flow through one
        registration point, so telemetry applies uniformly. ``service``
        overrides the default attribution, which is what a single process
        running several logical services needs.
        """
        if name in self.consumers:
            raise ConsumerError(f"Consumer '{name}' is already registered")
        self._observability.instrument_consumer(consumer, service=service)
        self.consumers[name] = consumer
        return consumer

    def include_producer(
        self,
        name: str,
        producer: EventProducer,
        *,
        service: Optional[str] = None,
    ) -> EventProducer:
        """Register a pre-built producer, instrumenting it at the same moment."""
        if name in self.producers:
            raise ProducerError(f"Producer '{name}' is already registered")
        self._observability.instrument_producer(producer, service=service)
        self.producers[name] = producer
        return producer

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
        elif len(self.consumers) == 1:
            next(iter(self.consumers.values())).subscribe(handler)
        else:
            # Refuse to guess: fanning one handler across every consumer —
            # including any absorbed from ambient MIDIL__EVENT config — is
            # almost never intended and silently mixes event streams.
            raise ConsumerError(
                f"Multiple consumers are registered "
                f"({list(self.consumers.keys())}) — pass "
                f"subscribe(handler, target=<name>) explicitly."
            )

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
        await self._observability.aclose()

    async def run(self) -> None:
        """Run the bus until interrupted — the paved-road worker entrypoint.

        Starts every consumer, then waits on SIGINT/SIGTERM and shuts down
        cleanly (consumers, producers, telemetry sink). This is the composition
        root's whole main loop, so services don't hand-roll signal handling::

            async def main() -> None:
                bus = EventBus()
                bus.subscribe(OrderHandler(), target="orders")
                await bus.run()

        Falls back to ``start()`` + a plain wait where signal handlers can't be
        installed (e.g. a non-main thread), so it never crashes on setup.
        """
        await self.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        installed = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
                installed = True
            except (NotImplementedError, RuntimeError):
                pass  # not the main thread / unsupported platform
        logger.info(
            "EventBus running — {} consumer(s), {} producer(s){}",
            len(self.consumers),
            len(self.producers),
            "" if installed else " (no signal handlers; cancel to stop)",
        )
        try:
            await stop.wait()
        finally:
            logger.info("EventBus shutting down…")
            await self.stop()

    @staticmethod
    def _config_from_settings() -> EventConfig:
        """Declarative config from ``MIDIL__EVENT``, or an empty bus.

        Declarative topology is optional: a bus populated entirely through
        ``include_consumer`` / ``include_producer`` is a first-class use, so a
        missing ``MIDIL__EVENT`` yields an empty config rather than an error.
        """
        from pymidil.exceptions import EventSettingsError
        from pymidil.settings import get_settings

        settings = get_settings()
        try:
            consumers = settings.list_consumers()
            producers = settings.list_producers()
        except EventSettingsError as error:
            logger.warning(
                f"An error occured while trying to load settings {error}, falling back to empty EventConfig ..."
            )
            return EventConfig()
        config = EventConfig(
            consumers={name: settings.get_consumer(name) for name in consumers},
            producers={name: settings.get_producer(name) for name in producers},
        )
        # Ambient config must be VISIBLE: this bus is about to build connectors
        # the caller never wrote in code (from MIDIL__EVENT / a .env in cwd).
        absorbed = [
            f"consumer '{n}' ({c.type})" for n, c in (config.consumers or {}).items()
        ]
        absorbed += [
            f"producer '{n}' ({p.type})" for n, p in (config.producers or {}).items()
        ]
        if absorbed:
            logger.info(
                f"EventBus loaded declarative config (MIDIL__EVENT): "
                f"{'; '.join(absorbed)}"
            )
        return config
