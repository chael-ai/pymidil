"""The bus is the platform: default-on observability + registration + run().

These pin the design we converged on — telemetry is a property of the bus, not
of transport primitives; it's built in (no opt-in), overridable by explicit
config, off with ``observability=False``; and it attaches at registration so
pre-built and config-built components are treated identically. Note the whole
file needs no env monkeypatching — observability is injected, not ambient.
"""

from __future__ import annotations

import asyncio

import pytest

from pymidil.event import Event, EventSubscriber
from pymidil.event.config import EventConfig
from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.event_bus import EventBus
from pymidil.event.observability import ObservabilityConfig
from pymidil.event.observability.emitter import (
    TelemetryDispatchHook,
    TelemetryProducerHook,
)
from pymidil.event.producer.base import BaseProducerConfig, EventProducer

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _config(**over) -> ObservabilityConfig:
    base = dict(observatory_url="http://obs.test", api_key="mo_k", service="orders-svc")
    base.update(over)
    return ObservabilityConfig(**base)


class DummyConsumer(EventConsumer):
    started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False


class DummyProducer(EventProducer):
    def __init__(self) -> None:
        super().__init__(BaseProducerConfig(type="fake"))

    async def _publish(self, event) -> None:
        ...

    async def close(self) -> None:
        ...


def _consumer() -> DummyConsumer:
    return DummyConsumer(BaseConsumerConfig(type="fake"))


def _dispatch_hooks(consumer) -> list:
    return [h for h in consumer._dispatch_hooks if isinstance(h, TelemetryDispatchHook)]


def _producer_hooks(producer) -> list:
    return [h for h in producer._producer_hooks if isinstance(h, TelemetryProducerHook)]


# ---- default-on, explicit override, off ---------------------------------------


def test_default_on_instruments_registered_components():
    bus = EventBus(EventConfig(), observability=_config())
    bus.include_consumer("orders", _consumer())
    bus.include_producer("out", DummyProducer())
    assert len(_dispatch_hooks(bus.consumers["orders"])) == 1
    assert len(_producer_hooks(bus.producers["out"])) == 1


def test_observability_false_is_off():
    bus = EventBus(EventConfig(), observability=False)
    bus.include_consumer("orders", _consumer())
    assert _dispatch_hooks(bus.consumers["orders"]) == []


def test_incomplete_contract_is_off():
    # URL but no service → would emit unknown-service rows → stays off.
    bus = EventBus(EventConfig(), observability=_config(service=None))
    bus.include_consumer("orders", _consumer())
    assert _dispatch_hooks(bus.consumers["orders"]) == []


def test_raw_component_stays_pure():
    # Constructed outside a bus → no telemetry, whatever the environment.
    consumer = _consumer()
    assert _dispatch_hooks(consumer) == []


# ---- registration parity + attribution ----------------------------------------


def test_per_registration_service_override():
    bus = EventBus(EventConfig(), observability=_config())
    bus.include_consumer("payments", _consumer(), service="ledger-svc")
    hook = _dispatch_hooks(bus.consumers["payments"])[0]
    assert hook._source_service == "ledger-svc"  # overrides the bus default


def test_every_registered_consumer_is_instrumented():
    # config-built and include_-built components share one registration funnel,
    # so instrumentation parity holds across however many are registered.
    bus = EventBus(EventConfig(), observability=_config())
    bus.include_consumer("a", _consumer())
    bus.include_consumer("b", _consumer())
    assert all(len(_dispatch_hooks(c)) == 1 for c in bus.consumers.values())


def test_duplicate_registration_is_refused():
    bus = EventBus(EventConfig(), observability=False)
    bus.include_consumer("orders", _consumer())
    with pytest.raises(Exception):
        bus.include_consumer("orders", _consumer())


# ---- run() lifecycle ----------------------------------------------------------


class Echo(EventSubscriber):
    async def handle(self, event: Event) -> None:
        ...


async def test_run_starts_waits_and_stops():
    bus = EventBus(EventConfig(), observability=False)
    consumer = bus.include_consumer("orders", _consumer())
    bus.subscribe(Echo(), target="orders")

    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0.05)
    assert consumer.started is True

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert consumer.started is False  # stop() ran on teardown


def test_missing_declarative_config_yields_empty_bus(monkeypatch):
    # include_-only composition must not require MIDIL__EVENT: when settings
    # report no event config, the bus starts empty instead of throwing.
    from pymidil.exceptions import EventSettingsError

    class _Unconfigured:
        def list_consumers(self):
            raise EventSettingsError("Event settings are not configured")

        def list_producers(self):
            raise EventSettingsError("Event settings are not configured")

    monkeypatch.setattr("pymidil.settings.get_settings", lambda: _Unconfigured())

    bus = EventBus(observability=False)  # no config arg → falls back to settings
    assert bus.consumers == {} and bus.producers == {}
    bus.include_consumer("orders", _consumer())
    assert "orders" in bus.consumers
